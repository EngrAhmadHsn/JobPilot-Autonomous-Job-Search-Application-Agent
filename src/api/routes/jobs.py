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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
from src.matching.sponsors import (
    attach_sponsor_status,
    sponsor_fields_for_jobs,
)
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
    only_embedded: bool = Field(
        False,
        description=(
            "WS-20: return only listings with a verified vector. Off by default — a "
            "pending listing stays visible (it may still match lexically) but earns no "
            "semantic credit."
        ),
    )


class JobSearchResponse(BaseModel):
    """Ranked matches plus pipeline outcome details."""

    profile_id: str
    results: list[JobMatchPair]
    source_errors: dict[str, str] = Field(default_factory=dict)
    stats: JobSearchStats
    degraded: bool = False
    #: WS-20: share of the considered listings that had a real semantic vector.
    semantic_coverage: float = 100.0


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


class JobSuggestion(BaseModel):
    """One autocomplete suggestion for the query field (WS-20 follow-up)."""

    value: str = Field(..., description="A job title the corpus holds")
    count: int = Field(..., description="How many stored listings carry it")


class JobSuggestResponse(BaseModel):
    """Query suggestions drawn from the corpus's own titles."""

    query: str
    suggestions: list[JobSuggestion] = Field(default_factory=list)


def get_job_search_executor(
    db: Annotated[Session, Depends(get_db)],
) -> Callable[..., JobSearchReport]:
    """Dependency seam for the store-only search executor (tests override this).

    The default executor is bound to the request-scoped database (the same
    engine ``get_db`` injected), so searches always read the DB the API serves
    — never an ambient SessionLocal.
    """
    from sqlalchemy.orm import sessionmaker

    def execute(profile, query, location, top_n, *, only_embedded=False) -> JobSearchReport:
        factory = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
        return search_stored_jobs(
            profile, query, location, top_n, only_embedded=only_embedded, session_factory=factory
        )

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

    report = executor(profile, req.query, req.location, req.top_n, only_embedded=req.only_embedded)

    # WS-22: attach the verified sponsorship finding (one batched lookup over
    # the imported registers). It is evidence for the operator, never a score
    # — the engine's own numbers are untouched.
    attach_sponsor_status(
        db,
        [pair.match for pair in report.results],
        [pair.job.company for pair in report.results],
    )

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
        semantic_coverage=report.semantic_coverage,
    )


@router.get("/suggest", response_model=JobSuggestResponse)
def suggest_job_queries(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
    q: str = "",
    limit: int = 10,
) -> JobSuggestResponse:
    """Autocomplete the query field from the titles the corpus actually holds.

    The suggestions are **titles from the stored corpus**, not a static list:
    the search's filter matches any token of the query against a listing's
    title and description, so a suggested title is guaranteed to be a
    meaningful query. They are ranked by how many listings carry the title, so
    the most common roles come first, and then alphabetically for a stable
    order across calls.

    ``q`` narrows the suggestions (a case-insensitive substring); an empty
    ``q`` returns the corpus's most common titles, which is a useful "what is
    in here" starting point. The corpus is shared board data, so no owner
    filter applies.
    """
    bounded = max(1, min(int(limit), 20))
    statement = (
        # ``select(JobDB)`` (not ``select(JobDB.title, …)``): the shared corpus
        # is named as the model, so the route/isolation AST check can see that
        # this reads ``jobs`` and not a user-scoped table.
        select(JobDB)
        .with_only_columns(JobDB.title, func.count().label("listings"))
        .where(JobDB.title.isnot(None))
        .group_by(JobDB.title)
        .order_by(func.count().desc(), JobDB.title.asc())
        .limit(200)
    )
    needle = q.strip().lower()
    if needle:
        statement = statement.where(func.lower(JobDB.title).contains(needle))
    rows = db.execute(statement).all()
    suggestions = [
        JobSuggestion(value=str(title), count=int(count))
        for title, count in rows[:bounded]
        if title
    ]
    return JobSuggestResponse(query=q, suggestions=suggestions)


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
    ranked: Annotated[
        bool,
        Query(
            description=(
                "WS-21: return the most recent match per job, ordered by "
                "overall score (the Tailor picker's relevance order) and "
                "limited after deduplication."
            )
        ),
    ] = False,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
) -> MatchesHistoryResponse:
    """Persisted matches for one profile.

    Default: the account's match **history** (one row per search), newest
    first. With ``ranked=true``: the most recent match of each job, best
    overall score first, limited after deduplication — relevance, not a
    trail.
    """
    if access.get_profile(db, scope, profile_id) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if ranked:
        rows = access.list_ranked_job_matches(db, scope, profile_id, limit=limit or 25)
    else:
        rows = access.list_job_matches(db, scope, profile_id)

    # WS-22: the persisted rows carry scores and the explanation, not the
    # company, so the sponsorship finding is computed from the shared corpus
    # and the register (see src.matching.sponsors) and added to the response.
    fields = sponsor_fields_for_jobs(db, [row.job_id for row in rows])
    matches = []
    for row in rows:
        serialized = match_row_to_dict(row)
        # Every requested id is present in `fields` (see the helper).
        status, note = fields[row.job_id]
        serialized["sponsor_status"] = status
        serialized["sponsor_note"] = note
        matches.append(serialized)
    return MatchesHistoryResponse(profile_id=profile_id, matches=matches)
