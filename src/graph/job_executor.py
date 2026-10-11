"""Executor for the job-search pipeline (WS-04): graph + report assembly.

Runs the compiled pipeline (``src.graph.job_workflow``) synchronously and
wraps the outcome in a serializable ``JobSearchReport``. Per plan §35 the
executor degrades instead of raising: source failures land in
``source_errors``, vector-store/persistence failures flip the report's
``degraded``/stats fields — an empty result set with a populated error map is
a valid, successful report.

FU-1 splits the production paths: :func:`refresh_jobs` fetches boards →
normalizes → deduplicates → persists → embeds (only new/changed texts, via
the content-hash cache) into the vector store, while :func:`search_stored_jobs`
matches a profile against the persisted corpus with zero board fetches and a
single query-embedding request. :func:`run_job_search` keeps its original
shape for tests and the demo (injected sources still flow through the graph).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from src.graph.job_state import JobMatchPair
from src.graph.job_workflow import StoreFactory, build_job_workflow
from src.resume.profile import CandidateProfile

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import sessionmaker

    from src.jobs.contracts import JobListing, JobSource

logger = logging.getLogger(__name__)

DEFAULT_TOP_N = 10
MAX_TOP_N = 50


class JobSearchStats(BaseModel):
    """Pipeline counters for one search run."""

    found: int = 0  # raw listings returned by the sources (pre-normalize)
    dropped: int = 0  # listings dropped by the normalize node
    deduped: int = 0  # unique listings that reached matching
    persisted: int = 0  # rows upserted into the jobs table
    stored: int = 0  # listings loaded from the jobs table (store-only search)


class JobSearchReport(BaseModel):
    """Result of one end-to-end job search run."""

    results: list[JobMatchPair] = Field(default_factory=list)
    source_errors: dict[str, str] = Field(default_factory=dict)
    stats: JobSearchStats = Field(default_factory=JobSearchStats)
    degraded: bool = False  # semantic scoring was unavailable (WS-03 mode)


class JobRefreshStats(BaseModel):
    """Pipeline counters for one daily refresh run (FU-1)."""

    found: int = 0  # raw listings returned by the sources (pre-normalize)
    dropped: int = 0  # listings dropped by the completeness filter
    deduped: int = 0  # unique listings after dedup
    persisted: int = 0  # rows upserted into the jobs table
    embedded: int = 0  # listings upserted into the vector store


class JobRefreshReport(BaseModel):
    """Result of one daily refresh run (FU-1).

    ``quota_exhausted`` marks a partial run stopped cleanly on the daily
    embedding budget (FU-4): rows are persisted, the embedding cache keeps
    every completed batch, and the next run resumes at zero extra cost.
    """

    stats: JobRefreshStats = Field(default_factory=JobRefreshStats)
    source_errors: dict[str, str] = Field(default_factory=dict)
    embedding_requests_planned: int = 0  # cache-miss estimate before embedding
    embedding_requests_used: int = 0  # actual batch requests spent
    quota_exhausted: bool = False
    degraded_embedding: bool = False  # vector store failed; rows persisted only


def run_job_search(
    profile: CandidateProfile,
    query: str | None = None,
    location: str | None = None,
    top_n: int = DEFAULT_TOP_N,
    *,
    sources: dict[str, JobSource] | None = None,
    store_factory: StoreFactory | None = None,
    session_factory: sessionmaker | None = None,
) -> JobSearchReport:
    """Run the full search→rank pipeline for one profile.

    Args:
        profile: Parsed candidate profile driving query planning and matching.
        query: Optional explicit search query; replaces the planner-derived
            query strings for every planned source when given.
        location: Optional location filter passed through to the sources.
        top_n: Size of the ranked slice returned (clamped to 1..MAX_TOP_N).
        sources: Source-name -> adapter override (tests/demo inject fixtures).
        store_factory: Vector-store override (tests/demo inject
            FakeEmbeddingFn-backed stores); ``None`` uses the real store.
        session_factory: Sessionmaker override for the persist node.

    Returns:
        JobSearchReport with ranked (job, match) pairs, per-source errors,
        pipeline stats, and the degraded flag. Never raises for source,
        vector-store, or persistence failures.
    """
    workflow_id = uuid.uuid4().hex[:8]
    clamped_top_n = max(1, min(int(top_n), MAX_TOP_N))
    logger.info(
        "Job search started",
        extra={
            "workflow_id": workflow_id,
            "query": query,
            "location": location,
            "top_n": clamped_top_n,
            "has_explicit_query": query is not None,
        },
    )

    graph = build_job_workflow(
        sources=sources,
        store_factory=store_factory,
        session_factory=session_factory,
    )
    initial_state = {
        "profile": profile,
        "query": query,
        "location": location,
        "top_n": clamped_top_n,
    }
    # With a checkpointer attached, invoke requires a thread_id config; the
    # final state comes back as a dict of field values.
    final_state: dict = graph.invoke(
        initial_state, config={"configurable": {"thread_id": workflow_id}}
    )

    stats = JobSearchStats(
        found=len(final_state.get("raw_jobs", [])),
        dropped=final_state.get("dropped", 0),
        deduped=len(final_state.get("jobs", [])),
        persisted=final_state.get("persisted", 0),
    )
    report = JobSearchReport(
        results=final_state.get("top", []),
        source_errors=final_state.get("source_errors", {}),
        stats=stats,
        degraded=final_state.get("degraded", False),
    )
    logger.info(
        "Job search complete",
        extra={
            "workflow_id": workflow_id,
            "found": stats.found,
            "deduped": stats.deduped,
            "persisted": stats.persisted,
            "returned": len(report.results),
            "failed_sources": sorted(report.source_errors),
            "degraded": report.degraded,
        },
    )
    return report


def default_store_factory() -> StoreFactory:
    """Lazily build the production vector store factory.

    Kept as a function (not a lambda) so callers can pass it without paying
    the chromadb import until a search actually needs the store.
    """
    from src.rag.chroma_store import ChromaVectorStore

    return ChromaVectorStore


# -- FU-1: decoupled refresh / store-only search -------------------------------


def _filter_complete(listings: list[JobListing]) -> tuple[list[JobListing], int]:
    """Drop listings without the minimal completeness fields (id/title/company)."""
    kept = [job for job in listings if job.id.strip() and job.title.strip() and job.company.strip()]
    return kept, len(listings) - len(kept)


def refresh_jobs(
    *,
    sources: dict[str, JobSource] | None = None,
    store_factory: StoreFactory | None = None,
    session_factory: sessionmaker | None = None,
    embedding_fn: object | None = None,
) -> JobRefreshReport:
    """Daily refresh: fetch boards → normalize → dedup → persist → embed (FU-1).

    Runs with an empty query for every registered source (fetch everything),
    so no profile is needed and the run is idempotent: ``save_jobs`` merges by
    canonical id and the Chroma upsert is id-stable, while the content-hash
    embedding cache means only new or changed texts cost API requests. Daily
    quota exhaustion (FU-4) stops the run cleanly with ``quota_exhausted`` —
    rows stay persisted and the next run resumes from the cache.

    Args:
        sources: Source-name -> adapter override (tests inject fixtures);
            defaults to the production registry.
        store_factory: Vector-store override; ``None`` builds the real store
            around ``embedding_fn`` (or a default ``GeminiEmbedding``).
        session_factory: Sessionmaker override for persistence.
        embedding_fn: Embedding override (tests inject fakes); also used for
            the budget planning/used accounting in the report.

    Returns:
        JobRefreshReport — never raises for source, persistence, vector-store,
        or quota failures.
    """
    workflow_id = uuid.uuid4().hex[:8]
    from src.jobs.registry import SOURCES, search_all_detailed
    from src.jobs.search_planner import SourceQuery

    active_sources = sources if sources is not None else SOURCES
    queries = [SourceQuery(source=name, query="") for name in active_sources]
    logger.info(
        "Job refresh started",
        extra={"workflow_id": workflow_id, "sources": sorted(active_sources)},
    )

    listings, source_errors = asyncio.run(search_all_detailed(queries, active_sources))
    kept, dropped = _filter_complete(listings)
    from src.jobs.deduplicate import deduplicate

    unique = deduplicate(kept)

    persisted = 0
    if unique:
        from src.db.jobs import save_jobs

        try:
            persisted = save_jobs(unique, session_factory=session_factory)
        except Exception:
            logger.exception("Persisting %d listings failed; continuing unpersisted", len(unique))

    embedded, planned, used, quota_exhausted, degraded = 0, 0, 0, False, False
    if unique:
        embedding = embedding_fn
        if embedding is None:
            from src.llm.embeddings import build_embedding_fn

            embedding = build_embedding_fn()
        budget_remaining = getattr(embedding, "remaining_daily_budget", None)
        budget_before = budget_remaining() if budget_remaining else None
        store = None
        try:
            if store_factory is not None:
                store = store_factory()
            else:
                from src.rag.chroma_store import ChromaVectorStore

                store = ChromaVectorStore(embedding_fn=embedding)
            estimate = getattr(embedding, "estimate_api_requests", None)
            if estimate is not None:
                planned = estimate([store.document_text(job) for job in unique])
            embedded = store.upsert_jobs(unique)
        except Exception as exc:
            from src.llm.client import LLMDailyQuotaExhausted

            if isinstance(exc, LLMDailyQuotaExhausted):
                # FU-4 clean stop: rows persist, the chunked upsert (FU-1)
                # keeps every completed batch in the store, and the next run
                # resumes at zero extra cost from the cache.
                quota_exhausted = True
                if store is not None:
                    try:
                        embedded = store.count()  # partial progress is real progress
                    except Exception:  # noqa: BLE001 - count is best-effort only
                        embedded = 0
                logger.warning(
                    "Refresh stopped on daily embedding quota after %d embedded; "
                    "resumable tomorrow",
                    embedded,
                )
            else:
                degraded = True
                logger.exception("Vector store refresh failed; rows persisted only")
        finally:
            if budget_before is not None and budget_remaining is not None:
                used = budget_before - budget_remaining()
    stats = JobRefreshStats(
        found=len(listings),
        dropped=dropped,
        deduped=len(unique),
        persisted=persisted,
        embedded=embedded,
    )
    report = JobRefreshReport(
        stats=stats,
        source_errors=source_errors,
        embedding_requests_planned=planned,
        embedding_requests_used=used,
        quota_exhausted=quota_exhausted,
        degraded_embedding=degraded,
    )
    logger.info(
        "Job refresh complete",
        extra={
            "workflow_id": workflow_id,
            "found": stats.found,
            "deduped": stats.deduped,
            "persisted": stats.persisted,
            "embedded": stats.embedded,
            "embedding_requests_planned": planned,
            "failed_sources": sorted(source_errors),
            "quota_exhausted": quota_exhausted,
        },
    )
    return report


def search_stored_jobs(
    profile: CandidateProfile,
    query: str | None = None,
    location: str | None = None,
    top_n: int = DEFAULT_TOP_N,
    *,
    store_factory: StoreFactory | None = None,
    session_factory: sessionmaker | None = None,
) -> JobSearchReport:
    """Match a profile against the persisted corpus — zero board fetches (FU-1).

    Loads every listing from the ``jobs`` table, scores it with the hybrid
    engine (semantics from the vector store, one query-embedding request for
    the candidate text), ranks, and returns the top-N. Optional ``query`` and
    ``location`` narrow the corpus client-side (ANY query token in
    title+description; case-insensitive location substring) — deterministic,
    no sources are ever contacted. Listings not yet in the vector store
    (embedding backfill still trickling, or a store failure) score without
    the semantic component and flip the report's ``degraded`` flag.

    Returns:
        JobSearchReport — never raises for store failures (degrades instead).
    """
    workflow_id = uuid.uuid4().hex[:8]
    clamped_top_n = max(1, min(int(top_n), MAX_TOP_N))
    logger.info(
        "Stored-job search started",
        extra={"workflow_id": workflow_id, "query": query, "location": location},
    )

    from src.db.jobs import JobDB, listing_from_row

    factory = session_factory
    if factory is None:
        from src.db.session import SessionLocal

        factory = SessionLocal
    with factory() as session:
        rows = session.query(JobDB).all()
    jobs = [listing_from_row(row) for row in rows]

    if query and query.strip():
        tokens = [token for token in (t.strip().lower() for t in query.split()) if len(token) >= 2]
        if tokens:
            jobs = [
                job
                for job in jobs
                if any(token in f"{job.title} {job.description or ''}".lower() for token in tokens)
            ]
    if location and location.strip():
        needle = location.strip().lower()
        jobs = [job for job in jobs if needle in (job.location or "").lower()]

    store = None
    if jobs:
        from src.graph.job_workflow import _get_store

        store = _get_store(store_factory)
    similarities: dict[str, float] = {}
    # An empty corpus is not degraded — there is nothing missing semantics.
    degraded = bool(jobs) and store is None
    if store is not None:
        from src.rag.chroma_store import candidate_query_text

        try:
            hits = store.query_similar(candidate_query_text(profile), n=max(1, store.count()))
            similarities = dict(hits)
            degraded = any(job.id not in similarities for job in jobs)
            if degraded:
                logger.warning(
                    "Some stored listings lack vectors (backfill in flight): %d/%d have semantics",
                    len(similarities),
                    len(jobs),
                )
        except Exception:
            logger.exception("Vector store unavailable; matching in degraded mode")
            similarities = {}
            degraded = True

    from src.matching.engine import calculate_match

    matches = [
        JobMatchPair(job=job, match=calculate_match(job, profile, semantic_score=sim))
        for job, sim in ((job, similarities.get(job.id)) for job in jobs)
    ]
    ranked = sorted(matches, key=lambda pair: pair.match.overall_score, reverse=True)
    top = ranked[:clamped_top_n]

    stats = JobSearchStats(
        found=0,  # store-only: no sources contacted
        deduped=len(jobs),
        stored=len(jobs),
    )
    report = JobSearchReport(results=top, stats=stats, degraded=degraded)
    logger.info(
        "Stored-job search complete",
        extra={
            "workflow_id": workflow_id,
            "considered": len(jobs),
            "returned": len(report.results),
            "degraded": report.degraded,
        },
    )
    return report


__all__ = [
    "DEFAULT_TOP_N",
    "MAX_TOP_N",
    "JobRefreshReport",
    "JobRefreshStats",
    "JobSearchReport",
    "JobSearchStats",
    "default_store_factory",
    "refresh_jobs",
    "run_job_search",
    "search_stored_jobs",
]

# Callable re-export used by type annotations in the API layer.
ExecutorFn = Callable[..., JobSearchReport]
