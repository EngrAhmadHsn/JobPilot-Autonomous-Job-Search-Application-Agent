"""WS-20 · score states, the fixed denominator, and the missing-data policy.

These are the acceptance tests for the core defect: missing information must
never be presented as a positive match, and a missing component must never
have its weight moved onto the others.
"""

from __future__ import annotations

import pytest

from src.jobs.contracts import JobListing
from src.matching.engine import calculate_match
from src.matching.scores import ComponentScore, ScoreState, blend, measured_state
from src.matching.weights import DEFAULT_WEIGHTS
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
    WorkPreferences,
)

KW = {"weights": dict(DEFAULT_WEIGHTS)}


def profile(
    skills: list[str] | None = None,
    *,
    experience: list[ExperienceEntry] | None = None,
    preferences: WorkPreferences | None = None,
) -> CandidateProfile:
    return CandidateProfile(
        personal_information=PersonalInformation(title="Engineer"),
        skills=skills or [],
        experience=experience or [],
        work_preferences=preferences or WorkPreferences(),
    )


def job(**kwargs) -> JobListing:
    defaults = {"id": "job-1", "source": "greenhouse", "title": "Engineer", "company": "Acme"}
    defaults.update(kwargs)
    return JobListing(**defaults)


# -- the states ---------------------------------------------------------------


def test_measured_state_classifies_value():
    assert measured_state(100.0) is ScoreState.MATCHED
    assert measured_state(60.0) is ScoreState.MATCHED
    assert measured_state(30.0) is ScoreState.PARTIAL_MATCH
    assert measured_state(0.0) is ScoreState.MISMATCH


def test_blend_unknown_component_keeps_its_weight():
    weights = {"a": 0.5, "b": 0.5}
    components = {
        "a": ComponentScore(name="a", value=80.0, state=ScoreState.MATCHED),
        "b": ComponentScore(name="b", value=0.0, state=ScoreState.CANDIDATE_DATA_MISSING),
    }
    result = blend(weights, components)
    assert result.overall_score == pytest.approx(40.0)  # (0.5*80 + 0.5*0) / 1.0
    assert result.evidence_coverage == pytest.approx(50.0)


def test_blend_not_applicable_is_removed_from_the_denominator():
    weights = {"a": 0.5, "b": 0.5}
    components = {
        "a": ComponentScore(name="a", value=80.0, state=ScoreState.MATCHED),
        "b": ComponentScore(name="b", value=0.0, state=ScoreState.NOT_APPLICABLE),
    }
    result = blend(weights, components)
    assert result.overall_score == pytest.approx(80.0)  # only "a" counts
    assert result.evidence_coverage == pytest.approx(100.0)


# -- missing candidate information --------------------------------------------


def test_candidate_without_dated_experience_is_unknown_not_70():
    result = calculate_match(
        job(experience_requirements="5+ years"), profile(), semantic_score=50, **KW
    )
    assert result.experience_score == 0.0
    assert result.component_states["experience"] == ScoreState.CANDIDATE_DATA_MISSING.value


def test_candidate_without_seniority_is_unknown_not_70():
    result = calculate_match(job(title="Senior Engineer"), profile(), semantic_score=50, **KW)
    assert result.seniority_score == 0.0
    assert result.component_states["seniority"] == ScoreState.CANDIDATE_DATA_MISSING.value


def test_candidate_without_preferences_is_unknown_not_70():
    result = calculate_match(
        job(remote_policy="onsite", location="NYC"), profile(), semantic_score=50, **KW
    )
    assert result.location_score == 0.0
    assert result.component_states["location"] == ScoreState.CANDIDATE_DATA_MISSING.value


def test_candidate_with_some_but_not_all_preferences():
    # employment type present, salary absent: the component is measured, not
    # unknown, and the missing half does not invent a value.
    prefs = WorkPreferences(employment_types=["full-time"])
    result = calculate_match(
        job(employment_type="full_time", salary="$100k"),
        profile(preferences=prefs),
        semantic_score=50,
        **KW,
    )
    assert result.component_states["preference"] in {
        ScoreState.MATCHED.value,
        ScoreState.PARTIAL_MATCH.value,
        ScoreState.MISMATCH.value,
    }
    assert result.preference_score == pytest.approx(100.0)


# -- missing job requirements -------------------------------------------------


def test_job_without_experience_requirement_is_unknown_not_70():
    result = calculate_match(
        job(),
        profile(experience=[ExperienceEntry(title="Dev", dates="2019 - 2024")]),
        semantic_score=50,
        **KW,
    )
    assert result.experience_score == 0.0
    assert result.component_states["experience"] == ScoreState.JOB_REQUIREMENT_MISSING.value


def test_job_without_seniority_is_unknown_not_70():
    result = calculate_match(
        job(title="Generic Role"),
        profile(experience=[ExperienceEntry(title="Senior Dev")]),
        semantic_score=50,
        **KW,
    )
    assert result.component_states["seniority"] == ScoreState.JOB_REQUIREMENT_MISSING.value


def test_job_without_structured_skills_is_unknown_not_70():
    result = calculate_match(job(), profile(["python"]), semantic_score=50, **KW)
    assert result.skill_score == 0.0
    assert result.component_states["skill"] == ScoreState.JOB_REQUIREMENT_MISSING.value


def test_unknown_is_reported_separately_from_a_mismatch():
    unknown = calculate_match(job(), profile(), semantic_score=50, **KW)
    mismatch = calculate_match(
        job(required_skills=["kubernetes"]), profile(["python"]), semantic_score=50, **KW
    )
    assert unknown.component_states["skill"] == ScoreState.JOB_REQUIREMENT_MISSING.value
    assert mismatch.component_states["skill"] == ScoreState.MISMATCH.value


# -- semantic: measured 0.0 vs unavailable ------------------------------------


def test_measured_zero_similarity_is_not_unavailable():
    measured = calculate_match(job(), profile(["python"]), semantic_score=0.0, **KW)
    unavailable = calculate_match(job(), profile(["python"]), semantic_score=None, **KW)
    assert measured.component_states["semantic"] == ScoreState.MISMATCH.value
    assert unavailable.component_states["semantic"] == ScoreState.EMBEDDING_UNAVAILABLE.value


def test_pending_embedding_state_is_reported():
    result = calculate_match(
        job(),
        profile(["python"]),
        semantic_score=None,
        semantic_state=ScoreState.EMBEDDING_PENDING,
        **KW,
    )
    assert result.component_states["semantic"] == ScoreState.EMBEDDING_PENDING.value


# -- the fixed denominator ----------------------------------------------------


def test_no_weight_redistribution_when_semantic_is_missing():
    """The regression test for the WS-03 defect.

    Before WS-20 the semantic weight was redistributed across the remaining
    components (``redistribute_without``), so a vector-less listing was scored
    over a denominator that excluded semantics — and could outrank an
    identical, fully-indexed listing. Now the denominator is fixed and the
    missing component contributes zero.
    """
    rich = job(required_skills=["python", "sql"], experience_requirements="3+ years")
    candidate = profile(
        ["python", "sql"],
        experience=[ExperienceEntry(title="Engineer", dates="2020 - present")],
    )
    with_vector = calculate_match(rich, candidate, semantic_score=95, **KW)
    without_vector = calculate_match(rich, candidate, semantic_score=None, **KW)

    # The denominator never changes: the full configured weight set.
    total = sum(DEFAULT_WEIGHTS.values())
    assert total == pytest.approx(1.0)
    expected = (
        sum(
            DEFAULT_WEIGHTS[name] * without_vector.__dict__[f"{name}_score"]
            for name in DEFAULT_WEIGHTS
        )
        / total
    )
    assert without_vector.overall_score == pytest.approx(expected)
    # And a missing vector can never beat a good measured one.
    assert without_vector.overall_score < with_vector.overall_score


def test_overall_stays_within_bounds_for_extremes():
    for semantic in (None, 0.0, 100.0):
        result = calculate_match(job(), profile(), semantic_score=semantic, **KW)
        assert 0.0 <= result.overall_score <= 100.0
        assert 0.0 <= result.evidence_coverage <= 100.0


def test_all_jobs_missing_vectors_yield_zero_semantic_coverage():
    result = calculate_match(job(), profile(["python"]), semantic_score=None, **KW)
    assert result.semantic_score == 0.0
    assert result.evidence_coverage < 100.0
