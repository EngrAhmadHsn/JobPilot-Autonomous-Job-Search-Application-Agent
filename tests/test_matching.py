"""Tests for the WS-03 hybrid matching engine: real scorers, boundaries,
weights, degraded mode, and end-to-end determinism with a FakeEmbeddingFn."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.jobs.contracts import JobListing
from src.matching.contracts import JobMatchResult
from src.matching.engine import calculate_match
from src.matching.experience import (
    experience_score,
    required_years,
    years_of_experience,
)
from src.matching.weights import DEFAULT_WEIGHTS
from src.rag.chroma_store import ChromaVectorStore, candidate_query_text
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
    WorkPreferences,
)

# --- helpers -----------------------------------------------------------------


def make_profile(
    skills: list[str] | None = None,
    experience: list[ExperienceEntry] | None = None,
    preferences: WorkPreferences | None = None,
) -> CandidateProfile:
    return CandidateProfile(
        personal_information=PersonalInformation(title="Engineer"),
        skills=skills or [],
        experience=experience or [],
        work_preferences=preferences or WorkPreferences(),
    )


def make_job(**kwargs) -> JobListing:
    defaults = {"id": "job-1", "source": "greenhouse", "title": "Engineer", "company": "Acme"}
    defaults.update(kwargs)
    return JobListing(**defaults)


DEFAULT_KW = {"weights": dict(DEFAULT_WEIGHTS)}


# --- skill scorer --------------------------------------------------------------


def test_skill_full_overlap_scores_100():
    job = make_job(required_skills=["python", "sql"], preferred_skills=["aws"])
    result = calculate_match(
        job, make_profile(["Python", "SQL", "AWS"]), semantic_score=50, **DEFAULT_KW
    )
    assert result.skill_score == 100.0
    assert set(result.matched_requirements) == {"python", "sql", "aws"}


def test_skill_preferred_hits_count_half():
    # required 2, preferred 1, only "python" matched: (1 + 0) / (2 + 0.5) = 40
    job = make_job(required_skills=["python", "sql"], preferred_skills=["aws"])
    result = calculate_match(job, make_profile(["python"]), semantic_score=50, **DEFAULT_KW)
    assert result.skill_score == pytest.approx(40.0)
    assert result.matched_requirements == ["python"]
    assert set(result.missing_requirements) == {"sql", "aws"}


def test_skill_matching_is_case_insensitive_but_lists_keep_job_casing():
    job = make_job(required_skills=["Python"])
    result = calculate_match(job, make_profile(["PYTHON"]), semantic_score=50, **DEFAULT_KW)
    assert result.skill_score == 100.0
    assert result.matched_requirements == ["Python"]


def test_job_without_stated_skills_is_neutral():
    job = make_job()
    result = calculate_match(job, make_profile(["python"]), semantic_score=50, **DEFAULT_KW)
    assert result.skill_score == 70.0
    assert result.matched_requirements == []


def test_missing_skill_listed():
    job = make_job(required_skills=["kubernetes"])
    result = calculate_match(job, make_profile([]), semantic_score=50, **DEFAULT_KW)
    assert "kubernetes" in result.missing_requirements
    assert len(result.explanation) > 0


# --- experience ----------------------------------------------------------------


def test_years_of_experience_sums_dated_entries():
    profile = make_profile(
        experience=[
            ExperienceEntry(title="Dev", company="A", dates="2019 - 2022"),
            ExperienceEntry(title="Dev", company="B", dates="2022 - present"),
        ]
    )
    expected = 3.0 + 4.0  # 2026 "present"
    assert years_of_experience(profile) == pytest.approx(expected)


def test_years_of_experience_none_without_dates():
    profile = make_profile(experience=[ExperienceEntry(title="Dev", company="A", dates="")])
    assert years_of_experience(profile) is None
    assert years_of_experience(make_profile()) is None


def test_years_falls_back_to_explicit_entry_years():
    profile = make_profile(experience=[ExperienceEntry(title="Dev", company="A", years=3)])
    assert years_of_experience(profile) == 3.0


def test_required_years_plus_format():
    assert required_years(make_job(experience_requirements="5+ years")) == 5.0


def test_required_years_range_takes_top():
    assert required_years(make_job(experience_requirements="3-5 years")) == 5.0


def test_required_years_from_description_first_line():
    job = make_job(description="At least 2 years of experience required.\nMore text.")
    assert required_years(job) == 2.0


def test_required_years_none_when_unstated():
    assert required_years(make_job()) is None


def test_experience_score_meets_requirement():
    job = make_job(experience_requirements="5+ years")
    profile = make_profile(experience=[ExperienceEntry(title="Dev", dates="2019 - 2024")])
    assert experience_score(job, profile) == 100.0


def test_experience_score_shortfall_penalized_25_per_year():
    job = make_job(experience_requirements="5+ years")
    profile = make_profile(experience=[ExperienceEntry(title="Dev", dates="2023 - present")])
    assert experience_score(job, profile) == pytest.approx(50.0)  # 3 years vs 5


def test_experience_score_neutral_without_requirement():
    assert experience_score(make_job(), make_profile()) == 70.0


def test_experience_score_neutral_when_candidate_undated():
    job = make_job(experience_requirements="5+ years")
    assert experience_score(job, make_profile()) == 70.0


# --- seniority -------------------------------------------------------------------


def test_seniority_exact_match_scores_100():
    job = make_job(title="Senior Python Developer")
    profile = make_profile(experience=[ExperienceEntry(title="Senior Backend Engineer")])
    result = calculate_match(job, profile, semantic_score=50, **DEFAULT_KW)
    assert result.seniority_score == 100.0


def test_seniority_gap_penalized_30_per_rank():
    job = make_job(title="Senior Platform Engineer")
    profile = make_profile(experience=[ExperienceEntry(title="Junior Developer")])
    result = calculate_match(job, profile, semantic_score=50, **DEFAULT_KW)
    assert result.seniority_score == pytest.approx(40.0)  # gap 2 -> 100 - 60


def test_seniority_unknown_candidate_is_neutral():
    job = make_job(title="Senior Platform Engineer")
    result = calculate_match(job, make_profile(), semantic_score=50, **DEFAULT_KW)
    assert result.seniority_score == 70.0


def test_job_seniority_field_takes_precedence_over_title():
    job = make_job(title="Grand Title Nobody Ranks", seniority="junior")
    profile = make_profile(experience=[ExperienceEntry(title="Senior Developer")])
    result = calculate_match(job, profile, semantic_score=50, **DEFAULT_KW)
    assert result.seniority_score == pytest.approx(40.0)


def test_intern_keyword_not_matched_inside_other_words():
    job = make_job(title="International Sales Manager")
    profile = make_profile(experience=[ExperienceEntry(title="Mid-level Analyst")])
    # job title has no rank keyword ("international" != "intern"); neutral.
    result = calculate_match(job, profile, semantic_score=50, **DEFAULT_KW)
    assert result.seniority_score == 70.0


# --- location ---------------------------------------------------------------------


def test_location_remote_job_scores_100():
    job = make_job(remote_policy="remote", location="Anywhere")
    result = calculate_match(job, make_profile(), semantic_score=50, **DEFAULT_KW)
    assert result.location_score == 100.0


def test_location_preferred_city_match_scores_100():
    prefs = WorkPreferences(preferred_locations=["Berlin"])
    job = make_job(remote_policy="onsite", location="Berlin, Germany")
    result = calculate_match(job, make_profile(preferences=prefs), semantic_score=50, **DEFAULT_KW)
    assert result.location_score == 100.0


def test_location_no_preferences_is_neutral():
    job = make_job(remote_policy="onsite", location="New York")
    result = calculate_match(job, make_profile(), semantic_score=50, **DEFAULT_KW)
    assert result.location_score == 70.0


def test_location_onsite_conflict_scores_25():
    prefs = WorkPreferences(remote_preference="remote", preferred_locations=["Lahore"])
    job = make_job(remote_policy="onsite", location="New York")
    result = calculate_match(job, make_profile(preferences=prefs), semantic_score=50, **DEFAULT_KW)
    assert result.location_score == 25.0


def test_location_prefers_onsite_policy_normalization():
    prefs = WorkPreferences(preferred_locations=["Lahore"])
    job = make_job(remote_policy="on-site", location="New York")
    result = calculate_match(job, make_profile(preferences=prefs), semantic_score=50, **DEFAULT_KW)
    assert result.location_score == 25.0


# --- preference ---------------------------------------------------------------------


def test_preference_employment_match_scores_100():
    prefs = WorkPreferences(employment_types=["full-time"])
    job = make_job(employment_type="full_time")
    result = calculate_match(job, make_profile(preferences=prefs), semantic_score=50, **DEFAULT_KW)
    assert result.preference_score == 100.0


def test_preference_employment_mismatch_scores_40():
    prefs = WorkPreferences(employment_types=["full-time"])
    job = make_job(employment_type="contract")
    result = calculate_match(job, make_profile(preferences=prefs), semantic_score=50, **DEFAULT_KW)
    assert result.preference_score == 40.0


def test_preference_salary_floor_respected_scores_100():
    prefs = WorkPreferences(min_salary="$120,000")
    job = make_job(salary="$130k - $150k")
    result = calculate_match(job, make_profile(preferences=prefs), semantic_score=50, **DEFAULT_KW)
    assert result.preference_score == 100.0


def test_preference_salary_floor_violated_scores_25():
    prefs = WorkPreferences(min_salary="150k")
    job = make_job(salary="$100,000 - $120,000")
    result = calculate_match(job, make_profile(preferences=prefs), semantic_score=50, **DEFAULT_KW)
    assert result.preference_score == 25.0


def test_preference_no_signals_is_neutral():
    result = calculate_match(make_job(), make_profile(), semantic_score=50, **DEFAULT_KW)
    assert result.preference_score == 70.0


def test_preference_subscores_average():
    prefs = WorkPreferences(employment_types=["full-time"], min_salary="$120k")
    job = make_job(employment_type="contract", salary="$140k+")  # emp mismatch, salary ok
    result = calculate_match(job, make_profile(preferences=prefs), semantic_score=50, **DEFAULT_KW)
    assert result.preference_score == pytest.approx(70.0)  # (40 + 100) / 2


# --- weights -------------------------------------------------------------------------


OVERRIDE_WEIGHTS = {
    "semantic": 0.4,
    "skill": 0.4,
    "experience": 0.05,
    "seniority": 0.05,
    "location": 0.05,
    "preference": 0.05,
}


def test_explicit_weight_override_changes_overall():
    job = make_job(required_skills=["python"])
    profile = make_profile(["python"])
    default_run = calculate_match(job, profile, semantic_score=50, weights=dict(DEFAULT_WEIGHTS))
    override_run = calculate_match(job, profile, semantic_score=50, weights=dict(OVERRIDE_WEIGHTS))
    assert default_run.overall_score != override_run.overall_score


def test_weights_must_sum_to_one():
    bad = dict(OVERRIDE_WEIGHTS, skill=0.9)  # sums to 1.3
    with pytest.raises(ValueError, match="sum"):
        calculate_match(make_job(), make_profile(), semantic_score=50, weights=bad)


def test_weights_reject_unknown_components():
    bad = dict(OVERRIDE_WEIGHTS, charisma=0.0)
    with pytest.raises(ValueError, match="Unknown"):
        calculate_match(make_job(), make_profile(), semantic_score=50, weights=bad)


def test_weights_reject_missing_components():
    bad = {k: v for k, v in OVERRIDE_WEIGHTS.items() if k != "location"}
    with pytest.raises(ValueError, match="Missing"):
        calculate_match(make_job(), make_profile(), semantic_score=50, weights=bad)


def test_weights_reject_non_positive_values():
    bad = dict(OVERRIDE_WEIGHTS, skill=0.0)
    with pytest.raises(ValueError, match="positive"):
        calculate_match(make_job(), make_profile(), semantic_score=50, weights=bad)


# --- degraded mode ---------------------------------------------------------------------


def test_degraded_mode_redistributes_weights_and_notes_explanation():
    job = make_job(required_skills=["python"])
    profile = make_profile(["python"])
    result = calculate_match(job, profile, semantic_score=None, weights=dict(DEFAULT_WEIGHTS))
    assert "degraded" in result.explanation
    # overall == weighted mean over the five remaining components (rescaled)
    expected = (
        0.375 * result.skill_score
        + 0.25 * result.experience_score
        + 0.125 * result.seniority_score
        + 0.125 * result.location_score
        + 0.125 * result.preference_score
    )
    assert result.overall_score == pytest.approx(expected)
    assert result.semantic_score == 0.0


def test_degraded_mode_differs_from_semantic_run():
    job = make_job(required_skills=["python"])
    profile = make_profile(["python"])
    degraded = calculate_match(job, profile, semantic_score=None, weights=dict(DEFAULT_WEIGHTS))
    with_semantic = calculate_match(job, profile, semantic_score=90, weights=dict(DEFAULT_WEIGHTS))
    assert degraded.overall_score != with_semantic.overall_score


# --- invariants & determinism --------------------------------------------------------------


def test_result_invariants_hold():
    job = make_job(
        required_skills=["python", "kubernetes"],
        preferred_skills=["aws"],
        remote_policy="hybrid",
        location="Berlin",
        experience_requirements="3+ years",
    )
    profile = make_profile(
        ["python"],
        experience=[ExperienceEntry(title="Senior Dev", dates="2020 - present")],
        preferences=WorkPreferences(preferred_locations=["Berlin"], min_salary="100k"),
    )
    result = calculate_match(job, profile, semantic_score=72.6, weights=dict(DEFAULT_WEIGHTS))
    assert isinstance(result, JobMatchResult)
    for field in (
        "overall_score",
        "semantic_score",
        "skill_score",
        "experience_score",
        "seniority_score",
        "location_score",
        "preference_score",
    ):
        assert 0.0 <= getattr(result, field) <= 100.0
    assert not (set(result.matched_requirements) & set(result.missing_requirements))
    assert "Semantic: 73%" in result.explanation  # readable component percentages


class HashEmbeddingFn:
    """Fixed-vector embedding double: md5-seeded, no state, fully deterministic."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        digest = hashlib.md5(text.encode("utf-8")).digest()
        return [byte / 255.0 for byte in digest[:8]]


def test_full_pipeline_deterministic_across_runs(tmp_path):
    """With a FakeEmbeddingFn the whole pipeline reproduces identical scores."""
    job = make_job(
        id="py-1",
        title="Backend Python Engineer",
        description="Build APIs with Python and FastAPI.",
        required_skills=["python", "fastapi"],
    )

    def run_once() -> list[float]:
        store = ChromaVectorStore(
            persist_dir=str(tmp_path / "chroma"),
            embedding_fn=HashEmbeddingFn(),
            settings=_settings(tmp_path),
        )
        store.upsert_jobs([job])
        profile = make_profile(["python", "fastapi"])
        similarities = dict(store.query_similar(candidate_query_text(profile), n=5))
        return [
            calculate_match(
                job, profile, semantic_score=similarities.get("py-1"), weights=dict(DEFAULT_WEIGHTS)
            ).overall_score
        ]

    first = run_once()
    second = run_once()
    assert first == second
    assert first[0] > 0


def _settings(tmp_path: Path):
    from types import SimpleNamespace

    return SimpleNamespace(
        chroma_dir=str(tmp_path / "chroma"),
        embedding_model="gemini-embedding-2",
        embedding_dimensionality=8,
    )
