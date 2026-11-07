"""The platform overview, read by a platform administrator (WS-17).

One endpoint: ``GET /api/admin/overview`` returns platform-wide aggregates —
how many accounts exist, how the applications are distributed across their
statuses, how the audit trail splits by outcome and by actor, and how large
the shared job corpus is.

**Why this is a superuser route, and why that is the whole control.**
WS-14 makes every other read tenant-scoped: a caller sees their own rows and
nothing else, and :mod:`src.db.access` is the only way a route reaches a
user-scoped table. This route is the one deliberate exception — the
platform's own view across owners — and it is safe for exactly one reason:
the scope it queries with is built from the **authenticated principal's**
``is_superuser`` flag, and a principal that is not a superuser is refused
with a 403 **before any query runs**. There is no header, query parameter
or body field that can widen the scope (WS-14 · R2), so there is no way to
ask for this view without the flag on the account.

The aggregates go through :mod:`src.db.access`, not through direct queries,
for the same reason every other route does: the isolation matrix greps the
route sources and fails if a route queries an owner-scoped table directly,
which is what keeps this exception from spreading.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.config.settings import get_settings
from src.db import access
from src.db.applications import ApplicationDB
from src.db.audit import AuditEventDB
from src.db.session import get_db
from src.runs import queue as run_queue
from src.runs import service as run_service
from src.runs import supervisor as worker_supervisor
from src.runs.embedding import JOB_TYPE_EMBEDDING
from src.security.audit import (
    ACTION_WORKER_START,
    ACTION_WORKER_STOP,
    OUTCOME_SUCCESS,
    record_audit,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_superuser(
    scope: Annotated[UserScope, Depends(current_scope)],
) -> UserScope:
    """Refuse anyone who is not a platform administrator.

    It depends on :func:`src.api.scope.current_scope`, so a request with no
    credential is refused with a 401 before this runs, and the answer comes
    from the session's own ``is_superuser`` flag — never from the request.
    """
    if not scope.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administration is available to platform administrators only.",
        )
    return scope


@router.get("/overview")
def read_overview(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(require_superuser)],
) -> dict:
    """Platform-wide counts, for the administration screen.

    Every figure is a live count over the platform's own tables. Nothing is
    cached, sampled or estimated: an administrator looking at this screen is
    looking at the database.
    """
    return {
        "accounts": {
            "total": access.count_users(db),
            "active": access.count_users(db, active=True),
            "superusers": access.count_users(db, superuser=True),
        },
        "applications": {
            "total": access.count_owned(db, scope, ApplicationDB),
            "by_status": access.group_owned(db, scope, ApplicationDB, ApplicationDB.status),
        },
        "workflows": {
            "total": access.count_distinct_owned(
                db, scope, ApplicationDB, ApplicationDB.workflow_id
            ),
        },
        "audit": {
            "total": access.count_owned(db, scope, AuditEventDB),
            "by_outcome": access.group_owned(db, scope, AuditEventDB, AuditEventDB.outcome),
            "by_actor_kind": access.group_owned(db, scope, AuditEventDB, AuditEventDB.actor_kind),
        },
        "corpus": {"jobs": access.count_jobs(db)},
        "generated_at": datetime.now(UTC).isoformat(),
    }


# -- WS-18: background execution ---------------------------------------------


class AdminRunsResponse(BaseModel):
    """Platform-level embedding executions."""

    runs: list[dict]
    count: int


class AdminRunDetailResponse(BaseModel):
    """One execution, with its checkpoints and item summary."""

    run: dict


class ResumeRunRequest(BaseModel):
    """The resume body.

    Deliberately empty: the administrator's identity comes from the session,
    and the model/dimension are validated against the server's own
    configuration. A request field that could name another principal, a
    different embedding space, or a larger budget would be a bypass.
    """


class RunActionResponse(BaseModel):
    """The answer to a recovery or cancellation request."""

    run_id: str
    status: str
    job_type: str
    queued: bool = True


def _current_embedding_identity() -> tuple[str, int]:
    """The configured provider's identity, for the resume check.

    Constructing the provider does not load model weights (both providers
    are lazy); it only reads the identity the vectors would be written with.
    """
    settings = get_settings()
    try:
        from src.llm.embeddings import build_embedding_fn

        embedding = build_embedding_fn(settings)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The configured embedding provider could not be constructed, so a "
                f"recovery cannot be validated: {type(exc).__name__}: {exc}"
            ),
        ) from exc
    return (
        str(getattr(embedding, "model", settings.embedding_model)),
        int(getattr(embedding, "dimensionality", settings.embedding_dimensionality)),
    )


@router.get("/embedding-runs", response_model=AdminRunsResponse)
def list_embedding_runs(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(require_superuser)],
    run_status: str | None = Query(None, alias="status"),
    limit: int = 50,
) -> AdminRunsResponse:
    """The platform's embedding executions, newest first.

    This is the screen an administrator opens after an interruption: it shows
    recoverable runs, paused runs, permanent failures and healthy history.
    """
    statuses = [run_status] if run_status else None
    runs = access.list_runs(
        db,
        scope,
        job_type=JOB_TYPE_EMBEDDING,
        statuses=statuses,
        limit=limit,
    )
    return AdminRunsResponse(runs=[run_service.run_to_dict(run) for run in runs], count=len(runs))


@router.get("/runs", response_model=AdminRunsResponse)
def list_all_runs(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(require_superuser)],
    job_type: str | None = None,
    run_status: str | None = Query(None, alias="status"),
    limit: int = 50,
) -> AdminRunsResponse:
    """Every durable run on the platform, newest first.

    The embedding-runs listing above is the recovery surface for one kind of
    work; this one is the platform's whole queue, which is what an operator
    needs when a refresh, a reconciliation and an embedding pass are all in
    flight — or when a queued run is not moving because no worker is running.

    Filters are optional and applied by the data layer, not by the route.
    """
    runs = access.list_runs(
        db,
        scope,
        job_type=job_type,
        statuses=[run_status] if run_status else None,
        limit=limit,
    )
    return AdminRunsResponse(runs=[run_service.run_to_dict(run) for run in runs], count=len(runs))


@router.get("/runs/{run_id}", response_model=AdminRunDetailResponse)
def read_any_run(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(require_superuser)],
) -> AdminRunDetailResponse:
    """One run of any type, with its checkpoint, counters and events."""
    run = access.get_run(db, scope, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return AdminRunDetailResponse(run=run_service.run_detail(db, run))


@router.get("/embedding-runs/{run_id}", response_model=AdminRunDetailResponse)
def read_embedding_run(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(require_superuser)],
) -> AdminRunDetailResponse:
    """One embedding run: progress, checkpoint, quota reason and failures."""
    run = access.get_run(db, scope, run_id)
    if run is None or run.job_type != JOB_TYPE_EMBEDDING:
        raise HTTPException(status_code=404, detail=f"Embedding run {run_id!r} not found")
    return AdminRunDetailResponse(run=run_service.run_detail(db, run))


@router.post(
    "/embedding-runs/{run_id}/resume",
    response_model=RunActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_embedding_run(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(require_superuser)],
    _body: ResumeRunRequest | None = None,
) -> RunActionResponse:
    """Resume the **outstanding** work of an interrupted embedding run.

    The administrator's identity is the authenticated principal (never a
    request field), the run must be in a resumable state, the embedding model
    and dimension must match the current provider, completed work is never
    requeued, and a concurrent resume loses the conditional update. The
    action is audited and returns the same durable run id.
    """
    model, dimension = _current_embedding_identity()
    try:
        resumed = run_service.resume_embedding_run(
            db,
            scope,
            run_id,
            expected_model=model,
            expected_dimension=dimension,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except run_queue.RunAlreadyResumed as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except run_queue.IllegalTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RunActionResponse(
        run_id=resumed.id,
        status=resumed.status,
        job_type=resumed.job_type,
        queued=resumed.status == "QUEUED",
    )


@router.post("/embedding-runs/{run_id}/cancel", response_model=RunActionResponse)
def cancel_embedding_run(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(require_superuser)],
) -> RunActionResponse:
    """Stop a run without deleting its history (safe cancellation)."""
    run = access.get_run(db, scope, run_id)
    if run is None or run.job_type != JOB_TYPE_EMBEDDING:
        raise HTTPException(status_code=404, detail=f"Embedding run {run_id!r} not found")
    try:
        cancelled = run_service.cancel_run(db, scope, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except run_queue.IllegalTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RunActionResponse(
        run_id=cancelled.id,
        status=cancelled.status,
        job_type=cancelled.job_type,
        queued=False,
    )


@router.post(
    "/embeddings/reconcile",
    response_model=RunActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reconcile_embeddings(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(require_superuser)],
) -> RunActionResponse:
    """Enqueue a reconciliation of the SQL corpus against the vector index.

    The worker detects missing/stale vectors, orphan vectors, interrupted
    items and inconsistent completion flags, repairs what it can safely
    repair, and records the counts on the run. It never rebuilds completed
    work unnecessarily.
    """
    try:
        run, created = run_service.enqueue_reconcile(db, scope)
    except run_queue.QueueFull as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    return RunActionResponse(
        run_id=run.id,
        status=run.status,
        job_type=run.job_type,
        queued=created,
    )


@router.get("/jobs/metrics")
def read_job_metrics(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(require_superuser)],
) -> dict:
    """Queue, worker, breaker and embedding-budget metrics.

    The numbers the brief asks an operator to be able to see: pending and
    running work, stale leases, retry backlog, the oldest pending item's age,
    worker heartbeat age, breaker states, and today's embedding spend.
    """
    return run_service.queue_metrics(db)


class WorkerStartRequest(BaseModel):
    """Optional shape for starting a worker."""

    worker_id: str | None = None


class WorkerActionResponse(BaseModel):
    """The result of starting or stopping a worker."""

    worker_id: str
    status: str
    pid: int | None = None
    detail: str = ""


@router.get("/health/workers")
def read_worker_health(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(require_superuser)],
) -> dict:
    """Whether a background worker is alive, and how to manage one.

    A process that answers HTTP requests says nothing about whether any
    worker is draining the queue, so this reads the heartbeats directly. It
    also reports whether this deployment lets the console start and stop
    workers, and how many it may run at once, so the screen can show the
    bound rather than hide it.
    """
    health = run_queue.worker_health(db)
    spawned = {handle.worker_id: handle for handle in worker_supervisor.spawned_workers()}
    for worker in health["workers"]:
        handle = spawned.get(worker["worker_id"])
        worker["spawned_by_api"] = handle is not None
        # Only a worker that is actually alive can be stopped meaningfully;
        # a stale row is one that is already gone.
        worker["stoppable"] = worker["healthy"]
    settings = get_settings()
    return {
        "workers": health,
        "queue": run_queue.queue_stats(db),
        "control": {
            "enabled": settings.worker_control_enabled,
            "max_concurrent": settings.worker_max_concurrent,
        },
    }


@router.post("/workers", response_model=WorkerActionResponse, status_code=status.HTTP_202_ACCEPTED)
def start_worker(
    scope: Annotated[UserScope, Depends(require_superuser)],
    body: WorkerStartRequest | None = None,
) -> WorkerActionResponse:
    """Start one background worker process, within the configured bound.

    The command is fixed (the application's own worker module) and the worker
    id is a label, not input. Starting is refused when the deployment has not
    enabled it, and when the maximum number of workers is already running. An
    administrator sees the bound on the screen; the server enforces it here.
    """
    try:
        handle = worker_supervisor.start_worker(worker_id=body.worker_id if body else None)
    except worker_supervisor.WorkerControlDisabled as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except worker_supervisor.WorkerLimitReached as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    record_audit(
        ACTION_WORKER_START,
        actor=scope.user_id,
        resource=handle.worker_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=scope.user_id,
        metadata={"worker_id": handle.worker_id, "pid": handle.pid},
    )
    return WorkerActionResponse(
        worker_id=handle.worker_id, status="starting", pid=handle.pid, detail="Worker starting"
    )


@router.post("/workers/{worker_id}/stop", response_model=WorkerActionResponse)
def stop_worker(
    worker_id: str,
    scope: Annotated[UserScope, Depends(require_superuser)],
) -> WorkerActionResponse:
    """Ask a running worker to finish its current batch and exit.

    The request is **cooperative**: it is written to the worker's heartbeat
    row and the worker acts on it, so a worker this API did not start (or no
    longer remembers) is stopped the same way. Nothing is signalled, and in-
    flight work is completed before the worker leaves.
    """
    try:
        changed = worker_supervisor.stop_worker(worker_id=worker_id)
    except worker_supervisor.WorkerControlDisabled as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No running worker {worker_id!r} to stop",
        )

    record_audit(
        ACTION_WORKER_STOP,
        actor=scope.user_id,
        resource=worker_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=scope.user_id,
        metadata={"worker_id": worker_id},
    )
    return WorkerActionResponse(
        worker_id=worker_id, status="stopping", detail="Worker will stop after the current batch"
    )
