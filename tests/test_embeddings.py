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
