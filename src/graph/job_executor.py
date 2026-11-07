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
from dataclasses import dataclass
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
    #: WS-20: how many of the considered listings had a usable semantic vector.
    semantic_covered: int = 0


class JobSearchReport(BaseModel):
    """Result of one end-to-end job search run."""

    results: list[JobMatchPair] = Field(default_factory=list)
    source_errors: dict[str, str] = Field(default_factory=dict)
    stats: JobSearchStats = Field(default_factory=JobSearchStats)
    degraded: bool = False  # some listings scored without the semantic component (WS-03/WS-20)
    #: WS-20: percentage of considered listings that had a real semantic vector.
    semantic_coverage: float = 100.0


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
    #: WS-18: the durable embedding run this refresh created, when it had
    #: work to queue. The same id appears in ``GET /api/runs`` and in the
    #: administration screen, so a report can be followed to its recovery.
    run_id: str | None = None


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

    WS-18: the implementation moved to :mod:`src.jobs.selection` so the
    durable embedding planner shares it. This name is kept because the
    WS-15 tests exercise the rule through it.
    """
    from src.jobs.selection import share_by_source

    return share_by_source(listings, limit)


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


@dataclass
class RefreshStageResult:
    """What the fetch/persist stage produced (WS-18).

    The stage is split from the embedding execution so the worker's refresh
    handler and the synchronous CLI can share one implementation: the fetch
    and the outbox are the same; only who drains the resulting work differs.
    """

    stats: JobRefreshStats
    source_errors: dict[str, str]
    plan: object  # src.runs.embedding.EmbeddingPlan (lazy import)
    run_id: str | None
    store: object | None
    embedding: object | None
    degraded: bool
    correlation_id: str


def _plan_without_store(listings: list[JobListing], *, budget: int):
    """Plan every admitted listing when the vector store is unavailable.

    The alternative — persisting rows and hoping a later refresh notices —
    is the disconnected state the transactional outbox exists to prevent.
    The document hash is computed without a store connection, so the work
    items are created now and the vectors follow when Chroma recovers.
    """
    from src.jobs.selection import share_by_source
    from src.rag.chroma_store import ChromaVectorStore
    from src.runs.embedding import EmbeddingPlan

    hashes = {
        job.id: ChromaVectorStore.content_hash(ChromaVectorStore.document_text(job))
        for job in listings
    }
    selected = share_by_source(listings, budget) if budget > 0 else []
    selected_ids = {job.id for job in selected}
    return EmbeddingPlan(
        outstanding=[(job, hashes[job.id]) for job in listings if job.id in selected_ids],
        already_embedded=0,
        capped=max(0, len(listings) - len(selected)),
    )


def fetch_and_persist(
    *,
    sources: dict[str, JobSource] | None = None,
    store_factory: StoreFactory | None = None,
    session_factory: sessionmaker | None = None,
    embedding_fn: object | None = None,
    owner_id: str | None = None,
    parent_run_id: str | None = None,
    raise_on_persist_error: bool = False,
) -> RefreshStageResult:
    """Fetch the boards, admit the listings, persist them **and** their work.

    WS-18: this is stage one of the refresh. The job rows and the embedding
    work items are written in one transaction (:func:`persist_refresh_batch`),
    so a crash cannot leave a listing that needs a vector with no record of
    that obligation. The returned run id is the durable handle the worker (or
    the synchronous caller) drains.
    """
    from src.runs.embedding import persist_refresh_batch, plan_outstanding

    workflow_id = uuid.uuid4().hex
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

    embedding = embedding_fn
    if embedding is None:
        from src.llm.embeddings import build_embedding_fn

        embedding = build_embedding_fn()

    store = None
    degraded = False
    if unique:
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
        except Exception:
            # WS-18 bulkhead: a vector-store outage degrades indexing, not
            # the corpus. The rows are persisted and the work is queued for
            # the worker to retry when the store returns.
            degraded = True
            store = None
            logger.exception("Vector store unavailable; the refresh persists and queues indexing")

    if unique and store is not None:
        plan = plan_outstanding(unique, store=store, budget=limits.max_embed_per_refresh)
    elif unique:
        plan = _plan_without_store(unique, budget=limits.max_embed_per_refresh)
    else:
        from src.runs.embedding import EmbeddingPlan

        plan = EmbeddingPlan(outstanding=[], already_embedded=0, capped=0)

    if plan.capped:
        logger.warning(
            "Embedding budget capped at %d listings for this refresh; "
            "%d listings stay persisted and are embedded by a later run",
            limits.max_embed_per_refresh,
            plan.capped,
        )

    persisted = 0
    run_id: str | None = None
    if unique:
        try:
            persisted, run_id = persist_refresh_batch(
                unique,
                plan,
                store=store,
                embedding=embedding,
                owner_id=owner_id,
                parent_run_id=parent_run_id,
                correlation_id=workflow_id,
                session_factory=session_factory,
                metadata={"failed_sources": sorted(source_errors)},
            )
        except Exception:
            logger.exception(
                "Persisting %d listings and their embedding work failed; "
                "the refresh will retry as a whole",
                len(unique),
            )
            if raise_on_persist_error:
                raise

    stats = JobRefreshStats(
        found=len(listings),
        dropped=dropped,
        deduped=len(unique),
        persisted=persisted,
        embedded=0,
        screened_out=len(spam_verdict.dropped),
        admission_capped=admission.total_dropped,
    )
    return RefreshStageResult(
        stats=stats,
        source_errors=source_errors,
        plan=plan,
        run_id=run_id,
        store=store,
        embedding=embedding,
        degraded=degraded,
        correlation_id=workflow_id,
    )


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
    canonical id, the Chroma upsert is id-stable, and the content hash makes
    an unchanged listing free. Daily quota exhaustion (FU-4) stops the run
    cleanly with ``quota_exhausted`` — rows stay persisted, the work items
    stay queued, and an administrator (or the next run) resumes.

    WS-18: this synchronous entry point uses the **same** outbox and handler
    as the worker. It is the CLI/test path; the API enqueues a durable run
    instead of calling this function inside a request.

    Args:
        sources: Source-name -> adapter override (tests inject fixtures);
            defaults to the production registry.
        store_factory: Vector-store override; ``None`` builds the real store
            around ``embedding_fn``.
        session_factory: Sessionmaker override for persistence.
        embedding_fn: Embedding override (tests inject fakes); also used for
            the budget planning/used accounting in the report.

    Returns:
        JobRefreshReport — never raises for source, vector-store, or quota
        failures. A persistence failure is reported as a zero persisted count
        (and the work is retried by the caller).
    """
    from src.runs.embedding import EmbeddingBatchResult, process_run_inline

    stage = fetch_and_persist(
        sources=sources,
        store_factory=store_factory,
        session_factory=session_factory,
        embedding_fn=embedding_fn,
    )
    embedding = stage.embedding
    budget_remaining = getattr(embedding, "remaining_daily_budget", None)
    budget_before = budget_remaining() if budget_remaining else None

    planned = 0
    estimate = getattr(embedding, "estimate_api_requests", None)
    if estimate is not None and stage.store is not None and stage.plan.outstanding:
        try:
            planned = estimate(
                [stage.store.document_text(job) for job, _hash in stage.plan.outstanding]
            )
        except Exception:  # noqa: BLE001 - planning is best-effort
            planned = 0

    batch = EmbeddingBatchResult()
    degraded = stage.degraded
    if stage.run_id and stage.store is not None:
        try:
            batch = process_run_inline(
                stage.run_id,
                worker_id=f"inline-{uuid.uuid4().hex[:8]}",
                store=stage.store,
                session_factory=session_factory,
            )
        except Exception:
            degraded = True
            logger.exception(
                "Inline embedding run %s failed; its outstanding work stays durable",
                stage.run_id,
            )
    elif stage.run_id is not None:
        # The store was unavailable: the work is queued, not lost.
        degraded = True

    if batch.error and not batch.completed and not batch.quota_exhausted:
        degraded = True

    used = 0
    if budget_before is not None and budget_remaining is not None:
        used = budget_before - budget_remaining()

    stats = stage.stats.model_copy(update={"embedded": batch.completed})
    report = JobRefreshReport(
        stats=stats,
        source_errors=stage.source_errors,
        embedding_requests_planned=planned,
        embedding_documents_planned=len(stage.plan.outstanding),
        embedding_requests_used=used,
        quota_exhausted=batch.quota_exhausted,
        degraded_embedding=degraded,
        run_id=stage.run_id,
    )
    logger.info(
        "Job refresh complete",
        extra={
            "workflow_id": stage.correlation_id,
            "run_id": stage.run_id,
            "found": stats.found,
            "deduped": stats.deduped,
            "persisted": stats.persisted,
            "embedded": stats.embedded,
            "embedding_requests_planned": planned,
            "failed_sources": sorted(stage.source_errors),
            "quota_exhausted": batch.quota_exhausted,
        },
    )
    return report


def search_stored_jobs(
    profile: CandidateProfile,
    query: str | None = None,
    location: str | None = None,
    top_n: int = DEFAULT_TOP_N,
    *,
    only_embedded: bool = False,
    store_factory: StoreFactory | None = None,
    session_factory: sessionmaker | None = None,
) -> JobSearchReport:
    """Match a profile against the persisted corpus — zero board fetches (FU-1).

    Loads every listing from the ``jobs`` table, scores it with the hybrid
    engine (semantics from the vector store, one query-embedding request for
    the candidate text; a BM25 lexical channel over the full posting), ranks,
    and returns the top-N. Optional ``query`` and ``location`` narrow the
    corpus client-side (ANY query token in title+description; case-insensitive
    location substring) — deterministic, no sources are ever contacted.

    WS-20: a listing with no vector is **not** advantaged. The WS-18 queue is
    consulted for its embedding state (``EMBEDDING_PENDING`` vs
    ``EMBEDDING_UNAVAILABLE``), it earns zero semantic credit, and the fixed
    denominator means nothing is redistributed onto it. ``only_embedded``
    filters such listings out entirely; it is off by default so a pending
    listing stays visible as a lexical/structured match. Ranking is a stable
    ``(score desc, job id)`` sort.

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
    store_unavailable = bool(jobs) and store is None
    if store is not None:
        from src.rag.chroma_store import candidate_query_text

        try:
            # Exact similarities for every stored listing (FU-7): Chroma's
            # query() drops one row when n_results == count, which used to
            # report a phantom gap and flip `degraded`.
            similarities = store.similarities_for_all(candidate_query_text(profile))
        except Exception:
            logger.exception("Vector store unavailable; matching with lexical + structured signals")
            similarities = {}
            store_unavailable = True

    # WS-20: ask the WS-18 queue what the embedding state of each vector-less
    # listing actually is, instead of collapsing "queued", "failed" and "the
    # store is down" into one boolean.
    from src.matching.embedding_status import embedding_status_for_jobs, is_pending_status
    from src.matching.lexical import (
        Bm25Index,
        candidate_lexical_text,
        candidate_tokens,
        lexical_score,
    )
    from src.matching.scores import ScoreState

    missing_ids = [job.id for job in jobs if job.id not in similarities]
    statuses = (
        embedding_status_for_jobs(missing_ids, session_factory=factory) if missing_ids else {}
    )

    # WS-20: an explicit, opt-in filter for fully-indexed results. Off by
    # default: a pending listing stays visible (it may still be a good lexical
    # match) but earns no semantic credit.
    if only_embedded:
        jobs = [job for job in jobs if job.id in similarities]

    index = Bm25Index(jobs)
    candidate_token_list = candidate_tokens(profile)
    candidate_text = candidate_lexical_text(profile)

    from src.matching.engine import calculate_match

    matches: list[JobMatchPair] = []
    semantic_covered = 0
    for job in jobs:
        if job.id in similarities:
            semantic_score: float | None = similarities[job.id]
            semantic_state: ScoreState | None = None
            semantic_covered += 1
        else:
            semantic_score = None
            if store_unavailable:
                semantic_state = ScoreState.EMBEDDING_UNAVAILABLE
            else:
                status = statuses.get(job.id)
                if status is None or is_pending_status(status):
                    semantic_state = ScoreState.EMBEDDING_PENDING
                else:
                    # An item exists but is not pending (e.g. COMPLETED) yet the
                    # store has no vector: treat as an outage, not a pending job.
                    semantic_state = ScoreState.EMBEDDING_UNAVAILABLE
        lexical_result = lexical_score(
            job,
            index=index,
            candidate_token_list=candidate_token_list,
            candidate_text=candidate_text,
        )
        match = calculate_match(
            job,
            profile,
            semantic_score=semantic_score,
            semantic_state=semantic_state,
            lexical=lexical_result,
        )
        matches.append(JobMatchPair(job=job, match=match))

    # Deterministic tie-break on the job id so a repeated search is stable.
    ranked = sorted(matches, key=lambda pair: (-pair.match.overall_score, pair.job.id))
    top = ranked[:clamped_top_n]

    degraded = bool(jobs) and semantic_covered < len(jobs)
    if degraded:
        logger.warning(
            "Semantic coverage %d/%d (pending or failed embeddings): those listings "
            "score without the semantic component",
            semantic_covered,
            len(jobs),
        )
    semantic_coverage = (semantic_covered / len(jobs) * 100.0) if jobs else 100.0

    stats = JobSearchStats(
        found=0,  # store-only: no sources contacted
        deduped=len(jobs),
        stored=len(jobs),
        semantic_covered=semantic_covered,
    )
    report = JobSearchReport(
        results=top, stats=stats, degraded=degraded, semantic_coverage=semantic_coverage
    )
    logger.info(
        "Stored-job search complete",
        extra={
            "workflow_id": workflow_id,
            "considered": len(jobs),
            "returned": len(report.results),
            "degraded": report.degraded,
            "semantic_coverage": round(semantic_coverage, 1),
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
