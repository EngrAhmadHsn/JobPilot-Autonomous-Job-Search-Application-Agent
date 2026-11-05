"""Checkpointed, recoverable job embedding (WS-18).

The embedding pipeline is the one this workstream exists for. The design in
one paragraph: **SQL says which listing and which content version need a
vector; a work item records that obligation durably; a worker claims it,
embeds, upserts, verifies, and only then marks it complete.** A crash at any
point leaves a row that says exactly what remains, and the next worker (or an
administrator's resume) continues from there.

Two boundaries are treated honestly:

- **SQL and Chroma are not one transaction.** Chroma is a projection. The
  work is at-least-once and the effects are idempotent (stable ids, stable
  content hashes). :meth:`ChromaVectorStore.verify_listings` is what makes
  "the upsert returned" insufficient: the vector is read back and compared
  with the document hash before completion.
- **The queue owns retries for durable work.** The provider layer still
  paces itself and retries a 429 once, but the durable retry — with a
  persisted attempt count and next-attempt time — lives here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.db.jobs import JobDB, listing_from_row, merge_jobs
from src.jobs.contracts import JobListing
from src.jobs.selection import share_by_source
from src.llm.errors import (
    LLMConfigError,
    LLMDailyQuotaExhausted,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)
from src.llm.resilience import backoff_delay
from src.runs import queue
from src.runs.state import (
    ERROR_PERMANENT,
    ERROR_QUOTA,
    ERROR_RETRYABLE,
    EVENT_BATCH_COMPLETED,
    EVENT_QUOTA_EXHAUSTED,
    WORK_CANCELLED,
    WORK_COMPLETED,
    WORK_FAILED,
    WORK_RETRY_WAIT,
    utcnow,
)

logger = logging.getLogger(__name__)

__all__ = [
    "EMBED_WORK_TYPE",
    "RECONCILE_WORK_TYPE",
    "EmbeddingBatchResult",
    "EmbeddingPlan",
    "ReconcileReport",
    "persist_refresh_batch",
    "plan_outstanding",
    "process_embedding_items",
    "process_run_inline",
    "reconcile_embeddings",
    "run_reconcile",
    "superseded_reason",
]

EMBED_WORK_TYPE = "embed"
RECONCILE_WORK_TYPE = "reconcile"

#: The job types the worker can execute.
JOB_TYPE_EMBEDDING = "embedding"
JOB_TYPE_REFRESH = "refresh"
JOB_TYPE_RECONCILE = "reconcile"


@dataclass(frozen=True)
class EmbeddingPlan:
    """What one refresh must embed, and what it already had."""

    outstanding: list[tuple[JobListing, str]]
    already_embedded: int
    capped: int

    @property
    def total_outstanding(self) -> int:
        return len(self.outstanding) + self.capped


@dataclass
class EmbeddingBatchResult:
    """The outcome of one claimed batch."""

    claimed: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    retry_scheduled: int = 0
    #: WS-18 observability: how much of the batch was already cached.
    cache_hits: int = 0
    cache_misses: int = 0
    quota_exhausted: bool = False
    error: str | None = None

    def merge(self, other: EmbeddingBatchResult) -> None:
        self.claimed += other.claimed
        self.completed += other.completed
        self.failed += other.failed
        self.skipped += other.skipped
        self.retry_scheduled += other.retry_scheduled
        self.cache_hits += other.cache_hits
        self.cache_misses += other.cache_misses
        self.quota_exhausted = self.quota_exhausted or other.quota_exhausted
        if other.error:
            self.error = other.error


@dataclass(frozen=True)
class ReconcileReport:
    """What a reconciliation found and what it did about it."""

    sql_listings: int
    vectors: int
    missing: int
    orphaned: int
    deleted_orphans: int
    planned: int
    capped: int
    run_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sql_listings": self.sql_listings,
            "vectors": self.vectors,
            "missing": self.missing,
            "orphaned": self.orphaned,
            "deleted_orphans": self.deleted_orphans,
            "planned": self.planned,
            "capped": self.capped,
            "run_id": self.run_id,
        }


def superseded_reason(item_content_hash: str, current_hash: str) -> str:
    """The diagnostic for a work item whose listing changed after it was queued."""
    return (
        "The listing changed after this work was queued "
        f"(queued {item_content_hash[:12]}, current {current_hash[:12]}); "
        "the newer content version has its own work item."
    )


def _factory(session_factory: sessionmaker | None) -> sessionmaker:
    if session_factory is not None:
        return session_factory
    from src.db.session import SessionLocal

    return SessionLocal


def embedding_identity(store, embedding=None) -> tuple[str, int]:
    """The model identity a run is planned for (the store is authoritative)."""
    from src.config.settings import get_settings

    settings = get_settings()
    model = (
        getattr(store, "embedding_model", None)
        or getattr(embedding, "model", None)
        or settings.embedding_model
    )
    dimension = (
        getattr(store, "dimension", None)
        or getattr(embedding, "dimensionality", None)
        or settings.embedding_dimension
    )
    return str(model), int(dimension)


# -- planning and the outbox -------------------------------------------------


def plan_outstanding(
    listings: list[JobListing],
    *,
    store,
    budget: int,
) -> EmbeddingPlan:
    """Which admitted listings still need a vector for their current content.

    A listing is outstanding when the store has no vector for its id **or**
    the vector it has was built from a different document. That second case
    is the one a content-hash cache alone cannot see: the cache may hold the
    new text while Chroma still holds the old vector.

    The selection is shared fairly between sources, so a flood on one board
    cannot take the whole per-refresh budget.
    """
    if not listings:
        return EmbeddingPlan(outstanding=[], already_embedded=0, capped=0)

    embedded = store.embedded_hashes(job.id for job in listings)
    missing: list[JobListing] = []
    hashes: dict[str, str] = {}
    for listing in listings:
        document = store.document_text(listing)
        content_hash = store.content_hash(document)
        hashes[listing.id] = content_hash
        if embedded.get(listing.id) != content_hash:
            missing.append(listing)

    selected = share_by_source(missing, budget) if budget > 0 else []
    selected_ids = {job.id for job in selected}
    outstanding = [(job, hashes[job.id]) for job in missing if job.id in selected_ids]
    return EmbeddingPlan(
        outstanding=outstanding,
        already_embedded=len(listings) - len(missing),
        capped=max(0, len(missing) - len(selected)),
    )


def persist_refresh_batch(
    listings: list[JobListing],
    plan: EmbeddingPlan,
    *,
    store,
    owner_id: str | None,
    correlation_id: str,
    parent_run_id: str | None = None,
    session_factory: sessionmaker | None = None,
    priority: int = queue.PRIORITY_EMBEDDING,
    embedding=None,
    metadata: dict[str, Any] | None = None,
) -> tuple[int, str | None]:
    """Persist the listings **and** create their embedding work, atomically.

    This is the transactional outbox the brief asks for. If the work items
    cannot be created, the job rows are rolled back with them — the caller
    sees one outcome, not a corpus that silently lost its indexing
    obligations.
    """
    model, dimension = embedding_identity(store, embedding)
    factory = _factory(session_factory)
    with factory() as session:
        persisted = merge_jobs(session, listings, seen_at=utcnow())
        run_id: str | None = None
        if plan.outstanding:
            enqueued = queue.enqueue_run(
                session,
                job_type=JOB_TYPE_EMBEDDING,
                correlation_id=correlation_id,
                owner_id=owner_id,
                priority=priority,
                items=[
                    queue.WorkSpec(
                        job_id=job.id,
                        work_type=EMBED_WORK_TYPE,
                        content_hash=content_hash,
                    )
                    for job, content_hash in plan.outstanding
                ],
                embedding_model=model,
                embedding_dimension=dimension,
                parent_run_id=parent_run_id,
                metadata={
                    "planned": len(plan.outstanding),
                    "already_embedded": plan.already_embedded,
                    "capped": plan.capped,
                    **(metadata or {}),
                },
            )
            run_id = enqueued.run_id
        session.commit()
    return persisted, run_id


# -- execution ---------------------------------------------------------------


def _classify(exc: BaseException) -> tuple[bool, str]:
    """Whether *exc* is worth another attempt, and the stored category."""
    if isinstance(exc, LLMDailyQuotaExhausted):
        return False, ERROR_QUOTA
    if isinstance(exc, (LLMRateLimited, LLMUnavailable, LLMTimeout)):
        return True, ERROR_RETRYABLE
    if isinstance(exc, (LLMConfigError, LLMInvalidOutput)):
        return False, ERROR_PERMANENT
    if isinstance(exc, LLMError):
        return False, ERROR_PERMANENT
    # A collection built with a different embedding space is a configuration
    # change, not a transient failure: retrying writes into the same wall.
    if type(exc).__name__ == "VectorStoreMismatch":
        return False, ERROR_PERMANENT
    # Anything else is infrastructure (a Chroma write, a database error):
    # transient by default, and bounded by the attempt cap.
    return True, ERROR_RETRYABLE


def _retry_outcome(
    item: queue.ClaimedWork,
    *,
    error: str,
    kind: str,
    now,
    max_attempts: int,
    base: float,
    max_delay: float,
) -> queue.ItemOutcome:
    if not _retryable(kind) or item.attempt_count >= max_attempts:
        return queue.ItemOutcome(
            item_id=item.id,
            lease_token=item.lease_token,
            status=WORK_FAILED,
            error=error,
            error_kind=kind,
        )
    delay = backoff_delay(item.attempt_count, base, max_delay=max_delay)
    return queue.ItemOutcome(
        item_id=item.id,
        lease_token=item.lease_token,
        status=WORK_RETRY_WAIT,
        error=error,
        error_kind=kind,
        next_attempt_at=now + timedelta(seconds=delay),
    )


def _retryable(kind: str) -> bool:
    return kind == ERROR_RETRYABLE


def _requeue_and_pause(
    *,
    run_id: str,
    items: list[queue.ClaimedWork],
    reason: str,
    session_factory: sessionmaker | None,
    worker_id: str,
    now,
) -> None:
    """A quota stop: release the batch, keep it queued, pause the run."""
    factory = _factory(session_factory)
    with factory() as session:
        for item in items:
            queue.requeue_item(
                session,
                item.id,
                lease_token=item.lease_token,
                next_attempt_at=None,
                error=reason,
            )
        queue.pause_run(session, run_id, reason=reason, error_kind=ERROR_QUOTA)
        queue.record_event(
            session,
            run_id,
            EVENT_QUOTA_EXHAUSTED,
            actor="agent",
            actor_kind="agent",
            actor_id=worker_id,
            message=reason,
            metadata={"released_items": len(items)},
        )
        session.commit()


def process_embedding_items(
    items: list[queue.ClaimedWork],
    *,
    run_id: str,
    worker_id: str,
    store,
    session_factory: sessionmaker | None = None,
    now=None,
    max_attempts: int | None = None,
) -> EmbeddingBatchResult:
    """Embed, upsert, verify and settle one claimed batch.

    The order is the brief's order: claim → commit the lease → load the job
    row → generate/retrieve the vector → upsert → **verify** → mark complete
    → record the event. No database transaction is held open across the
    embedding call: the claim is already committed by
    :func:`src.runs.queue.claim_work_items`.
    """
    from src.config.settings import get_settings

    moment = now or utcnow()
    settings = get_settings()
    attempt_cap = max_attempts if max_attempts is not None else settings.worker_max_attempts
    result = EmbeddingBatchResult(claimed=len(items))
    if not items:
        return result

    factory = _factory(session_factory)
    with factory() as session:
        rows = {
            row.id: row
            for row in session.execute(
                select(JobDB).where(JobDB.id.in_([item.job_id for item in items]))
            ).scalars()
        }

    outcomes: list[queue.ItemOutcome] = []
    listings: list[JobListing] = []
    texts: list[str] = []
    hashes: dict[str, str] = {}
    by_id: dict[str, queue.ClaimedWork] = {}
    superseded: list[queue.ClaimedWork] = []

    for item in items:
        by_id[item.id] = item
        row = rows.get(item.job_id)
        if row is None:
            outcomes.append(
                queue.ItemOutcome(
                    item_id=item.id,
                    lease_token=item.lease_token,
                    status=WORK_FAILED,
                    error=f"Listing {item.job_id!r} no longer exists in the corpus.",
                    error_kind=ERROR_PERMANENT,
                )
            )
            result.failed += 1
            continue
        listing = listing_from_row(row)
        document = store.document_text(listing)
        current_hash = store.content_hash(document)
        if current_hash != item.content_hash:
            superseded.append(item)
            outcomes.append(
                queue.ItemOutcome(
                    item_id=item.id,
                    lease_token=item.lease_token,
                    status=WORK_CANCELLED,
                    error=superseded_reason(item.content_hash, current_hash),
                    error_kind=ERROR_PERMANENT,
                )
            )
            result.skipped += 1
            continue
        listings.append(listing)
        texts.append(document)
        hashes[listing.id] = current_hash

    if listings:
        flags = store.cached_flags(texts)
        result.cache_hits = sum(1 for flag in flags if flag)
        result.cache_misses = len(flags) - result.cache_hits
        try:
            store.upsert_jobs(listings)
            verified = store.verify_listings(listings, hashes)
        except LLMDailyQuotaExhausted as exc:
            _requeue_and_pause(
                run_id=run_id,
                items=items,
                reason=str(exc) or "Daily embedding budget spent",
                session_factory=session_factory,
                worker_id=worker_id,
                now=moment,
            )
            result.quota_exhausted = True
            result.error = str(exc)
            return result
        except Exception as exc:  # noqa: BLE001 - classified below
            retryable, kind = _classify(exc)
            message = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Embedding batch for run %s failed (%s); %d item(s) to %s",
                run_id,
                message,
                len(listings),
                "retry" if retryable else "fail",
            )
            for listing in listings:
                item = by_id_by_job(items, listing.id)
                if item is None:  # pragma: no cover - defensive
                    continue
                outcome = _retry_outcome(
                    item,
                    error=message,
                    kind=kind,
                    now=moment,
                    max_attempts=attempt_cap,
                    base=settings.worker_retry_base_seconds,
                    max_delay=settings.worker_retry_max_seconds,
                )
                outcomes.append(outcome)
                if outcome.status == WORK_RETRY_WAIT:
                    result.retry_scheduled += 1
                else:
                    result.failed += 1
            result.error = message
            _settle(run_id, outcomes, worker_id, session_factory, moment, result)
            return result

        for listing in listings:
            item = by_id_by_job(items, listing.id)
            if item is None:  # pragma: no cover - defensive
                continue
            if listing.id in verified:
                outcomes.append(
                    queue.ItemOutcome(
                        item_id=item.id,
                        lease_token=item.lease_token,
                        status=WORK_COMPLETED,
                    )
                )
                result.completed += 1
            else:
                outcome = _retry_outcome(
                    item,
                    error="The vector could not be verified after the upsert.",
                    kind=ERROR_RETRYABLE,
                    now=moment,
                    max_attempts=attempt_cap,
                    base=settings.worker_retry_base_seconds,
                    max_delay=settings.worker_retry_max_seconds,
                )
                outcomes.append(outcome)
                if outcome.status == WORK_RETRY_WAIT:
                    result.retry_scheduled += 1
                else:
                    result.failed += 1

    if superseded:
        logger.info(
            "Run %s: %d work item(s) skipped because the listing content changed",
            run_id,
            len(superseded),
        )

    _settle(run_id, outcomes, worker_id, session_factory, moment, result)
    return result


def by_id_by_job(items: list[queue.ClaimedWork], job_id: str) -> queue.ClaimedWork | None:
    """The claimed item for *job_id* (a batch is one item per job)."""
    for item in items:
        if item.job_id == job_id:
            return item
    return None


def _settle(
    run_id: str,
    outcomes: list[queue.ItemOutcome],
    worker_id: str,
    session_factory: sessionmaker | None,
    moment,
    result: EmbeddingBatchResult,
) -> None:
    if not outcomes:
        queue.settle_work_items(
            run_id=run_id,
            outcomes=[],
            worker_id=worker_id,
            session_factory=session_factory,
            now=moment,
        )
        return
    queue.settle_work_items(
        run_id=run_id,
        outcomes=outcomes,
        worker_id=worker_id,
        session_factory=session_factory,
        event=EVENT_BATCH_COMPLETED,
        message=(
            f"Batch settled: {result.completed} completed, "
            f"{result.retry_scheduled} retrying, {result.failed} failed, "
            f"{result.skipped} skipped"
        ),
        metadata={
            "completed": result.completed,
            "retry_scheduled": result.retry_scheduled,
            "failed": result.failed,
            "skipped": result.skipped,
            "cache_hits": result.cache_hits,
            "cache_misses": result.cache_misses,
        },
        now=moment,
    )


def process_run_inline(
    run_id: str,
    *,
    worker_id: str,
    store,
    session_factory: sessionmaker | None = None,
    limit: int | None = None,
    lease_seconds: float | None = None,
    now=None,
) -> EmbeddingBatchResult:
    """Drain one run in the current process (the offline/CLI path).

    The same claim/verify/settle machinery the worker uses, scoped to one
    run so an operator's CLI invocation cannot take another run's work.
    """
    from src.config.settings import get_settings

    settings = get_settings()
    aggregate = EmbeddingBatchResult()
    batch_limit = limit or settings.worker_batch_size
    while True:
        items = queue.claim_work_items(
            worker_id=worker_id,
            limit=batch_limit,
            lease_seconds=lease_seconds or settings.worker_lease_seconds,
            session_factory=session_factory,
            run_ids=[run_id],
            now=now,
        )
        if not items:
            break
        batch = process_embedding_items(
            items,
            run_id=run_id,
            worker_id=worker_id,
            store=store,
            session_factory=session_factory,
            now=now,
        )
        aggregate.merge(batch)
        if batch.quota_exhausted:
            break
        if not batch.completed and not batch.retry_scheduled and not batch.skipped:
            # Nothing moved: stop rather than spin on a failing batch.
            break
    return aggregate


# -- reconciliation ----------------------------------------------------------


def reconcile_embeddings(
    *,
    store,
    correlation_id: str,
    owner_id: str | None = None,
    session_factory: sessionmaker | None = None,
    budget: int | None = None,
    delete_orphans: bool = True,
    reconcile_run_id: str | None = None,
) -> ReconcileReport:
    """Find and repair every SQL/Chroma divergence the brief enumerates.

    Detects:

    - SQL listings with no vector, or with a vector built from older content;
    - Chroma vectors whose source row no longer exists;
    - work items marked complete whose vector is missing (those listings are
      exactly the "no vector" set, so they are re-planned);
    - interrupted work items (the caller runs the lease reaper first).

    Repairs are **compensating**, not distributed: missing vectors become new
    work in a fresh embedding run; orphan vectors are deleted (a vector
    without a row can never be shown or applied to).
    """
    from src.security.limits import get_limits

    limits = get_limits()
    factory = _factory(session_factory)
    with factory() as session:
        rows = session.execute(select(JobDB).limit(limits.max_corpus_listings)).scalars().all()
        listings = [listing_from_row(row) for row in rows]
        sql_ids = {job.id for job in listings}
        vectors = store.stored_ids()
        stored = store.embedded_hashes(job.id for job in listings)

        missing: list[JobListing] = []
        for job in listings:
            document = store.document_text(job)
            if stored.get(job.id) != store.content_hash(document):
                missing.append(job)

        orphans = sorted(vectors - sql_ids)
        deleted = 0
        if orphans and delete_orphans:
            try:
                deleted = store.delete_jobs(orphans)
            except Exception:
                logger.exception("Deleting %d orphan vector(s) failed", len(orphans))

        selected = share_by_source(
            missing, budget if budget is not None else limits.max_embed_per_refresh
        )
        run_id: str | None = None
        if selected:
            model, dimension = embedding_identity(store)
            hashes = {job.id: store.content_hash(store.document_text(job)) for job in selected}
            enqueued = queue.enqueue_run(
                session,
                job_type=JOB_TYPE_EMBEDDING,
                correlation_id=correlation_id,
                owner_id=owner_id,
                priority=queue.PRIORITY_EMBEDDING,
                items=[
                    queue.WorkSpec(
                        job_id=job.id,
                        work_type=EMBED_WORK_TYPE,
                        content_hash=hashes[job.id],
                    )
                    for job in selected
                ],
                embedding_model=model,
                embedding_dimension=dimension,
                parent_run_id=reconcile_run_id,
                metadata={
                    "source": "reconciliation",
                    "missing": len(missing),
                    "capped": len(missing) - len(selected),
                },
            )
            run_id = enqueued.run_id
        session.commit()

    report = ReconcileReport(
        sql_listings=len(listings),
        vectors=len(vectors),
        missing=len(missing),
        orphaned=len(orphans),
        deleted_orphans=deleted,
        planned=len(selected),
        capped=max(0, len(missing) - len(selected)),
        run_id=run_id,
    )
    logger.info(
        "Reconciliation: %d listings, %d vectors, %d missing, %d orphaned (%d deleted), %d planned",
        report.sql_listings,
        report.vectors,
        report.missing,
        report.orphaned,
        report.deleted_orphans,
        report.planned,
    )
    return report


def run_reconcile(
    *,
    correlation_id: str,
    owner_id: str | None = None,
    session_factory: sessionmaker | None = None,
    store=None,
    reconcile_run_id: str | None = None,
) -> ReconcileReport:
    """Reconcile with the production store when the caller has none.

    The store is built lazily so an offline reconciliation test can inject a
    fake without importing Chroma, and the worker builds the real one only
    when a reconcile run is actually claimed.
    """
    if store is None:
        from src.llm.embeddings import build_embedding_fn
        from src.rag.chroma_store import ChromaVectorStore

        store = ChromaVectorStore(embedding_fn=build_embedding_fn())
    return reconcile_embeddings(
        store=store,
        correlation_id=correlation_id,
        owner_id=owner_id,
        session_factory=session_factory,
        reconcile_run_id=reconcile_run_id,
    )
