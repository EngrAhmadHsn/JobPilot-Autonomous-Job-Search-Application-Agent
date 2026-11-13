"""WS-29 · Materialize the survivors, score the rest.

Measured on the live corpus: `calculate_match` over 8,558 listings costs 1.91 s,
and **99.6%** of the 23-field `JobMatchResult` objects it builds are discarded
at `top_n=30` — 8,558 explanations totalling 7.38 M characters.

The split must change *when* that materialization happens, never *what* it
produces: the same numbers, the same ordering, the same tie-break.
"""

from __future__ import annotations

import pytest

from src.jobs.contracts import JobListing
from src.matching.engine import CandidateContext, calculate_match, score_listing
from src.matching.lexical import Bm25Index, lexical_score
from src.matching.scores import ScoreState
from src.resume.profile import CandidateProfile, WorkPreferences


def _listing(index: int, **overrides) -> JobListing:
    data = {
        "id": f"test:{index}",
        "source": "test",
        "source_job_id": str(index),
        "title": "Senior Backend Engineer",
        "company": "Acme",
        "description": "Python and SQL at scale.",
        "required_skills": ["Python", "SQL"],
        "experience_requirements": "5 years",
        "location": "Berlin",
        "remote_policy": "hybrid",
    }
    data.update(overrides)
    return JobListing(**data)


def _profile() -> CandidateProfile:
    return CandidateProfile(
        skills=["Python", "SQL", "Go"],
        work_preferences=WorkPreferences(preferred_locations=["Berlin"]),
    )


def test_the_cheap_score_matches_the_full_result():
    """`score_listing` must produce the same numbers `calculate_match` does."""
    profile = _profile()
    context = CandidateContext.for_profile(profile)
    jobs = [_listing(i) for i in range(1, 6)]
    index = Bm25Index(jobs)

    for job in jobs:
        lexical = lexical_score(
            job, index=index, candidate_token_list=["python", "sql"], candidate_text="python sql"
        )
        cheap = score_listing(
            job,
            profile,
            semantic_score=50.0,
            lexical=lexical,
            context=context,
        )
        full = calculate_match(
            job,
            profile,
            semantic_score=50.0,
            lexical=lexical,
            context=context,
        )
        assert cheap.overall_score == pytest.approx(full.overall_score)
        assert cheap.evidence_coverage == pytest.approx(full.evidence_coverage)
        assert cheap.role_capped == full.role_capped


def test_the_cheap_score_does_not_build_a_full_result():
    """The point of the split: no explanation, no notes, no component states."""
    profile = _profile()
    context = CandidateContext.for_profile(profile)
    job = _listing(1)
    index = Bm25Index([job])
    lexical = lexical_score(
        job, index=index, candidate_token_list=["python"], candidate_text="python"
    )

    score = score_listing(
        job,
        profile,
        semantic_score=None,
        semantic_state=ScoreState.EMBEDDING_UNAVAILABLE,
        lexical=lexical,
        context=context,
    )

    assert not hasattr(score, "explanation")
    assert not hasattr(score, "component_states")


def test_a_role_capped_listing_is_capped_in_both_paths():
    """The role cap is part of the ranking number, not the materialization.

    A candidate with one narrow target and a listing in a different family is
    capped at ROLE_MISMATCH_CAP; the cheap path must report that, or the
    ranking would differ from the full path on exactly the listings the cap
    exists to demote.
    """
    from src.matching.roles import ROLE_MISMATCH_CAP
    from src.resume.application_profile import ApplicationProfile, JobSearchPreferences

    profile = CandidateProfile(
        skills=["Python"],
        application_profile=ApplicationProfile(
            # The marker is the dotted path, not the group: `roles.py` checks
            # `"preferences.target_roles" in confirmed_fields` to decide the
            # target list is authoritative.
            preferences=JobSearchPreferences(target_roles=["Graphic Designer"]),
            confirmed_fields=["preferences.target_roles"],
        ),
    )
    context = CandidateContext.for_profile(profile)
    job = _listing(1, title="Senior Backend Engineer", description="Python and SQL.")
    index = Bm25Index([job])
    lexical = lexical_score(
        job, index=index, candidate_token_list=["python"], candidate_text="python"
    )

    cheap = score_listing(job, profile, semantic_score=90.0, lexical=lexical, context=context)
    full = calculate_match(job, profile, semantic_score=90.0, lexical=lexical, context=context)

    assert full.role_capped is True
    assert cheap.role_capped is True
    assert cheap.overall_score <= ROLE_MISMATCH_CAP
    assert cheap.overall_score == pytest.approx(full.overall_score)


def test_the_ranking_is_unchanged_by_the_split():
    """The two-phase order must equal the one-phase order, ties included.

    Ties are the risk: the sort key is `(-score, job.id)`, and a split that
    sorted on score alone would order them differently.
    """
    profile = _profile()
    context = CandidateContext.for_profile(profile)
    # Three identical listings, so only the id tie-break decides the order.
    jobs = [_listing(i, description="Python and SQL at scale.") for i in (3, 1, 2)]
    index = Bm25Index(jobs)

    def lexical_for(job):
        return lexical_score(
            job, index=index, candidate_token_list=["python", "sql"], candidate_text="python sql"
        )

    one_phase = sorted(
        (
            job.id,
            calculate_match(
                job, profile, semantic_score=40.0, lexical=lexical_for(job), context=context
            ).overall_score,
        )
        for job in jobs
    )
    one_phase = sorted(one_phase, key=lambda row: (-row[1], row[0]))

    two_phase = sorted(
        (
            job.id,
            score_listing(
                job, profile, semantic_score=40.0, lexical=lexical_for(job), context=context
            ).overall_score,
        )
        for job in jobs
    )
    two_phase = sorted(two_phase, key=lambda row: (-row[1], row[0]))

    assert [row[0] for row in two_phase] == [row[0] for row in one_phase]
    assert two_phase == one_phase


def test_the_survivors_get_the_identical_full_result():
    """Phase 2 must produce the full result, not a re-score with different input."""
    profile = _profile()
    context = CandidateContext.for_profile(profile)
    job = _listing(7)
    index = Bm25Index([job])
    lexical = lexical_score(
        job, index=index, candidate_token_list=["python", "sql"], candidate_text="python sql"
    )

    cheap = score_listing(job, profile, semantic_score=33.0, lexical=lexical, context=context)
    full = calculate_match(job, profile, semantic_score=33.0, lexical=lexical, context=context)

    assert full.overall_score == pytest.approx(cheap.overall_score)
    assert full.explanation
    assert full.component_states


def test_an_unknown_semantic_score_is_handled_identically():
    """The embedding-unavailable state must not diverge between the paths."""
    profile = _profile()
    context = CandidateContext.for_profile(profile)
    job = _listing(1)
    index = Bm25Index([job])
    lexical = lexical_score(
        job, index=index, candidate_token_list=["python"], candidate_text="python"
    )

    cheap = score_listing(
        job,
        profile,
        semantic_score=None,
        semantic_state=ScoreState.EMBEDDING_PENDING,
        lexical=lexical,
        context=context,
    )
    full = calculate_match(
        job,
        profile,
        semantic_score=None,
        semantic_state=ScoreState.EMBEDDING_PENDING,
        lexical=lexical,
        context=context,
    )

    assert cheap.overall_score == pytest.approx(full.overall_score)
    assert full.component_states["semantic"] == ScoreState.EMBEDDING_PENDING.value
