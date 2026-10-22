"""The caller's document library (WS-13 · Phase C).

The console needs to *show* the documents an account already has — the
résumé it uploaded, the tailored résumés the agent produced — so that the
operator can attach one to an application instead of typing a server-side
path.

Two read-only endpoints:

- ``GET /api/documents`` — the caller's documents, newest first.
- ``GET /api/documents/{document_id}/download`` — one of them.

**Where the list comes from.** The system has no table of "documents": a
résumé *is* a candidate profile (the parser made a profile out of it), and
a tailored résumé is a tailoring record. The library is therefore the
union of the caller's profiles and the caller's tailorings, read through
the scoped accessors — so a caller sees their own documents and nobody
else's.

**Why the path travels with the listing.** The prepare endpoint takes the
path of the résumé to attach, and the server checks that the path is
inside a directory it owns. The console cannot invent a path, and it
should not have to: the listing carries the path of a file the *server*
knows about, and the server's containment check still has the last word.
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
from src.security.paths import PathNotAllowedError, assert_within_allowed_roots

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

#: The media types the library may serve.
_MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}


def _size_of(path: str) -> int | None:
    """The size of the stored file, when it is there."""
    try:
        return Path(path).stat().st_size
    except OSError:
        return None


def _documents(db: Session, scope: UserScope) -> list[dict]:
    """The caller's documents, newest first.

    A résumé the account uploaded, and every tailored résumé the agent
    produced for it. The file may be gone from the disk (a clean-up, a
    moved file); the row still stands, so the entry is still listed and
    says the file is missing.
    """
    documents: list[dict] = []

    for profile in access.list_profiles(db, scope):
        name = profile.name or "Untitled"
        documents.append(
            {
                "id": f"profile-{profile.id}",
                "kind": "resume",
                "title": f"Résumé — {name}",
                "filename": Path(profile.file_path).name,
                "path": profile.file_path,
                "size_bytes": _size_of(profile.file_path),
                "created_at": profile.created_at.isoformat() if profile.created_at else None,
                "profile_id": profile.id,
                "job_id": None,
            }
        )

    for tailored in access.list_tailored(db, scope):
        documents.append(
            {
                "id": f"tailored-{tailored.id}",
                "kind": "tailored",
                "title": f"Tailored résumé — {tailored.job_id}",
                "filename": Path(tailored.docx_path).name,
                "path": tailored.docx_path,
                "size_bytes": _size_of(tailored.docx_path),
                "created_at": tailored.created_at.isoformat() if tailored.created_at else None,
                "profile_id": tailored.profile_id,
                "job_id": tailored.job_id,
            }
        )

    documents.sort(key=lambda item: item["created_at"] or "", reverse=True)
    return documents


@router.get("")
def list_documents(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> dict:
    """The caller's documents, newest first.

    Args:
        db: The request-scoped database session.
        scope: The caller's access scope.

    Returns:
        The documents and how many there are.
    """
    documents = _documents(db, scope)
    return {"documents": documents, "count": len(documents)}


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> FileResponse:
    """Download one of the caller's documents.

    Args:
        document_id: The document's id (``profile-<id>`` or ``tailored-<id>``).
        db: The request-scoped database session.
        scope: The caller's access scope.

    Returns:
        The file.

    Raises:
        HTTPException 404: The document is unknown, or its file is gone.
    """
    prefix, _, identifier = document_id.partition("-")
    if not identifier or prefix not in {"profile", "tailored"}:
        raise HTTPException(status_code=404, detail=f"Document {document_id!r} not found")

    if prefix == "profile":
        row = access.get_profile(db, scope, identifier)
        stored_path = row.file_path if row is not None else None
    else:
        row = access.get_tailored(db, scope, identifier)
        stored_path = row.docx_path if row is not None else None

    if row is None or not stored_path:
        raise HTTPException(status_code=404, detail=f"Document {document_id!r} not found")

    try:
        path = assert_within_allowed_roots(stored_path, what="document")
    except PathNotAllowedError as exc:
        logger.warning("Refused a document download for %r: %s", document_id, exc)
        raise HTTPException(status_code=404, detail="The file is not available") from exc

    if not path.is_file():
        raise HTTPException(status_code=404, detail="The file is not available")

    return FileResponse(
        path,
        media_type=_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        filename=path.name,
    )
