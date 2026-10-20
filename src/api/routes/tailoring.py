"""Tailoring API (WS-05).

``POST /api/tailor`` runs the full pipeline for one stored profile and one
stored job: grounded research, tailored content, factuality validation, a
rendered DOCX and the ATS report. The result is persisted so it can be served
again after a restart.

``GET /api/tailored/{id}`` returns a stored tailoring record.

A factuality failure is **not** an error: the stripped-safe content plus the
violations *is* the product, so the endpoint answers 200 with the report.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.db.jobs import JobDB, listing_from_row
from src.db.profiles import CandidateProfileDB, profile_from_row
from src.db.session import get_db
from src.db.tailored import TailoredResumeDB, build_tailored_row, stored_from_row
from src.llm.client import LLMError
from src.research.engine import JobInsights
from src.resume.ats import AtsReport
from src.resume.pipeline import run_tailoring
from src.resume.tailor import FactualityReport, GenerateFn, TailoredResume

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tailoring"])


class TailorRequest(BaseModel):
    """Request body for a tailoring run."""

    profile_id: str = Field(..., description="Id returned by POST /api/resumes")
    job_id: str = Field(..., description="Canonical job id (source:id)")


class TailorResponse(BaseModel):
    """The tailoring result, its reports and the rendered file path."""

    tailoring_id: str
    profile_id: str
    job_id: str
    tailored: TailoredResume
    factuality: FactualityReport
    ats_report: AtsReport
    insights: JobInsights
    docx_path: str


class StoredTailoringResponse(TailorResponse):
    """A stored tailoring record (adds the creation time)."""

    created_at: str


def get_generate_fn() -> GenerateFn | None:
    """Dependency seam for the structured-generation call.

    The default is ``None``, which makes the pipeline use the configured LLM
    client. Tests (and future deployments) override this dependency to inject
    a deterministic generator without touching the route logic.
    """
    return None


@router.post("/tailor", response_model=TailorResponse)
def tailor_resume_endpoint(
    req: TailorRequest,
    db: Annotated[Session, Depends(get_db)],
    generate: Annotated[GenerateFn | None, Depends(get_generate_fn)],
) -> TailorResponse:
    """Tailor a resume for one job, render it and report on it.

    Returns 404 when the profile or the job is unknown, and 503 when the
    language model is unavailable. A factuality violation is reported inside
    the 200 response, never as an error.
    """
    profile_row = db.get(CandidateProfileDB, req.profile_id)
    if profile_row is None:
        raise HTTPException(status_code=404, detail=f"Profile {req.profile_id!r} not found")
    job_row = db.get(JobDB, req.job_id)
    if job_row is None:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id!r} not found")

    profile = profile_from_row(profile_row)
    job = listing_from_row(job_row)

    # SEC-13 audit hook (ids only, never the resume text).
    logger.info("Tailoring requested", extra={"profile_id": req.profile_id, "job_id": req.job_id})

    try:
        outcome = run_tailoring(
            profile,
            job,
            generate=generate,
            profile_id=req.profile_id,
            job_id=req.job_id,
        )
    except LLMError as exc:
        # The message never carries request content or the API key.
        logger.warning("Tailoring failed: LLM unavailable (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=503, detail="The language model is unavailable; try again later."
        ) from exc

    row = build_tailored_row(
        profile_id=req.profile_id,
        job_id=req.job_id,
        tailored=outcome.tailored,
        factuality=outcome.factuality,
        ats_report=outcome.ats_report,
        insights=outcome.insights,
        docx_path=outcome.docx_path,
    )
    db.add(row)
    db.commit()

    logger.info(
        "Tailoring complete",
        extra={
            "tailoring_id": row.id,
            "factuality_passed": outcome.factuality.passed,
            "ats_score": outcome.ats_report.score,
        },
    )
    return TailorResponse(
        tailoring_id=row.id,
        profile_id=row.profile_id,
        job_id=row.job_id,
        tailored=outcome.tailored,
        factuality=outcome.factuality,
        ats_report=outcome.ats_report,
        insights=outcome.insights,
        docx_path=outcome.docx_path,
    )


@router.get("/tailored/{tailoring_id}", response_model=StoredTailoringResponse)
def get_tailored(
    tailoring_id: str, db: Annotated[Session, Depends(get_db)]
) -> StoredTailoringResponse:
    """Return one stored tailoring record with its reports and file path."""
    row = db.get(TailoredResumeDB, tailoring_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Tailoring {tailoring_id!r} not found")
    stored = stored_from_row(row)
    return StoredTailoringResponse(
        tailoring_id=stored.tailoring_id,
        profile_id=stored.profile_id,
        job_id=stored.job_id,
        tailored=stored.tailored,
        factuality=stored.factuality,
        ats_report=stored.ats_report,
        insights=stored.insights or JobInsights(),
        docx_path=stored.docx_path,
        created_at=stored.created_at.isoformat(),
    )
