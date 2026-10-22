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
    from src.security.limits import SecurityLimits

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
    # WS-12: what the abuse controls dropped. A limit that discards data
    # silently is indistinguishable from a bug, so every drop is counted.
    screened_out: int = 0  # dropped by the fake-job / spam screen
    admission_capped: int = 0  # dropped by the corpus admission limits


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
    # WS-15: the documents that had to be **embedded** — the cache misses.
    # On the local provider this is the whole cost of the refresh, and it
    # is the number the daily work budget is denominated in, so it is the
    # number an operator needs to see to understand what a refresh cost.
    embedding_documents_planned: int = 0
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


def _corpus_size(session_factory: sessionmaker | None = None) -> int | None:
    """How many listings the corpus already holds (``None`` when unknown).

    Used by the admission control to keep the corpus inside its cap. A
    failure to count is not fatal: the caller reports ``None`` and the
    corpus limit is simply not applied for this run.
    """
    try:
        from src.db.jobs import JobDB
        from src.db.session import SessionLocal

        factory = session_factory or SessionLocal
        with factory() as session:
            return int(session.query(JobDB).count())
    except Exception:
        logger.exception("Counting the corpus failed; the corpus cap is not applied")
        return None


def _share_by_source(listings: list[JobListing], limit: int) -> list[JobListing]:
    """Take up to *limit* listings, round-robin across their sources.

    WS-15: a board is untrusted input, so **one** board must not be able to
    spend the whole embedding budget. The listings arrive in board order, and
    a hostile board controls its own order, so taking "the first N" is
    taking "whatever the attacker put first". Taking them round-robin
    instead gives every source an equal share of the budget until its own
    listings run out, so a flood on one board is bounded at roughly
    ``1 / number_of_sources`` of the work.
    """
    if limit <= 0 or not listings:
        return []
    buckets: dict[str, list[JobListing]] = {}
    order: list[str] = []
    for listing in listings:
        source = listing.source or "unknown"
        if source not in buckets:
            buckets[source] = []
            order.append(source)
        buckets[source].append(listing)

    chosen: list[JobListing] = []
    depth = 0
    while len(chosen) < limit:
        added = False
        for source in order:
            bucket = buckets[source]
            if depth < len(bucket):
                chosen.append(bucket[depth])
                added = True
                if len(chosen) >= limit:
                    break
        if not added:
            break
        depth += 1
    return chosen


def _select_for_embedding(
    listings: list[JobListing],
    embedding: object,
    store: object,
    *,
    budget: int,
) -> tuple[list[JobListing], int, bool]:
    """Choose the listings this refresh will embed, and how much work that is.

    WS-15: the budget is denominated in **cache misses** — the embeddings
    that actually cost something. The first implementation took the first N
    listings in board order, which meant:

    - a listing that was already embedded still consumed budget, even
      though re-embedding it costs a cache lookup and nothing else; and
    - a flood that occupied the front of a board's response took the whole
      budget, permanently, because a board's order is stable.

    So the misses are selected first (and shared fairly between the
    sources), the already-cached listings follow to refresh their
    metadata, and the daily work budget caps the misses across a whole
    day — the ceiling a flood that spreads itself over many refreshes
    runs into.

    Args:
        listings: The admitted listings, in board order.
        embedding: The embedding provider (asked what it already has).
        store: The vector store (asked for the document text).
        budget: The per-refresh cap on the embeddings that cost something.

    Returns:
        The listings to embed, the number of embeddings planned, and
        whether the daily work budget is the reason the list is short.
    """
    if not listings:
        return [], 0, False

    texts = [store.document_text(job) for job in listings]
    is_cached = getattr(embedding, "is_cached", None)
    if is_cached is None:
        flags = [False] * len(listings)
    else:
        flags = [bool(flag) for flag in is_cached(texts)]

    misses = [job for job, cached in zip(listings, flags) if not cached]
    hits = [job for job, cached in zip(listings, flags) if cached]

    # The daily work budget: the ceiling across a whole day, which the
    # per-refresh budget alone does not provide.
    remaining = getattr(embedding, "remaining_work_budget", None)
    remaining = remaining() if remaining is not None else None
    work_exhausted = False
    if remaining is not None and remaining < len(misses):
        misses = misses[: max(0, remaining)]
        work_exhausted = True

    # The per-refresh budget, shared fairly between the sources.
    misses = _share_by_source(misses, budget)
    # The cached listings cost a lookup, not an embedding, so they ride
    # along to refresh the store's metadata — bounded by the same budget.
    to_embed = misses + _share_by_source(hits, budget)
    return to_embed, len(misses), work_exhausted


def _evict_stale_listings(
    session_factory: sessionmaker | None,
    limits: SecurityLimits,
) -> list[str]:
    """Make room in a full corpus by dropping the stalest listings.

    WS-15: the corpus cap is a bound, and a bound that can only be reached
    once and never left is an outage. The eviction is bounded too — one
    refresh may not turn into a mass delete — and it takes the listings
    that have not been seen on a board for the longest, so the listings
    the boards keep serving stay.

    Returns:
        The ids of the evicted listings (so their vectors can go too).
    """
    from src.db.jobs import prune_stale_jobs

    keep = max(0, limits.max_corpus_listings - limits.max_corpus_evictions_per_refresh)
    try:
        removed = prune_stale_jobs(
            session_factory,
            keep=keep,
            limit=limits.max_corpus_evictions_per_refresh,
        )
    except Exception:
        logger.exception("Evicting the stale listings failed; the corpus cap still applies")
        return []
    if removed:
        logger.warning(
            "The corpus was at its cap; evicted %d listings that had not been seen for the longest",
            len(removed),
        )
    return removed


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

    # WS-12: screen the batch before anything is persisted or embedded. A
    # board is untrusted input: a flood of machine-generated listings must
    # not reach the corpus, the vector store, or the embedding budget.
    from src.jobs.spam import screen_listings

    screened, spam_verdict = screen_listings(unique)
    if spam_verdict.dropped:
        logger.warning(
            "Spam screening dropped %d of %d listings: %s",
            len(spam_verdict.dropped),
            len(unique),
            "; ".join(reason for _id, reason in spam_verdict.dropped[:5]),
        )
    unique = screened

    # WS-12: admission control — no single board and no single refresh may
    # grow the corpus without bound, and the corpus itself is capped so the
    # full-corpus read in the search stays affordable.
    from src.security.admission import admit_listings
    from src.security.limits import get_limits

    limits = get_limits()

    # WS-15: the corpus **evicts** before it admits. The cap used to be a
    # one-way door: once the corpus was full, `room` was zero and nothing
    # was admitted again — from any source, ever. A flood could end the
    # application's life with five refreshes and no way back. The corpus
    # now makes room by dropping the listings that have not been seen on a
    # board for the longest, so the bound still protects the read path and
    # the corpus still moves.
    corpus_size = _corpus_size(session_factory)
    evicted_ids: list[str] = []
    if corpus_size is not None and corpus_size >= limits.max_corpus_listings:
        evicted_ids = _evict_stale_listings(session_factory, limits)
        corpus_size = _corpus_size(session_factory)

    admission = admit_listings(unique, corpus_size=corpus_size)
    unique = admission.admitted
    if admission.total_dropped:
        logger.warning(
            "Admission control dropped %d listings (per-source %d, per-refresh %d, corpus %d)",
            admission.total_dropped,
            admission.per_source_capped,
            admission.per_refresh_capped,
            admission.corpus_capped,
        )

    persisted = 0
    if unique:
        from src.db.jobs import save_jobs

        try:
            persisted = save_jobs(unique, session_factory=session_factory)
        except Exception:
            logger.exception("Persisting %d listings failed; continuing unpersisted", len(unique))

    embedded, planned, used, quota_exhausted, degraded = 0, 0, 0, False, False
    documents_planned = 0
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
            # The evicted listings lose their vectors too, so the store
            # does not keep scoring rows the corpus no longer has.
            if evicted_ids:
                try:
                    store.delete_jobs(evicted_ids)
                except Exception:
                    logger.exception(
                        "Deleting the vectors of %d evicted listings failed; "
                        "the search ignores them (they have no row)",
                        len(evicted_ids),
                    )
            # WS-12: the embedding work per refresh is bounded. A flood of
            # unique listings would otherwise spend the provider's whole
            # daily quota — and fill the embedding cache — on texts nobody
            # will ever search for, starving the legitimate ones.
            embed_budget = limits.max_embed_per_refresh
            to_embed, misses_planned, work_exhausted = _select_for_embedding(
                unique, embedding, store, budget=embed_budget
            )
            documents_planned = misses_planned
            if work_exhausted:
                quota_exhausted = True
                logger.warning(
                    "The daily embedding work budget is spent; %d listings stay "
                    "persisted and are embedded after the daily reset",
                    len(unique) - len(to_embed),
                )
            if len(to_embed) < len(unique):
                logger.warning(
                    "Embedding budget capped at %d listings for this refresh; "
                    "%d listings stay persisted and are embedded by a later run",
                    embed_budget,
                    len(unique) - len(to_embed),
                )
            estimate = getattr(embedding, "estimate_api_requests", None)
            if estimate is not None:
                planned = estimate([store.document_text(job) for job in to_embed])
            embedded = store.upsert_jobs(to_embed)
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
        screened_out=len(spam_verdict.dropped),
        admission_capped=admission.total_dropped,
    )
    report = JobRefreshReport(
        stats=stats,
        source_errors=source_errors,
        embedding_requests_planned=planned,
        embedding_documents_planned=documents_planned,
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
    # WS-12: the corpus read is bounded. Every search loads the corpus, so
    # an unbounded corpus is an unbounded search — the corpus cap in the
    # admission control is the primary defence, and this limit is the
    # backstop for a corpus that grew before the cap was in place.
    from src.security.limits import get_limits

    corpus_limit = get_limits().max_corpus_listings
    with factory() as session:
        rows = session.query(JobDB).limit(corpus_limit).all()
    if len(rows) >= corpus_limit:
        logger.warning(
            "Search considered %d listings (the corpus cap); results may be partial",
            len(rows),
        )
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
            # Exact similarities for every stored listing (FU-7): Chroma's
            # query() drops one row when n_results == count, which used to
            # report a phantom gap and flip `degraded`.
            similarities = store.similarities_for_all(candidate_query_text(profile))
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
