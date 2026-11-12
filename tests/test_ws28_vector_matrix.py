"""WS-28 §11.13 · The resident vector matrix and the memo key.

Two properties, and the reason each one is worth a test:

- **A memo hit must not fetch the ids.** The key used to include the covered-id
  count, which was only known after `collection.get(include=[])` — so a "hit"
  still paid 23 ms. Keying on `collection.count()` makes it a dict read.
- **The matrix must be reused, and must never outlive a write.** Reuse is the
  ~1 s saving. Staleness is the risk, and it is answered three ways: a write
  from this process clears it, a size change rebuilds it, and the TTL expires it.

The exactness property is pinned elsewhere and by measurement: the matrix is a
normalized copy of the same vectors the page scan uses, and the matvec is the
same `unit_matrix @ unit_query`. `test_the_matrix_scores_match_the_page_scan`
proves it directly rather than by argument.
"""

from __future__ import annotations

import math
import re
import zlib
from types import SimpleNamespace

import pytest

from src.jobs.contracts import JobListing
from src.rag import chroma_store
from src.rag.chroma_store import ChromaVectorStore

DIM = 64


def token_vector(text: str) -> list[float]:
    """Deterministic bag-of-tokens unit vector (stable across runs)."""
    vector = [0.0] * DIM
    for token in re.findall(r"[a-z]+", text.casefold()):
        index = zlib.crc32(token.encode("utf-8")) % DIM
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def unnormalized_vector(text: str, scale: float = 7.5) -> list[float]:
    """A deterministic vector that is **not** unit length.

    The normalizer inside the store is what makes a cosine out of a dot
    product, so a fixture of unit vectors would make the normalization a no-op
    and let a broken normalizer pass. Chroma returns whatever was stored, and
    a real provider's vectors are not exactly unit length either, so this is
    also the more honest input.
    """
    return [value * scale for value in token_vector(text)]


class CountingEmbeddingFn:
    """Deterministic, **unnormalized** vectors, and a query counter."""

    def __init__(self) -> None:
        self.query_calls = 0

    def embed_documents(self, texts, *, on_progress=None):
        return [unnormalized_vector(text) for text in texts]

    def embed_query(self, text):
        self.query_calls += 1
        # A different scale from the documents, so the query normalization is
        # exercised independently of the row normalization.
        return unnormalized_vector(text, scale=3.25)


def make_store(tmp_path) -> ChromaVectorStore:
    settings = SimpleNamespace(
        chroma_dir=str(tmp_path / "chroma"),
        embedding_model="gemini-embedding-2",
        embedding_dimensionality=DIM,
    )
    return ChromaVectorStore(embedding_fn=CountingEmbeddingFn(), settings=settings)


def listing(index: int, body: str) -> JobListing:
    return JobListing(
        id=f"test:{index}",
        source="test",
        source_job_id=str(index),
        title=f"Engineer {index}",
        company="Acme",
        description=body,
    )


@pytest.fixture(autouse=True)
def _clean_caches():
    """Both process caches are module state; one test must not see another's."""
    chroma_store.clear_process_scan_cache()
    chroma_store.clear_vector_matrix_cache()
    yield
    chroma_store.clear_process_scan_cache()
    chroma_store.clear_vector_matrix_cache()


# --------------------------------------------------------------------------
# The memo key
# --------------------------------------------------------------------------


def test_a_memo_hit_does_not_fetch_the_ids(tmp_path, monkeypatch):
    """The whole point of the key change: a hit is a dict read.

    A hit that still called ``collection.get(include=[])`` would pay 23 ms on
    the 7,666-listing corpus for an answer it already has.
    """
    store = make_store(tmp_path)
    store.upsert_jobs([listing(1, "python sql"), listing(2, "react css")])

    store.similarities_for_all("python sql")

    # Count the id fetches after the first search populated the memo.
    calls = {"n": 0}
    original = store._collection.get

    def counting_get(*args, **kwargs):
        if not kwargs.get("ids") and not args:
            calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(store._collection, "get", counting_get)

    second = store.similarities_for_all("python sql")

    assert calls["n"] == 0, "a memo hit must not enumerate the collection"
    assert set(second) == {"test:1", "test:2"}


def test_a_memo_miss_still_scores_every_listing(tmp_path):
    """The hit path being cheap must not change what a miss returns."""
    store = make_store(tmp_path)
    store.upsert_jobs([listing(1, "python sql"), listing(2, "react css")])

    scores = store.similarities_for_all("python sql")

    assert set(scores) == {"test:1", "test:2"}
    assert scores["test:1"] > scores["test:2"]


# --------------------------------------------------------------------------
# The resident matrix
# --------------------------------------------------------------------------


def test_the_matrix_is_reused_across_searches(tmp_path):
    """A second search must not re-fetch the vectors.

    The fetch is the ~1 s item on the real corpus; reuse is the whole saving.
    This counts *vector* pages specifically, so it cannot pass by the memo
    happening to serve the same query.
    """
    store = make_store(tmp_path)
    store.upsert_jobs([listing(1, "python sql"), listing(2, "react css")])

    store.similarities_for_all("python sql")

    fetches = {"n": 0}
    original = store._collection.get

    def counting_get(*args, **kwargs):
        if "embeddings" in (kwargs.get("include") or []):
            fetches["n"] += 1
        return original(*args, **kwargs)

    store._collection.get = counting_get
    try:
        # A *different* query: the scan memo cannot serve this, so only the
        # matrix cache can.
        store.similarities_for_all("react css")
    finally:
        del store._collection.get

    assert fetches["n"] == 0, "the resident matrix must serve a new query"


def test_the_matrix_scores_match_the_page_scan(tmp_path):
    """Exactness: the matrix path and the page path must agree.

    The page scan is kept as the reference. If a future change makes the matrix
    path skip a normalization or mis-align a row, this fails.
    """
    store = make_store(tmp_path)
    store.upsert_jobs(
        [
            listing(i, body)
            for i, body in enumerate(
                ["python sql", "react css", "python react", "sql server"], start=1
            )
        ]
    )

    query = "python sql server"
    via_matrix = store.similarities_for_all(query)

    # Force the memo miss, then the matrix miss, and take the reference.
    chroma_store.clear_process_scan_cache()
    chroma_store.clear_vector_matrix_cache()
    reference: dict[str, float] = {}
    all_ids = store._collection.get(include=[]).get("ids") or []
    vector = store._embedding_fn.embed_query(chroma_store.build_query_text(query))
    for start in range(0, len(all_ids), chroma_store.SCAN_PAGE_SIZE):
        page = all_ids[start : start + chroma_store.SCAN_PAGE_SIZE]
        result = store._collection.get(ids=page, include=["embeddings"])
        page_embeddings = result.get("embeddings")
        if page_embeddings is None:  # numpy: `or []` raises on truthiness
            page_embeddings = []
        reference.update(
            store._similarities_for_page(result.get("ids") or [], page_embeddings, vector)
        )

    assert set(via_matrix) == set(reference)
    for job_id, expected in reference.items():
        assert via_matrix[job_id] == pytest.approx(expected, abs=1e-5), job_id


def test_a_write_clears_the_matrix(tmp_path):
    """A delete must not leave the matrix describing the old corpus."""
    store = make_store(tmp_path)
    store.upsert_jobs([listing(1, "python sql"), listing(2, "react css")])
    store.similarities_for_all("python sql")

    store.delete_jobs(["test:1"])

    after = store.similarities_for_all("python sql")
    assert set(after) == {"test:2"}, "the deleted listing must be gone"


def test_a_size_change_rebuilds_the_matrix(tmp_path):
    """A write by *another* process is only visible as a size change."""
    store = make_store(tmp_path)
    store.upsert_jobs([listing(1, "python sql")])
    store.similarities_for_all("python sql")

    # Simulate the worker process: write through a second store on the same
    # collection, then search through the first.
    other = ChromaVectorStore(
        embedding_fn=CountingEmbeddingFn(),
        settings=SimpleNamespace(
            chroma_dir=str(tmp_path / "chroma"),
            embedding_model="gemini-embedding-2",
            embedding_dimensionality=DIM,
        ),
    )
    other.upsert_jobs([listing(2, "react css")])

    after = store.similarities_for_all("python sql")
    assert set(after) == {"test:1", "test:2"}, "the new listing must be scored"


def test_an_expired_matrix_is_rebuilt(tmp_path, monkeypatch):
    """The TTL is what resolves a same-size write by another process."""
    store = make_store(tmp_path)
    store.upsert_jobs([listing(1, "python sql")])
    store.similarities_for_all("python sql")

    key = next(iter(chroma_store._VECTOR_MATRIX))
    stored_at, built_count, ids, matrix, degenerate = chroma_store._VECTOR_MATRIX[key]
    chroma_store._VECTOR_MATRIX[key] = (
        stored_at - chroma_store._PROCESS_SCAN_TTL_SECONDS - 1.0,
        built_count,
        ids,
        matrix,
        degenerate,
    )

    fetches = {"n": 0}
    original = store._collection.get

    def counting_get(*args, **kwargs):
        if "embeddings" in (kwargs.get("include") or []):
            fetches["n"] += 1
        return original(*args, **kwargs)

    store._collection.get = counting_get
    try:
        store.similarities_for_all("react css")
    finally:
        del store._collection.get

    assert fetches["n"] > 0, "an expired matrix must be rebuilt"


def test_an_empty_collection_scores_nothing(tmp_path):
    """An empty store has no matrix and no scores."""
    store = make_store(tmp_path)
    assert store.similarities_for_all("anything") == {}
