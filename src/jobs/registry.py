"""Job-source registry and multi-source search orchestration (WS-02 task 5).

``SOURCES`` maps source names to adapter singletons. ``search_all`` fans a
list of planned queries out to the requested sources concurrently, skips a
source whose adapter raised (plan §35: "job source unavailable → try
another"), deduplicates the results, persists the survivors, and returns
them. A failing source degrades to a warning, never a failed search.

**The dedup is per source, not across sources.** ``src/jobs/deduplicate.py``
keys include ``job.source``, so the same posting on Greenhouse and on
Ashby is **two rows**. This docstring used to say "deduplicates across
sources", which the code has never done — a docstring that overclaims is
worse than a missing one, because a reader relies on it instead of
reading the code. Cross-source merging is WS-26 Phase 2 / WS-23b §12.3.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence

from src.jobs.ashby_adapter import AshbyJobAdapter
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
    "ashby": AshbyJobAdapter(),
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


async def fetch_changed_all(
    sources: Mapping[str, JobSource] | None = None,
    *,
    session_factory=None,
) -> tuple[list[JobListing], dict[str, str]]:
    """The listings that changed since the last refresh (WS-23, Phase 4).

    A source that implements :class:`~src.jobs.contracts.DeltaJobSource`
    is asked only for what changed; every other source is fetched whole.

    The reason this matters is not speed — it is **completeness**. The
    refresh used to fetch each board in one request with
    ``?content=true``. A board whose response exceeded the size cap
    raised ``SourceError`` and the whole board vanished: three live boards
    (9.83, 9.58 and 13.58 MiB) were silently dropped by the 8 MiB cap,
    taking 1,696 listings with them. The delta path fetches the *light*
    list instead — 91 KB to 792 KB for every board in the registry — and
    then fetches content only for the listings that changed, so the
    oversized-board cliff does not exist.

    The stored change stamps live in ``jobs.extra_metadata["updated_at"]``,
    which is where the adapter writes them.

    Returns:
        The changed listings, and a ``source -> error`` map for the
        sources that failed. A source that fails contributes nothing and
        is reported; the others still refresh.
    """
    active_sources = sources if sources is not None else SOURCES
    known = _stored_update_stamps(session_factory)

    listings: list[JobListing] = []
    errors: dict[str, str] = {}

    for name, adapter in active_sources.items():
        fetch_changed = getattr(adapter, "fetch_changed", None)
        if fetch_changed is None:
            # The source cannot report deltas; fetch it whole.
            try:
                full = await adapter.search("")
            except Exception as exc:  # noqa: BLE001 - a source degrades, never fails
                logger.warning("Job source %s failed and was skipped: %s", name, exc)
                errors[name] = f"{type(exc).__name__}: {exc}"
                continue
            listings.extend(full)
            continue
        try:
            changed = await fetch_changed(known.get(name, {}))
        except Exception as exc:  # noqa: BLE001 - a source degrades, never fails
            logger.warning("Job source %s failed its delta refresh: %s", name, exc)
            errors[name] = f"{type(exc).__name__}: {exc}"
            continue
        listings.extend(changed)

    return listings, errors


def _stored_update_stamps(session_factory=None) -> dict[str, dict[str, str]]:
    """The stored change stamp for every listing, grouped by source.

    The stamp is the adapter's own ``updated_at`` value, kept in
    ``extra_metadata`` so the delta can be computed without adding a
    column per source.
    """
    from sqlalchemy import select

    from src.db.jobs import JobDB
    from src.db.session import SessionLocal

    factory = session_factory or SessionLocal
    stamps: dict[str, dict[str, str]] = {}
    try:
        with factory() as session:
            rows = session.execute(select(JobDB.id, JobDB.source, JobDB.extra_metadata)).all()
    except Exception:
        logger.exception("Could not read the stored change stamps; every listing is treated as new")
        return stamps
    for job_id, source, metadata in rows:
        if not isinstance(metadata, dict):
            continue
        stamp = metadata.get("updated_at")
        if not isinstance(stamp, str) or not stamp:
            continue
        stamps.setdefault(source, {})[job_id] = stamp
    return stamps


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
