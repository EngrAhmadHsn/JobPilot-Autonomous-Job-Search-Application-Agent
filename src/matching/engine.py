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
from typing import Any, NamedTuple

from src.config.settings import get_settings
from src.jobs.contracts import JobListing
from src.matching.contracts import JobMatchResult
from src.matching.corpus_cache import CorpusArtifacts
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

#: "The caller did not precompute this" — distinct from a precomputed ``None``,
#: which is a real value ("the listing states no requirement").
_UNCACHED = object()

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

#: The same ladder, compiled once. WS-24c: the ladder used to build a regex
#: with ``re.search`` per keyword per call — 19 of them for every title on
#: every search (18,345 calls per search on the 8,558-listing corpus, since
#: the component tries ``seniority`` and then ``title``). ``re``'s internal
#: cache hid the compilation, but not the per-call matching work.
_SENIORITY_PATTERNS: tuple[tuple[str, int, re.Pattern[str]], ...] = tuple(
    (keyword, rank, re.compile(rf"\b{re.escape(keyword)}\b")) for keyword, rank in _SENIORITY_RANKS
)


def _seniority_rank(text: str | None) -> int | None:
    """The seniority rank a text states, or ``None`` when it states none.

    The ladder is tried from the most senior keyword down and the first match
    wins, so "Senior Staff Engineer" is staff and "Lead Data Scientist" is
    lead. WS-24c keeps that order exactly and adds a **substring prefilter**:
    a word-boundary regex can only match if the bare keyword occurs at all, so
    the 19 regex matches per title become 19 ``in`` checks that escalate to a
    regex only on a hit. The regex is still the arbiter — "international"
    contains "intern" but does not word-boundary-match it — so the answer is
    unchanged by construction.
    """
    if not text or not text.strip():
        return None
    lowered = text.casefold()
    for keyword, rank, pattern in _SENIORITY_PATTERNS:
        if keyword in lowered and pattern.search(lowered) is not None:
            return rank
    return None


def _effective_preferences(profile: CandidateProfile) -> WorkPreferences:
    """The candidate's preferences: what they confirmed, then what the résumé said.

    WS-21 makes the merge explicit about *cleared* values. The application
    profile is saved as a whole document, and ``confirmed_fields`` records the
    groups the user saved: once ``preferences`` is confirmed, every field it
    owns is the user's answer — including an empty one, which means "cleared"
    and must not resurrect the résumé's value. The same holds for
    ``answers.compensation``: a confirmed expectation beats the résumé's
    verbatim ``min_salary`` (the WS-20 order had it backwards), and a
    confirmed empty salary is *no* floor, not the old one.

    Groups without a marker keep the WS-20 semantics (a truthy confirmed value
    wins, the résumé is the fallback), so a pre-WS-21 save behaves as it did.
    """
    resume = profile.work_preferences
    app = getattr(profile, "application_profile", None)
    prefs = getattr(app, "preferences", None) if app is not None else None
    answers = getattr(app, "answers", None) if app is not None else None
    if prefs is None:
        return resume

    confirmed = set(getattr(app, "confirmed_fields", None) or [])
    preferences_confirmed = "preferences" in confirmed
    compensation_confirmed = "answers.compensation" in confirmed

    merged = resume.model_copy(deep=True)
    if preferences_confirmed:
        # Explicitly saved: even an empty value is the answer.
        merged.remote_preference = prefs.remote_preference
        merged.preferred_locations = list(prefs.preferred_locations)
        merged.employment_types = list(prefs.employment_types)
    else:
        if prefs.remote_preference:
            merged.remote_preference = prefs.remote_preference
        if prefs.preferred_locations:
            merged.preferred_locations = list(prefs.preferred_locations)
        if prefs.employment_types:
            merged.employment_types = list(prefs.employment_types)

    compensation = getattr(answers, "compensation", None) if answers is not None else None
    expected = getattr(compensation, "expected_salary", None) if compensation is not None else None
    if compensation_confirmed:
        merged.min_salary = None
        if expected is not None:
            currency = getattr(compensation, "expected_currency", None) or ""
            merged.min_salary = f"{currency} {expected:g}".strip()
    elif expected is not None and not merged.min_salary:
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


def _skill_component(
    job: JobListing, profile: CandidateProfile, *, context: CandidateContext | None = None
) -> ComponentScore:
    required = [skill for skill in job.required_skills if skill.strip()]
    preferred = [skill for skill in job.preferred_skills if skill.strip()]
    matched_names = [*required, *preferred]
    if not matched_names:
        return ComponentScore(
            name="skill",
            state=ScoreState.JOB_REQUIREMENT_MISSING,
            reason="the listing states no required or preferred skills",
        )
    if context is None:
        context = CandidateContext.for_profile(profile)
    candidate = context.skill_set
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


def _experience_component(
    job: JobListing,
    profile: CandidateProfile,
    *,
    requirement: float | None | object = _UNCACHED,
    context: CandidateContext | None = None,
) -> ComponentScore:
    if requirement is _UNCACHED:
        from src.matching.experience import required_years

        requirement = required_years(job)
    if requirement is None:
        return ComponentScore(
            name="experience",
            state=ScoreState.JOB_REQUIREMENT_MISSING,
            reason="the listing states no experience requirement",
        )
    # WS-24c: the candidate's total experience is derived once per search,
    # not twice per listing. It used to be computed here AND again inside
    # ``experience_score``, each a union over every dated entry.
    if context is None:
        context = CandidateContext.for_profile(profile)
    actual = context.years_of_experience
    if actual is None:
        return ComponentScore(
            name="experience",
            state=ScoreState.CANDIDATE_DATA_MISSING,
            reason=(
                f"the job asks for {requirement:.0f} years of experience; the candidate "
                "profile has no dated experience"
            ),
        )
    # The same arithmetic ``experience_score`` performs, on the two values
    # already resolved above — so the second date-range union is not paid.
    value = max(0.0, min(100.0, 100.0 - 25.0 * max(0.0, requirement - actual)))
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


def _seniority_component(
    job: JobListing,
    profile: CandidateProfile,
    *,
    job_rank: int | None | object = _UNCACHED,
    candidate_rank: int | None | object = _UNCACHED,
) -> ComponentScore:
    """The seniority comparison.

    WS-24c: both ranks are precomputable — the job's from the listing (the
    corpus artifacts carry it), the candidate's from the profile (the
    context carries it). Each was being derived per listing; the candidate's
    in particular walked every dated experience entry on every one.
    """
    if job_rank is _UNCACHED:
        job_rank = _seniority_rank(job.seniority) or _seniority_rank(job.title)
    if job_rank is None:
        return ComponentScore(
            name="seniority",
            state=ScoreState.JOB_REQUIREMENT_MISSING,
            reason="the listing states no seniority level",
        )
    if candidate_rank is _UNCACHED:
        candidate_rank = _candidate_rank(profile)
    if candidate_rank is None:
        return ComponentScore(
            name="seniority",
            state=ScoreState.CANDIDATE_DATA_MISSING,
            reason="the candidate profile states no seniority level or titled role",
        )
    value = max(0.0, min(100.0, 100.0 - 30.0 * abs(candidate_rank - job_rank)))
    return ComponentScore(name="seniority", value=value, state=measured_state(value))


def _location_component(
    job: JobListing,
    profile: CandidateProfile,
    *,
    context: CandidateContext | None = None,
) -> ComponentScore:
    if context is None:
        context = CandidateContext.for_profile(profile)
    prefs = context.effective_preferences
    policy = (job.remote_policy or "").casefold().replace("-", "").replace(" ", "")
    job_location = (job.location or "").casefold()
    preferred = context.preferred_locations

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
        return ComponentScore(name="location", value=value, state=measured_state(value))

    # WS-23: the fallback used to assert ``value = 40.0`` — a **measured**
    # PARTIAL_MATCH — when the listing stated neither a policy nor a
    # matching location. Under a fixed denominator that is not a neutral
    # default: it is a 5.4-point penalty (weight 0.09 x (100 - 40))
    # applied to every listing whose source does not publish a work mode.
    # Measured before this change: 78.5% of the corpus (all 5,255
    # Greenhouse rows and all 350 Lever rows) took this branch, including
    # listings that were fully remote.
    #
    # The honest reading of "the listing states no location or work mode"
    # is **unknown**, and unknown has a meaning in this engine: it
    # contributes zero to the numerator and keeps its weight in the
    # denominator, so it lowers the score and shows up in
    # ``evidence_coverage``. The 40 was a hidden subsidy for sparse rows
    # dressed up as a measurement.
    #
    # A listing that DOES state a location, but one the candidate did not
    # name, is still a measurement: it is a location that does not match.
    if job_location:
        value = 40.0
        return ComponentScore(name="location", value=value, state=measured_state(value))
    return ComponentScore(
        name="location",
        state=ScoreState.JOB_REQUIREMENT_MISSING,
        reason="the listing states no location or work mode",
    )


def _preference_component(
    job: JobListing,
    profile: CandidateProfile,
    *,
    context: CandidateContext | None = None,
) -> ComponentScore:
    if context is None:
        context = CandidateContext.for_profile(profile)
    subscores: list[float] = []
    job_has_signal = False

    employment_pref = context.employment_types
    job_employment = _normalize_employment_type(job.employment_type)
    if job_employment:
        job_has_signal = True
    if employment_pref and job_employment:
        subscores.append(100.0 if job_employment in employment_pref else 40.0)

    candidate_min = context.parsed_min_salary
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
    *,
    important_terms: list[tuple[str, float]] | None = None,
    context: CandidateContext | None = None,
) -> ComponentScore:
    if context is None:
        context = CandidateContext.for_profile(profile)
    tokens = context.tokens
    text = context.text
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
        job,
        index=index,
        candidate_token_list=tokens,
        candidate_text=text,
        important_terms=important_terms,
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


class CandidateContext:
    """The candidate-derived values that every listing's score needs.

    WS-24. These are pure functions of the **profile**, and the profile
    does not change while a search runs — but they were being recomputed
    for every listing. Measured on the 6,696-listing corpus, a warm
    search spent **10.8 s** of its 12.6 s re-tokenizing the candidate's
    text 6,697 times, and a further 3.0 s re-embedding the candidate
    query for the same reason.

    Computing them once and sharing them turns the per-listing work from
    O(N) tokenizations into O(1) plus O(N) dictionary lookups.

    The context is built once per search and passed to
    :func:`calculate_match`. It is immutable, so sharing it across
    listings and across requests (while the profile is unchanged) is
    safe.
    """

    __slots__ = (
        "candidate_rank",
        "effective_preferences",
        "employment_types",
        "lowered_text",
        "parsed_min_salary",
        "preferred_locations",
        "profile",
        "skill_set",
        "text",
        "token_set",
        "tokens",
        "years_of_experience",
    )

    def __init__(
        self,
        profile: CandidateProfile,
        *,
        tokens: list[str],
        text: str,
    ) -> None:
        self.profile = profile
        self.tokens = tokens
        self.text = text
        #: The candidate's skills, lowercased once. The skill component
        #: compares every listing's skills against it, and the comparison
        #: was rebuilding the set for each listing.
        self.skill_set = frozenset(
            skill.strip().casefold() for skill in profile.skills if skill.strip()
        )
        #: The candidate's tokens as a set, built once (WS-24b).
        #:
        #: ``lexical_score`` rebuilt this for every listing — 8,558
        #: identical set constructions per search — to answer "is this
        #: term one the candidate has?".
        self.token_set = frozenset(tokens)
        #: The candidate's text, lowercased once (WS-24b).
        #:
        #: The phrase check lowercased the whole candidate text for every
        #: listing: 8,558 lowerings of the same string per search.
        self.lowered_text = text.lower()

        # -- WS-24c: the rest of the per-listing candidate recomputation ----
        #
        # Every value below is a pure function of the profile, and the
        # profile does not change while a search runs. Each was computed
        # inside a component builder, so a search paid for it once per
        # listing: the preferences merge alone deep-copied the whole
        # ``WorkPreferences`` model twice per listing (17,116 copies per
        # search on the 8,558-listing corpus), and the candidate's years of
        # experience were re-derived from an entry-by-entry date-range union
        # twice per listing.
        self.effective_preferences = _effective_preferences(profile)
        self.candidate_rank = _candidate_rank(profile)
        from src.matching.experience import years_of_experience as _years_of_experience

        self.years_of_experience = _years_of_experience(profile)
        #: The preferred locations, stripped and lowercased once — the
        #: location component rebuilt this list for every listing.
        self.preferred_locations = tuple(
            location.strip().casefold()
            for location in self.effective_preferences.preferred_locations
            if location.strip()
        )
        #: The employment types the candidate accepts, normalized once.
        self.employment_types = tuple(
            normalized
            for normalized in (
                _normalize_employment_type(value)
                for value in self.effective_preferences.employment_types
            )
            if normalized
        )
        #: The candidate's salary floor, parsed once from its free-form text.
        self.parsed_min_salary = _parse_salary(self.effective_preferences.min_salary)

    @classmethod
    def for_profile(cls, profile: CandidateProfile) -> CandidateContext:
        """Build the context for a profile."""
        return cls(
            profile,
            tokens=candidate_tokens(profile),
            text=candidate_lexical_text(profile),
        )


class ListingScore(NamedTuple):
    """The numbers a **ranking** needs, and nothing else (WS-29).

    `calculate_match` builds a 23-field result with an explanation string, a
    note list and an eight-entry state map. Ranking needs three numbers. On the
    live corpus 8,528 of 8,558 full results are built and discarded
    (99.6% at `top_n=30`), so the bulk path scores with this and materializes
    only the survivors.
    """

    overall_score: float
    evidence_coverage: float
    role_capped: bool


def _scored_components(
    job: JobListing,
    profile: CandidateProfile,
    *,
    semantic_score: float | None,
    semantic_state: ScoreState | None,
    lexical: LexicalResult | None,
    bm25_index: Bm25Index | None,
    effective_weights: dict[str, float],
    artifacts: CorpusArtifacts | None,
    context: CandidateContext,
) -> tuple[dict[str, ComponentScore], RoleRelevance]:
    """The eight components and the role comparison, for one listing.

    Shared by :func:`calculate_match` and :func:`score_listing` so the two can
    never disagree about a number — the only difference between them is what
    they do with the result.
    """
    cached_classification = (
        artifacts.role_classifications.get(job.id) if artifacts is not None else None
    )
    relevance = role_relevance(profile, job, classification=cached_classification)

    cached_terms = artifacts.lexical_terms.get(job.id) if artifacts is not None else None
    cached_requirement: float | None | object = (
        artifacts.required_years.get(job.id, _UNCACHED) if artifacts is not None else _UNCACHED
    )
    cached_rank: int | None | object = (
        artifacts.seniority_ranks.get(job.id, _UNCACHED) if artifacts is not None else _UNCACHED
    )

    components: dict[str, ComponentScore] = {
        "semantic": _semantic_component(job, semantic_score, semantic_state),
        "lexical": _lexical_component(
            job,
            profile,
            lexical,
            bm25_index,
            important_terms=cached_terms,
            context=context,
        ),
        "skill": _skill_component(job, profile, context=context),
        "experience": _experience_component(
            job, profile, requirement=cached_requirement, context=context
        ),
        "seniority": _seniority_component(
            job, profile, job_rank=cached_rank, candidate_rank=context.candidate_rank
        ),
        "location": _location_component(job, profile, context=context),
        "preference": _preference_component(job, profile, context=context),
        "role": _role_component(relevance),
    }
    return components, relevance


def _overall_score(
    components: dict[str, ComponentScore],
    relevance: RoleRelevance,
    effective_weights: dict[str, float],
) -> tuple[float, Any]:
    """The blended score, with the WS-21 role cap applied."""
    blended = blend(effective_weights, components)
    overall = blended.overall_score
    if relevance.capped:
        overall = min(overall, ROLE_MISMATCH_CAP)
    return overall, blended


def score_listing(
    job: JobListing,
    profile: CandidateProfile,
    *,
    semantic_score: float | None = None,
    semantic_state: ScoreState | None = None,
    lexical: LexicalResult | None = None,
    bm25_index: Bm25Index | None = None,
    weights: dict[str, float] | None = None,
    artifacts: CorpusArtifacts | None = None,
    context: CandidateContext | None = None,
) -> ListingScore:
    """Score one listing **for ranking**, without materializing a result.

    The same components, the same blend and the same role cap as
    :func:`calculate_match` — they share :func:`_scored_components` and
    :func:`_overall_score`, and `tests/test_ws29_two_phase_scoring.py` pins that
    the two agree to the last digit. What this omits is the materialization: the
    explanation string, the notes, the evidence lists, the component-state map
    and the pydantic validation of a 23-field model.

    Use this to rank a corpus, then :func:`calculate_match` for the slice that
    will actually be returned.
    """
    if weights is not None:
        effective_weights = validate_weights(weights)
    else:
        configured = get_settings().match_weights
        effective_weights = validate_weights(configured) if configured else dict(DEFAULT_WEIGHTS)

    if context is None:
        context = CandidateContext.for_profile(profile)

    components, relevance = _scored_components(
        job,
        profile,
        semantic_score=semantic_score,
        semantic_state=semantic_state,
        lexical=lexical,
        bm25_index=bm25_index,
        effective_weights=effective_weights,
        artifacts=artifacts,
        context=context,
    )
    overall, blended = _overall_score(components, relevance, effective_weights)
    return ListingScore(
        overall_score=overall,
        evidence_coverage=blended.evidence_coverage,
        role_capped=relevance.capped,
    )


def calculate_match(
    job: JobListing,
    profile: CandidateProfile,
    *,
    semantic_score: float | None = None,
    semantic_state: ScoreState | None = None,
    lexical: LexicalResult | None = None,
    bm25_index: Bm25Index | None = None,
    weights: dict[str, float] | None = None,
    artifacts: CorpusArtifacts | None = None,
    context: CandidateContext | None = None,
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
        artifacts: The corpus cache (WS-21 follow-up). When the listing is in
            it, the per-listing computations that depend only on the listing —
            its important terms and its stated experience bar — are read
            instead of recomputed; a listing outside the cache computes them
            as before.
        context: The candidate-derived values (WS-24), computed once per
            search and shared by every listing. Without it they are
            recomputed per listing, which cost 10.8 s of a warm search on
            the 6,696-listing corpus.

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

    if context is None:
        context = CandidateContext.for_profile(profile)

    # WS-21: the occupational-role comparison, computed once and turned into
    # the eighth component below (and, on a WEAK/UNRELATED role, the cap).
    #
    # WS-24: the listing's classification comes from the corpus cache when
    # it is there, so the taxonomy scan is not repeated for every listing
    # on every search.
    #
    # WS-29: the components and the cap are shared with `score_listing`, which
    # ranks the corpus without materializing a result. Extracting them is what
    # guarantees the two paths cannot disagree about a number.
    components, relevance = _scored_components(
        job,
        profile,
        semantic_score=semantic_score,
        semantic_state=semantic_state,
        lexical=lexical,
        bm25_index=bm25_index,
        effective_weights=effective_weights,
        artifacts=artifacts,
        context=context,
    )
    overall, blended = _overall_score(components, relevance, effective_weights)

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

    # WS-24c: this ran at INFO for every listing — 8,558 log records per
    # search, each through the PII-masking filter. The search's own summary
    # (in ``search_stored_jobs``) is the record an operator reads; a
    # per-listing line belongs at DEBUG.
    logger.debug("Match calculated for %s at %s: %.1f", job.title, job.company, overall)

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
