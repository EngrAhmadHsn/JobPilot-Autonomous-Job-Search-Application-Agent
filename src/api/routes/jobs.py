"""Job search and match API (WS-04).

``POST /api/jobs/search`` loads a stored profile, runs the full search→rank
pipeline (``src.graph.job_executor.run_job_search``), persists one
``job_matches`` row per returned result, and responds with the ranked
( job, match ) pairs, per-source errors, and pipeline stats. ``GET
/api/jobs/{id}`` returns a stored listing; ``GET
/api/profiles/{id}/matches`` returns persisted match history.

The executor is exposed as a FastAPI dependency so tests (and later
deployments) can override it without touching the route logic. The route is
synchronous on purpose: the pipeline's nodes use ``asyncio.run`` internally,
which requires a thread without a running event loop (FastAPI runs sync
endpoints in a threadpool).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.db.jobs import JobDB, listing_from_row
from src.db.matches import JobMatchDB, build_match_rows, match_row_to_dict
from src.db.profiles import CandidateProfileDB, profile_from_row
from src.db.session import get_db
from src.graph.job_executor import JobSearchReport, JobSearchStats, run_job_search
from src.graph.job_state import JobMatchPair

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
profiles_router = APIRouter(prefix="/api/profiles", tags=["profiles"])


class JobSearchRequest(BaseModel):
    """Request body for a full pipeline job search."""

    profile_id: str = Field(..., description="Id returned by POST /api/resumes")
    query: str | None = Field(None, description="Optional explicit search query")
    location: str | None = Field(None, description="Optional location filter")
    top_n: int = Field(10, ge=1, description="Size of the ranked slice (clamped server-side)")


class JobSearchResponse(BaseModel):
    """Ranked matches plus pipeline outcome details."""

    profile_id: str
    results: list[JobMatchPair]
    source_errors: dict[str, str] = Field(default_factory=dict)
    stats: JobSearchStats
    degraded: bool = False


class MatchesHistoryResponse(BaseModel):
    """Persisted matches for one profile (history across searches)."""

    profile_id: str
    matches: list[dict]


def get_job_search_executor() -> Callable[..., JobSearchReport]:
    """Dependency seam for the search executor (tests override this)."""
    return run_job_search


@router.post("/search", response_model=JobSearchResponse)
def search_jobs(
    req: JobSearchRequest,
    db: Annotated[Session, Depends(get_db)],
    executor: Annotated[Callable[..., JobSearchReport], Depends(get_job_search_executor)],
) -> JobSearchResponse:
    """Run the full pipeline for one stored profile and persist the matches.

    A failing job source degrades the report, not the request: the response
    is HTTP 200 with ``source_errors`` populated (plan §35). Match rows are
    persisted for the returned results so history survives restarts.
    """
    profile_row = db.get(CandidateProfileDB, req.profile_id)
    if profile_row is None:
        raise HTTPException(status_code=404, detail=f"Profile {req.profile_id!r} not found")
    profile = profile_from_row(profile_row)

    # SEC-13 audit hook (ids/counts only, never PII).
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
        db.add_all(build_match_rows(req.profile_id, report.results))
        db.commit()

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
def get_job(job_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Return one stored job listing (canonical ``{source}:{id}`` key)."""
    row = db.get(JobDB, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return {"job": listing_from_row(row)}


@profiles_router.get("/{profile_id}/matches", response_model=MatchesHistoryResponse)
def get_profile_matches(
    profile_id: str, db: Annotated[Session, Depends(get_db)]
) -> MatchesHistoryResponse:
    """Persisted match history for one profile, oldest first."""
    if db.get(CandidateProfileDB, profile_id) is None:
        raise HTTPException(status_code=404, detail=f"Profile {profile_id!r} not found")
    rows = (
        db.query(JobMatchDB)
        .filter(JobMatchDB.profile_id == profile_id)
        .order_by(JobMatchDB.id)
        .all()
    )
    return MatchesHistoryResponse(
        profile_id=profile_id, matches=[match_row_to_dict(row) for row in rows]
    )
