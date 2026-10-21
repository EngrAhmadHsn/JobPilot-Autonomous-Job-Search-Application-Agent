"""Resume upload and retrieval API (WS-04, hardened in WS-06).

``POST /api/resumes`` accepts a multipart resume upload, validates it with
the shared upload validator (WS-06 · SEC-10: extension whitelist, size cap,
real-file check, generated file name), parses it into a CandidateProfile,
persists it (``candidate_profiles`` table) and returns the profile id with
deterministic validation warnings. ``GET /api/resumes/{id}`` returns the
stored profile.

Uploads are audited (WS-06 · SEC-13) with context counts only — never the
resume text, never a piece of personal data.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.api.validation import UploadValidationError, validate_resume_upload
from src.db import access
from src.db.profiles import (
    build_profile_row,
    profile_from_row,
)
from src.db.session import get_db
from src.resume.parser import parse_resume
from src.resume.profile import CandidateProfile, validate_candidate_profile
from src.security.audit import (
    ACTION_RESUME_UPLOAD,
    OUTCOME_ERROR,
    OUTCOME_SUCCESS,
    SYSTEM_ACTOR,
    record_audit,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


class ResumeUploadResponse(BaseModel):
    """Response for a successful upload."""

    profile_id: str = Field(..., description="Id to use for job searches")
    warnings: list[str] = Field(default_factory=list)
    profile: CandidateProfile


class ResumeProfileResponse(BaseModel):
    """Stored profile response."""

    profile_id: str
    profile: CandidateProfile


@router.post("", response_model=ResumeUploadResponse)
def upload_resume(
    file: UploadFile,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> ResumeUploadResponse:
    """Parse and persist an uploaded resume (DOCX/TXT/MD, <= 5 MB).

    Returns the generated ``profile_id`` plus the deterministic validation
    warnings from the Phase-2 validation step. The upload is rejected with
    HTTP 400 for a disallowed extension, an oversized file, a file that is not
    a real document, or a file that cannot be parsed.
    """
    try:
        file_path = validate_resume_upload(file, owner_id=scope.user_id)
    except UploadValidationError as exc:
        logger.warning("Resume upload rejected: %s", exc)
        record_audit(
            ACTION_RESUME_UPLOAD,
            actor=SYSTEM_ACTOR,
            resource=file.filename or "upload",
            outcome=OUTCOME_ERROR,
            owner_id=scope.user_id,
            metadata={"reason": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    profile_id = file_path.stem
    extension = file_path.suffix.lower()

    try:
        profile = parse_resume(str(file_path))
    except Exception as exc:
        file_path.unlink(missing_ok=True)
        logger.warning("Resume parse failed: %s", exc)
        record_audit(
            ACTION_RESUME_UPLOAD,
            actor=SYSTEM_ACTOR,
            resource=profile_id,
            outcome=OUTCOME_ERROR,
            owner_id=scope.user_id,
            metadata={"reason": "the stored file could not be parsed"},
        )
        raise HTTPException(status_code=400, detail=f"Resume could not be parsed: {exc}") from exc

    warnings = validate_candidate_profile(profile)

    row = build_profile_row(profile, str(file_path), owner_id=scope.user_id)
    db.add(row)
    db.commit()

    # SEC-13 audit event (counts only, never PII).
    record_audit(
        ACTION_RESUME_UPLOAD,
        actor=SYSTEM_ACTOR,
        resource=profile_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=scope.user_id,
        metadata={
            "extension": extension,
            "bytes": file_path.stat().st_size,
            "warning_count": len(warnings),
        },
    )
    logger.info(
        "Resume uploaded",
        extra={
            "profile_id": row.id,
            "extension": extension,
            "warning_count": len(warnings),
        },
    )
    return ResumeUploadResponse(profile_id=row.id, warnings=warnings, profile=profile)


@router.get("/{profile_id}", response_model=ResumeProfileResponse)
def get_resume(
    profile_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> ResumeProfileResponse:
    """Return the stored profile JSON for one uploaded resume."""
    row = access.get_profile(db, scope, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return ResumeProfileResponse(profile_id=row.id, profile=profile_from_row(row))
