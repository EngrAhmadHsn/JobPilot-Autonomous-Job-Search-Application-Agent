"""Job search and match API (WS-04 + FU-1).

``POST /api/jobs/search`` is **store-only** (FU-1): it loads a stored profile,
matches it against the persisted job corpus (``search_stored_jobs`` — zero
board fetches, one query-embedding request), persists one ``job_matches`` row
per returned result, and responds with the ranked ( job, match ) pairs and
stats. ``POST /api/jobs/refresh`` runs the decoupled daily refresh (fetch
boards → normalize → dedup → persist → embed new/changed texts); cron/Task
Scheduler should prefer the ``scripts/refresh_jobs.py`` CLI wrapper, which is
the same call without HTTP timeout concerns. ``GET /api/jobs/{id}`` returns a
stored listing; ``GET /api/profiles/{id}/matches`` returns persisted match
history.

Executors are exposed as FastAPI dependencies so tests (and later
deployments) can override them without touching the route logic. Routes are
synchronous on purpose: pipeline internals use ``asyncio.run``, which
requires a thread without a running event loop (FastAPI runs sync endpoints
in a threadpool).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.db import access
from src.db.jobs import JobDB, listing_from_row
from src.db.matches import build_match_rows, match_row_to_dict
from src.db.profiles import profile_from_row
from src.db.session import get_db
from src.graph.job_executor import (
    JobSearchReport,
    JobSearchStats,
    search_stored_jobs,
)
from src.graph.job_state import JobMatchPair
from src.runs import queue as run_queue
from src.runs import service as run_service
from src.security.audit import (
    ACTION_JOB_SEARCH,
    ACTION_MATCH_COMPUTE,
    OUTCOME_SUCCESS,
    SYSTEM_ACTOR,
    record_audit,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
profiles_router = APIRouter(prefix="/api/profiles", tags=["profiles"])
runs_router = APIRouter(prefix="/api/runs", tags=["runs"])


class JobSearchRequest(BaseModel):
    """Request body for a store-only job search (FU-1)."""

    profile_id: str = Field(..., description="Id returned by POST /api/resumes")
    query: str | None = Field(
        None, description="Optional client-side corpus filter (ANY token in title+description)"
    )
    location: str | None = Field(
        None, description="Optional case-insensitive location substring filter"
    )
    top_n: int = Field(10, ge=1, description="Size of the ranked slice (clamped server-side)")


class JobSearchResponse(BaseModel):
    """Ranked matches plus pipeline outcome details."""

    profile_id: str
    results: list[JobMatchPair]
    source_errors: dict[str, str] = Field(default_factory=dict)
    stats: JobSearchStats
    degraded: bool = False


class RunAcceptedResponse(BaseModel):
    """A durable run the API has accepted (WS-18).

    This is the refresh contract now: ``202 Accepted`` and a persistent id.
    The caller polls ``GET /api/runs/{run_id}`` (or the administration
    endpoints) for the actual state. ``existing`` is true when an active
    refresh was already queued and this request joined it instead of
    starting a second one.
    """

    run_id: str
    status: str
    job_type: str
    correlation_id: str
    created_at: datetime
    existing: bool = False


class RunsListResponse(BaseModel):
    """The caller's own execution history."""

    runs: list[dict]
    count: int


class RunDetailResponse(BaseModel):
    """One run, with its checkpoints and item summary."""

    run: dict


class MatchesHistoryResponse(BaseModel):
    """Persisted matches for one profile (history across searches)."""

    profile_id: str
    matches: list[dict]


def get_job_search_executor(
    db: Annotated[Session, Depends(get_db)],
) -> Callable[..., JobSearchReport]:
    """Dependency seam for the store-only search executor (tests override this).

    The default executor is bound to the request-scoped database (the same
    engine ``get_db`` injected), so searches always read the DB the API serves
    — never an ambient SessionLocal.
    """
    from sqlalchemy.orm import sessionmaker

    def execute(profile, query, location, top_n) -> JobSearchReport:
        factory = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
        return search_stored_jobs(profile, query, location, top_n, session_factory=factory)

    return execute


@router.post(
    "/refresh",
    response_model=RunAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_jobs_endpoint(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> RunAcceptedResponse:
    """Accept a corpus refresh as **durable background work** (WS-18).

    The request no longer performs the refresh. It writes a ``job_runs`` row
    and responds ``202`` with that row's id, so closing the browser, losing
    the connection, or restarting the API cannot lose the accepted work. The
    separate worker executes it; ``GET /api/runs/{run_id}`` reports progress
    from persistent state.

    A refresh that is already queued or running is returned instead of
    duplicated: two clicks are one refresh.

    WS-15: this route needs a credential. It is the most expensive
    operation in the system, and the queue (not the request) now bounds it.
    """
    try:
        run, created = run_service.enqueue_refresh(db, scope)
    except run_queue.QueueFull as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    logger.info(
        "Job refresh enqueued",
        extra={
            "run_id": run.id,
            "correlation_id": run.correlation_id,
            "newly_created": created,
            "actor": scope.user_id,
        },
    )
    return RunAcceptedResponse(
        run_id=run.id,
        status=run.status,
        job_type=run.job_type,
        correlation_id=run.correlation_id,
        created_at=run.created_at,
        existing=not created,
    )


@runs_router.get("", response_model=RunsListResponse)
def list_runs(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
    limit: int = 25,
) -> RunsListResponse:
    """The caller's own execution history (newest first).

    An ordinary account sees the runs it requested; an administrator sees
    every run, including the platform's. A platform run has no owner, so it
    is never returned to an ordinary caller.
    """
    runs = run_service.list_runs_for_scope(db, scope, limit=limit)
    return RunsListResponse(runs=[run_service.run_to_dict(run) for run in runs], count=len(runs))


@runs_router.get("/{run_id}", response_model=RunDetailResponse)
def get_run(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> RunDetailResponse:
    """One run's persistent state, checkpoints and item summary.

    A foreign run and a missing one answer the same 404, so the route is not
    an existence oracle.
    """
    run = run_service.get_run_for_scope(db, scope, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return RunDetailResponse(run=run_service.run_detail(db, run))


@router.post("/search", response_model=JobSearchResponse)
def search_jobs(
    req: JobSearchRequest,
    db: Annotated[Session, Depends(get_db)],
    executor: Annotated[Callable[..., JobSearchReport], Depends(get_job_search_executor)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> JobSearchResponse:
    """Match one stored profile against the persisted corpus (store-only, FU-1).

    Zero board fetches: listings come from the ``jobs`` table, semantics from
    the vector store (one query-embedding request for the candidate text).
    Match rows are persisted for the returned results so history survives
    restarts. Listings without vectors yet (backfill in flight) score without
    semantics and flip ``degraded``.
    """
    profile_row = access.get_profile(db, scope, req.profile_id)
    if profile_row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile = profile_from_row(profile_row)

    # SEC-13 audit event (ids/counts only, never PII).
    logger.info(
        "Job search requested",
        extra={
            "profile_id": req.profile_id,
            "has_query": bool(req.query),
            "has_location": bool(req.location),
            "top_n": req.top_n,
        },
    )

    report = executor(profile, req.query, req.location, req.top_n)

    if report.results:
        db.add_all(build_match_rows(req.profile_id, report.results, owner_id=scope.user_id))
        db.commit()

    record_audit(
        ACTION_JOB_SEARCH,
        actor=SYSTEM_ACTOR,
        resource=req.profile_id,
        outcome=OUTCOME_SUCCESS,
        metadata={
            "returned": len(report.results),
            "degraded": report.degraded,
            "has_query": bool(req.query),
            "has_location": bool(req.location),
            "failed_sources": sorted(report.source_errors),
        },
    )
    record_audit(
        ACTION_MATCH_COMPUTE,
        actor=SYSTEM_ACTOR,
        resource=req.profile_id,
        outcome=OUTCOME_SUCCESS,
        metadata={"matches": len(report.results), "degraded": report.degraded},
    )

    logger.info(
        "Job search complete",
        extra={
            "profile_id": req.profile_id,
            "returned": len(report.results),
            "failed_sources": sorted(report.source_errors),
            "degraded": report.degraded,
        },
    )
    return JobSearchResponse(
        profile_id=req.profile_id,
        results=report.results,
        source_errors=report.source_errors,
        stats=report.stats,
        degraded=report.degraded,
    )


@router.get("/{job_id}")
def get_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> dict:
    """Return one stored job listing (canonical ``{source}:{id}`` key).

    WS-15: this route needs a credential like every other reading route.
    The corpus is shared (the listings are public board data, so there is
    no tenant to filter on), but an open read of the whole corpus is an
    open enumeration of it, and the route was the only one left that
    answered without asking who was asking.
    """
    row = db.get(JobDB, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return {"job": listing_from_row(row)}


@profiles_router.get("/{profile_id}/matches", response_model=MatchesHistoryResponse)
def get_profile_matches(
    profile_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> MatchesHistoryResponse:
    """Persisted match history for one profile, oldest first."""
    if access.get_profile(db, scope, profile_id) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    rows = access.list_job_matches(db, scope, profile_id)
    return MatchesHistoryResponse(
        profile_id=profile_id, matches=[match_row_to_dict(row) for row in rows]
    )
