"""Tests for the WS-03 embedding layer (src/llm/embeddings.py).

No network: the genai client is replaced by a duck-typed fake recording every
``embed_content`` call, so call-counting (cache hit/miss accounting) and the
one-content-entry-per-text aggregation contract are directly assertable.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.llm.client import LLMConfigError, LLMError, LLMRateLimited, LLMUnavailable
from src.llm.embeddings import (
    GeminiEmbedding,
    build_document_text,
    build_query_text,
)


class FakeEmbeddingsAPI:
    """Duck-typed ``client.models`` that records embed_content calls.

    Mirrors the live SDK contract the real call path uses: entries may be
    ``Content``-like objects (with ``parts[0].text``) or bare strings; texts
    are unwrapped for assertions.
    """

    def __init__(
        self,
        vector: list[float] | None = None,
        error: Exception | None = None,
        result_count: int | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self.vector = vector or [1.0, 0.0, 0.0]
        self.error = error
        self.result_count = result_count

    @staticmethod
    def _entry_text(entry) -> str:
        parts = getattr(entry, "parts", None)
        if parts:
            return parts[0].text
        return entry

    def embed_content(self, model, contents, config=None):
        self.calls.append(
            {"model": model, "contents": [self._entry_text(c) for c in contents], "config": config}
        )
        if self.error is not None:
            raise self.error
        count = self.result_count if self.result_count is not None else len(contents)
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=list(self.vector)) for _ in range(count)]
        )


def make_embedding(tmp_path, api: FakeEmbeddingsAPI, **kwargs) -> GeminiEmbedding:
    defaults = {
        "model": "gemini-embedding-2",
        "dimensionality": 768,
        "cache_path": tmp_path / "embedding_cache.sqlite",
        "client": SimpleNamespace(models=api),
    }
    defaults.update(kwargs)
    return GeminiEmbedding(**defaults)


def test_prefix_builders_match_documented_format():
    assert (
        build_document_text("Python Dev", "Builds APIs") == "title: Python Dev | text: Builds APIs"
    )
    assert (
        build_query_text("senior python engineer")
        == "task: search result | query: senior python engineer"
    )


def test_embed_documents_returns_one_vector_per_text(tmp_path):
    # Aggregation gotcha locked: N texts in one call -> N vectors, and the
    # single API call carried N separate contents entries (never a join).
    api = FakeEmbeddingsAPI()
    embedding = make_embedding(tmp_path, api)
    texts = [f"document {index}" for index in range(5)]

    vectors = embedding.embed_documents(texts)

    assert len(vectors) == 5
    assert len(api.calls) == 1
    assert api.calls[0]["contents"] == texts
    assert all(vector == [1.0, 0.0, 0.0] for vector in vectors)


def test_embed_documents_empty_input_makes_no_call(tmp_path):
    api = FakeEmbeddingsAPI()
    embedding = make_embedding(tmp_path, api)
    assert embedding.embed_documents([]) == []
    assert api.calls == []


def test_cache_hit_miss_accounting(tmp_path):
    api = FakeEmbeddingsAPI()
    embedding = make_embedding(tmp_path, api)

    embedding.embed_documents(["alpha", "beta"])
    assert len(api.calls) == 1  # one batched call for both misses

    embedding.embed_documents(["alpha", "beta"])
    assert len(api.calls) == 1  # fully cached: zero additional API calls

    embedding.embed_documents(["alpha", "gamma"])
    assert len(api.calls) == 2  # only "gamma" was a miss
    assert api.calls[1]["contents"] == ["gamma"]

    # A query sharing a document's exact text is a cache hit too.
    embedding.embed_query("alpha")
    assert len(api.calls) == 2

    # A fresh instance over the same cache file still needs no API calls.
    warm = make_embedding(
        tmp_path, FakeEmbeddingsAPI(), cache_path=tmp_path / "embedding_cache.sqlite"
    )
    warm.embed_documents(["alpha", "beta", "gamma"])
    assert warm._injected_client.models.calls == []


def test_long_input_truncated_with_warning(tmp_path, caplog):
    api = FakeEmbeddingsAPI()
    embedding = make_embedding(tmp_path, api)
    long_text = "x" * 10_000

    with caplog.at_level("WARNING", logger="src.llm.embeddings"):
        embedding.embed_documents([long_text])

    assert api.calls[0]["contents"] == ["x" * GeminiEmbedding.MAX_TEXT_CHARS]
    assert any("truncated" in record.message for record in caplog.records)


def test_rate_limit_error_maps_to_llm_rate_limited(tmp_path):
    api = FakeEmbeddingsAPI(error=RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded"))
    embedding = make_embedding(tmp_path, api)
    with pytest.raises(LLMRateLimited):
        embedding.embed_documents(["text"])


def test_unavailable_error_maps_to_llm_unavailable(tmp_path):
    api = FakeEmbeddingsAPI(error=RuntimeError("503 Service Unavailable"))
    embedding = make_embedding(tmp_path, api)
    with pytest.raises(LLMUnavailable):
        embedding.embed_query("text")


def test_missing_api_key_maps_to_llm_config_error(tmp_path):
    embedding = GeminiEmbedding(
        api_key="",
        model="gemini-embedding-2",
        dimensionality=768,
        cache_path=tmp_path / "cache.sqlite",
    )
    with pytest.raises(LLMConfigError, match="LLM_API_KEY"):
        embedding.embed_documents(["text"])


def test_result_count_mismatch_raises(tmp_path):
    # Aggregation guard: 2 inputs but the API returned 1 embedding.
    api = FakeEmbeddingsAPI(result_count=1)
    embedding = make_embedding(tmp_path, api)
    with pytest.raises(LLMError, match="embeddings"):
        embedding.embed_documents(["one", "two"])


def test_real_call_path_wraps_each_text_and_pins_dimensionality(tmp_path):
    # The real call path (live-verified aggregation contract): each text is
    # its own Content object and output_dimensionality is pinned in config.
    api = FakeEmbeddingsAPI()
    embedding = make_embedding(tmp_path, api)

    recorded: dict = {}

    class FakePart:
        def __init__(self, text):
            self.text = text

    class FakeContent:
        def __init__(self, role, parts):
            self.role = role
            self.parts = parts

    class FakeTypes:
        Part = FakePart
        Content = FakeContent

        class EmbedContentConfig:
            def __init__(self, **kwargs):
                recorded.update(kwargs)

    embedding._types = FakeTypes
    embedding._injected_client = None
    embedding._client = SimpleNamespace(models=api)
    embedding.embed_documents(["first", "second"])

    assert api.calls[0]["contents"] == ["first", "second"]  # unwrapped by the fake
    assert recorded == {"output_dimensionality": 768}


# ------------------------------------------------------- batch-size cap (live finding)


def test_documents_chunked_at_api_batch_cap(tmp_path) -> None:
    """>100 misses are split into <=100-request batches (live API rejects larger)."""
    api = FakeEmbeddingsAPI()
    embedding = make_embedding(tmp_path, api)
    texts = [f"job listing {i} python backend" for i in range(250)]

    vectors = embedding.embed_documents(texts)

    assert len(vectors) == 250
    assert [len(call["contents"]) for call in api.calls] == [100, 100, 50]
    # Order alignment across chunk boundaries.
    first_of_each_chunk = [call["contents"][0] for call in api.calls]
    assert first_of_each_chunk == [texts[0], texts[100], texts[200]]


def test_cached_documents_produce_no_extra_batches(tmp_path) -> None:
    """A second run is fully served from the cache: zero API calls."""
    api = FakeEmbeddingsAPI()
    embedding = make_embedding(tmp_path, api)
    texts = [f"job listing {i} python backend" for i in range(150)]
    embedding.embed_documents(texts)
    calls_after_first = len(api.calls)

    embedding.embed_documents(texts)

    assert calls_after_first == 2  # 100 + 50
    assert len(api.calls) == calls_after_first


# ------------------------------------------------- FU-4 quota budget/pacing


class ScriptedEmbeddingsAPI(FakeEmbeddingsAPI):
    """Fake that raises a scripted exception per call before succeeding."""

    def __init__(self, errors: list[Exception | None], vector: list[float] | None = None):
        super().__init__(vector=vector)
        self._script = list(errors)

    def embed_content(self, model, contents, config=None):
        self.calls.append(
            {"model": model, "contents": [self._entry_text(c) for c in contents], "config": config}
        )
        if self._script:
            error = self._script.pop(0)
            if error is not None:
                raise error
        count = self.result_count if self.result_count is not None else len(contents)
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=list(self.vector)) for _ in range(count)]
        )


class _FakeTypesModule:
    """Minimal stand-in for google.genai.types on the real call path."""

    class Part:
        def __init__(self, text):
            self.text = text

    class Content:
        def __init__(self, role, parts):
            self.role = role
            self.parts = parts

    class EmbedContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs


def _real_path_embedding(tmp_path, api, **kwargs):
    """make_embedding flipped onto the real (paced/budgeted) call path."""
    embedding = make_embedding(tmp_path, api, **kwargs)
    embedding._injected_client = None
    embedding._client = SimpleNamespace(models=api)
    embedding._types = _FakeTypesModule
    return embedding


def test_daily_quota_429_raises_llm_daily_quota_exhausted(tmp_path, monkeypatch):
    from src.llm.client import LLMDailyQuotaExhausted

    monkeypatch.setattr("time.sleep", lambda _s: None)
    api = ScriptedEmbeddingsAPI(
        [
            Exception(
                "429 RESOURCE_EXHAUSTED quota: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
            )
        ]
    )
    embedding = _real_path_embedding(tmp_path, api)

    with pytest.raises(LLMDailyQuotaExhausted):
        embedding.embed_documents(["text one", "text two"])
    assert len(api.calls) == 1  # daily exhaustion: no retry spam


def test_per_minute_429_retries_bounded_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    api = ScriptedEmbeddingsAPI(
        [Exception("429 quota: GenerateRequestsPerMinute"), None],
        vector=[0.5, 0.5],
    )
    embedding = _real_path_embedding(tmp_path, api)

    vectors = embedding.embed_documents(["text one"])

    assert len(api.calls) == 2  # one retry, then success
    assert vectors == [[0.5, 0.5]]


def test_per_minute_429_bounded_retries_then_raises(tmp_path, monkeypatch):
    from src.llm.client import LLMRateLimited

    monkeypatch.setattr("time.sleep", lambda _s: None)
    error = Exception("429 quota: GenerateRequestsPerMinute")
    api = ScriptedEmbeddingsAPI(
        [error] * (1 + GeminiEmbedding.RATE_LIMIT_RETRIES)  # never succeeds
    )
    embedding = _real_path_embedding(tmp_path, api)

    with pytest.raises(LLMRateLimited):
        embedding.embed_documents(["text one"])
    # initial call + RATE_LIMIT_RETRIES retries, then fail fast.
    assert len(api.calls) == 1 + GeminiEmbedding.RATE_LIMIT_RETRIES


def test_daily_budget_gate_blocks_call_before_it_happens(tmp_path, monkeypatch):
    from src.llm.client import LLMDailyQuotaExhausted

    monkeypatch.setattr("time.sleep", lambda _s: None)
    api = FakeEmbeddingsAPI()
    embedding = _real_path_embedding(tmp_path, api, rpd_limit=2)
    embedding._cache.record_api_request()
    embedding._cache.record_api_request()

    with pytest.raises(LLMDailyQuotaExhausted):
        embedding.embed_documents(["text one"])
    assert api.calls == []  # budget spent: the call is refused client-side
    assert embedding.remaining_daily_budget() == 0


def test_successful_batch_requests_recorded_and_budget_decrements(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    api = FakeEmbeddingsAPI()
    embedding = _real_path_embedding(tmp_path, api, rpd_limit=20)
    assert embedding.remaining_daily_budget() == 20

    embedding.embed_documents([f"job {i} python" for i in range(150)])  # 2 batches

    assert len(api.calls) == 2
    assert embedding.remaining_daily_budget() == 18  # persistent counter
    assert embedding._cache.requests_today() == 2


def test_estimate_api_requests_counts_cache_misses_in_batches(tmp_path):
    api = FakeEmbeddingsAPI()
    embedding = make_embedding(tmp_path, api, rpd_limit=20)
    texts = [f"job {i} python" for i in range(150)]

    assert embedding.estimate_api_requests([]) == 0
    assert embedding.estimate_api_requests(texts) == 2  # 150 misses -> 2 batches

    embedding.embed_documents(texts)
    assert embedding.estimate_api_requests(texts) == 0  # all cached now
    assert embedding.estimate_api_requests(texts[:1] + ["brand new text"]) == 1


def test_injected_clients_are_never_paced_or_gated(tmp_path):
    """Tests/fakes bypass pacing and the budget gate: a scripted 429 surfaces
    immediately with no retries and no counter writes."""
    from src.llm.client import LLMDailyQuotaExhausted

    api = ScriptedEmbeddingsAPI([Exception("429 quota: GenerateRequestsPerDay")])
    embedding = make_embedding(tmp_path, api)  # injected client path

    with pytest.raises(LLMDailyQuotaExhausted):
        embedding.embed_documents(["text one"])
    assert len(api.calls) == 1  # fail fast: no bounded-retry loop on this path
    assert embedding._cache.requests_today() == 0  # nothing recorded


# --------------------------------------------- FU-7 local provider (fastembed)


class FakeTextEmbedding:
    """Duck-typed fastembed ``TextEmbedding`` double: records inputs.

    Returns a fixed vector per call so float conversion, alignment, and
    verbatim-text passing are directly assertable — no model download, no
    fastembed import on the embed path.
    """

    def __init__(self, vector: list[float] | None = None, error: Exception | None = None):
        self.embedded: list[list[str]] = []
        self.vector = vector or [1.0, 0.5, -0.25]
        self.error = error

    def embed(self, texts, **kwargs):
        self.embedded.append(list(texts))
        if self.error is not None:
            raise self.error
        return [self.vector for _ in texts]


def make_fastembed(tmp_path, double=None, **kwargs):
    from src.llm.embeddings import FastembedEmbedding

    defaults = {
        "model": "google/embeddinggemma-2@int8",
        "dimensionality": 768,
        "cache_dir": str(tmp_path / "fastembed"),
    }
    defaults.update(kwargs)
    return FastembedEmbedding(text_embedding=double or FakeTextEmbedding(), **defaults)


def test_fastembed_inputs_pass_verbatim_and_vectors_cast_to_floats(tmp_path):
    """Callers own the prefixes (same contract as GeminiEmbedding): the doc/query
    strings reach the double verbatim; outputs come back as plain float lists."""
    double = FakeTextEmbedding()
    embedding = make_fastembed(tmp_path, double)

    vectors = embedding.embed_documents(["title: Dev | text: Builds APIs", "second"])

    assert double.embedded == [["title: Dev | text: Builds APIs", "second"]]
    assert vectors == [[1.0, 0.5, -0.25], [1.0, 0.5, -0.25]]
    assert all(isinstance(value, float) for vector in vectors for value in vector)


def test_fastembed_query_truncates_at_max_text_chars(tmp_path):
    from src.llm.embeddings import MAX_TEXT_CHARS

    double = FakeTextEmbedding()
    embedding = make_fastembed(tmp_path, double)
    long_text = "y" * 10_000

    embedding.embed_documents([long_text])
    assert double.embedded[0] == ["y" * MAX_TEXT_CHARS]

    embedding.embed_query(long_text)
    assert double.embedded[1] == ["y" * MAX_TEXT_CHARS]


def test_fastembed_empty_input_makes_no_call(tmp_path):
    double = FakeTextEmbedding()
    embedding = make_fastembed(tmp_path, double)
    assert embedding.embed_documents([]) == []
    assert double.embedded == []


def test_fastembed_identity_and_determinism(tmp_path):
    embedding = make_fastembed(tmp_path)
    assert embedding.model == "google/embeddinggemma-2@int8"
    assert embedding.dimensionality == 768
    first = embedding.embed_query("python backend")
    assert embedding.embed_query("python backend") == first


def test_fastembed_vector_count_mismatch_raises(tmp_path):
    class ShortDouble(FakeTextEmbedding):
        def embed(self, texts, **kwargs):
            super().embed(texts)
            return [self.vector]  # one vector for two inputs

    embedding = make_fastembed(tmp_path, ShortDouble())
    with pytest.raises(LLMError, match="misalign"):
        embedding.embed_documents(["one", "two"])


def test_fastembed_real_path_rejects_unsupported_identity(tmp_path):
    """Without an injected double, an unknown model identity fails fast —
    before any fastembed import or download."""
    from src.llm.embeddings import FastembedEmbedding

    embedding = FastembedEmbedding(
        model="text-embedding-004", dimensionality=768, cache_dir=str(tmp_path)
    )
    with pytest.raises(LLMConfigError, match="google/embeddinggemma-2"):
        embedding.embed_documents(["text"])


def test_fastembed_real_path_rejects_dimensionality_mismatch(tmp_path):
    from src.llm.embeddings import FastembedEmbedding

    embedding = FastembedEmbedding(
        model="google/embeddinggemma-2@int8", dimensionality=1536, cache_dir=str(tmp_path)
    )
    with pytest.raises(LLMConfigError, match="768"):
        embedding.embed_documents(["text"])


def test_parse_gemma_identity_variants():
    from src.llm.embeddings import parse_gemma_identity

    assert parse_gemma_identity("google/embeddinggemma-2@int8") == "int8"
    assert parse_gemma_identity("google/embeddinggemma-2@fp32") == "fp32"
    assert parse_gemma_identity("gemini-embedding-2") is None
    assert parse_gemma_identity("google/embeddinggemma@int8") is None


# ------------------------------------------------- FU-7 live findings: shims


def test_ensure_tokenizer_context_patches_sentinel_length_preserving(tmp_path):
    """The live finding: the export ships a ~1e30 sentinel model_max_length and
    fastembed refuses it. The patch replaces the digits in place — byte length
    must be preserved or fastembed's remote-size verification flags the cache
    corrupted (found live the hard way)."""
    import json

    from src.llm.embeddings import FASTEMBED_TOKENIZER_CONTEXT, ensure_tokenizer_context

    snapshot = tmp_path / "models--onnx-community--embeddinggemma-2-ONNX" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    original = json.dumps(
        {"model_max_length": 1000000000000000019884624838656, "tokenizer_class": "GemmaTokenizer"}
    )
    config_path = snapshot / "tokenizer_config.json"
    config_path.write_text(original, encoding="utf-8")

    ensure_tokenizer_context(str(tmp_path))

    patched = config_path.read_text(encoding="utf-8")
    assert len(patched) == len(original)  # byte-length-preserving
    assert json.loads(patched)["model_max_length"] == FASTEMBED_TOKENIZER_CONTEXT

    # Idempotent: a second run is a no-op.
    ensure_tokenizer_context(str(tmp_path))
    assert config_path.read_text(encoding="utf-8") == patched


def test_ensure_tokenizer_context_skips_usable_cap_and_missing_model(tmp_path):
    import json

    from src.llm.embeddings import ensure_tokenizer_context

    # Model not downloaded: no-op, no error.
    ensure_tokenizer_context(str(tmp_path))

    snapshot = tmp_path / "models--onnx-community--embeddinggemma-2-ONNX" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    usable = json.dumps({"model_max_length": 8192})
    config_path = snapshot / "tokenizer_config.json"
    config_path.write_text(usable, encoding="utf-8")

    ensure_tokenizer_context(str(tmp_path))
    assert config_path.read_text(encoding="utf-8") == usable  # untouched


def test_text_only_session_injects_zero_features():
    """Live finding: the fused graph requires image/video/audio feature inputs
    fastembed never feeds. The shim fills them with zero-shaped tensors."""
    from types import SimpleNamespace

    from src.llm.embeddings import _TextOnlySession

    recorded = {}

    class FakeSession:
        def get_inputs(self):
            return [
                SimpleNamespace(name="input_ids", shape=["batch", "seq"]),
                SimpleNamespace(name="attention_mask", shape=["batch", "seq"]),
                SimpleNamespace(name="image_features", shape=["num_image_tokens", 512]),
                SimpleNamespace(name="video_features", shape=["num_video_tokens", 512]),
                SimpleNamespace(name="audio_features", shape=["num_audio_tokens", 512]),
            ]

        def run(self, output_names, feed):
            recorded.update(feed)
            return [[1.0, 2.0]]

    shim = _TextOnlySession(FakeSession())
    feed = {"input_ids": [[1, 2]], "attention_mask": [[1, 1]]}
    assert shim.run(["sentence_embedding"], feed) == [[1.0, 2.0]]

    import numpy as np

    for name in ("image_features", "video_features", "audio_features"):
        assert name in recorded
        assert recorded[name].shape == (0, 512)  # dynamic dim -> zero rows
        assert recorded[name].dtype == np.float32
    # Explicitly provided inputs are never overwritten.
    assert recorded["input_ids"] == [[1, 2]]


def test_register_gemma_variant_rejects_forbidden_fp16():
    from src.llm.embeddings import _register_gemma_variant

    with pytest.raises(LLMConfigError, match="fp16 is forbidden"):
        _register_gemma_variant("fp16")


def test_register_gemma_variant_is_idempotent_per_process():
    """The registration runs once inside the lazy init; a second embedder over
    the same variant must not raise (fastembed rejects duplicate names)."""
    from src.llm.embeddings import _register_gemma_variant

    first = _register_gemma_variant("int8")
    assert first == "onnx-community/embeddinggemma-2-ONNX:int8"
    assert _register_gemma_variant("int8") == first


def test_fastembed_cache_dir_env_override(tmp_path, monkeypatch):
    from src.llm.embeddings import fastembed_cache_dir

    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path / "custom"))
    assert fastembed_cache_dir() == str(tmp_path / "custom")
    monkeypatch.delenv("FASTEMBED_CACHE_PATH")
    assert fastembed_cache_dir().endswith("fastembed")


def test_build_embedding_fn_selects_provider_per_settings(tmp_path):
    from types import SimpleNamespace

    from src.llm.client import LLMConfigError
    from src.llm.embeddings import FastembedEmbedding, GeminiEmbedding, build_embedding_fn

    fast = build_embedding_fn(
        SimpleNamespace(
            embedding_provider="fastembed",
            embedding_model="google/embeddinggemma-2@int8",
            embedding_dimensionality=768,
            data_dir=str(tmp_path),
        )
    )
    assert isinstance(fast, FastembedEmbedding)

    gemini = build_embedding_fn(
        SimpleNamespace(
            embedding_provider="gemini",
            embedding_model="gemini-embedding-2",
            embedding_dimensionality=768,
            data_dir=str(tmp_path / "gemini"),
            llm_api_key="",
            embedding_rpm_limit=5,
            embedding_rpd_limit=20,
        )
    )
    assert isinstance(gemini, GeminiEmbedding)
    gemini._cache.close()

    with pytest.raises(LLMConfigError, match="EMBEDDING_PROVIDER"):
        build_embedding_fn(SimpleNamespace(embedding_provider="openai"))
