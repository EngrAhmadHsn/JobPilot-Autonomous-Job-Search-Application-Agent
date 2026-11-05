"""The database-backed work queue (WS-18).

The queue is a table, not a broker. Every operation here is one database
transaction, and the two engines get an honest implementation of the same
contract:

- **PostgreSQL** claims with ``SELECT ... FOR UPDATE SKIP LOCKED`` — the
  canonical queue idiom — then writes the lease in the same transaction.
- **SQLite** has no row locks, so the claim is a **conditional update**: the
  row is claimed only if it is still ``QUEUED``/``RETRY_WAIT`` at the moment
  the write lands, and ``rowcount == 1`` is the lock. Two workers may select
  the same candidate; only one update wins.

Nothing here pretends a process-local lock coordinates workers. The lease
token is the fence: a completion or failure is conditioned on it, so a worker
whose lease was reclaimed cannot write a stale result.

The queue is **bounded** (:data:`QueueFull`) and **prioritised** (a resumed
run is claimed before new work), which is what keeps an administrator's
recovery ahead of the next scheduled refresh.
"""

from __future__ import annotations

import logging
import os
import socket
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from src.db.runs import JobRunDB, JobRunEventDB, JobWorkItemDB, WorkerHeartbeatDB
from src.runs.state import (
    ACTIVE_RUN_STATUSES,
    CLAIMABLE_RUN_STATUSES,
    ERROR_RETRYABLE,
    EVENT_RECOVERY_REQUESTED,
    EVENT_RECOVERY_STARTED,
    EVENT_RUN_CANCELLED,
    EVENT_RUN_COMPLETED,
    EVENT_RUN_CREATED,
    EVENT_RUN_FAILED,
    EVENT_RUN_PAUSED,
    EVENT_WORKER_CLAIMED,
    EVENT_WORKER_INTERRUPTED,
    RESUMABLE_RUN_STATUSES,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PARTIAL,
    RUN_PAUSED,
    RUN_QUEUED,
    RUN_RECOVERABLE,
    RUN_RETRY_WAIT,
    RUN_RUNNING,
    WORK_CANCELLED,
    WORK_COMPLETED,
    WORK_FAILED,
    WORK_QUEUED,
    WORK_RETRY_WAIT,
    WORK_RUNNING,
    IllegalTransition,
    LeaseLost,
    assert_transition,
    assert_work_transition,
    utcnow,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ClaimedWork",
    "EnqueuedRun",
    "ItemOutcome",
    "Progress",
    "QueueFull",
    "RunAlreadyResumed",
    "WorkSpec",
    "cancel_run",
    "claim_work_items",
    "enqueue_run",
    "find_active_run",
    "get_run",
    "get_run_events",
    "get_run_items",
    "heartbeat_worker",
    "list_runs",
    "mark_worker_stopped",
    "pause_run",
    "queue_stats",
    "reap_expired_leases",
    "record_event",
    "register_worker",
    "requeue_item",
    "resume_run",
    "settle_work_items",
    "worker_health",
]

#: Priorities. Lower is claimed first.
PRIORITY_RECOVERY = 10
PRIORITY_EMBEDDING = 20
PRIORITY_REFRESH = 30
PRIORITY_RECONCILE = 40

QUEUE_RETRY_AFTER_SECONDS = 30


class QueueFull(RuntimeError):
    """The bounded queue is at capacity; the work was not accepted.

    Carries ``retry_after`` so the API can answer with a truthful
    ``Retry-After`` instead of a generic refusal.
    """

    def __init__(self, message: str, *, retry_after: int = QUEUE_RETRY_AFTER_SECONDS) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RunAlreadyResumed(RuntimeError):
    """Another request already moved the run back into the queue."""


@dataclass(frozen=True)
class WorkSpec:
    """One unit of work to create with a run."""

    job_id: str
    work_type: str = "embed"
    content_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClaimedWork:
    """A work item this worker now owns, with its fencing token."""

    id: str
    run_id: str
    job_id: str
    work_type: str
    content_hash: str
    embedding_model: str
    embedding_dimension: int
    attempt_count: int
    lease_token: str
    priority: int


@dataclass(frozen=True)
class ItemOutcome:
    """What happened to one claimed item."""

    item_id: str
    lease_token: str
    status: str
    error: str | None = None
    error_kind: str | None = None
    next_attempt_at: datetime | None = None


@dataclass(frozen=True)
class Progress:
    """A run's counters after a checkpoint."""

    run_id: str
    status: str
    total: int
    completed: int
    failed: int
    skipped: int
    outstanding: int


@dataclass(frozen=True)
class EnqueuedRun:
    """The durable identity of an accepted run."""

    run_id: str
    status: str
    job_type: str
    correlation_id: str
    created_at: datetime


def _factory(session_factory: sessionmaker | None) -> sessionmaker:
    if session_factory is not None:
        return session_factory
    from src.db.session import SessionLocal

    return SessionLocal


def _now(now: datetime | None) -> datetime:
    return now or utcnow()


def _settings():
    from src.config.settings import get_settings

    return get_settings()


def _limits():
    from src.security.limits import get_limits

    return get_limits()


def _clean(text: str | None, limit: int = 500) -> str | None:
    """Strip control characters and bound a diagnostic before it is stored."""
    if not text:
        return None
    from src.security.redaction import strip_control_characters

    return strip_control_characters(str(text))[:limit]


def record_event(
    session: Session,
    run_id: str,
    event: str,
    *,
    work_item_id: str | None = None,
    actor: str = "system",
    actor_kind: str = "system",
    actor_id: str | None = None,
    owner_id: str | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> JobRunEventDB:
    """Append one lifecycle event (the caller commits)."""
    from src.security.redaction import sanitize_metadata

    row = JobRunEventDB(
        run_id=str(run_id),
        work_item_id=work_item_id,
        event=str(event)[:120],
        actor=_clean(actor, 120) or "system",
        actor_kind=actor_kind,
        actor_id=_clean(actor_id, 120),
        owner_id=owner_id,
        message=_clean(message),
        extra_metadata=sanitize_metadata(metadata or {}),
    )
    session.add(row)
    return row


# -- enqueue ------------------------------------------------------------------


def enqueue_run(
    session: Session,
    *,
    job_type: str,
    correlation_id: str,
    owner_id: str | None = None,
    priority: int = 100,
    items: Sequence[WorkSpec] | None = None,
    embedding_model: str | None = None,
    embedding_dimension: int | None = None,
    parent_run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    enforce_capacity: bool = True,
) -> EnqueuedRun:
    """Create a run (and its items) durably. The caller commits.

    The capacity check is what makes "accepted work" a bounded promise: a
    queue that grows without limit is a memory/disk exhaustion path wearing
    a progress bar.
    """
    plan = list(items or [])
    if enforce_capacity:
        limits = _limits()
        active = int(
            session.execute(
                select(func.count())
                .select_from(JobRunDB)
                .where(JobRunDB.status.in_(tuple(ACTIVE_RUN_STATUSES)))
            ).scalar()
            or 0
        )
        if active >= limits.max_pending_runs:
            raise QueueFull(
                f"The background queue is at its run limit ({limits.max_pending_runs}). "
                "Wait for the current work to finish, then retry.",
                retry_after=QUEUE_RETRY_AFTER_SECONDS,
            )
        pending_items = int(
            session.execute(
                select(func.count())
                .select_from(JobWorkItemDB)
                .where(JobWorkItemDB.status.in_((WORK_QUEUED, WORK_RUNNING, WORK_RETRY_WAIT)))
            ).scalar()
            or 0
        )
        if pending_items + len(plan) > limits.max_pending_work_items:
            raise QueueFull(
                f"The background queue is at its work-item limit "
                f"({limits.max_pending_work_items}). Wait for the current work to finish, "
                "then retry.",
                retry_after=QUEUE_RETRY_AFTER_SECONDS,
            )

    run = JobRunDB(
        job_type=str(job_type)[:40],
        status=RUN_QUEUED,
        priority=int(priority),
        owner_id=owner_id,
        correlation_id=str(correlation_id)[:64],
        parent_run_id=parent_run_id,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        total_items=len(plan),
        extra_metadata=dict(metadata or {}),
    )
    session.add(run)
    session.flush()  # the id is generated application-side, but the row must exist first

    seen: set[tuple[str, str, str, str, int]] = set()
    created = 0
    for spec in plan:
        identity = (
            spec.job_id,
            spec.work_type,
            spec.content_hash,
            embedding_model or "",
            int(embedding_dimension or 0),
        )
        if identity in seen:
            continue
        seen.add(identity)
        if not session.execute(
            select(JobWorkItemDB.id).where(
                JobWorkItemDB.run_id == run.id,
                JobWorkItemDB.job_id == spec.job_id,
                JobWorkItemDB.work_type == spec.work_type,
                JobWorkItemDB.content_hash == spec.content_hash,
                JobWorkItemDB.embedding_model == (embedding_model or ""),
                JobWorkItemDB.embedding_dimension == int(embedding_dimension or 0),
            )
        ).first():
            session.add(
                JobWorkItemDB(
                    run_id=run.id,
                    job_id=spec.job_id,
                    work_type=spec.work_type,
                    content_hash=spec.content_hash,
                    embedding_model=embedding_model or "",
                    embedding_dimension=int(embedding_dimension or 0),
                    status=WORK_QUEUED,
                    extra_metadata=dict(spec.metadata),
                )
            )
            created += 1
    run.total_items = created
    record_event(
        session,
        run.id,
        EVENT_RUN_CREATED,
        owner_id=owner_id,
        message=f"{job_type} run accepted with {created} item(s)",
        metadata={"job_type": job_type, "items": created, "priority": int(priority)},
    )
    return EnqueuedRun(
        run_id=run.id,
        status=run.status,
        job_type=run.job_type,
        correlation_id=run.correlation_id,
        created_at=run.created_at,
    )


def find_active_run(session: Session, job_type: str) -> JobRunDB | None:
    """The oldest run of this type the worker may still make progress on."""
    return session.execute(
        select(JobRunDB)
        .where(
            JobRunDB.job_type == job_type,
            JobRunDB.status.in_(tuple(CLAIMABLE_RUN_STATUSES)),
        )
        .order_by(JobRunDB.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()


# -- claiming -----------------------------------------------------------------


def _candidate_ids(
    session: Session,
    *,
    limit: int,
    now: datetime,
    run_ids: Sequence[str] | None = None,
) -> list[str]:
    statement = (
        select(JobWorkItemDB.id)
        .join(JobRunDB, JobWorkItemDB.run_id == JobRunDB.id)
        .where(
            JobWorkItemDB.status.in_((WORK_QUEUED, WORK_RETRY_WAIT)),
            or_(
                JobWorkItemDB.next_attempt_at.is_(None),
                JobWorkItemDB.next_attempt_at <= now,
            ),
            JobRunDB.status.in_(tuple(CLAIMABLE_RUN_STATUSES)),
        )
        .order_by(
            JobRunDB.priority.asc(),
            JobWorkItemDB.next_attempt_at.asc(),
            JobWorkItemDB.created_at.asc(),
            JobWorkItemDB.id.asc(),
        )
        .limit(limit)
    )
    if run_ids:
        statement = statement.where(JobWorkItemDB.run_id.in_(tuple(run_ids)))
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        # The canonical queue claim: the rows are locked, and a second worker
        # skips them rather than waiting.
        statement = statement.with_for_update(skip_locked=True, of=JobWorkItemDB)
    return list(session.execute(statement).scalars())


def claim_work_items(
    *,
    worker_id: str,
    limit: int,
    lease_seconds: float,
    session_factory: sessionmaker | None = None,
    now: datetime | None = None,
    run_ids: Sequence[str] | None = None,
) -> list[ClaimedWork]:
    """Atomically claim up to *limit* due items for *worker_id*."""
    if limit < 1:
        return []
    moment = _now(now)
    factory = _factory(session_factory)
    claimed: list[ClaimedWork] = []
    with factory() as session:
        # On SQLite the select is advisory; the conditional update is the
        # lock. Ask for more candidates than needed so lost races do not
        # leave the batch short.
        wants = (
            limit
            if session.bind is not None and session.bind.dialect.name == "postgresql"
            else limit * 4
        )
        candidates = _candidate_ids(session, limit=wants, now=moment, run_ids=run_ids)
        for item_id in candidates:
            if len(claimed) >= limit:
                break
            token = uuid.uuid4().hex
            result = session.execute(
                update(JobWorkItemDB)
                .where(
                    JobWorkItemDB.id == item_id,
                    JobWorkItemDB.status.in_((WORK_QUEUED, WORK_RETRY_WAIT)),
                    or_(
                        JobWorkItemDB.next_attempt_at.is_(None),
                        JobWorkItemDB.next_attempt_at <= moment,
                    ),
                )
                .values(
                    status=WORK_RUNNING,
                    lease_owner=worker_id,
                    lease_token=token,
                    lease_expires_at=moment + timedelta(seconds=lease_seconds),
                    attempt_count=JobWorkItemDB.attempt_count + 1,
                    last_error=None,
                    last_error_kind=None,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:  # another worker won this one
                continue
            claimed.append(
                ClaimedWork(
                    id=item_id,
                    run_id="",  # filled below from the row
                    job_id="",
                    work_type="",
                    content_hash="",
                    embedding_model="",
                    embedding_dimension=0,
                    attempt_count=0,
                    lease_token=token,
                    priority=100,
                )
            )

        if not claimed:
            session.commit()
            return []

        ids = [item.id for item in claimed]
        rows = {
            row[0].id: row
            for row in session.execute(
                select(JobWorkItemDB, JobRunDB.priority)
                .join(JobRunDB, JobWorkItemDB.run_id == JobRunDB.id)
                .where(JobWorkItemDB.id.in_(ids))
            ).all()
        }
        claimed = [
            ClaimedWork(
                id=item.id,
                run_id=rows[item.id][0].run_id,
                job_id=rows[item.id][0].job_id,
                work_type=rows[item.id][0].work_type,
                content_hash=rows[item.id][0].content_hash,
                embedding_model=rows[item.id][0].embedding_model,
                embedding_dimension=rows[item.id][0].embedding_dimension,
                attempt_count=rows[item.id][0].attempt_count,
                lease_token=item.lease_token,
                priority=int(rows[item.id][1]),
            )
            for item in claimed
        ]

        # The run starts (QUEUED -> RUNNING is the only automatic adoption;
        # a RECOVERABLE run waits for an attributable resume).
        run_ids = {item.run_id for item in claimed}
        session.execute(
            update(JobRunDB)
            .where(
                JobRunDB.id.in_(run_ids),
                JobRunDB.status.in_((RUN_QUEUED, RUN_RETRY_WAIT)),
            )
            .values(
                status=RUN_RUNNING,
                started_at=func.coalesce(JobRunDB.started_at, moment),
                heartbeat_at=moment,
                lease_owner=worker_id,
                lease_expires_at=moment + timedelta(seconds=lease_seconds),
                attempt_count=JobRunDB.attempt_count + 1,
            )
            .execution_options(synchronize_session=False)
        )
        session.execute(
            update(JobRunDB)
            .where(JobRunDB.id.in_(run_ids))
            .values(heartbeat_at=moment, lease_owner=worker_id)
            .execution_options(synchronize_session=False)
        )
        for run_id in run_ids:
            record_event(
                session,
                run_id,
                EVENT_WORKER_CLAIMED,
                actor="agent",
                actor_kind="agent",
                actor_id=worker_id,
                message=f"{worker_id} claimed {sum(1 for item in claimed if item.run_id == run_id)} item(s)",
                metadata={"worker_id": worker_id},
            )
        session.commit()
    return claimed


# -- settling -----------------------------------------------------------------


def _recount(session: Session, run_id: str) -> dict[str, int]:
    rows = session.execute(
        select(JobWorkItemDB.status, func.count())
        .where(JobWorkItemDB.run_id == run_id)
        .group_by(JobWorkItemDB.status)
    ).all()
    return {str(status): int(count) for status, count in rows}


def checkpoint_run(
    session: Session,
    run_id: str,
    *,
    now: datetime | None = None,
    touch_heartbeat: bool = True,
) -> Progress:
    """Recount a run, finalise it when nothing is outstanding, return progress."""
    moment = _now(now)
    counts = _recount(session, run_id)
    total = sum(counts.values())
    completed = counts.get(WORK_COMPLETED, 0)
    failed = counts.get(WORK_FAILED, 0)
    skipped = counts.get(WORK_CANCELLED, 0)
    retry_wait = counts.get(WORK_RETRY_WAIT, 0)
    queued = counts.get(WORK_QUEUED, 0)
    running = counts.get(WORK_RUNNING, 0)
    outstanding = queued + running + retry_wait

    run = session.get(JobRunDB, run_id)
    if run is None:
        raise LookupError(f"Run {run_id!r} does not exist")

    run.total_items = total
    run.completed_items = completed
    run.failed_items = failed
    run.skipped_items = skipped
    if touch_heartbeat:
        run.heartbeat_at = moment

    if run.status in (RUN_COMPLETED, RUN_CANCELLED):
        return Progress(run.id, run.status, total, completed, failed, skipped, outstanding)

    if outstanding:
        target = RUN_RETRY_WAIT if retry_wait and not (queued or running) else RUN_RUNNING
        # PAUSED is a deliberate stop and RECOVERABLE waits for an
        # attributable resume; neither is erased by a checkpoint.
        if run.status not in (RUN_PAUSED, RUN_RECOVERABLE):
            assert_transition(run.status, target)
            run.status = target
    else:
        if failed and completed:
            target = RUN_PARTIAL
        elif failed:
            target = RUN_FAILED
        else:
            target = RUN_COMPLETED
        if run.status != target:
            assert_transition(run.status, target)
            run.status = target
            run.completed_at = moment
            run.lease_owner = None
            run.lease_expires_at = None
            event = {
                RUN_COMPLETED: EVENT_RUN_COMPLETED,
                RUN_PARTIAL: EVENT_RUN_FAILED,
                RUN_FAILED: EVENT_RUN_FAILED,
            }[target]
            record_event(
                session,
                run.id,
                event,
                owner_id=run.owner_id,
                message=(
                    f"{run.job_type} run {target.lower()}: "
                    f"{completed} completed, {failed} failed, {skipped} skipped"
                ),
                metadata={
                    "total": total,
                    "completed": completed,
                    "failed": failed,
                    "skipped": skipped,
                },
            )
    return Progress(run.id, run.status, total, completed, failed, skipped, outstanding)


def settle_work_items(
    *,
    run_id: str,
    outcomes: Sequence[ItemOutcome],
    worker_id: str,
    session_factory: sessionmaker | None = None,
    event: str | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
    max_attempts: int | None = None,
) -> Progress:
    """Record the outcome of a batch and checkpoint the run once.

    Every write is conditioned on the item's lease token. If any item in the
    batch is stale, the whole transaction rolls back and :class:`LeaseLost`
    is raised: the batch's items shared a lease, so they were reclaimed
    together, and none of the stale worker's claims may land.
    """
    moment = _now(now)
    factory = _factory(session_factory)
    with factory() as session:
        if not outcomes:
            progress = checkpoint_run(session, run_id, now=moment)
            session.commit()
            return progress
        for outcome in outcomes:
            target = outcome.status
            assert_work_transition(WORK_RUNNING, target)
            values: dict[str, Any] = {
                "status": target,
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "last_error": _clean(outcome.error),
                "last_error_kind": outcome.error_kind,
            }
            if target == WORK_COMPLETED:
                values["completed_at"] = moment
                values["next_attempt_at"] = None
            elif target == WORK_RETRY_WAIT:
                values["next_attempt_at"] = outcome.next_attempt_at or moment
            result = session.execute(
                update(JobWorkItemDB)
                .where(
                    JobWorkItemDB.id == outcome.item_id,
                    JobWorkItemDB.lease_token == outcome.lease_token,
                    JobWorkItemDB.status == WORK_RUNNING,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                session.rollback()
                raise LeaseLost(
                    f"Work item {outcome.item_id!r} no longer belongs to lease "
                    f"{outcome.lease_token!r}; the result was discarded."
                )
        progress = checkpoint_run(session, run_id, now=moment)
        if event:
            record_event(
                session,
                run_id,
                event,
                actor="agent",
                actor_kind="agent",
                actor_id=worker_id,
                message=message,
                metadata=metadata,
            )
        session.commit()
    return progress


def requeue_item(
    session: Session,
    item_id: str,
    *,
    lease_token: str,
    next_attempt_at: datetime | None = None,
    error: str | None = None,
) -> bool:
    """Return a claimed item to the queue (quota stop) inside a transaction."""
    result = session.execute(
        update(JobWorkItemDB)
        .where(
            JobWorkItemDB.id == item_id,
            JobWorkItemDB.lease_token == lease_token,
            JobWorkItemDB.status == WORK_RUNNING,
        )
        .values(
            status=WORK_QUEUED,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            next_attempt_at=next_attempt_at,
            last_error=_clean(error),
            last_error_kind=ERROR_RETRYABLE if error else None,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def pause_run(
    session: Session,
    run_id: str,
    *,
    reason: str,
    error_kind: str = "quota",
    message: str | None = None,
) -> None:
    """Stop a run cleanly, leaving its outstanding items queued."""
    run = session.get(JobRunDB, run_id)
    if run is None or run.status in (RUN_COMPLETED, RUN_CANCELLED, RUN_PAUSED):
        return
    assert_transition(run.status, RUN_PAUSED)
    run.status = RUN_PAUSED
    run.last_error = _clean(reason)
    run.last_error_kind = error_kind
    run.lease_owner = None
    run.lease_expires_at = None
    run.extra_metadata = {**(run.extra_metadata or {}), "pause_reason": reason}
    record_event(
        session,
        run.id,
        EVENT_RUN_PAUSED,
        owner_id=run.owner_id,
        message=message or reason,
        metadata={"reason": reason},
    )


# -- lease reaping ------------------------------------------------------------


def reap_expired_leases(
    *,
    session_factory: sessionmaker | None = None,
    now: datetime | None = None,
    run_stale_seconds: float | None = None,
    max_attempts: int | None = None,
) -> dict[str, int]:
    """Requeue abandoned work and mark interrupted runs recoverable.

    Returns ``{"items": n, "runs": n, "exhausted": n}`` for the log line and
    the metrics endpoint.
    """
    moment = _now(now)
    settings = _settings()
    stale = run_stale_seconds if run_stale_seconds is not None else settings.run_stale_seconds
    attempt_cap = max_attempts if max_attempts is not None else settings.worker_max_attempts
    factory = _factory(session_factory)
    expired_items = 0
    exhausted = 0
    expired_runs = 0

    with factory() as session:
        affected_runs = {
            str(run_id)
            for (run_id,) in session.execute(
                select(JobWorkItemDB.run_id)
                .where(
                    JobWorkItemDB.status == WORK_RUNNING,
                    JobWorkItemDB.lease_expires_at.is_not(None),
                    JobWorkItemDB.lease_expires_at < moment,
                )
                .distinct()
            ).all()
        }
        # An item that has burned its attempts stops being retried. This is
        # the ceiling that stops a crash loop from spinning forever.
        exhausted_result = session.execute(
            update(JobWorkItemDB)
            .where(
                JobWorkItemDB.status == WORK_RUNNING,
                JobWorkItemDB.lease_expires_at.is_not(None),
                JobWorkItemDB.lease_expires_at < moment,
                JobWorkItemDB.attempt_count >= attempt_cap,
            )
            .values(
                status=WORK_FAILED,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                last_error=f"Worker lease expired after {attempt_cap} attempt(s)",
                last_error_kind="retryable",
            )
            .execution_options(synchronize_session=False)
        )
        exhausted = int(exhausted_result.rowcount or 0)

        expired_result = session.execute(
            update(JobWorkItemDB)
            .where(
                JobWorkItemDB.status == WORK_RUNNING,
                JobWorkItemDB.lease_expires_at.is_not(None),
                JobWorkItemDB.lease_expires_at < moment,
                JobWorkItemDB.attempt_count < attempt_cap,
            )
            .values(
                status=WORK_QUEUED,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                next_attempt_at=moment,
                last_error="Worker lease expired; work requeued",
                last_error_kind=ERROR_RETRYABLE,
            )
            .execution_options(synchronize_session=False)
        )
        expired_items = int(expired_result.rowcount or 0)

        # A run whose abandoned items were just requeued (or exhausted) gets
        # its counters corrected now, without refreshing the heartbeat of a
        # run whose worker may be dead.
        for run_id in affected_runs:
            checkpoint_run(session, run_id, now=moment, touch_heartbeat=False)

        stale_before = moment - timedelta(seconds=stale)
        interrupted = session.execute(
            select(JobRunDB).where(
                JobRunDB.status == RUN_RUNNING,
                or_(JobRunDB.heartbeat_at.is_(None), JobRunDB.heartbeat_at < stale_before),
            )
        ).scalars()
        for run in interrupted:
            outstanding = int(
                session.execute(
                    select(func.count())
                    .select_from(JobWorkItemDB)
                    .where(
                        JobWorkItemDB.run_id == run.id,
                        JobWorkItemDB.status.in_((WORK_QUEUED, WORK_RUNNING, WORK_RETRY_WAIT)),
                    )
                ).scalar()
                or 0
            )
            if outstanding:
                assert_transition(run.status, RUN_RECOVERABLE)
                run.status = RUN_RECOVERABLE
                run.lease_owner = None
                run.lease_expires_at = None
                run.last_error = "Worker stopped heartbeating; the run is recoverable"
                run.last_error_kind = ERROR_RETRYABLE
                run.heartbeat_at = moment
                record_event(
                    session,
                    run.id,
                    EVENT_WORKER_INTERRUPTED,
                    owner_id=run.owner_id,
                    message=(f"Worker stopped heartbeating with {outstanding} outstanding item(s)"),
                    metadata={"outstanding": outstanding, "stale_after_seconds": stale},
                )
                expired_runs += 1
            else:
                checkpoint_run(session, run.id, now=moment)
        session.commit()

    if expired_items or exhausted or expired_runs:
        logger.warning(
            "Lease reaper: requeued %d item(s), failed %d exhausted item(s), "
            "marked %d run(s) recoverable",
            expired_items,
            exhausted,
            expired_runs,
        )
    return {"items": expired_items, "runs": expired_runs, "exhausted": exhausted}


# -- recovery -----------------------------------------------------------------


def resume_run(
    session: Session,
    *,
    run_id: str,
    actor: str,
    actor_kind: str = "user",
    actor_id: str | None = None,
    expected_model: str | None = None,
    expected_dimension: int | None = None,
    now: datetime | None = None,
) -> JobRunDB:
    """Put a stopped run back in the queue, keeping completed work.

    The conditional update is the concurrency control: two administrators
    clicking Resume produce exactly one requeue. The second gets
    :class:`RunAlreadyResumed`.
    """
    moment = _now(now)
    run = session.get(JobRunDB, run_id)
    if run is None:
        raise LookupError(f"Run {run_id!r} does not exist")
    if run.status not in RESUMABLE_RUN_STATUSES:
        raise IllegalTransition(
            f"Run {run.id} is {run.status}; only a paused, recoverable, retrying, "
            "failed or partial run may be resumed."
        )
    if run.job_type == "embedding":
        if expected_model is not None and run.embedding_model != expected_model:
            raise ValueError(
                f"This run embedded with model {run.embedding_model!r}, but the "
                f"configured provider is {expected_model!r}. A model change is a new "
                "embedding space: re-embed the corpus instead of resuming this run."
            )
        if expected_dimension is not None and run.embedding_dimension != expected_dimension:
            raise ValueError(
                f"This run embedded at dimension {run.embedding_dimension}, but the "
                f"configured provider uses {expected_dimension}. Re-embed the corpus "
                "instead of resuming this run."
            )

    result = session.execute(
        update(JobRunDB)
        .where(JobRunDB.id == run.id, JobRunDB.status == run.status)
        .values(
            status=RUN_QUEUED,
            priority=PRIORITY_RECOVERY,
            heartbeat_at=None,
            lease_owner=None,
            lease_expires_at=None,
            completed_at=None,
            last_error=None,
            last_error_kind=None,
            attempt_count=0,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise RunAlreadyResumed(
            f"Run {run_id!r} was resumed by another request; this one made no change."
        )

    # Outstanding work only: completed items are never requeued, and an item
    # whose worker still holds a live lease is left to that worker.
    requeued = session.execute(
        update(JobWorkItemDB)
        .where(
            JobWorkItemDB.run_id == run.id,
            or_(
                JobWorkItemDB.status.in_((WORK_QUEUED, WORK_RETRY_WAIT, WORK_FAILED)),
                (
                    (JobWorkItemDB.status == WORK_RUNNING)
                    & (
                        JobWorkItemDB.lease_expires_at.is_(None)
                        | (JobWorkItemDB.lease_expires_at <= moment)
                    )
                ),
            ),
        )
        .values(
            status=WORK_QUEUED,
            attempt_count=0,
            next_attempt_at=moment,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            last_error=None,
            last_error_kind=None,
        )
        .execution_options(synchronize_session=False)
    )

    record_event(
        session,
        run.id,
        EVENT_RECOVERY_REQUESTED,
        actor=actor,
        actor_kind=actor_kind,
        actor_id=actor_id,
        owner_id=run.owner_id,
        message=f"Recovery requested; {int(requeued.rowcount or 0)} item(s) requeued",
        metadata={
            "requeued": int(requeued.rowcount or 0),
            "previous_status": run.status,
        },
    )
    record_event(
        session,
        run.id,
        EVENT_RECOVERY_STARTED,
        actor=actor,
        actor_kind=actor_kind,
        actor_id=actor_id,
        owner_id=run.owner_id,
        message="Run queued for recovery",
        metadata={"priority": PRIORITY_RECOVERY},
    )
    session.refresh(run)
    return run


def cancel_run(
    session: Session,
    *,
    run_id: str,
    actor: str,
    actor_kind: str = "user",
    actor_id: str | None = None,
    now: datetime | None = None,
) -> JobRunDB:
    """Stop a run without deleting its history. Outstanding items are cancelled."""
    moment = _now(now)
    run = session.get(JobRunDB, run_id)
    if run is None:
        raise LookupError(f"Run {run_id!r} does not exist")
    if run.status in (RUN_COMPLETED, RUN_CANCELLED):
        raise IllegalTransition(f"Run {run.id} is already {run.status}.")
    assert_transition(run.status, RUN_CANCELLED)
    run.status = RUN_CANCELLED
    run.completed_at = moment
    run.lease_owner = None
    run.lease_expires_at = None
    session.execute(
        update(JobWorkItemDB)
        .where(
            JobWorkItemDB.run_id == run.id,
            JobWorkItemDB.status.in_((WORK_QUEUED, WORK_RUNNING, WORK_RETRY_WAIT)),
        )
        .values(
            status=WORK_CANCELLED,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            last_error="Run cancelled",
            last_error_kind="permanent",
        )
        .execution_options(synchronize_session=False)
    )
    record_event(
        session,
        run.id,
        EVENT_RUN_CANCELLED,
        actor=actor,
        actor_kind=actor_kind,
        actor_id=actor_id,
        owner_id=run.owner_id,
        message="Run cancelled by an administrator",
    )
    # The status is an ORM change, not a Core UPDATE: flush it before the
    # refresh, or the refresh reads the old row and the caller is told the
    # cancellation did not happen.
    session.flush()
    session.refresh(run)
    return run


# -- reads and metrics --------------------------------------------------------


def get_run(session: Session, run_id: str) -> JobRunDB | None:
    return session.get(JobRunDB, run_id)


def list_runs(
    session: Session,
    *,
    job_type: str | None = None,
    statuses: Sequence[str] | None = None,
    owner_id: str | None = None,
    limit: int = 50,
) -> list[JobRunDB]:
    statement = select(JobRunDB).order_by(JobRunDB.created_at.desc())
    if job_type:
        statement = statement.where(JobRunDB.job_type == job_type)
    if statuses:
        statement = statement.where(JobRunDB.status.in_(tuple(statuses)))
    if owner_id is not None:
        statement = statement.where(JobRunDB.owner_id == owner_id)
    return list(session.execute(statement.limit(max(1, min(limit, 200)))).scalars())


def get_run_items(session: Session, run_id: str, *, limit: int = 200) -> list[JobWorkItemDB]:
    return list(
        session.execute(
            select(JobWorkItemDB)
            .where(JobWorkItemDB.run_id == run_id)
            .order_by(JobWorkItemDB.created_at.asc(), JobWorkItemDB.id.asc())
            .limit(max(1, min(limit, 500)))
        ).scalars()
    )


def get_run_events(session: Session, run_id: str, *, limit: int = 200) -> list[JobRunEventDB]:
    return list(
        session.execute(
            select(JobRunEventDB)
            .where(JobRunEventDB.run_id == run_id)
            .order_by(JobRunEventDB.id.desc())
            .limit(max(1, min(limit, 500)))
        ).scalars()
    )


def queue_stats(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """The queue's health, as cheap aggregate queries."""
    moment = _now(now)
    item_counts = {
        str(status): int(count)
        for status, count in session.execute(
            select(JobWorkItemDB.status, func.count()).group_by(JobWorkItemDB.status)
        ).all()
    }
    run_counts = {
        str(status): int(count)
        for status, count in session.execute(
            select(JobRunDB.status, func.count()).group_by(JobRunDB.status)
        ).all()
    }
    stale_leases = int(
        session.execute(
            select(func.count())
            .select_from(JobWorkItemDB)
            .where(
                JobWorkItemDB.status == WORK_RUNNING,
                JobWorkItemDB.lease_expires_at.is_not(None),
                JobWorkItemDB.lease_expires_at < moment,
            )
        ).scalar()
        or 0
    )
    # "Reclaimed" is a running item that has been claimed more than once:
    # the first claim's lease expired and the reaper requeued it.
    reclaimed = int(
        session.execute(
            select(func.count())
            .select_from(JobWorkItemDB)
            .where(
                JobWorkItemDB.status == WORK_RUNNING,
                JobWorkItemDB.attempt_count > 1,
            )
        ).scalar()
        or 0
    )
    oldest_pending = session.execute(
        select(func.min(JobWorkItemDB.created_at)).where(
            JobWorkItemDB.status.in_((WORK_QUEUED, WORK_RETRY_WAIT))
        )
    ).scalar()
    oldest_age = (moment - oldest_pending).total_seconds() if oldest_pending else 0.0
    return {
        "items": {
            "queued": item_counts.get(WORK_QUEUED, 0),
            "running": item_counts.get(WORK_RUNNING, 0),
            "retry_wait": item_counts.get(WORK_RETRY_WAIT, 0),
            "completed": item_counts.get(WORK_COMPLETED, 0),
            "failed": item_counts.get(WORK_FAILED, 0),
            "cancelled": item_counts.get(WORK_CANCELLED, 0),
            "stale_leases": stale_leases,
            "reclaimed_leases": reclaimed,
            "oldest_pending_age_seconds": round(max(0.0, oldest_age), 3),
        },
        "runs": {
            "queued": run_counts.get(RUN_QUEUED, 0),
            "running": run_counts.get(RUN_RUNNING, 0),
            "paused": run_counts.get(RUN_PAUSED, 0),
            "retry_wait": run_counts.get(RUN_RETRY_WAIT, 0),
            "recoverable": run_counts.get(RUN_RECOVERABLE, 0),
            "completed": run_counts.get(RUN_COMPLETED, 0),
            "partial": run_counts.get(RUN_PARTIAL, 0),
            "failed": run_counts.get(RUN_FAILED, 0),
            "cancelled": run_counts.get(RUN_CANCELLED, 0),
        },
    }


# -- worker registry ----------------------------------------------------------


def register_worker(
    session: Session,
    *,
    worker_id: str,
    pid: int | None = None,
    hostname: str | None = None,
    now: datetime | None = None,
) -> WorkerHeartbeatDB:
    """Claim (or re-claim) a worker id and record the start."""
    moment = _now(now)
    row = session.get(WorkerHeartbeatDB, worker_id)
    if row is None:
        row = WorkerHeartbeatDB(
            worker_id=worker_id,
            status="running",
            pid=pid if pid is not None else os.getpid(),
            hostname=hostname or socket.gethostname(),
            started_at=moment,
            last_heartbeat_at=moment,
            starts=1,
        )
        session.add(row)
    else:
        row.status = "running"
        row.pid = pid if pid is not None else os.getpid()
        row.hostname = hostname or socket.gethostname()
        row.started_at = moment
        row.last_heartbeat_at = moment
        row.stopped_at = None
        row.starts += 1
    session.commit()
    return row


def heartbeat_worker(
    session: Session,
    *,
    worker_id: str,
    current_run_id: str | None = None,
    processed_items: int = 0,
    failed_items: int = 0,
    now: datetime | None = None,
) -> None:
    session.execute(
        update(WorkerHeartbeatDB)
        .where(WorkerHeartbeatDB.worker_id == worker_id)
        .values(
            status="running",
            last_heartbeat_at=_now(now),
            current_run_id=current_run_id,
            processed_items=WorkerHeartbeatDB.processed_items + int(processed_items),
            failed_items=WorkerHeartbeatDB.failed_items + int(failed_items),
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()


def mark_worker_stopped(
    session: Session, *, worker_id: str, status: str = "stopped", now: datetime | None = None
) -> None:
    session.execute(
        update(WorkerHeartbeatDB)
        .where(WorkerHeartbeatDB.worker_id == worker_id)
        .values(status=status, stopped_at=_now(now))
        .execution_options(synchronize_session=False)
    )
    session.commit()


def worker_health(
    session: Session, *, stale_after_seconds: float | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Whether a background worker is alive, which the API cannot infer."""
    moment = _now(now)
    stale_after = (
        stale_after_seconds if stale_after_seconds is not None else _settings().worker_stale_seconds
    )
    workers = list(
        session.execute(
            select(WorkerHeartbeatDB).order_by(WorkerHeartbeatDB.last_heartbeat_at.desc())
        ).scalars()
    )
    entries = []
    healthy = 0
    for worker in workers:
        age = (moment - worker.last_heartbeat_at).total_seconds()
        is_healthy = worker.status == "running" and age <= stale_after
        elapsed_minutes = max(
            (moment - worker.started_at).total_seconds() / 60.0, 1.0 / 60.0
        )
        healthy += 1 if is_healthy else 0
        entries.append(
            {
                "worker_id": worker.worker_id,
                "status": worker.status,
                "hostname": worker.hostname,
                "pid": worker.pid,
                "heartbeat_age_seconds": round(max(0.0, age), 3),
                "healthy": is_healthy,
                "starts": worker.starts,
                "processed_items": worker.processed_items,
                "failed_items": worker.failed_items,
                "work_per_minute": round(worker.processed_items / elapsed_minutes, 3),
                "current_run_id": worker.current_run_id,
            }
        )
    return {
        "healthy": healthy,
        "total": len(entries),
        "stale_after_seconds": stale_after,
        "workers": entries,
    }


def iter_active_run_ids(session: Session) -> Iterable[str]:
    """The ids of every run the worker may still progress (diagnostics)."""
    return session.execute(
        select(JobRunDB.id).where(JobRunDB.status.in_(tuple(ACTIVE_RUN_STATUSES)))
    ).scalars()
