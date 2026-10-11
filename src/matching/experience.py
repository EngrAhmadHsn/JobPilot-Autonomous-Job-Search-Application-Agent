"""Experience-year parsing for the matching engine (WS-03).

Deterministic extraction of candidate experience span and job requirement
years. A year is only ever counted when a date range (or an explicit
``ExperienceEntry.years``) says so — nothing is inferred from project lists,
education dates, or skill mentions.

Year-range parsing uses the same pattern as the resume parser
(``_YEAR_RANGE_RE`` there); "present" resolves to the current year.
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
# "5+ years", "at least 3 years", "3-5 years" (first number is the stated bar).
_REQUIRED_YEARS_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*\+?\s*years?\b", re.IGNORECASE)

MAX_CANDIDATE_YEARS = 50.0
MAX_REQUIRED_YEARS = 30.0


def years_of_experience(profile: CandidateProfile) -> float | None:
    """Total experience span in years from dated entries, or None if undated.

    Each entry contributes ``max_end - min_start`` of its own date ranges
    (overlaps within one entry are not double-counted); entries without
    parseable dates fall back to an explicit ``years`` value when present.
    """
    total = 0.0
    dated_any = False
    current_year = datetime.now(tz=UTC).year
    for entry in profile.experience:
        ranges: list[tuple[float, float]] = []
        for match in _YEAR_RANGE_RE.finditer(entry.dates or ""):
            start = float(match.group(1))
            end = float(match.group(2)) if match.group(2) else float(current_year)
            ranges.append((start, end))
        if ranges:
            dated_any = True
            total += max(0.0, max(end for _, end in ranges) - min(start for start, _ in ranges))
        elif entry.years is not None and entry.years > 0:
            dated_any = True
            total += float(entry.years)
    if not dated_any:
        return None
    return min(total, MAX_CANDIDATE_YEARS)


def required_years(job: JobListing) -> float | None:
    """Years of experience the listing demands, or None when unstated.

    Searched in ``experience_requirements`` first, then the description's
    first line. For a range ("3-5 years") the regex naturally lands on the
    last number before "years", i.e. the top of the stated range.
    """
    text = (job.experience_requirements or "").strip()
    if not text and job.description:
        text = job.description.strip().splitlines()[0] if job.description.strip() else ""
    match = _REQUIRED_YEARS_RE.search(text)
    if match is None:
        return None
    return min(float(match.group(1)), MAX_REQUIRED_YEARS)


def experience_score(job: JobListing, profile: CandidateProfile) -> float:
    """Score how candidate experience meets the stated requirement.

    ``100 - 25`` per missing year, clamped to 0-100. When either side is
    unknown (no requirement stated, or no dated candidate experience) the
    score is the documented neutral 70 — absence of evidence is not scored
    as failure.
    """
    required = required_years(job)
    if required is None:
        return 70.0
    actual = years_of_experience(profile)
    if actual is None:
        return 70.0
    return max(0.0, min(100.0, 100.0 - 25.0 * max(0.0, required - actual)))
