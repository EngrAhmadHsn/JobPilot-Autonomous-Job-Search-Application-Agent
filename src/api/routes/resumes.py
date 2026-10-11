"""Resume upload and retrieval API (WS-04).

``POST /api/resumes`` accepts a multipart resume upload, validates it
(extension whitelist, size cap, parseability — the minimal version; the full
shared validation util lands in WS-06), parses it into a CandidateProfile,
persists it (``candidate_profiles`` table) and returns the profile id with
deterministic validation warnings. ``GET /api/resumes/{id}`` returns the
stored profile.

Audit hooks (task 7 — full system in WS-06): uploads log context counts
(size, extension, warning count) with no PII in log fields.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.config.settings import ensure_dir, get_settings
from src.db.profiles import (
    CandidateProfileDB,
    build_profile_row,
    generate_profile_id,
    profile_from_row,
)
from src.db.session import get_db
from src.resume.parser import parse_resume
from src.resume.profile import CandidateProfile, validate_candidate_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

ALLOWED_EXTENSIONS = {".docx", ".txt", ".md"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB cap (shared util with more rules: WS-06)


class ResumeUploadResponse(BaseModel):
    """Response for a successful upload."""

    profile_id: str = Field(..., description="Id to use for job searches")
    warnings: list[str] = Field(default_factory=list)
    profile: CandidateProfile


class ResumeProfileResponse(BaseModel):
    """Stored profile response."""

    profile_id: str
    profile: CandidateProfile


def _extension_of(filename: str | None) -> str:
    """Lowercased suffix of an uploaded filename ('' when absent)."""
    if not filename:
        return ""
    return Path(filename).suffix.lower()


@router.post("", response_model=ResumeUploadResponse)
def upload_resume(
    file: UploadFile, db: Annotated[Session, Depends(get_db)]
) -> ResumeUploadResponse:
    """Parse and persist an uploaded resume (DOCX/TXT/MD, <= 5 MB).

    Returns the generated ``profile_id`` plus the deterministic validation
    warnings from the Phase-2 validation step. The upload is rejected with
    HTTP 400 for a disallowed extension, an oversized file, or a file that
    cannot be parsed (e.g. a corrupt DOCX).
    """
    extension = _extension_of(file.filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported resume type {extension!r}; allowed: "
            f"{', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    payload = file.file.read()  # framework parsed the multipart body already
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Resume exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit "
            f"({len(payload)} bytes)",
        )
    if not payload:
        raise HTTPException(status_code=400, detail="Resume file is empty")

    upload_dir = ensure_dir(get_settings().resume_upload_dir)
    profile_id = generate_profile_id()
    file_path = upload_dir / f"{profile_id}{extension}"
    file_path.write_bytes(payload)

    try:
        profile = parse_resume(str(file_path))
    except Exception as exc:
        file_path.unlink(missing_ok=True)
        logger.warning("Resume parse failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Resume could not be parsed: {exc}") from exc

    warnings = validate_candidate_profile(profile)

    row = build_profile_row(profile, str(file_path))
    db.add(row)
    db.commit()

    # SEC-13 audit hook (counts only, never PII).
    logger.info(
        "Resume uploaded",
        extra={
            "profile_id": row.id,
            "extension": extension,
            "bytes": len(payload),
            "warning_count": len(warnings),
        },
    )
    return ResumeUploadResponse(profile_id=row.id, warnings=warnings, profile=profile)


@router.get("/{profile_id}", response_model=ResumeProfileResponse)
def get_resume(
    profile_id: str, db: Annotated[Session, Depends(get_db)]
) -> ResumeProfileResponse:
    """Return the stored profile JSON for one uploaded resume."""
    row = db.get(CandidateProfileDB, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Profile {profile_id!r} not found")
    return ResumeProfileResponse(profile_id=row.id, profile=profile_from_row(row))
