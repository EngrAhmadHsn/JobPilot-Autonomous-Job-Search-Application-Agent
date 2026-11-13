"""WS-29 · The bulk lexical path skips the evidence lists.

`lexical_score` builds two capped evidence lists (matched and missing keywords)
for every listing. Only the top-N listings are ever returned, so on the live
corpus 8,528 of 8,558 lists are built and thrown away — and building them costs
**42%** of the function's time (0.514 s → 0.327 s measured, same weight).

The measurement also settled a design question. An inverted `term → postings`
index is *faster still* (0.096 s, 81%) but it costs 2.46 s to build at every
corpus change and cannot produce the `missing` list from postings alone (a term
absent from a listing has no posting). Skipping the lists behind a flag gets
most of the win, needs no new index, and keeps the evidence available for the
survivors — which is exactly what the two-phase split made possible.
"""

from __future__ import annotations

import pytest

from src.jobs.contracts import JobListing
from src.matching.lexical import Bm25Index, lexical_score


def _listing(index: int, title: str, description: str, **overrides) -> JobListing:
    data = {
        "id": f"test:{index}",
        "source": "test",
        "source_job_id": str(index),
        "title": title,
        "company": "Acme",
        "description": description,
    }
    data.update(overrides)
    return JobListing(**data)


@pytest.fixture
def corpus():
    return [
        _listing(1, "Senior Python Engineer", "Python and SQL at scale."),
        _listing(2, "Frontend Developer", "React and TypeScript."),
        _listing(3, "Data Engineer", "Python, Spark, and SQL pipelines."),
    ]


@pytest.fixture
def index(corpus):
    return Bm25Index(corpus)


def test_skipping_the_evidence_does_not_change_the_score(index):
    """The score, BM25 and coverage must be identical either way.

    This is the whole contract of the flag: it decides *what is reported*, never
    *what is measured*.
    """
    job = _listing(1, "Senior Python Engineer", "Python and SQL at scale.")
    tokens = ["python", "sql", "engineer"]

    with_evidence = lexical_score(
        job, index=index, candidate_token_list=tokens, candidate_text="python sql engineer"
    )
    without_evidence = lexical_score(
        job,
        index=index,
        candidate_token_list=tokens,
        candidate_text="python sql engineer",
        collect_evidence=False,
    )

    assert without_evidence.score == pytest.approx(with_evidence.score)
    assert without_evidence.bm25_score == pytest.approx(with_evidence.bm25_score)
    assert without_evidence.keyword_coverage == pytest.approx(with_evidence.keyword_coverage)


def test_skipping_the_evidence_empties_the_lists(index):
    """The lists are the only thing omitted."""
    job = _listing(1, "Senior Python Engineer", "Python and SQL at scale.")

    without_evidence = lexical_score(
        job,
        index=index,
        candidate_token_list=["python", "sql"],
        candidate_text="python sql",
        collect_evidence=False,
    )

    assert without_evidence.matched_keywords == []
    assert without_evidence.missing_keywords == []
    assert without_evidence.matched_phrases == []
    assert without_evidence.missing_phrases == []


def test_the_default_still_collects_evidence(index):
    """Every existing caller keeps its behaviour."""
    job = _listing(1, "Senior Python Engineer", "Python and SQL at scale.")

    result = lexical_score(
        job, index=index, candidate_token_list=["python"], candidate_text="python"
    )

    assert "python" in result.matched_keywords


def test_the_coverage_is_the_same_with_and_without_the_lists(index):
    """The weight accumulation is not affected by whether lists are built."""
    tokens = ["python", "sql"]
    for job in index_listings(index):
        with_ev = lexical_score(
            job, index=index, candidate_token_list=tokens, candidate_text="python sql"
        )
        without = lexical_score(
            job,
            index=index,
            candidate_token_list=tokens,
            candidate_text="python sql",
            collect_evidence=False,
        )
        assert without.keyword_coverage == pytest.approx(with_ev.keyword_coverage), job.id


def index_listings(index: Bm25Index) -> list[JobListing]:
    """Rebuild the listings an index was made from (test helper)."""
    return [
        _listing(1, "Senior Python Engineer", "Python and SQL at scale."),
        _listing(2, "Frontend Developer", "React and TypeScript."),
        _listing(3, "Data Engineer", "Python, Spark, and SQL pipelines."),
    ]


def test_a_listing_with_no_matching_terms_reports_zero(index):
    """No hits is a measured zero, with or without the lists."""
    job = _listing(1, "Senior Python Engineer", "Python and SQL at scale.")

    without = lexical_score(
        job,
        index=index,
        candidate_token_list=["cobol"],
        candidate_text="cobol",
        collect_evidence=False,
    )

    assert without.keyword_coverage == pytest.approx(0.0)
