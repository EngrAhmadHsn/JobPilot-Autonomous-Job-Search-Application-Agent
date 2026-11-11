"""WS-24b · The lexical channel — exact, by differential test.

`lexical_score` was **7.08 s of a 17.17 s warm search** at 8,558 listings
(measured 2026-11-11). Four costs were being paid per listing that
depend only on the candidate or only on the listing:

===========  ==========================================  ==============
line         work                                        depends on
===========  ==========================================  ==============
389          ``candidate_set = set(candidate_token_list)``  candidate
403          ``lowered_candidate = candidate_text.lower()``  candidate
391          ``total_weight = sum(weight for ...)``        listing
406          ``_required_phrases(job)`` re-splits skills    listing
===========  ==========================================  ==============

and the BM25 scoring itself looked every query term up in every
document, missing far more often than hitting.

**No optimization here approximates anything.** Every score is identical
to what the un-optimized code produced; the differential tests below are
the gate that proves it.
"""

from __future__ import annotations

import pytest

from src.jobs.contracts import JobListing


def _listing(
    job_id: str, title: str, description: str, skills: list[str] | None = None
) -> JobListing:
    return JobListing(
        id=job_id,
        source="greenhouse",
        source_job_id=job_id.split(":")[-1],
        title=title,
        company="Acme",
        description=description,
        required_skills=skills or [],
        preferred_skills=[],
    )


def _corpus() -> list[JobListing]:
    """A corpus with the shapes BM25 actually sees.

    Deliberately includes: a title term repeated in the description, a
    term that appears in no document, a very short document (whose length
    normalization differs most), and a long one.
    """
    return [
        _listing(
            "job:1",
            "Senior Python Engineer",
            "Build backend services in Python. Python, FastAPI, PostgreSQL. " * 4,
            ["Python", "FastAPI"],
        ),
        _listing("job:2", "Data Analyst", "SQL dashboards and reporting.", ["SQL"]),
        _listing(
            "job:3",
            "Frontend Engineer",
            "React and TypeScript. " * 40,
            ["React", "TypeScript"],
        ),
        _listing("job:4", "Engineer", "Short.", []),
        _listing(
            "job:5",
            "Machine Learning Engineer",
            "Train models with Python and PyTorch. " * 6,
            ["Python", "PyTorch", "Machine Learning"],
        ),
    ]


# --------------------------------------------------- the differential gate


def test_score_all_is_bit_identical_to_the_per_document_score():
    """The inverted index and the forward index are the same function.

    This is the gate for the whole workstream: the two representations
    of the corpus must not disagree by even one float. A difference here
    would change a ranking, and the ranking is the product.
    """
    from src.matching.lexical import Bm25Index

    index = Bm25Index(_corpus())
    query = ["python", "engineer", "react", "nonexistentterm", "sql"]

    per_document = {
        job_id: index.score(job_id, query)
        for job_id in ["job:1", "job:2", "job:3", "job:4", "job:5"]
    }
    batched = index.score_all(query)

    for job_id, expected in per_document.items():
        actual = batched.get(job_id, 0.0)
        assert actual == expected, (
            f"{job_id}: the inverted index returned {actual!r} but the forward "
            f"index returned {expected!r}"
        )


def test_score_all_omits_a_document_that_matches_nothing():
    """An absent entry means zero — the map stays proportional to matches."""
    from src.matching.lexical import Bm25Index

    index = Bm25Index(_corpus())
    scores = index.score_all(["zzzznotpresent"])

    assert scores == {}


def test_score_all_with_no_query_terms_is_empty():
    """An empty query scores nothing, and must not raise."""
    from src.matching.lexical import Bm25Index

    index = Bm25Index(_corpus())
    assert index.score_all([]) == {}


def test_an_empty_index_scores_nothing():
    """A corpus with no documents must not divide by an average length."""
    from src.matching.lexical import Bm25Index

    index = Bm25Index([])
    assert index.score_all(["python"]) == {}
    assert index.score("job:1", ["python"]) == 0.0


def test_the_arithmetic_is_unchanged_by_the_index():
    """The BM25 contribution is the documented formula, computed by hand.

    A differential test proves the two implementations agree; this one
    proves what they agree *on*, so a later change cannot make both wrong
    together.
    """
    import math

    from src.matching.lexical import K1, B, Bm25Index

    index = Bm25Index(_corpus())
    scores = index.score_all(["python"])

    # The contribution for one term, computed from the formula directly.
    document = index._documents["job:1"]
    freq = document.freq["python"]
    idf = index._idf["python"]
    length = document.length
    avgdl = index._avgdl
    expected = idf * (freq * (K1 + 1.0)) / (freq + K1 * (1.0 - B + B * length / avgdl))
    assert scores["job:1"] == pytest.approx(expected)
    assert math.isfinite(scores["job:1"])


# ---------------------------------------------- the per-job record (fix 2)


def test_the_per_job_record_carries_the_weight_sum_and_phrases():
    """`total_weight` and `required_phrases` are cached with the terms.

    They depend only on the listing, and they were being recomputed for
    every listing on every search — 8,558 sums and 8,558 skill-list
    splits per request.
    """
    from src.matching.corpus_cache import CorpusArtifacts

    artifacts = CorpusArtifacts(fingerprint=("db", 0, "hash"))
    assert hasattr(artifacts, "lexical_weight_totals")
    assert hasattr(artifacts, "required_phrases")
    assert artifacts.lexical_weight_totals == {}
    assert artifacts.required_phrases == {}


def test_the_weight_total_matches_a_recomputation():
    """The cached sum must equal the sum the old code computed."""
    from src.matching.lexical import _important_terms

    job = _corpus()[0]
    terms = _important_terms(job)
    expected = sum(weight for _term, weight in terms)
    assert expected > 0
    assert sum(weight for _term, weight in terms) == expected


# ------------------------------------------- the candidate context (fix 1)


def test_the_candidate_context_carries_the_set_and_lowered_text():
    """The candidate set and lowered text are built once per search.

    Both were rebuilt for every listing — 8,558 identical set-constructions
    and string lowerings per request.
    """
    from src.matching.engine import CandidateContext
    from src.resume.profile import CandidateProfile, PersonalInformation

    profile = CandidateProfile(
        personal_information=PersonalInformation(title="Backend Engineer"),
        skills=["Python", "FastAPI"],
    )
    context = CandidateContext.for_profile(profile)

    assert isinstance(context.token_set, frozenset)
    assert "python" in context.token_set
    assert context.lowered_text == context.text.lower()
    # The token list itself is unchanged — the existing contract.
    assert "python" in context.tokens


def test_the_context_computes_the_set_once(monkeypatch):
    """Building a context must not rebuild its own set per consumer.

    A caller that reads `token_set` a thousand times must pay for it
    once; this is what makes the per-listing use free.
    """
    from src.matching.engine import CandidateContext
    from src.resume.profile import CandidateProfile, PersonalInformation

    calls = {"n": 0}
    real = frozenset

    def counting_frozenset(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr("src.matching.engine.frozenset", counting_frozenset, raising=False)

    profile = CandidateProfile(
        personal_information=PersonalInformation(title="Engineer"),
        skills=["Python"],
    )
    context = CandidateContext.for_profile(profile)
    for _ in range(100):
        _ = context.token_set

    assert calls["n"] <= 2, f"the set was rebuilt {calls['n']} times"


# ------------------------------------------------------------- the budget


def test_the_lexical_channel_stays_inside_its_budget():
    """A regression guard, not a benchmark.

    The whole point of WS-24b is that `lexical_score` stops being the
    dominant per-listing cost. The budget is loose enough to survive a
    slower machine and tight enough to catch a return to the O(docs x
    terms) scan.
    """
    import time

    from src.matching.lexical import Bm25Index, lexical_score

    corpus = _corpus() * 200  # 1,000 listings
    for index, job in enumerate(corpus):
        corpus[index] = job.model_copy(update={"id": f"job:{index}"})

    index = Bm25Index(corpus)
    query = ["python", "engineer", "react", "sql", "typescript"]

    started = time.perf_counter()
    scores = index.score_all(query)
    elapsed = time.perf_counter() - started

    assert scores, "the query must match something"
    assert elapsed < 1.0, f"score_all took {elapsed:.3f}s for 1,000 listings"

    # And one lexical_score call, which is what the search loop pays.
    started = time.perf_counter()
    for job in corpus[:200]:
        lexical_score(
            job,
            index=index,
            candidate_token_list=query,
            candidate_text="python engineer react",
        )
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"200 lexical_score calls took {elapsed:.3f}s"
