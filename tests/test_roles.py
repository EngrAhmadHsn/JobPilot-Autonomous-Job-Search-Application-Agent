"""WS-21: occupational-role classification, target roles and the role gate.

The defects these tests pin down: a Data Analyst and a Physical Design
Engineer ranking top-10 for a Web Developer because a single generic skill
matched at 100 % and no signal compared *what kind of work* the listing is.
"""

from __future__ import annotations

import pytest

from src.jobs.contracts import JobListing
from src.matching.engine import calculate_match
from src.matching.roles import (
    BAND_ADJACENT,
    BAND_SAME,
    BAND_UNRELATED,
    BAND_WEAK,
    ROLE_MISMATCH_CAP,
    classify_job_role,
    compatibility,
    resolve_candidate_targets,
    role_relevance,
)
from src.resume.application_profile import (
    ApplicationProfile,
    JobSearchPreferences,
)
from src.resume.profile import CandidateProfile, ExperienceEntry, PersonalInformation

# --- helpers -----------------------------------------------------------------


def job(title: str, **kwargs) -> JobListing:
    defaults = {"id": "job-1", "source": "greenhouse", "company": "Acme"}
    defaults.update(kwargs)
    return JobListing(title=title, **defaults)


def web_profile(*, targets: list[str] | None = None, confirmed: bool = True) -> CandidateProfile:
    """A web developer whose targets are confirmed (or by headline)."""
    application = ApplicationProfile(
        preferences=JobSearchPreferences(target_roles=list(targets) if targets is not None else []),
        confirmed_fields=["preferences.target_roles"] if confirmed else [],
    )
    return CandidateProfile(
        personal_information=PersonalInformation(title="Web Developer"),
        skills=["JavaScript", "React", "Node.js", "SQL", "Python"],
        experience=[ExperienceEntry(title="Web Developer", company="A", years=4)],
        application_profile=application,
    )


# --- classification ------------------------------------------------------------


def test_physical_design_engineer_is_hardware_even_though_it_lists_python():
    c = classify_job_role(
        job(
            "Physical Design Engineer",
            required_skills=["Python"],
            description=(
                "Work on silicon design: RTL, timing closure, place and route, "
                "logic synthesis, power integrity."
            ),
        )
    )
    assert c.family == "hardware_physical_design"
    assert c.confidence >= 0.6
    assert not c.ambiguous


def test_senior_analyst_is_analytics_not_a_generic_engineer():
    c = classify_job_role(
        job(
            "Senior Analyst, France & Netherlands (12 Month Fixed-Term Contract)",
            required_skills=["SQL"],
            description="Build dashboards and reporting for business metrics.",
        )
    )
    assert c.family == "data_analytics"


def test_a_manager_role_records_the_manager_track():
    c = classify_job_role(job("Manager, Applied AI Engineering (Codex)"))
    assert c.family == "data_science_ml"
    assert c.track == "manager"


def test_title_beats_description_beats_technology():
    # The description talks web; the title says data analyst; SQL is a shared
    # technology. The title wins.
    c = classify_job_role(
        job(
            "Data Analyst",
            required_skills=["SQL"],
            description="Build responsive web applications and single page applications.",
        )
    )
    assert c.family == "data_analytics"


def test_a_technology_alone_does_not_confer_a_profession():
    # Python and SQL are shared technologies, not professions: their combined
    # weight (1.25) stays below the classification floor.
    c = classify_job_role(job("Chief of Staff", required_skills=["Python", "SQL"]))
    assert c.family is None
    assert c.track == "manager"


def test_unrecognisable_listing_is_unknown_not_a_guess():
    c = classify_job_role(job("Chief Happiness Officer", description="Spread joy."))
    assert c.family is None
    assert c.evidence == []


def test_ambiguous_listings_are_flagged():
    # A genuinely hybrid title: growth engineering sits between marketing and
    # software — exactly the case that must not ride one reading to a score.
    c = classify_job_role(job("Growth Engineer"))
    assert c.family == "marketing"
    assert c.second_family == "software_engineering"
    assert c.ambiguous


def test_compatibility_bands_are_symmetric_and_conservative_by_default():
    assert compatibility("web_development", "web_development") == BAND_SAME
    assert compatibility("web_development", "software_engineering") == BAND_ADJACENT
    assert compatibility("web_development", "software_engineering") == compatibility(
        "software_engineering", "web_development"
    )
    assert compatibility("web_development", "hardware_physical_design") == BAND_UNRELATED
    # An unlisted pair defaults to WEAK — conservative on purpose.
    assert compatibility("research", "sales") == BAND_WEAK


# --- candidate targets ----------------------------------------------------------


def test_confirmed_targets_are_authoritative():
    targets = resolve_candidate_targets(
        web_profile(targets=["Web Developer", "Frontend Developer"])
    )
    assert targets.source == "user"
    assert targets.families == ["web_development"]
    assert targets.raw == ["Web Developer", "Frontend Developer"]


def test_a_cleared_target_field_is_not_re_inferred():
    profile = web_profile(targets=[], confirmed=True)
    profile.application_profile.professional.current_title = "Senior AI Engineer"
    targets = resolve_candidate_targets(profile)
    assert targets.source == "cleared"
    assert targets.families == []


def test_inference_prefers_the_confirmed_current_title_then_the_headline():
    with_title = web_profile(confirmed=False)
    with_title.application_profile.professional.current_title = "Data Analyst"
    inferred = resolve_candidate_targets(with_title)
    assert inferred.source == "inferred"
    assert inferred.families == ["data_analytics"]

    headline_only = web_profile(confirmed=False)
    inferred = resolve_candidate_targets(headline_only)
    assert inferred.families == ["web_development"]
    assert inferred.raw == ["Web Developer"]


def test_no_targets_at_all_is_none():
    profile = CandidateProfile(personal_information=PersonalInformation())
    assert resolve_candidate_targets(profile).source == "none"


# --- the role comparison and the engine gate -------------------------------------


def test_a_web_developer_is_unrelated_to_physical_design():
    relevance = role_relevance(
        web_profile(targets=["Web Developer"]),
        job("Physical Design Engineer", required_skills=["Python"]),
    )
    assert relevance.family == "hardware_physical_design"
    assert relevance.value <= 25.0  # the UNRELATED band, below the mismatch cap
    assert relevance.capped


def test_a_web_developer_is_unrelated_to_a_data_analyst():
    relevance = role_relevance(
        web_profile(targets=["Web Developer"]),
        job(
            "Senior Analyst, France & Netherlands (12 Month Fixed-Term Contract)",
            required_skills=["SQL"],
            description="Build dashboards and reporting.",
        ),
    )
    assert relevance.family == "data_analytics"
    assert relevance.capped


def test_a_web_developer_is_a_strong_match_to_web_work():
    relevance = role_relevance(
        web_profile(targets=["Web Developer", "Full-Stack Developer"]),
        job("Senior React Full-stack Developer", required_skills=["React", "Node.js"]),
    )
    assert relevance.family == "web_development"
    assert relevance.value == 100.0
    assert not relevance.capped


def test_a_software_role_is_adjacent_and_not_capped():
    relevance = role_relevance(
        web_profile(targets=["Web Developer"]),
        job("Software Engineer, Safety Engineering"),
    )
    assert relevance.value == BAND_ADJACENT
    assert not relevance.capped


def test_a_management_role_against_an_ic_target_is_penalised():
    manager_job = job("Manager, Applied AI Engineering (Codex)")
    ic = role_relevance(web_profile(targets=["Web Developer"]), manager_job)
    manager = role_relevance(web_profile(targets=["Web Development Manager"]), manager_job)
    assert ic.track == "manager"
    assert ic.capped  # the track factor pushes it below the UNRELATED floor
    # Same role family (AI) either way; the IC target pays the management
    # penalty (0.5×) and the management target does not.
    assert manager.value == pytest.approx(ic.value * 2)
    assert manager.track == "manager"


def test_no_targets_is_candidate_data_missing_and_never_capped():
    bare = CandidateProfile(personal_information=PersonalInformation(), skills=["Python", "SQL"])
    relevance = role_relevance(bare, job("Physical Design Engineer"))
    assert relevance.target_source == "none"
    result = calculate_match(job("Physical Design Engineer"), bare, semantic_score=50)
    assert result.component_states["role"] == "CANDIDATE_DATA_MISSING"
    assert result.role_capped is False


def test_an_unclassifiable_listing_is_job_requirement_missing():
    result = calculate_match(
        job("Chief Happiness Officer", description="Spread joy."),
        web_profile(targets=["Web Developer"]),
        semantic_score=50,
    )
    assert result.component_states["role"] == "JOB_REQUIREMENT_MISSING"
    assert result.role_score == 0.0


def test_the_unrelated_role_caps_the_overall_score():
    """The headline defect: everything else 100 must not beat the role mismatch."""
    profile = web_profile(targets=["Web Developer"])
    unrelated = calculate_match(
        job(
            "Physical Design Engineer",
            required_skills=["Python"],
            description="RTL, timing closure, place and route, silicon.",
            salary="$200,000",
            employment_type="full-time",
            remote_policy="remote",
        ),
        profile,
        semantic_score=70,
    )
    assert unrelated.role_capped is True
    assert unrelated.overall_score <= ROLE_MISMATCH_CAP
    assert "capped" in unrelated.explanation
    assert "Classified role:" in unrelated.explanation


def test_a_relevant_role_outscores_an_unrelated_one_on_the_same_signals():
    profile = web_profile(targets=["Web Developer"])
    else_kwargs = {
        "required_skills": ["Python"],
        "salary": "$200,000",
        "employment_type": "full-time",
        "remote_policy": "remote",
    }
    relevant = calculate_match(
        job("Senior React Developer", description="Responsive web applications.", **else_kwargs),
        profile,
        semantic_score=70,
    )
    unrelated = calculate_match(
        job("Physical Design Engineer", description="RTL and timing closure.", **else_kwargs),
        profile,
        semantic_score=70,
    )
    assert relevant.overall_score > unrelated.overall_score
    assert not relevant.role_capped
    assert unrelated.role_capped


def test_an_inferred_target_is_labelled_in_the_result():
    profile = web_profile(targets=[], confirmed=False)  # headline: Web Developer
    result = calculate_match(job("Senior React Developer"), profile, semantic_score=50)
    assert result.role_target_source == "inferred"
    assert "inferred" in result.explanation
    assert result.component_states["role"] in {"MATCHED", "PARTIAL_MATCH"}


def test_role_fields_are_reported_on_every_result():
    result = calculate_match(
        job("Senior React Developer"),
        web_profile(targets=["Web Developer"]),
        semantic_score=50,
    )
    assert result.role_score == pytest.approx(100.0)
    assert result.role_family == "web_development"
    assert result.role_targets == ["Web Developer"]
    assert result.role_target_source == "user"
    assert result.role_capped is False
    assert "role" in result.component_states
