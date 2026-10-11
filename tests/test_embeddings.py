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
    long_text = "x" * 7_000

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
    embedding._injected_client = None  # noqa: SLF001
    embedding._client = SimpleNamespace(models=api)  # noqa: SLF001
    embedding._types = _FakeTypesModule  # noqa: SLF001
    return embedding


def test_daily_quota_429_raises_llm_daily_quota_exhausted(tmp_path, monkeypatch):
    from src.llm.client import LLMDailyQuotaExhausted

    monkeypatch.setattr("time.sleep", lambda _s: None)
    api = ScriptedEmbeddingsAPI(
        [Exception("429 RESOURCE_EXHAUSTED quota: GenerateRequestsPerDayPerProjectPerModel-FreeTier")]
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
