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
from src.matching.roles import (
    FAMILY_LABELS,
    ROLE_MISMATCH_CAP,
    RoleRelevance,
    role_relevance,
)
from src.matching.scores import ComponentScore, ScoreState, blend, measured_state
from src.matching.weights import DEFAULT_WEIGHTS, validate_weights
from src.resume.profile import CandidateProfile, WorkPreferences, work_preferences_stated

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


def _effective_preferences(profile: CandidateProfile) -> WorkPreferences:
    """The candidate's preferences: what they confirmed, then what the résumé said.

    A résumé rarely states a work mode or a salary floor; the application
    profile is where the user does. A confirmed value therefore *wins* over a
    résumé-derived one, field by field, and the résumé value is the fallback.
    This is what makes editing the preferences on the Profile screen change the
    ranking, instead of only changing a display.
    """
    resume = profile.work_preferences
    app = getattr(profile, "application_profile", None)
    prefs = getattr(app, "preferences", None) if app is not None else None
    answers = getattr(app, "answers", None) if app is not None else None
    if prefs is None:
        return resume

    merged = resume.model_copy(deep=True)
    if prefs.remote_preference:
        merged.remote_preference = prefs.remote_preference
    if prefs.preferred_locations:
        merged.preferred_locations = list(prefs.preferred_locations)
    if prefs.employment_types:
        merged.employment_types = list(prefs.employment_types)
    compensation = getattr(answers, "compensation", None) if answers is not None else None
    expected = getattr(compensation, "expected_salary", None) if compensation is not None else None
    if expected is not None and not merged.min_salary:
        currency = getattr(compensation, "expected_currency", None) or ""
        merged.min_salary = f"{currency} {expected:g}".strip()
    return merged


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
    coverage = (len(required_hits) + 0.5 * len(preferred_hits)) / denominator
    # WS-21: thin evidence cannot deliver a full score. A one-token list is a
    # weak statement of what the job needs — the same token appears in half
    # the corpus — so the coverage is damped by how much evidence there is
    # (two listed requirements are full confidence). Without this, a listing
    # that names one generic skill matched by everyone scored like a listing
    # whose real requirement list is fully met.
    evidence_factor = min(1.0, denominator / 2.0)
    value = max(0.0, min(100.0, coverage * evidence_factor * 100))
    reason = ""
    if evidence_factor < 1.0 and coverage > 0:
        reason = (
            f"only {len(matched_names)} listed requirement(s); the score is damped "
            "because a very short requirement list is weak evidence"
        )
    return ComponentScore(
        name="skill",
        value=value,
        state=measured_state(value),
        reason=reason,
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
    prefs = _effective_preferences(profile)
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
    prefs = _effective_preferences(profile)
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


def _role_component(relevance: RoleRelevance) -> ComponentScore:
    """The occupational-role component, from a precomputed comparison.

    Unknown and measured states follow the WS-20 vocabulary: no target roles
    is candidate data missing; an unclassifiable listing is a missing job
    requirement; an unrelated role is a *measured mismatch* worth its low
    value (and, in ``calculate_match``, a cap).
    """
    if relevance.target_source in {"none", "cleared"}:
        return ComponentScore(
            name="role",
            state=ScoreState.CANDIDATE_DATA_MISSING,
            reason=relevance.reason or "the candidate has no target roles",
        )
    if relevance.family is None:
        return ComponentScore(
            name="role",
            state=ScoreState.JOB_REQUIREMENT_MISSING,
            reason=relevance.reason or "the listing's occupational role is not recognisable",
        )
    return ComponentScore(
        name="role",
        value=relevance.value,
        state=measured_state(relevance.value),
        reason=relevance.reason,
        matched=[FAMILY_LABELS.get(relevance.family, relevance.family)],
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

    # WS-21: the occupational-role comparison, computed once and turned into
    # the eighth component below (and, on a WEAK/UNRELATED role, the cap).
    relevance = role_relevance(profile, job)

    components: dict[str, ComponentScore] = {
        "semantic": _semantic_component(job, semantic_score, semantic_state),
        "lexical": _lexical_component(job, profile, lexical, bm25_index),
        "skill": _skill_component(job, profile),
        "experience": _experience_component(job, profile),
        "seniority": _seniority_component(job, profile),
        "location": _location_component(job, profile),
        "preference": _preference_component(job, profile),
        "role": _role_component(relevance),
    }
    blended = blend(effective_weights, components)

    # WS-21: a role the candidate's targets are WEAK-to-UNRELATED against can
    # never read as a match. The cap is below the evaluation's decision
    # threshold (30) and is always reported — see `role_capped` and the notes.
    overall = blended.overall_score
    if relevance.capped:
        overall = min(overall, ROLE_MISMATCH_CAP)

    skill_match = components["skill"]
    lexical_component = components["lexical"]
    notes = [
        f"{name}: {component.reason}" for name, component in components.items() if component.reason
    ]

    parts = [f"Match score: {overall:.0f}/100"]
    parts.append(f"Evidence coverage: {blended.evidence_coverage:.0f}%")
    for name in (
        "semantic",
        "lexical",
        "skill",
        "experience",
        "seniority",
        "location",
        "preference",
        "role",
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
    if relevance.family is not None:
        # WS-21 · §2.5: the role evidence, concisely — the classified family,
        # the classifier's confidence, and the targets the comparison used.
        family_label = FAMILY_LABELS.get(relevance.family, relevance.family)
        sentence = f" Classified role: {family_label} (confidence {relevance.confidence:.0%}"
        if relevance.second_family is not None and relevance.confidence < 1.0:
            second_label = FAMILY_LABELS.get(relevance.second_family, relevance.second_family)
            sentence += f", second reading {second_label}"
        sentence += ")"
        if relevance.targets:
            sentence += (
                f"; candidate targets: {', '.join(relevance.targets[:5])}"
                f" ({relevance.target_source})"
            )
        explanation += sentence + "."
    if notes:
        explanation += " Notes: " + "; ".join(notes) + "."

    logger.info("Match calculated for %s at %s: %.1f", job.title, job.company, overall)

    return JobMatchResult(
        overall_score=overall,
        semantic_score=components["semantic"].value,
        lexical_score=components["lexical"].value,
        skill_score=components["skill"].value,
        experience_score=components["experience"].value,
        seniority_score=components["seniority"].value,
        location_score=components["location"].value,
        preference_score=components["preference"].value,
        role_score=components["role"].value,
        role_family=relevance.family,
        role_family_confidence=relevance.confidence,
        role_targets=list(relevance.targets),
        role_target_source=relevance.target_source,
        role_capped=relevance.capped,
        evidence_coverage=blended.evidence_coverage,
        component_states={name: component.state.value for name, component in components.items()},
        notes=notes,
        missing_requirements=skill_match.missing,
        matched_requirements=skill_match.matched,
        missing_keywords=lexical_component.missing,
        matched_keywords=lexical_component.matched,
        explanation=explanation,
    )
