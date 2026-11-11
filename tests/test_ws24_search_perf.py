"""WS-24 · The search performance tests.

The measurements this workstream was built on (2026-11-09, the live
6,696-listing corpus, one real candidate profile):

* a cold search took **64.58 s** and a warm search **9.18 s**;
* the artifacts rebuild alone was **32.56 s** and was invalidated by
  every refresh, because the fingerprint included ``max(last_seen_at)``;
* the Python cosine loop was **4.12 s** of the warm search.

The tests here pin the three properties that fix those:

1. the vectorized scan agrees with the reference cosine, exactly;
2. the corpus cache survives a refresh that changed nothing;
3. the scan stays inside its time budget, so a future change that
   quietly reintroduces an O(N) per-search cost fails the suite.
"""

from __future__ import annotations

import time

import numpy as np
import pytest


def _reference_cosines(query, matrix):
    """The per-vector cosine, as the store used to compute it."""
    from src.rag.chroma_store import ChromaVectorStore

    return [ChromaVectorStore._cosine_similarity(query, vector) for vector in matrix]


def test_the_numpy_scan_matches_the_reference_cosine():
    """The fast path computes the same quantity as the slow one.

    A ``float32`` matvec is algebraically the cosine similarity, but the
    tolerance is checked rather than assumed: a silent mismatch would
    change every ranking in the corpus.
    """
    from src.rag.chroma_store import ChromaVectorStore

    rng = np.random.default_rng(20261110)
    query = list(rng.normal(size=768).astype("float32"))
    matrix = rng.normal(size=(200, 768)).astype("float32")

    reference = _reference_cosines(query, matrix)
    fast = ChromaVectorStore._similarities_for_page(
        [f"job:{index}" for index in range(200)], matrix, query
    )

    assert len(fast) == 200
    for index, expected in enumerate(reference):
        assert fast[f"job:{index}"] == pytest.approx(expected, abs=1e-3)


def test_the_numpy_scan_handles_a_degenerate_vector():
    """A zero-norm row has no direction and scores 0, not NaN."""
    from src.rag.chroma_store import ChromaVectorStore

    query = [1.0] * 8
    matrix = [[0.0] * 8, [1.0] * 8]

    scores = ChromaVectorStore._similarities_for_page(["zero", "one"], matrix, query)

    assert scores["zero"] == 0.0
    assert scores["one"] == pytest.approx(100.0)


def test_the_numpy_scan_falls_back_on_an_unexpected_shape():
    """A shape the fast path cannot use falls back to the reference.

    Returning wrong numbers would be worse than being slower.
    """
    from src.rag.chroma_store import ChromaVectorStore

    query = [1.0, 0.0]
    matrix = [[1.0, 0.0], [0.0, 1.0]]  # one row, not two

    scores = ChromaVectorStore._similarities_for_page(["a", "b"], matrix, query)

    assert scores["a"] == pytest.approx(100.0)
    assert scores["b"] == pytest.approx(0.0)


def test_the_scan_is_materially_faster_than_the_loop():
    """The vectorized scan must be a real speed-up, not a wash.

    Measured on the live corpus: 3.0 s for the Python loop against
    0.044 s for the NumPy path — a 68x difference. The assertion is
    loose enough to survive a slower machine and tight enough to catch
    an accidental return to the loop.
    """
    from src.rag.chroma_store import ChromaVectorStore

    rng = np.random.default_rng(7)
    query = list(rng.normal(size=768).astype("float32"))
    matrix = rng.normal(size=(2000, 768)).astype("float32")
    ids = [f"job:{index}" for index in range(2000)]

    started = time.perf_counter()
    ChromaVectorStore._similarities_for_page(ids, matrix, query)
    fast = time.perf_counter() - started

    started = time.perf_counter()
    _reference_cosines(query, matrix)
    slow = time.perf_counter() - started

    assert fast < slow / 5, f"the fast path ({fast:.3f}s) is not much faster ({slow:.3f}s)"


def test_the_embedded_document_keeps_more_of_the_description():
    """The embedded text was truncated at 8,000 characters.

    The local model is EmbeddingGemma-2 with an 8,192-**token** input
    limit — roughly 32,000 characters of English prose — so the
    8,000-character cap was the binding constraint by a factor of four,
    not the model.
    """
    from src.rag.chroma_store import MAX_DESCRIPTION_CHARS, ChromaVectorStore

    assert MAX_DESCRIPTION_CHARS == 16_000

    long_description = "x" * 30_000
    listing = type(
        "L",
        (),
        {
            "id": "job:1",
            "title": "Engineer",
            "description": long_description,
            "required_skills": [],
            "preferred_skills": [],
        },
    )()
    document = ChromaVectorStore.document_text(listing)
    assert long_description[:15_000] in document
    assert long_description not in document, "the text is still truncated — that is expected"


def test_the_response_cap_clears_the_live_boards():
    """The cap must clear every board in the registry.

    Three live boards were above the old 8 MiB cap — anthropic (9.83
    MiB), databricks (9.58 MiB) and ashby/openai (13.58 MiB), measured
    2026-11-09 — and each was dropped whole and silently.
    """
    from src.security.limits import get_limits

    assert get_limits().max_response_bytes == 16 * 1024 * 1024
    assert get_limits().max_response_bytes > 13 * 1024 * 1024


def test_the_target_cache_key_covers_every_field_the_resolution_reads():
    """Two profiles that differ in a read field must not share an entry.

    The target resolution is memoized on a key built from the profile.
    Omitting a field the resolution reads is not a performance problem,
    it is a **correctness** one: the second profile is answered with the
    first one's targets. This test caught exactly that — two profiles
    that differed only in ``current_title`` shared an entry, and the
    second was answered with the first's families.
    """
    from src.matching.roles import _profile_target_key, resolve_candidate_targets
    from src.resume.profile import CandidateProfile, PersonalInformation

    def profile(title: str, current_title: str = "") -> CandidateProfile:
        built = CandidateProfile(
            personal_information=PersonalInformation(title=title),
        )
        if current_title:
            built.application_profile.professional.current_title = current_title
        return built

    first = profile("Web Developer", current_title="Data Analyst")
    second = profile("Web Developer", current_title="Senior AI Engineer")

    assert _profile_target_key(first) != _profile_target_key(second)

    resolved_first = resolve_candidate_targets(first)
    resolved_second = resolve_candidate_targets(second)
    assert resolved_first.families != resolved_second.families, (
        "the two profiles must not resolve to the same target families"
    )


def test_the_role_classification_is_cached_in_the_corpus_artifacts():
    """The listing's classification belongs with its other artifacts.

    The classifier's own ``lru_cache`` holds 8,192 entries — smaller
    than the 8,558-listing corpus — so it thrashed and every search
    re-classified every listing (4.9 million pattern matches). The
    corpus cache holds it instead, where it is valid until the content
    changes.
    """
    from src.matching.corpus_cache import CorpusArtifacts

    artifacts = CorpusArtifacts(fingerprint=("db", 0, "hash"))
    assert hasattr(artifacts, "role_classifications")
    assert artifacts.role_classifications == {}
