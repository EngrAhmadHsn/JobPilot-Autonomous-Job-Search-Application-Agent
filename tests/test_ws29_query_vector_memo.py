"""WS-29 · A repeat search by an unchanged profile reuses its query vector.

The ONNX pass costs ~0.45 ms per character and the candidate text is 4,555
characters, so a repeat search re-pays ~2 s for a vector it already had.

The memo is process-local and memory-only. WS-14 · Phase G forbids a *shared,
persistent* cache — a hit on identical text would tell a second tenant that
somebody else submitted the same text, and a stored vector is a candidate
fingerprint that can be inverted. A dictionary that dies with the process is
neither shared nor durable, which is the same distinction WS-24c already drew
for the similarity map.
"""

from __future__ import annotations

import pytest


class CountingEmbedding:
    """A fastembed ``TextEmbedding`` double that counts the inference calls.

    A **generator**, like the real thing: fastembed's ``embed()`` yields, so the
    inference happens while the result is consumed. The counter increments
    inside the generator, which is where the work is.
    """

    model = "test-model"
    dimensionality = 8

    def __init__(self) -> None:
        self.query_calls = 0
        self.embedded: list[list[str]] = []

    def embed(self, texts, **kwargs):
        self.embedded.append(list(texts))
        self.query_calls += 1
        for text in texts:
            # A vector derived from the text's characters, so two different
            # strings of the same length are still distinguishable.
            yield [float(sum(map(ord, text))), float(len(text))] + [0.0] * 6


@pytest.fixture(autouse=True)
def _clean_memo():
    """The memo is module state; one test must not see another's entries."""
    from src.llm import embeddings as emb

    emb.clear_query_vector_memo()
    yield
    emb.clear_query_vector_memo()


def test_a_repeat_query_is_not_re_embedded():
    """The same text twice must reach the provider once."""
    from src.llm.embeddings import FastembedEmbedding

    provider = CountingEmbedding()
    embedding = FastembedEmbedding(text_embedding=provider)

    first = embedding.embed_query("a candidate summary")
    second = embedding.embed_query("a candidate summary")

    assert provider.query_calls == 1
    assert first == second


def test_a_different_text_is_a_different_vector():
    """Two profiles must never share a vector."""
    from src.llm.embeddings import FastembedEmbedding

    provider = CountingEmbedding()
    embedding = FastembedEmbedding(text_embedding=provider)

    one = embedding.embed_query("candidate one")
    two = embedding.embed_query("candidate two")

    assert provider.query_calls == 2
    assert one != two


def test_the_memo_returns_a_copy_not_its_own_list():
    """A caller mutating the returned list must not corrupt the memo.

    The store may normalize in place or a caller may sort; either would poison
    every later search if the vector were handed out by reference.
    """
    from src.llm.embeddings import FastembedEmbedding

    provider = CountingEmbedding()
    embedding = FastembedEmbedding(text_embedding=provider)

    first = embedding.embed_query("a candidate summary")
    first[0] = 999.0
    second = embedding.embed_query("a candidate summary")

    assert second[0] != 999.0


def test_the_memo_holds_no_readable_text():
    """The key is a digest, so no candidate prose is retained."""
    import hashlib

    from src.llm import embeddings as emb

    provider = CountingEmbedding()
    emb.FastembedEmbedding(text_embedding=provider).embed_query("a very specific summary")

    keys = repr(tuple(emb._QUERY_VECTOR_MEMO.keys()))
    assert "a very specific summary" not in keys
    assert hashlib.sha256(b"a very specific summary").hexdigest() in keys


def test_the_memo_is_bounded():
    """It must not grow with every profile an operator visits."""
    from src.llm import embeddings as emb

    provider = CountingEmbedding()
    embedding = emb.FastembedEmbedding(text_embedding=provider)

    for index in range(emb._QUERY_VECTOR_MEMO_ENTRIES + 5):
        embedding.embed_query(f"candidate {index}")

    assert len(emb._QUERY_VECTOR_MEMO) == emb._QUERY_VECTOR_MEMO_ENTRIES


def test_an_expired_entry_is_recomputed():
    """The TTL bounds a vector held for a profile that has since changed."""
    from src.llm import embeddings as emb

    provider = CountingEmbedding()
    embedding = emb.FastembedEmbedding(text_embedding=provider)
    embedding.embed_query("a candidate summary")
    assert provider.query_calls == 1

    key = next(iter(emb._QUERY_VECTOR_MEMO))
    stored_at, vector = emb._QUERY_VECTOR_MEMO[key]
    emb._QUERY_VECTOR_MEMO[key] = (
        stored_at - emb._QUERY_VECTOR_MEMO_TTL_SECONDS - 1.0,
        vector,
    )
    embedding.embed_query("a candidate summary")

    assert provider.query_calls == 2


def test_the_document_path_is_unaffected():
    """Documents are cached in SQLite already; the query memo must not touch them."""
    from src.llm import embeddings as emb

    provider = CountingEmbedding()
    embedding = emb.FastembedEmbedding(text_embedding=provider)

    embedding.embed_documents(["one document", "one document"])

    assert not emb._QUERY_VECTOR_MEMO, "a document must never enter the query memo"
