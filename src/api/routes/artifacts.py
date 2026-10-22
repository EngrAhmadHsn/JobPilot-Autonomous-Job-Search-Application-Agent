"""Artifact downloads for the operator console (WS-13 · BA-1, BA-2).

Two **read-only** endpoints that let a browser fetch a file the server
already holds:

- ``GET /api/tailored/{tailoring_id}/download`` — the rendered DOCX of a
  tailoring. The API returned a *server-side path* for it, and a browser
  cannot read a filesystem path.
- ``GET /api/applications/{application_id}/evidence/{filename}`` — the
  evidence screenshot (or the action trace) of a tracked application. The
  same problem: the evidence records a path, not a URL.

Both are ``GET``s, both are path-contained, and neither changes the
behaviour of an existing route. They exist because the console has to be
able to *show* the evidence rather than describe it — a screenshot the
operator cannot open is not evidence, it is a claim.

The containment is the security property: a filename that is not a plain
file name is refused, and the resolved path must be inside a directory this
application owns (``src/security/paths.py``). A request cannot name
``../../.env``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.db import access
from src.db.session import get_db
from src.security.paths import is_absolute_path
from src.storage.paths import (
    KIND_EVIDENCE,
    UserPathNotAllowedError,
    assert_within_owned_storage,
    assert_within_user_root,
    user_dir,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["artifacts"])


#: The media types the artifact endpoints may serve.
_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/json",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _safe_file_name(name: str) -> str:
    """Return *name* when it is a plain file name, or raise a 400.

    A name with a separator, a parent reference or a drive letter is not a
    file name, it is a path, and the endpoint only ever serves one file.
    """
    if not name or name != Path(name).name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="The file name is not valid")
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="The file name is not valid")
    return name


def _media_type(path: Path) -> str:
    return _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _artifact_path(stored: str, owner_id: str) -> Path:
    """Where a stored artifact path points, for *owner_id*.

    The browser layer stores an evidence artifact as a **bare file name**
    (``b3046adb.png``), relative to the evidence directory. A bare name is
    therefore resolved inside the **owner's own** evidence directory
    (WS-14 · Phase B) — not inside the shared one, which would be a
    cross-tenant read. Everything else is used as it is, and the
    containment check that follows is what actually decides.
    """
    candidate = Path(stored)
    if not is_absolute_path(stored) and len(candidate.parts) == 1:
        candidate = user_dir(owner_id, KIND_EVIDENCE) / candidate
    return candidate


@router.get("/api/tailored/{tailoring_id}/download")
def download_tailored_docx(
    tailoring_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> FileResponse:
    """Download the DOCX rendered for one tailoring.

    Args:
        tailoring_id: The tailoring record whose DOCX is wanted.
        db: The request-scoped database session.

    Returns:
        The DOCX file.

    Raises:
        HTTPException 404: The tailoring, or its rendered file, is unknown.
    """
    row = access.get_tailored(db, scope, tailoring_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Tailoring not found")

    try:
        # WS-14 · Phase B: the containment is against the **owner's own**
        # directory, not against a shared root.
        # WS-15: the caller's own storage — their per-user directory plus
        # the legacy shared directories their account claimed. The legacy
        # files are the corpus that pre-dates the per-user layout; without
        # this the operator's own historical documents would 404.
        path = assert_within_owned_storage(row.docx_path, scope.user_id, what="rendered resume")
    except UserPathNotAllowedError as exc:
        logger.warning("Refused a DOCX download for %r: %s", tailoring_id, exc)
        raise HTTPException(status_code=404, detail="The rendered file is not available") from exc

    if not path.is_file():
        raise HTTPException(status_code=404, detail="The rendered file is not available")

    return FileResponse(
        path,
        media_type=_media_type(path),
        filename=path.name,
    )


@router.get("/api/applications/{application_id}/evidence/{filename}")
def download_evidence(
    application_id: str,
    filename: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> FileResponse:
    """Download one evidence artifact of a tracked application.

    Args:
        application_id: The tracked application the artifact belongs to.
        filename: The artifact's file name (the screenshot or the trace).
        db: The request-scoped database session.

    Returns:
        The artifact file.

    Raises:
        HTTPException 400: The file name is not a plain file name.
        HTTPException 404: The application, or the artifact, is unknown.
    """
    name = _safe_file_name(filename)

    application = access.get_application(db, scope, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    # WS-14 · A2: the evidence rows are read through the scoped accessor.
    # The route used to query the table directly with a dynamically
    # resolved model name — which is exactly the shape the "no direct
    # route queries" rule exists to catch, and which a text search for a
    # model name cannot see.
    evidence = access.list_evidence(db, scope, application.workflow_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="This application has no evidence")

    for record in evidence:
        for stored in (record.screenshot_path, record.trace_path):
            if not stored:
                continue
            candidate = _artifact_path(stored, scope.user_id)
            if candidate.name != name:
                continue
            try:
                # WS-14 · Phase B: the containment is against the
                # **owner's own** directory, not against a shared root.
                path = assert_within_user_root(candidate, scope.user_id, what="evidence file")
            except UserPathNotAllowedError as exc:
                logger.warning("Refused an evidence download for %r: %s", application_id, exc)
                raise HTTPException(
                    status_code=404, detail="The evidence file is not available"
                ) from exc
            if not path.is_file():
                raise HTTPException(status_code=404, detail="The evidence file is not available")
            return FileResponse(path, media_type=_media_type(path), filename=path.name)

    raise HTTPException(status_code=404, detail=f"No evidence file named {name!r}")


@router.get("/api/applications/{application_id}/evidence")
def list_application_evidence(
    application_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> dict:
    """The evidence records of one tracked application.

    The evidence rows are the record of what happened: the confirmation text
    the page showed, the status the adapter reported, and the paths of the
    artifacts. The tracking API answers with the application's *history*, not
    with its evidence, so the console cannot show a past submission's
    confirmation text without this.

    Args:
        application_id: The tracked application.
        db: The request-scoped database session.
        scope: The caller's access scope.

    Returns:
        The evidence records, newest first.

    Raises:
        HTTPException 404: The application is unknown.
    """
    application = access.get_application(db, scope, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    records = access.list_evidence(db, scope, application.workflow_id)
    return {
        "evidence": [
            {
                "confirmation_text": record.confirmation_text,
                "status": record.status,
                "screenshot_path": record.screenshot_path,
                "trace_path": record.trace_path,
                "job_url": record.job_url,
                "recorded_at": record.recorded_at.isoformat() if record.recorded_at else None,
            }
            for record in records
        ]
    }
