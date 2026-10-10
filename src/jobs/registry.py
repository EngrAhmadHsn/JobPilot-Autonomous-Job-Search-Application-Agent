"""Job-source registry and multi-source search orchestration (WS-02 task 5).

``SOURCES`` maps source names to adapter singletons. ``search_all`` fans a
list of planned queries out to the requested sources concurrently, skips a
source whose adapter raised (plan §35: "job source unavailable → try
another"), deduplicates across sources, persists the survivors, and returns
them. A failing source degrades to a warning, never a failed search.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence

from src.jobs.contracts import JobListing, JobSource
from src.jobs.deduplicate import deduplicate
from src.jobs.greenhouse_adapter import GreenhouseJobAdapter
from src.jobs.lever_adapter import LeverJobAdapter
from src.jobs.remotive_adapter import RemotiveJobAdapter
from src.jobs.search_planner import SourceQuery

logger = logging.getLogger(__name__)

SOURCES: dict[str, JobSource] = {
    "greenhouse": GreenhouseJobAdapter(),
    "lever": LeverJobAdapter(),
    "remotive": RemotiveJobAdapter(),
}

# The LinkedIn placeholder adapter exists in the tree but is deliberately
# NOT registered here: it returns nothing and AGENTS.md forbids scraping
# LinkedIn (see docs/implementation/00-OVERVIEW.md, out-of-scope list).


async def search_all(
    queries: Sequence[SourceQuery],
    sources: Mapping[str, JobSource] | None = None,
    *,
    persist: bool = True,
) -> list[JobListing]:
    """Search the requested sources, dedup, persist, and return unique listings.

    Args:
        queries: Planned queries (see ``src.jobs.search_planner.plan_queries``);
            queries for unknown source names are skipped with a warning.
        sources: Source-name -> adapter mapping; defaults to ``SOURCES``.
            Tests inject MockTransport-backed adapters here.
        persist: Upsert the deduplicated listings into the ``jobs`` table
            (default). Disable for pure in-memory searches.

    Returns:
        Deduplicated listings from every source that answered.
    """
    active_sources = sources if sources is not None else SOURCES
    planned: list[tuple[str, JobSource, SourceQuery]] = []
    for query in queries:
        adapter = active_sources.get(query.source)
        if adapter is None:
            logger.warning("No adapter registered for source %r; skipping query", query.source)
            continue
        planned.append((query.source, adapter, query))

    if not planned:
        return []

    results = await asyncio.gather(
        *(adapter.search(query.query, query.location) for _source, adapter, query in planned),
        return_exceptions=True,
    )

    listings: list[JobListing] = []
    for (source, _adapter, _query), result in zip(planned, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("Job source %s failed and was skipped: %s", source, result)
            continue
        listings.extend(result)

    unique = deduplicate(listings)
    if persist and unique:
        from src.db.jobs import save_jobs

        try:
            saved = save_jobs(unique)
            logger.info("Persisted %d/%d unique listings to the jobs table", saved, len(unique))
        except Exception:
            # Persistence failure must not discard an in-memory search result.
            logger.exception(
                "Persisting %d listings failed; returning them unpersisted", len(unique)
            )
    return unique
