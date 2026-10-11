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


async def _fan_out(
    queries: Sequence[SourceQuery],
    active_sources: Mapping[str, JobSource],
) -> tuple[list[JobListing], dict[str, str]]:
    """Run every planned query concurrently, tolerating per-source failures.

    Returns the raw (un-deduplicated) listings from every source that
    answered plus a ``source -> error message`` map for the sources that
    raised (plan §35: a failing source degrades the search, never fails it).
    """
    planned: list[tuple[str, JobSource, SourceQuery]] = []
    for query in queries:
        adapter = active_sources.get(query.source)
        if adapter is None:
            logger.warning("No adapter registered for source %r; skipping query", query.source)
            continue
        planned.append((query.source, adapter, query))

    if not planned:
        return [], {}

    results = await asyncio.gather(
        *(adapter.search(query.query, query.location) for _source, adapter, query in planned),
        return_exceptions=True,
    )

    listings: list[JobListing] = []
    source_errors: dict[str, str] = {}
    for (source, _adapter, _query), result in zip(planned, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("Job source %s failed and was skipped: %s", source, result)
            source_errors[source] = f"{type(result).__name__}: {result}"
            continue
        listings.extend(result)
    return listings, source_errors


async def search_all_detailed(
    queries: Sequence[SourceQuery],
    sources: Mapping[str, JobSource] | None = None,
) -> tuple[list[JobListing], dict[str, str]]:
    """Search sources and report per-source errors alongside the raw listings.

    WS-04 pipeline primitive (``src.graph.job_workflow`` search node): unlike
    :func:`search_all` it does not deduplicate or persist — the pipeline owns
    those as explicit nodes — and it surfaces which sources failed instead of
    only logging, so the failure is visible in the search report.
    """
    active_sources = sources if sources is not None else SOURCES
    return await _fan_out(queries, active_sources)


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
    listings, _errors = await _fan_out(queries, active_sources)

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
