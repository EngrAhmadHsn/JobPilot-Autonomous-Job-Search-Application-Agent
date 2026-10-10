"""Hybrid matching engine."""

from __future__ import annotations

import logging

from src.jobs.contracts import JobListing
from src.matching.contracts import JobMatchResult

logger = logging.getLogger(__name__)


def calculate_match(
    job: JobListing,
    candidate_skills: list[str],
    weights: dict[str, float] | None = None,
) -> JobMatchResult:
    """Calculate hybrid match score between job and candidate profile.

    Args:
        job: Normalized job listing
        candidate_skills: List of candidate skills
        weights: Optional weight overrides for scoring components

    Returns:
        JobMatchResult with scores and explanation
    """
    default_weights = {
        "semantic": 0.2,
        "skill": 0.3,
        "experience": 0.2,
        "seniority": 0.1,
        "location": 0.1,
        "preference": 0.1,
    }
    w = weights or default_weights

    # Skill overlap score
    job_skills = set(job.required_skills + job.preferred_skills)
    candidate_skills_set = set(candidate_skills)
    matched_skills = job_skills & candidate_skills_set
    skill_score = (len(matched_skills) / max(len(job_skills), 1)) * 100 if job_skills else 0

    # Semantic score (placeholder: would use embeddings)
    semantic_score = 50.0  # Placeholder

    # Experience score (placeholder)
    experience_score = 60.0

    # Seniority score (placeholder)
    seniority_score = 70.0

    # Location score
    location_score = 100.0 if job.location else 50.0

    # Preference score (placeholder)
    preference_score = 50.0

    overall = (
        w["semantic"] * semantic_score
        + w["skill"] * skill_score
        + w["experience"] * experience_score
        + w["seniority"] * seniority_score
        + w["location"] * location_score
        + w["preference"] * preference_score
    ) / sum(w.values())

    missing = list(job_skills - candidate_skills_set)
    matched = list(matched_skills)

    explanation = (
        f"Match score: {overall:.0f}/100. "
        f"Skills: {skill_score:.0f}%, Semantic: {semantic_score:.0f}%. "
        f"Matched: {matched}. Missing: {missing}."
    )

    logger.info("Match calculated for %s at %s: %.1f", job.title, job.company, overall)

    return JobMatchResult(
        overall_score=overall,
        semantic_score=semantic_score,
        skill_score=skill_score,
        experience_score=experience_score,
        seniority_score=seniority_score,
        location_score=location_score,
        preference_score=preference_score,
        missing_requirements=missing,
        matched_requirements=matched,
        explanation=explanation,
    )
