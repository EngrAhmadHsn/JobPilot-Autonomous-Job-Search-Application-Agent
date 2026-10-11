"""Hybrid matching engine (WS-03): six real, deterministic scorers.

Every component is computed from data — the candidate profile and the
normalized listing — except semantic similarity, which is passed in by the
caller (the Chroma vector store stays behind the call site, keeping this
module vector-store-agnostic and fully testable without embeddings).

Score conventions shared by the subjective components: a component whose
inputs are unknown on either side scores the documented neutral 70 instead of
guessing, and hard conflicts (e.g. an onsite-only job against stated remote
preferences) score 25.
"""

from __future__ import annotations

import logging
import re

from src.config.settings import get_settings
from src.jobs.contracts import JobListing
from src.matching.contracts import JobMatchResult
from src.matching.experience import experience_score
from src.matching.weights import DEFAULT_WEIGHTS, redistribute_without, validate_weights
from src.resume.profile import CandidateProfile, work_preferences_stated

logger = logging.getLogger(__name__)

NEUTRAL_SCORE = 70.0
CONFLICT_SCORE = 25.0

# Rank ladder for seniority comparison (checked highest first so "senior staff"
# resolves to staff). Word-boundary matching keeps "intern" out of
# "international".
_SENIORITY_RANKS: tuple[tuple[str, int], ...] = (
    ("principal", 5),
    ("staff", 4),
    ("lead", 4),
    ("senior", 3),
    ("sr.", 3),
    ("mid", 2),
    ("junior", 1),
    ("jr.", 1),
    ("intern", 0),
)


def _seniority_rank(text: str | None) -> int | None:
    if not text or not text.strip():
        return None
    lowered = text.casefold()
    for keyword, rank in _SENIORITY_RANKS:
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            return rank
    return None


def _normalize_employment_type(value: str | None) -> str:
    return re.sub(r"[\s_]+", "-", (value or "").strip().casefold())


def _parse_salary(text: str | None) -> tuple[float, float] | None:
    """Parse a free-form salary string into (min, max) in currency units.

    Understands "$120,000", "120k", "€80,000-€100,000". Returns None when no
    number can be extracted; ambiguity (e.g. "401(k)") is skipped.
    """
    if not text:
        return None
    cleaned = re.sub(r"(?<=\d),(?=\d)", "", text)
    values: list[float] = []
    for number, suffix in re.findall(r"(\d+(?:\.\d+)?)\s*([kKmM])?\b", cleaned):
        if number == "401":  # 401(k) retirement-plan noise, not a salary figure
            continue
        amount = float(number)
        if suffix and suffix.casefold() == "k":
            amount *= 1_000
        elif suffix and suffix.casefold() == "m":
            amount *= 1_000_000
        values.append(amount)
    if not values:
        return None
    return (min(values), max(values))


def _skill_score(job: JobListing, profile: CandidateProfile) -> tuple[float, list[str], list[str]]:
    """Weighted skill overlap: required hits count 1.0, preferred hits 0.5."""
    required = [skill for skill in job.required_skills if skill.strip()]
    preferred = [skill for skill in job.preferred_skills if skill.strip()]
    candidate = {skill.strip().casefold() for skill in profile.skills}

    required_hits = [skill for skill in required if skill.strip().casefold() in candidate]
    preferred_hits = [skill for skill in preferred if skill.strip().casefold() in candidate]
    matched = [*required_hits, *preferred_hits]
    missing = [
        skill for skill in [*required, *preferred] if skill.strip().casefold() not in candidate
    ]

    denominator = len(required) + 0.5 * len(preferred)
    if denominator == 0:
        return NEUTRAL_SCORE, matched, missing  # job states no skills: no evidence
    score = (len(required_hits) + 0.5 * len(preferred_hits)) / denominator * 100
    return max(0.0, min(100.0, score)), matched, missing


def _seniority_score(job: JobListing, profile: CandidateProfile) -> float:
    candidate_rank = _seniority_rank(profile.experience[0].title if profile.experience else None)
    job_rank = _seniority_rank(job.seniority) or _seniority_rank(job.title)
    if candidate_rank is None or job_rank is None:
        return NEUTRAL_SCORE
    return max(0.0, min(100.0, 100.0 - 30.0 * abs(candidate_rank - job_rank)))


def _location_score(job: JobListing, profile: CandidateProfile) -> float:
    prefs = profile.work_preferences
    policy = (job.remote_policy or "").casefold().replace("-", "").replace(" ", "")
    job_location = (job.location or "").casefold()
    preferred = [loc.strip().casefold() for loc in prefs.preferred_locations if loc.strip()]

    if policy == "remote":
        return 100.0
    if (
        preferred
        and job_location
        and any(loc in job_location or job_location in loc for loc in preferred)
    ):
        return 100.0
    if not work_preferences_stated(prefs):
        return NEUTRAL_SCORE
    if policy == "onsite":
        return CONFLICT_SCORE  # onsite-only job against stated preferences
    return NEUTRAL_SCORE


def _preference_score(job: JobListing, profile: CandidateProfile) -> float:
    prefs = profile.work_preferences
    subscores: list[float] = []

    employment_pref = [
        normalized
        for normalized in (_normalize_employment_type(t) for t in prefs.employment_types)
        if normalized
    ]
    job_employment = _normalize_employment_type(job.employment_type)
    if employment_pref and job_employment:
        subscores.append(100.0 if job_employment in employment_pref else 40.0)

    candidate_min = _parse_salary(prefs.min_salary)
    job_salary = _parse_salary(job.salary)
    if candidate_min is not None and job_salary is not None:
        subscores.append(100.0 if job_salary[1] >= candidate_min[0] else CONFLICT_SCORE)

    if not subscores:
        return NEUTRAL_SCORE
    return sum(subscores) / len(subscores)


def calculate_match(
    job: JobListing,
    profile: CandidateProfile,
    *,
    semantic_score: float | None = None,
    weights: dict[str, float] | None = None,
) -> JobMatchResult:
    """Calculate the hybrid match between a job listing and a candidate profile.

    Args:
        job: Normalized job listing.
        profile: Validated candidate profile (skills, experience, preferences).
        semantic_score: Semantic similarity in 0-100 from the vector store;
            ``None`` enables degraded mode (skill-focused, weights
            redistributed) for when embeddings are unavailable.
        weights: Component weight overrides; must sum to ~1.0. Falls back to
            the ``MATCH_WEIGHTS`` env setting, then the documented defaults.

    Returns:
        JobMatchResult with per-component scores and a human-readable
        explanation.
    """
    if weights is not None:
        effective_base = validate_weights(weights)
    else:
        configured = get_settings().match_weights
        effective_base = validate_weights(configured) if configured else dict(DEFAULT_WEIGHTS)

    notes: list[str] = []
    if semantic_score is None:
        effective_weights = redistribute_without(effective_base, "semantic")
        semantic_value = 0.0
        notes.append(
            "degraded mode: semantic scoring unavailable (embeddings disabled or "
            "failed); semantic weight redistributed across remaining components"
        )
    else:
        effective_weights = effective_base
        semantic_value = max(0.0, min(100.0, semantic_score))

    skill_value, matched, missing = _skill_score(job, profile)

    components = {
        "semantic": semantic_value,
        "skill": skill_value,
        "experience": experience_score(job, profile),
        "seniority": _seniority_score(job, profile),
        "location": _location_score(job, profile),
        "preference": _preference_score(job, profile),
    }
    total_weight = sum(effective_weights.values())
    overall = (
        sum(effective_weights[name] * components[name] for name in effective_weights) / total_weight
    )
    overall = max(0.0, min(100.0, overall))

    parts = [f"Match score: {overall:.0f}/100"]
    if "semantic" in effective_weights:
        parts.append(f"Semantic: {semantic_value:.0f}%")
    parts.append(f"Skills: {skill_value:.0f}%")
    parts.append(f"Experience: {components['experience']:.0f}%")
    parts.append(f"Seniority: {components['seniority']:.0f}%")
    parts.append(f"Location: {components['location']:.0f}%")
    parts.append(f"Preference: {components['preference']:.0f}%")
    explanation = ", ".join(parts) + "."
    explanation += f" Matched skills: {', '.join(matched) if matched else 'none'}."
    explanation += f" Missing skills: {', '.join(missing) if missing else 'none'}."
    if notes:
        explanation += " Notes: " + "; ".join(notes) + "."

    logger.info("Match calculated for %s at %s: %.1f", job.title, job.company, overall)

    return JobMatchResult(
        overall_score=overall,
        semantic_score=semantic_value,
        skill_score=skill_value,
        experience_score=components["experience"],
        seniority_score=components["seniority"],
        location_score=components["location"],
        preference_score=components["preference"],
        missing_requirements=missing,
        matched_requirements=matched,
        explanation=explanation,
    )
