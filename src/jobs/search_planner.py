"""Deterministic search-query planner (WS-02 task 4).

Turns a parsed candidate profile into per-source queries. Pure function, no
LLM (plan §22.2): queries come only from the profile's own title and skills,
in a fixed derivation order, so the same profile always plans the same
queries.

Greenhouse and Lever have no server-side query parameter — they are fetched
board-wide and filtered client-side by the adapter — while Remotive benefits
from a single focused free-text query. The planner therefore produces at most
three queries (title, first skill trio, second skill trio) applied to every
configured source; adapters use or ignore them as their API allows.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from src.resume.profile import CandidateProfile

# Sources planned for by default; the registry owns the actual adapters.
PLANNED_SOURCES: tuple[str, ...] = ("greenhouse", "lever", "remotive")

_MAX_QUERIES = 3
_SKILLS_PER_QUERY = 3


class SourceQuery(BaseModel):
    """One planned query for one source."""

    source: str
    query: str
    location: str | None = None


def _derive_query_strings(profile: CandidateProfile) -> list[str]:
    queries: list[str] = []
    title = profile.personal_information.title.strip()
    if title:
        queries.append(title)
    skills = [skill.strip() for skill in profile.skills if skill.strip()]
    start = 0
    while len(queries) < _MAX_QUERIES and start < len(skills):
        combo = " ".join(skills[start : start + _SKILLS_PER_QUERY])
        start += _SKILLS_PER_QUERY
        if combo.lower() not in {q.lower() for q in queries}:
            queries.append(combo)
    return queries


def plan_queries(
    profile: CandidateProfile, sources: Sequence[str] = PLANNED_SOURCES
) -> list[SourceQuery]:
    """Derive 1-3 queries per source from a candidate profile.

    Args:
        profile: Parsed candidate profile driving the derivation.
        sources: Source names to plan for; defaults to the production
            sources. The pipeline passes its actually-registered sources so
            fixture/injected adapters get queries too (WS-04).

    An empty query string means "fetch everything the source offers with no
    text filter" — used when the profile has neither a title nor skills.
    """
    query_strings = _derive_query_strings(profile) or [""]
    return [
        SourceQuery(source=source, query=query) for query in query_strings for source in sources
    ]
