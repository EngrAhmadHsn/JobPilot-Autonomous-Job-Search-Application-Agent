"""Experience-year parsing for the matching engine (WS-03, WS-20).

Deterministic extraction of candidate experience span and job requirement
years. A year is only ever counted when a date range (or an explicit
``ExperienceEntry.years``) says so — nothing is inferred from project lists,
education dates, or skill mentions.

WS-20 changes:

- **No double counting.** Every dated range across every entry is collected and
  *unioned*, so two concurrent roles count once, not twice. The old
  per-entry ``max(end) - min(start)`` summed overlaps.
- **The whole description is searched**, not just the first line, and the
  requirement patterns cover ``3+ years``, ``3-5 years``, ``at least 4
  years``, ``minimum of 3 years``, ``4 or more years``.
- **Total vs technology-specific.** A requirement of the form ``3 years with
  Python`` / ``4 years of React experience`` is reported as a
  technology-specific bar and is **not** used as the total professional bar.
- **Explicit candidate facts supplement the résumé.** An
  ``ApplicationProfile.professional.total_experience_years`` the user confirmed
  is used when the résumé has no dated experience.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from src.jobs.contracts import JobListing
from src.resume.profile import CandidateProfile

# Same pattern as src/resume/parser.py: "2019 - 2022", "2019 – present", "2020 to 2021".
_YEAR_RANGE_RE = re.compile(
    r"\b((?:19|20)\d{2})\b\s*(?:-|–|—|to)\s*(?:\b((?:19|20)\d{2})\b|present)", re.IGNORECASE
)

# "3+ years", "at least 4 years", "minimum of 3 years", "4 or more years",
# "3-5 years". The leading phrase is optional; a bare "N years" also matches.
_YEARS_CONTEXT = r"(?:(?:at\s+least|minimum(?:\s+of)?|min\.?|over|more\s+than)\s+)?"
_REQUIRED_YEARS_RE = re.compile(
    rf"(?:{_YEARS_CONTEXT})(?P<years>\d+(?:\.\d+)?)(?:\s*-\s*\d+(?:\.\d+)?)?\s*\+?\s*years?",
    re.IGNORECASE,
)
_REQUIRED_RANGE_RE = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*-\s*(?P<high>\d+(?:\.\d+)?)\s*\+?\s*years?",
    re.IGNORECASE,
)
_OR_MORE_RE = re.compile(r"(?P<years>\d+(?:\.\d+)?)\s+or\s+more\s+years?", re.IGNORECASE)

# "... years (of experience)? (in|with|using|of) <tech>" — a technology bar.
# The generic nouns are excluded: "5 years of experience" is a *total* bar,
# not a technology bar, and only "5 years in React" is specific.
_TECH_CONTEXT_RE = re.compile(
    r"years?\s+(?:of\s+)?(?:professional\s+|hands-on\s+|industry\s+)?"
    r"(?:experience\s+)?(?:in|with|using|of)\s+"
    r"(?!(?:experience|work|professional|related|relevant|similar|prior|industry)\b)"
    r"(?P<tech>[A-Za-z][\w.+#/-]*)",
    re.IGNORECASE,
)

MAX_CANDIDATE_YEARS = 50.0
MAX_REQUIRED_YEARS = 30.0


def _merge_ranges(ranges: list[tuple[float, float]]) -> float:
    """Total years covered by a set of ranges, counting overlaps once."""
    if not ranges:
        return 0.0
    ordered = sorted(ranges)
    total = 0.0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            total += current_end - current_start
            current_start, current_end = start, end
    total += current_end - current_start
    return total


def years_of_experience(profile: CandidateProfile) -> float | None:
    """Total experience span in years from dated entries, or None if undated.

    Every dated range across the whole profile is unioned, so overlapping
    employment is counted once. Entries without parseable dates fall back to an
    explicit ``years`` value when present. When the résumé has no dated
    experience, an explicitly confirmed ``total_experience_years`` on the
    application profile is used instead of returning ``None``.
    """
    current_year = datetime.now(tz=UTC).year
    ranges: list[tuple[float, float]] = []
    for entry in profile.experience:
        matched_any = False
        for match in _YEAR_RANGE_RE.finditer(entry.dates or ""):
            start = float(match.group(1))
            end = float(match.group(2)) if match.group(2) else float(current_year)
            ranges.append((start, end))
            matched_any = True
        if not matched_any and entry.years is not None and entry.years > 0:
            # An explicit years figure is a duration, not a date range: keep it
            # as a synthetic range so it unions with the others.
            ranges.append((0.0, float(entry.years)))
    if ranges:
        return min(_merge_ranges(ranges), MAX_CANDIDATE_YEARS)
    return confirmed_years(profile)


def confirmed_years(profile: CandidateProfile) -> float | None:
    """Years the user explicitly confirmed (application profile), or None."""
    app = getattr(profile, "application_profile", None)
    if app is None:
        return None
    value = getattr(getattr(app, "professional", None), "total_experience_years", None)
    if value is None or value <= 0:
        return None
    return min(float(value), MAX_CANDIDATE_YEARS)


def required_years(job: JobListing) -> float | None:
    """Years of experience the listing demands, or None when unstated.

    The **whole** description is searched (WS-20), not just its first line.
    ``experience_requirements`` is searched first. For a range ("3-5 years")
    the top of the stated range is the bar. A technology-specific mention
    ("3 years with Python") is skipped in favour of a general bar.
    """
    text = (job.experience_requirements or "").strip()
    parts = [text] if text else []
    if job.description:
        parts.append(job.description)
    return _extract_required_years("\n".join(parts))


def _extract_required_years(text: str) -> float | None:
    if not text:
        return None
    general: list[float] = []
    for sentence in re.split(r"[\n.;•]+", text):
        years = _years_in_sentence(sentence)
        if years is None:
            continue
        # Skip a technology-specific bar: it is not the total requirement.
        if _TECH_CONTEXT_RE.search(sentence):
            continue
        general.append(years)
    if not general:
        return None
    return min(max(general), MAX_REQUIRED_YEARS)


def _years_in_sentence(sentence: str) -> float | None:
    """The stated bar in one sentence, or None.

    Order matters: an explicit "N or more" or "at least N" beats a bare range,
    and a range ("3-5") is read as its top. The first matching form wins so the
    earliest requirement in the sentence is the one reported.
    """
    earliest: tuple[int, float] | None = None
    for regex, pick in (
        (_OR_MORE_RE, lambda m: float(m.group("years"))),
        (_REQUIRED_RANGE_RE, lambda m: float(m.group("high"))),
    ):
        match = regex.search(sentence)
        if match is not None:
            candidate = (match.start(), pick(match))
            if earliest is None or candidate[0] < earliest[0]:
                earliest = candidate
    phrase = _REQUIRED_YEARS_RE.search(sentence)
    if phrase is not None:
        candidate = (phrase.start(), float(phrase.group("years")))
        if earliest is None or candidate[0] < earliest[0]:
            earliest = candidate
    if earliest is None:
        return None
    return min(earliest[1], MAX_REQUIRED_YEARS)


def experience_score(job: JobListing, profile: CandidateProfile) -> float | None:
    """Score how candidate experience meets the stated requirement.

    ``100 - 25`` per missing year, clamped to 0-100. Returns ``None`` when
    either side is unknown (no requirement stated, or no dated candidate
    experience) — the engine turns that into an explicit
    ``JOB_REQUIREMENT_MISSING`` / ``CANDIDATE_DATA_MISSING`` state rather than
    a neutral 70 (WS-20).
    """
    required = required_years(job)
    if required is None:
        return None
    actual = years_of_experience(profile)
    if actual is None:
        return None
    return max(0.0, min(100.0, 100.0 - 25.0 * max(0.0, required - actual)))
