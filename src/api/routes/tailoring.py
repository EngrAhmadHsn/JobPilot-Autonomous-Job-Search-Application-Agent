"""Tailoring API (WS-05).

``POST /api/tailor`` runs the full pipeline for one stored profile and one
stored job: grounded research, tailored content, factuality validation, the
deliverable and the ATS report. The result is persisted so it can be served
again after a restart.

The deliverable is the caller's **own uploaded résumé, edited in place**
(WS-31), so its formatting survives; when the original cannot be edited a fresh
document is rendered instead and the response's ``render`` report says which
happened and why.

``GET /api/tailored/{id}`` returns a stored tailoring record, and
``PUT /api/tailored/{id}`` (WS-47) saves the studio's section edits: the
edited content is revalidated against the stored profile with the pipeline's
own factuality validator, the ATS report is re-run, the deliverable is
re-produced through the WS-31 in-place path, and the row is stamped with
``edited_at``.

A factuality failure is **not** an error — in either direction: the
stripped-safe content plus the violations *is* the product, so the endpoint
answers 200 with the report.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.db import access
from src.db.jobs import JobDB, listing_from_row
from src.db.profiles import profile_from_row
from src.db.session import get_db
from src.db.tailored import (
    StoredTailoring,
    build_tailored_row,
    generate_tailoring_id,
    stored_from_row,
)
from src.llm.errors import (
    LLMConfigError,
    LLMCredentialError,
    LLMDailyQuotaExhausted,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMTimeout,
)
from src.research.engine import JobInsights
from src.resume.ats import AtsReport, analyze_ats
from src.resume.edit import RenderReport, deliver_tailored_resume
from src.resume.pipeline import apply_tailored_edit, revalidate_tailored, run_tailoring
from src.resume.style import StyleReport, analyze_tailored
from src.resume.tailor import FactualityReport, GenerateFn, TailoredResume
from src.storage.paths import KIND_TAILORED, user_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tailoring"])


class TailorRequest(BaseModel):
    """Request body for a tailoring run."""

    profile_id: str = Field(..., description="Id returned by POST /api/resumes")
    job_id: str = Field(..., description="Canonical job id (source:id)")


class TailorResponse(BaseModel):
    """The tailoring result, its reports and the path of the deliverable."""

    tailoring_id: str
    profile_id: str
    job_id: str
    tailored: TailoredResume
    factuality: FactualityReport
    ats_report: AtsReport
    #: WS-22: the deterministic style verdict on the delivered content.
    style: StyleReport
    insights: JobInsights
    docx_path: str
    #: WS-31: how the deliverable was produced — the caller's own uploaded
    #: résumé edited in place (``in_place``) or a freshly rendered document
    #: (``regenerated``), with the counts and the reasons.
    render: RenderReport = RenderReport()


class StoredTailoringResponse(TailorResponse):
    """A stored tailoring record (adds the creation time)."""

    created_at: str
    #: WS-47: when the candidate last saved an edit of their own, or ``None``
    #: while the record is still the tailoring run's own output. The console's
    #: status chip reads it ("proposed" vs "edited by you").
    edited_at: str | None = None


#: WS-47: the edit contract's bound for every section. A summary, a bullet
#: set, or a cover letter beyond this length is not an edit, it is a document;
#: the request is refused before any work is done.
MAX_SECTION_CHARS = 8000


class TailoredEditRequest(BaseModel):
    """The sections the studio saves, as plain text (WS-47).

    Every field is optional — the console edits one section at a time — and
    at least one must be present. ``experience`` and ``projects`` are one
    bullet per line; they are re-chunked onto the resume's **existing**
    entries in order, so no entry can be added, removed or renamed by an
    edit (the factuality validator and the in-place editor both rely on that
    identity). A factuality violation is reported in the response and never
    blocks the save.
    """

    summary: str | None = Field(
        default=None,
        max_length=MAX_SECTION_CHARS,
        description="The edited professional summary.",
    )
    experience: str | None = Field(
        default=None,
        max_length=MAX_SECTION_CHARS,
        description="The edited experience bullets, one per line.",
    )
    projects: str | None = Field(
        default=None,
        max_length=MAX_SECTION_CHARS,
        description="The edited project bullets, one per line.",
    )
    cover_letter: str | None = Field(
        default=None,
        max_length=MAX_SECTION_CHARS,
        description="The edited cover letter.",
    )

    @model_validator(mode="after")
    def _at_least_one_section(self) -> TailoredEditRequest:
        """Refuse a body that edits nothing — it would be a no-op save."""
        if (
            self.summary is None
            and self.experience is None
            and self.projects is None
            and self.cover_letter is None
        ):
            raise ValueError(
                "At least one section must be provided: summary, experience, "
                "projects or cover_letter."
            )
        return self


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
    scope: Annotated[UserScope, Depends(current_scope)],
) -> TailorResponse:
    """Tailor a resume for one job, render it and report on it.

    Returns 404 when the profile or the job is unknown, and 503 when the
    language model is unavailable. A factuality violation is reported inside
    the 200 response, never as an error.
    """
    profile_row = access.get_profile(db, scope, req.profile_id)
    if profile_row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    job_row = db.get(JobDB, req.job_id)
    if job_row is None:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id!r} not found")

    profile = profile_from_row(profile_row)
    job = listing_from_row(job_row)

    # SEC-13 audit hook (ids only, never the resume text).
    logger.info("Tailoring requested", extra={"profile_id": req.profile_id, "job_id": req.job_id})

    # Use the same identity for the new row and its file, not the job id:
    # separate runs for the same profile/job must not share a deliverable.
    tailoring_id = generate_tailoring_id()
    try:
        outcome = run_tailoring(
            profile,
            job,
            generate=generate,
            out_dir=user_dir(scope.user_id, KIND_TAILORED),
            profile_id=req.profile_id,
            job_id=req.job_id,
            artifact_id=tailoring_id,
            upload_path=profile_row.file_path,
        )
    except LLMCredentialError as exc:
        logger.warning("Tailoring refused: the caller's model credential is unusable")
        raise HTTPException(
            status_code=409,
            detail=(
                "Your model key is missing or unusable. Add or update it under "
                "Account → Model credentials."
            ),
        ) from exc
    except LLMConfigError as exc:
        # Distinguish repairs without relaying or logging the provider body.
        message = str(exc)
        if message.startswith("LLM_API_KEY is not set"):
            detail = (
                "The language model is not configured: no API key is set. "
                "An operator needs to set LLM_API_KEY (and LLM_PROVIDER). "
                "Retrying will not help."
            )
        elif message.startswith("LLM rejected the API key"):
            detail = (
                "The language model is not configured correctly: the provider "
                "rejected the deployment's API key. An operator needs to check "
                "LLM_API_KEY and LLM_PROVIDER. Retrying will not help."
            )
        else:
            detail = (
                "The language model is not configured correctly. An operator needs "
                "to check the deployment's model settings. Retrying will not help."
            )
        logger.warning("Tailoring refused: the model is misconfigured (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail=detail) from exc
    except LLMError as exc:
        if isinstance(exc, LLMDailyQuotaExhausted):
            detail = (
                "The language model's daily quota is exhausted; try again after the quota resets."
            )
        elif isinstance(exc, LLMRateLimited):
            detail = "The language model is rate-limiting requests; try again later."
        elif isinstance(exc, LLMTimeout):
            detail = "The language model timed out while generating the tailored draft; try again."
        elif isinstance(exc, LLMInvalidOutput):
            detail = "The language model did not return a usable tailored draft; try again."
        else:
            detail = "The language model is unavailable; try again later."
        logger.warning("Tailoring failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail=detail) from exc

    row = build_tailored_row(
        tailoring_id=tailoring_id,
        owner_id=scope.user_id,
        profile_id=req.profile_id,
        job_id=req.job_id,
        tailored=outcome.tailored,
        factuality=outcome.factuality,
        ats_report=outcome.ats_report,
        style=outcome.style,
        insights=outcome.insights,
        render=outcome.render,
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
            "render_mode": outcome.render.mode,
        },
    )
    return TailorResponse(
        tailoring_id=row.id,
        profile_id=row.profile_id,
        job_id=row.job_id,
        tailored=outcome.tailored,
        factuality=outcome.factuality,
        ats_report=outcome.ats_report,
        style=outcome.style,
        insights=outcome.insights,
        render=outcome.render,
        docx_path=outcome.docx_path,
    )


@router.get("/tailored/{tailoring_id}", response_model=StoredTailoringResponse)
def get_tailored(
    tailoring_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> StoredTailoringResponse:
    """Return one stored tailoring record with its reports and file path."""
    row = access.get_tailored(db, scope, tailoring_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Tailoring not found")
    return _stored_response(stored_from_row(row))


def _stored_response(stored: StoredTailoring) -> StoredTailoringResponse:
    """The stored-tailoring shape the GET and the PUT both answer with."""
    return StoredTailoringResponse(
        tailoring_id=stored.tailoring_id,
        profile_id=stored.profile_id,
        job_id=stored.job_id,
        tailored=stored.tailored,
        factuality=stored.factuality,
        ats_report=stored.ats_report,
        style=stored.style,
        insights=stored.insights or JobInsights(),
        render=stored.render,
        docx_path=stored.docx_path,
        created_at=stored.created_at.isoformat(),
        edited_at=stored.edited_at.isoformat() if stored.edited_at else None,
    )


@router.put("/tailored/{tailoring_id}", response_model=StoredTailoringResponse)
def edit_tailored(
    tailoring_id: str,
    req: TailoredEditRequest,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> StoredTailoringResponse:
    """Save the studio's section edits and revalidate everything (WS-47).

    The edit is treated exactly like a generation, minus the model: the
    edited sections are validated against the stored profile (the pipeline's
    own validator — no new claims), the ATS report is re-run, and the
    deliverable is re-produced at the addressed draft's own path. The same
    row is updated and stamped ``edited_at``.

    A factuality violation is **not** an error: the stripped content plus the
    report is the save's result, and the response answers 200 with it. A
    foreign or missing tailoring answers 404; a tailoring whose profile or
    job has since been deleted answers 409 — the edit cannot be validated
    against facts that no longer exist, and re-tailoring is the repair.
    """
    row = access.get_tailored_for_update(db, scope, tailoring_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Tailoring not found")

    profile_row = access.get_profile(db, scope, row.profile_id)
    if profile_row is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "The profile this tailoring was built from no longer exists, so "
                "the edit cannot be validated against it. Re-tailor the resume instead."
            ),
        )
    job_row = db.get(JobDB, row.job_id)
    if job_row is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "The job this tailoring targeted is no longer stored, so the ATS "
                "report cannot be re-run. Re-tailor the resume instead."
            ),
        )

    profile = profile_from_row(profile_row)
    job = listing_from_row(job_row)
    stored = stored_from_row(row)

    logger.info("Tailoring edit received", extra={"tailoring_id": tailoring_id})

    try:
        edited = apply_tailored_edit(
            stored.tailored,
            summary=req.summary,
            experience=req.experience,
            projects=req.projects,
            cover_letter=req.cover_letter,
        )
    except ValueError as exc:
        # A section that has nowhere to go (no entries to re-chunk onto) is a
        # client-contract problem, not a server failure.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    tailored, factuality = revalidate_tailored(edited, profile)

    # Never write through the stored path: a legacy file may be shared with
    # another row. Render from the original upload into this draft's own file.
    path, render = deliver_tailored_resume(
        tailored,
        profile,
        upload_path=profile_row.file_path,
        out_dir=user_dir(scope.user_id, KIND_TAILORED),
        profile_id=row.profile_id,
        job_id=row.job_id,
        artifact_id=row.id,
    )
    ats_report = analyze_ats(tailored, profile, job, docx_path=path)
    style = analyze_tailored(tailored)

    # Persist everything the edit re-produced, stamped as edited. The JSON
    # columns are replaced whole (never mutated in place), which is what
    # marks them dirty under SQLAlchemy.
    edited_at = datetime.now(UTC)
    row.tailored = tailored.model_dump(mode="json")
    row.factuality = factuality.model_dump(mode="json")
    row.ats_report = ats_report.model_dump(mode="json")
    row.style = style.model_dump(mode="json")
    row.render = render.model_dump(mode="json")
    row.docx_path = str(path.resolve())
    row.edited_at = edited_at
    db.commit()

    logger.info(
        "Tailoring edited",
        extra={
            "tailoring_id": tailoring_id,
            "factuality_passed": factuality.passed,
            "ats_score": ats_report.score,
            "render_mode": render.mode,
        },
    )
    # The commit expired the row's state; refresh so the response is rebuilt
    # from what the database actually holds — the same path the GET serves.
    db.refresh(row)
    return _stored_response(stored_from_row(row))
