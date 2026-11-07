"""Hybrid matching engine (WS-03; score semantics rewritten in WS-20).

Seven deterministic scorers — ``semantic``, ``lexical``, ``skill``,
``experience``, ``seniority``, ``location``, ``preference`` — blended over a
**fixed** denominator. The caller supplies the semantic similarity (the vector
store stays behind the call site, so this module is testable without
embeddings); everything else is computed from the profile and the listing.

WS-20 replaces the old neutral-70 defaults and weight redistribution with an
explicit policy (see :mod:`src.matching.scores`):

- a component whose evidence is missing is **unknown** — it contributes zero
  and says *why*, and its weight stays in the denominator, so a listing is
  never rewarded for missing information;
- a missing embedding no longer redistributes its weight onto the others;
- every result carries an **evidence coverage** so an earned score is
  distinguishable from a defaulted one.
"""

from __future__ import annotations

import logging
import re

from src.config.settings import get_settings
from src.jobs.contracts import JobListing
from src.matching.contracts import JobMatchResult
from src.matching.experience import experience_score
from src.matching.lexical import (
    Bm25Index,
    LexicalResult,
    candidate_lexical_text,
    candidate_tokens,
    lexical_score,
)
from src.matching.scores import ComponentScore, ScoreState, blend, measured_state
from src.matching.weights import DEFAULT_WEIGHTS, validate_weights
from src.resume.profile import CandidateProfile, work_preferences_stated

logger = logging.getLogger(__name__)

CONFLICT_SCORE = 25.0

# Rank ladder for seniority comparison (checked highest first so "senior staff"
# resolves to staff). Word-boundary matching keeps "intern" out of
# "international".
_SENIORITY_RANKS: tuple[tuple[str, int], ...] = (
    ("distinguished", 6),
    ("principal", 5),
    ("staff", 4),
    ("lead", 4),
    ("architect", 4),
    ("senior", 3),
    ("sr.", 3),
    ("snr", 3),
    ("mid-level", 2),
    ("midweight", 2),
    ("mid", 2),
    ("associate", 2),
    ("junior", 1),
    ("jr.", 1),
    ("jr", 1),
    ("entry level", 1),
    ("graduate", 1),
    ("intern", 0),
    ("trainee", 0),
)

_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")


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


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------


def _semantic_component(
    job: JobListing, semantic_score: float | None, state: ScoreState | None
) -> ComponentScore:
    if semantic_score is None:
        resolved = state or ScoreState.EMBEDDING_UNAVAILABLE
        if resolved is ScoreState.EMBEDDING_PENDING:
            reason = "semantic scoring pending: this listing has no vector yet"
        elif resolved is ScoreState.CANDIDATE_DATA_MISSING:
            reason = "semantic scoring unavailable: the candidate text is empty"
        else:
            reason = "semantic scoring unavailable: the vector store could not be read"
        return ComponentScore(name="semantic", value=0.0, state=resolved, reason=reason)
    value = max(0.0, min(100.0, semantic_score))
    return ComponentScore(name="semantic", value=value, state=measured_state(value))


def _skill_component(job: JobListing, profile: CandidateProfile) -> ComponentScore:
    required = [skill for skill in job.required_skills if skill.strip()]
    preferred = [skill for skill in job.preferred_skills if skill.strip()]
    matched_names = [*required, *preferred]
    if not matched_names:
        return ComponentScore(
            name="skill",
            state=ScoreState.JOB_REQUIREMENT_MISSING,
            reason="the listing states no required or preferred skills",
        )
    candidate = {skill.strip().casefold() for skill in profile.skills}
    if not candidate:
        return ComponentScore(
            name="skill",
            state=ScoreState.CANDIDATE_DATA_MISSING,
            reason="the candidate profile lists no skills",
            missing=matched_names,
        )
    required_hits = [skill for skill in required if skill.strip().casefold() in candidate]
    preferred_hits = [skill for skill in preferred if skill.strip().casefold() in candidate]
    matched = [*required_hits, *preferred_hits]
    missing = [skill for skill in matched_names if skill.strip().casefold() not in candidate]
    denominator = len(required) + 0.5 * len(preferred)
    value = max(
        0.0, min(100.0, (len(required_hits) + 0.5 * len(preferred_hits)) / denominator * 100)
    )
    return ComponentScore(
        name="skill",
        value=value,
        state=measured_state(value),
        matched=matched,
        missing=missing,
    )


def _experience_component(job: JobListing, profile: CandidateProfile) -> ComponentScore:
    from src.matching.experience import required_years, years_of_experience

    requirement = required_years(job)
    if requirement is None:
        return ComponentScore(
            name="experience",
            state=ScoreState.JOB_REQUIREMENT_MISSING,
            reason="the listing states no experience requirement",
        )
    actual = years_of_experience(profile)
    if actual is None:
        return ComponentScore(
            name="experience",
            state=ScoreState.CANDIDATE_DATA_MISSING,
            reason=(
                f"the job asks for {requirement:.0f} years of experience; the candidate "
                "profile has no dated experience"
            ),
        )
    value = experience_score(job, profile) or 0.0
    state = measured_state(value)
    reason = ""
    if state is ScoreState.MISMATCH:
        reason = f"candidate has {actual:.0f} years against a {requirement:.0f}-year requirement"
    return ComponentScore(name="experience", value=value, state=state, reason=reason)


def _candidate_rank(profile: CandidateProfile) -> int | None:
    """Candidate seniority: confirmed level, then most recent role, then peak."""
    confirmed = getattr(profile, "application_profile", None)
    confirmed_level = getattr(getattr(confirmed, "professional", None), "seniority_level", None)
    confirmed_rank = _seniority_rank(confirmed_level)
    if confirmed_rank is not None:
        return confirmed_rank
    if not profile.experience:
        return None
    # Most recent dated entry wins; an undated entry does not.
    best_rank: int | None = None
    best_end = -1.0
    for entry in profile.experience:
        years = [float(year) for year in _YEAR_RE.findall(entry.dates or "")]
        end = max(years) if years else -1.0
        if end > best_end:
            best_end = end
            best_rank = _seniority_rank(entry.title)
    if best_rank is not None:
        return best_rank
    # Fall back to the highest rank anywhere in the history.
    ranks = [
        rank for rank in (_seniority_rank(e.title) for e in profile.experience) if rank is not None
    ]
    return max(ranks) if ranks else None


def _seniority_component(job: JobListing, profile: CandidateProfile) -> ComponentScore:
    job_rank = _seniority_rank(job.seniority) or _seniority_rank(job.title)
    if job_rank is None:
        return ComponentScore(
            name="seniority",
            state=ScoreState.JOB_REQUIREMENT_MISSING,
            reason="the listing states no seniority level",
        )
    candidate_rank = _candidate_rank(profile)
    if candidate_rank is None:
        return ComponentScore(
            name="seniority",
            state=ScoreState.CANDIDATE_DATA_MISSING,
            reason="the candidate profile states no seniority level or titled role",
        )
    value = max(0.0, min(100.0, 100.0 - 30.0 * abs(candidate_rank - job_rank)))
    return ComponentScore(name="seniority", value=value, state=measured_state(value))


def _location_component(job: JobListing, profile: CandidateProfile) -> ComponentScore:
    prefs = profile.work_preferences
    policy = (job.remote_policy or "").casefold().replace("-", "").replace(" ", "")
    job_location = (job.location or "").casefold()
    preferred = [loc.strip().casefold() for loc in prefs.preferred_locations if loc.strip()]

    if policy == "remote":
        return ComponentScore(name="location", value=100.0, state=ScoreState.MATCHED)
    if (
        preferred
        and job_location
        and any(loc in job_location or job_location in loc for loc in preferred)
    ):
        return ComponentScore(name="location", value=100.0, state=ScoreState.MATCHED)
    if not work_preferences_stated(prefs):
        return ComponentScore(
            name="location",
            state=ScoreState.CANDIDATE_DATA_MISSING,
            reason="the candidate states no location or work-mode preference",
        )
    if not job_location and not policy:
        return ComponentScore(
            name="location",
            state=ScoreState.JOB_REQUIREMENT_MISSING,
            reason="the listing states no location or work mode",
        )
    if policy == "onsite":
        return ComponentScore(
            name="location",
            value=CONFLICT_SCORE,
            state=ScoreState.MISMATCH,
            reason="onsite-only listing against the candidate's stated preferences",
        )
    if policy == "hybrid":
        value = 55.0
    else:
        value = 40.0
    return ComponentScore(name="location", value=value, state=measured_state(value))


def _preference_component(job: JobListing, profile: CandidateProfile) -> ComponentScore:
    prefs = profile.work_preferences
    subscores: list[float] = []
    job_has_signal = False

    employment_pref = [
        normalized
        for normalized in (_normalize_employment_type(t) for t in prefs.employment_types)
        if normalized
    ]
    job_employment = _normalize_employment_type(job.employment_type)
    if job_employment:
        job_has_signal = True
    if employment_pref and job_employment:
        subscores.append(100.0 if job_employment in employment_pref else 40.0)

    candidate_min = _parse_salary(prefs.min_salary)
    job_salary = _parse_salary(job.salary)
    if job_salary is not None:
        job_has_signal = True
    if candidate_min is not None and job_salary is not None:
        subscores.append(100.0 if job_salary[1] >= candidate_min[0] else CONFLICT_SCORE)

    if not job_has_signal:
        return ComponentScore(
            name="preference",
            state=ScoreState.JOB_REQUIREMENT_MISSING,
            reason="the listing states no employment type or salary",
        )
    if not subscores:
        return ComponentScore(
            name="preference",
            state=ScoreState.CANDIDATE_DATA_MISSING,
            reason="the candidate states no employment-type or salary preference",
        )
    value = sum(subscores) / len(subscores)
    return ComponentScore(name="preference", value=value, state=measured_state(value))


def _lexical_component(
    job: JobListing,
    profile: CandidateProfile,
    lexical: LexicalResult | None,
    index: Bm25Index | None,
) -> ComponentScore:
    tokens = candidate_tokens(profile)
    text = candidate_lexical_text(profile)
    if not tokens or not text.strip():
        return ComponentScore(
            name="lexical",
            state=ScoreState.CANDIDATE_DATA_MISSING,
            reason="the candidate profile has no professional text to match against",
        )
    if not (job.title or job.description or job.required_skills or job.preferred_skills):
        return ComponentScore(
            name="lexical",
            state=ScoreState.JOB_REQUIREMENT_MISSING,
            reason="the listing has no text to match against",
        )
    result = lexical or lexical_score(
        job, index=index, candidate_token_list=tokens, candidate_text=text
    )
    return ComponentScore(
        name="lexical",
        value=result.score,
        state=measured_state(result.score),
        matched=result.matched_keywords,
        missing=result.missing_keywords,
    )


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def calculate_match(
    job: JobListing,
    profile: CandidateProfile,
    *,
    semantic_score: float | None = None,
    semantic_state: ScoreState | None = None,
    lexical: LexicalResult | None = None,
    bm25_index: Bm25Index | None = None,
    weights: dict[str, float] | None = None,
) -> JobMatchResult:
    """Calculate the hybrid match between a job listing and a candidate profile.

    Args:
        job: Normalized job listing.
        profile: Validated candidate profile (skills, experience, preferences
            and the user-confirmed application profile).
        semantic_score: Semantic similarity 0-100 from the vector store, or
            ``None`` when the listing has no usable vector. A measured ``0.0``
            is *not* the same as ``None`` and is treated as a measurement.
        semantic_state: Why the semantic score is missing
            (``EMBEDDING_PENDING`` / ``EMBEDDING_UNAVAILABLE`` /
            ``CANDIDATE_DATA_MISSING``); ignored when ``semantic_score`` is set.
        lexical: A precomputed lexical result (the bulk search builds one
            BM25 index and scores each listing against it).
        bm25_index: A shared index used when ``lexical`` is not supplied.
        weights: Component weight overrides; must sum to ~1.0 and name every
            default component. Falls back to ``MATCH_WEIGHTS``, then defaults.

    Returns:
        JobMatchResult — component scores, their states, evidence coverage and
        a human-readable explanation. Never raises for missing inputs; missing
        inputs become explicit unknown states.
    """
    if weights is not None:
        effective_weights = validate_weights(weights)
    else:
        configured = get_settings().match_weights
        effective_weights = validate_weights(configured) if configured else dict(DEFAULT_WEIGHTS)

    components: dict[str, ComponentScore] = {
        "semantic": _semantic_component(job, semantic_score, semantic_state),
        "lexical": _lexical_component(job, profile, lexical, bm25_index),
        "skill": _skill_component(job, profile),
        "experience": _experience_component(job, profile),
        "seniority": _seniority_component(job, profile),
        "location": _location_component(job, profile),
        "preference": _preference_component(job, profile),
    }
    blended = blend(effective_weights, components)

    skill_match = components["skill"]
    lexical_component = components["lexical"]
    notes = [
        f"{name}: {component.reason}" for name, component in components.items() if component.reason
    ]

    parts = [f"Match score: {blended.overall_score:.0f}/100"]
    parts.append(f"Evidence coverage: {blended.evidence_coverage:.0f}%")
    for name in (
        "semantic",
        "lexical",
        "skill",
        "experience",
        "seniority",
        "location",
        "preference",
    ):
        component = components[name]
        if component.state in {ScoreState.MATCHED, ScoreState.PARTIAL_MATCH, ScoreState.MISMATCH}:
            parts.append(f"{name.capitalize()}: {component.value:.0f}%")
        else:
            parts.append(f"{name.capitalize()}: unknown ({component.state.value})")
    explanation = ", ".join(parts) + "."
    explanation += (
        f" Matched skills: {', '.join(skill_match.matched) if skill_match.matched else 'none'}."
    )
    explanation += (
        f" Missing skills: {', '.join(skill_match.missing) if skill_match.missing else 'none'}."
    )
    if lexical_component.missing:
        shown = ", ".join(lexical_component.missing[:10])
        explanation += f" Missing keywords: {shown}."
    if notes:
        explanation += " Notes: " + "; ".join(notes) + "."

    logger.info(
        "Match calculated for %s at %s: %.1f", job.title, job.company, blended.overall_score
    )

    return JobMatchResult(
        overall_score=blended.overall_score,
        semantic_score=components["semantic"].value,
        lexical_score=components["lexical"].value,
        skill_score=components["skill"].value,
        experience_score=components["experience"].value,
        seniority_score=components["seniority"].value,
        location_score=components["location"].value,
        preference_score=components["preference"].value,
        evidence_coverage=blended.evidence_coverage,
        component_states={name: component.state.value for name, component in components.items()},
        notes=notes,
        missing_requirements=skill_match.missing,
        matched_requirements=skill_match.matched,
        missing_keywords=lexical_component.missing,
        matched_keywords=lexical_component.matched,
        explanation=explanation,
    )
