"""Durable-execution service layer (WS-18).

The routes are thin; the decisions live here. Three rules are enforced in
this module rather than in a route, because a route that forgot one would be
a route that silently widens the surface:

- **An ordinary caller sees their own runs and nothing else.** A platform
  run (no owner) is administrator-only. A foreign run is ``None`` — the same
  answer as a missing one, so the API is not an existence oracle.
- **Only a platform administrator may resume, cancel or reconcile.** The
  route's ``require_superuser`` dependency is the boundary; this module
  re-checks nothing about the identity (it receives a scope) and everything
  about the *run's* state.
- **A resume is a state transition, not a request to try harder.** Completed
  work is never requeued, a concurrent resume loses the conditional update,
  and a model/dimension change refuses the resume.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db import access
from src.db.access import UserScope
from src.db.jobs import JobDB
from src.db.runs import JobRunDB, JobWorkItemDB
from src.runs import queue
from src.runs.embedding import JOB_TYPE_EMBEDDING, JOB_TYPE_RECONCILE, JOB_TYPE_REFRESH
from src.runs.state import (
    ACTIVE_RUN_STATUSES,
    WORK_CANCELLED,
    WORK_COMPLETED,
    WORK_FAILED,
    WORK_QUEUED,
    WORK_RETRY_WAIT,
    WORK_RUNNING,
    utcnow,
)
from src.security.audit import (
    ACTION_RUN_CANCEL,
    ACTION_RUN_ENQUEUE,
    ACTION_RUN_RECONCILE,
    ACTION_RUN_RESUME,
    OUTCOME_SUCCESS,
    Actor,
    record_audit,
)

logger = logging.getLogger(__name__)

__all__ = [
    "cancel_run",
    "enqueue_reconcile",
    "enqueue_refresh",
    "enqueue_refresh_platform",
    "get_run_for_scope",
    "list_runs_for_scope",
    "queue_metrics",
    "resume_embedding_run",
    "run_detail",
    "run_to_dict",
]


def _accept_refresh(
    db: Session,
    *,
    owner_id: str | None,
    actor: Actor,
    audit_owner_id: str,
    correlation_id: str | None,
) -> tuple[JobRunDB, bool]:
    existing = queue.find_active_run(db, JOB_TYPE_REFRESH)
    if existing is not None:
        return existing, False
    accepted = queue.enqueue_run(
        db,
        job_type=JOB_TYPE_REFRESH,
        correlation_id=correlation_id or uuid.uuid4().hex,
        owner_id=owner_id,
        priority=queue.PRIORITY_REFRESH,
        items=[queue.WorkSpec(job_id="", work_type="refresh", content_hash="")],
    )
    record_audit(
        ACTION_RUN_ENQUEUE,
        actor=actor,
        resource=accepted.run_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=audit_owner_id,
        metadata={"job_type": JOB_TYPE_REFRESH, "correlation_id": accepted.correlation_id},
        session=db,
    )
    db.commit()
    run = db.get(JobRunDB, accepted.run_id)
    assert run is not None  # just created in this transaction
    return run, True


def enqueue_refresh(
    db: Session,
    scope: UserScope,
    *,
    correlation_id: str | None = None,
) -> tuple[JobRunDB, bool]:
    """Accept a refresh durably. Returns ``(run, created)``.

    A refresh that is already queued or running is **returned**, not
    duplicated: two clicks are one refresh. The suppression is the run
    table's own state, so it holds across API processes.
    """
    return _accept_refresh(
        db,
        owner_id=scope.user_id,
        actor=Actor.user(scope.user_id),
        audit_owner_id=scope.user_id,
        correlation_id=correlation_id,
    )


def enqueue_refresh_platform(
    db: Session, *, correlation_id: str | None = None
) -> tuple[JobRunDB, bool]:
    """Accept a scheduled refresh with no user owner (the CLI/cron path).

    A platform run is visible to administrators, not to an ordinary caller:
    it was not requested by a person's session, and attributing it to one
    would be a false claim about who asked for it.
    """
    from src.db.users import LEGACY_OWNER_ID

    return _accept_refresh(
        db,
        owner_id=None,
        actor=Actor.system(),
        audit_owner_id=LEGACY_OWNER_ID,
        correlation_id=correlation_id,
    )


def enqueue_reconcile(
    db: Session,
    scope: UserScope,
    *,
    correlation_id: str | None = None,
) -> tuple[JobRunDB, bool]:
    """Accept a reconciliation run (administrator-only at the route)."""
    existing = queue.find_active_run(db, JOB_TYPE_RECONCILE)
    if existing is not None:
        return existing, False
    accepted = queue.enqueue_run(
        db,
        job_type=JOB_TYPE_RECONCILE,
        correlation_id=correlation_id or uuid.uuid4().hex,
        owner_id=scope.user_id,
        priority=queue.PRIORITY_RECONCILE,
        items=[queue.WorkSpec(job_id="", work_type="reconcile", content_hash="")],
    )
    record_audit(
        ACTION_RUN_RECONCILE,
        actor=Actor.user(scope.user_id),
        resource=accepted.run_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=scope.user_id,
        metadata={"job_type": JOB_TYPE_RECONCILE},
        session=db,
    )
    db.commit()
    run = db.get(JobRunDB, accepted.run_id)
    assert run is not None
    return run, True


def get_run_for_scope(db: Session, scope: UserScope, run_id: str) -> JobRunDB | None:
    """The run if this scope may see it; ``None`` otherwise (no oracle)."""
    run = db.get(JobRunDB, run_id)
    if run is None:
        return None
    if scope.is_superuser:
        return run
    if run.owner_id is not None and run.owner_id == scope.user_id:
        return run
    # A platform run has no owner; it is the administrator's view, and an
    # ordinary caller gets the same "not found" as for a foreign id.
    return None


def list_runs_for_scope(db: Session, scope: UserScope, *, limit: int = 50) -> list[JobRunDB]:
    """The caller's own runs in a bounded page."""
    if scope.is_superuser:
        return queue.list_runs(db, limit=limit)
    return queue.list_runs(db, owner_id=scope.user_id, limit=limit)


def resume_embedding_run(
    db: Session,
    scope: UserScope,
    run_id: str,
    *,
    expected_model: str,
    expected_dimension: int,
) -> JobRunDB:
    """The administrator's explicit recovery action.

    Raises:
        LookupError: no such embedding run.
        queue.IllegalTransition: the run is not in a resumable state.
        queue.RunAlreadyResumed: a concurrent request already resumed it.
        ValueError: the run embedded a different model or dimension.
    """
    run = access.get_run(db, scope, run_id)
    if run is None or run.job_type != JOB_TYPE_EMBEDDING:
        raise LookupError(f"Embedding run {run_id!r} does not exist.")
    previous = run.status
    resumed = queue.resume_run(
        db,
        run_id=run_id,
        actor=Actor.user(scope.user_id).label,
        actor_kind="user",
        actor_id=scope.user_id,
        expected_model=expected_model,
        expected_dimension=expected_dimension,
        now=utcnow(),
    )
    db.commit()
    record_audit(
        ACTION_RUN_RESUME,
        actor=Actor.user(scope.user_id),
        resource=run_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=scope.user_id,
        metadata={
            "previous_status": previous,
            "status": resumed.status,
            "embedding_model": resumed.embedding_model,
            "embedding_dimension": resumed.embedding_dimension,
        },
        session=db,
    )
    db.commit()
    db.refresh(resumed)
    return resumed


def cancel_run(db: Session, scope: UserScope, run_id: str) -> JobRunDB:
    """Stop a run without deleting its history (administrator action)."""
    run = access.get_run(db, scope, run_id)
    if run is None:
        raise LookupError(f"Run {run_id!r} does not exist.")
    cancelled = queue.cancel_run(
        db,
        run_id=run_id,
        actor=Actor.user(scope.user_id).label,
        actor_kind="user",
        actor_id=scope.user_id,
        now=utcnow(),
    )
    db.commit()
    record_audit(
        ACTION_RUN_CANCEL,
        actor=Actor.user(scope.user_id),
        resource=run_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=scope.user_id,
        metadata={"job_type": cancelled.job_type},
        session=db,
    )
    db.commit()
    db.refresh(cancelled)
    return cancelled


# -- serialisation ------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def run_to_dict(run: JobRunDB) -> dict[str, Any]:
    """The contract the console renders. Never includes item contents."""
    total = int(run.total_items or 0)
    done = int(run.completed_items or 0) + int(run.failed_items or 0) + int(run.skipped_items or 0)
    return {
        "id": run.id,
        "job_type": run.job_type,
        "status": run.status,
        "priority": run.priority,
        "owner_id": run.owner_id,
        "correlation_id": run.correlation_id,
        "parent_run_id": run.parent_run_id,
        "embedding_model": run.embedding_model,
        "embedding_dimension": run.embedding_dimension,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        "heartbeat_at": _iso(run.heartbeat_at),
        "lease": {
            "owner": run.lease_owner,
            "expires_at": _iso(run.lease_expires_at),
        },
        "attempt_count": int(run.attempt_count or 0),
        "total_items": total,
        "completed_items": int(run.completed_items or 0),
        "failed_items": int(run.failed_items or 0),
        "skipped_items": int(run.skipped_items or 0),
        "remaining_items": max(0, total - done),
        "progress_percent": round((done / total) * 100, 1) if total else 0.0,
        "last_error": run.last_error,
        "last_error_kind": run.last_error_kind,
        "metadata": dict(run.extra_metadata or {}),
        "resumable": run.job_type == JOB_TYPE_EMBEDDING
        and run.status in queue.RESUMABLE_RUN_STATUSES,
        "cancellable": run.status in ACTIVE_RUN_STATUSES
        or run.status in queue.RESUMABLE_RUN_STATUSES,
    }


def run_detail(db: Session, run: JobRunDB, *, include_items: bool = True) -> dict[str, Any]:
    """A run plus its checkpoints, item summary and recent error samples."""
    body = run_to_dict(run)
    counts = {
        str(status): int(count)
        for status, count in db.execute(
            select(JobWorkItemDB.status, func.count())
            .where(JobWorkItemDB.run_id == run.id)
            .group_by(JobWorkItemDB.status)
        ).all()
    }
    body["items"] = {
        "queued": counts.get(WORK_QUEUED, 0),
        "running": counts.get(WORK_RUNNING, 0),
        "retry_wait": counts.get(WORK_RETRY_WAIT, 0),
        "completed": counts.get(WORK_COMPLETED, 0),
        "failed": counts.get(WORK_FAILED, 0),
        "cancelled": counts.get(WORK_CANCELLED, 0),
    }
    events = queue.get_run_events(db, run.id, limit=100)
    body["events"] = [
        {
            "id": event.id,
            "event": event.event,
            "at": _iso(event.at),
            "actor": event.actor,
            "actor_kind": event.actor_kind,
            "message": event.message,
            "metadata": dict(event.extra_metadata or {}),
        }
        for event in events
    ]
    if include_items:
        failures = list(
            db.execute(
                select(JobWorkItemDB)
                .where(
                    JobWorkItemDB.run_id == run.id,
                    JobWorkItemDB.status == WORK_FAILED,
                )
                .order_by(JobWorkItemDB.attempt_count.desc())
                .limit(20)
            ).scalars()
        )
        body["failed_work_items"] = [
            {
                "id": item.id,
                "job_id": item.job_id,
                "attempt_count": item.attempt_count,
                "last_error": item.last_error,
                "last_error_kind": item.last_error_kind,
            }
            for item in failures
        ]
    body["checkpoint"] = {
        "last_event": body["events"][0] if body["events"] else None,
        "heartbeat_at": _iso(run.heartbeat_at),
    }
    return body


# -- metrics ------------------------------------------------------------------


def embedding_budget_usage() -> dict[str, Any]:
    """The persistent embedding counters, read without opening the provider.

    The numbers live in ``data/embedding_cache.sqlite`` (the file the
    providers already own). A read-only connection keeps the health endpoint
    from creating the database or taking a write lock.
    """
    from src.config.settings import get_settings
    from src.security.limits import get_limits

    settings = get_settings()
    limits = get_limits()
    path = Path(settings.data_dir) / "embedding_cache.sqlite"
    day = datetime.now(UTC).date().isoformat()
    usage: dict[str, Any] = {
        "documents_today": 0,
        "documents_limit": limits.max_embed_work_per_day,
        "requests_today": 0,
        "requests_limit": settings.embedding_rpd_limit,
        "cache_entries": 0,
        "cache_limit": limits.max_cache_entries,
    }
    if not path.exists():
        return usage
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT count FROM embed_work WHERE day = ?", (day,)
            ).fetchone()
            usage["documents_today"] = int(row[0]) if row else 0
            row = connection.execute(
                "SELECT count FROM api_requests WHERE day = ?", (day,)
            ).fetchone()
            usage["requests_today"] = int(row[0]) if row else 0
            row = connection.execute("SELECT count(*) FROM embeddings").fetchone()
            usage["cache_entries"] = int(row[0]) if row else 0
        finally:
            connection.close()
    except Exception:
        logger.debug("Embedding budget usage unavailable", exc_info=True)
    return usage


def queue_metrics(db: Session) -> dict[str, Any]:
    """Queue, worker, breaker and embedding metrics for the administrator.

    Counts only: no listing text, no candidate data, no credential.
    """
    from src.llm.resilience import breaker_snapshot

    corpus = int(db.execute(select(func.count()).select_from(JobDB)).scalar() or 0)
    return {
        "queue": queue.queue_stats(db),
        "workers": queue.worker_health(db),
        "breakers": breaker_snapshot(),
        "embedding": {
            "corpus": corpus,
            "budget": embedding_budget_usage(),
            "runs": {
                "active": int(
                    db.execute(
                        select(func.count())
                        .select_from(JobRunDB)
                        .where(JobRunDB.status.in_(tuple(ACTIVE_RUN_STATUSES)))
                    ).scalar()
                    or 0
                ),
                "recoverable": int(
                    db.execute(
                        select(func.count())
                        .select_from(JobRunDB)
                        .where(JobRunDB.status == "RECOVERABLE")
                    ).scalar()
                    or 0
                ),
            },
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
