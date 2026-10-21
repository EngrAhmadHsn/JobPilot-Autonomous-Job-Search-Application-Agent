"""Resume upload validation (WS-06 · SEC-10).

An uploaded resume is an untrusted file. It is checked before it is stored
and before it is parsed:

1. **Type** — only ``.docx``, ``.txt`` and ``.md`` are accepted.
2. **Size** — at most 5 MB. The payload is read with a cap, so an oversized
   upload is never fully materialised in memory.
3. **Content** — a ``.docx`` must be a real ZIP *and* open with
   ``python-docx`` (a renamed ZIP or a polyglot is rejected); a ``.txt`` /
   ``.md`` must decode as UTF-8.
4. **Name** — the filename is reduced to its base name, and the stored file
   is named after the generated profile id, so a hostile filename can never
   escape the upload directory.

A rejected upload never echoes the file content back to the caller.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import UploadFile

from src.config.settings import ensure_dir, get_settings

ALLOWED_EXTENSIONS = frozenset({".docx", ".txt", ".md"})
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


class UploadValidationError(ValueError):
    """The uploaded file is not an acceptable resume."""


def _extension_of(filename: str | None) -> str:
    """The lowercased suffix of an uploaded filename ('' when absent)."""
    if not filename:
        return ""
    return Path(filename).suffix.lower()


def _read_capped(file: UploadFile) -> bytes:
    """Read the payload, refusing anything above the size cap."""
    payload = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise UploadValidationError(
            f"Resume exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit"
        )
    if not payload:
        raise UploadValidationError("Resume file is empty")
    return payload


def _validate_docx(payload: bytes) -> None:
    """A DOCX must be a real ZIP that python-docx can open."""
    if not zipfile.is_zipfile(io.BytesIO(payload)):
        raise UploadValidationError("The uploaded .docx is not a valid Office document")
    try:
        from docx import Document

        Document(io.BytesIO(payload))
    except Exception as exc:
        raise UploadValidationError("The uploaded .docx could not be opened") from exc


def _validate_text(payload: bytes) -> None:
    """A TXT/MD file must decode as UTF-8."""
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UploadValidationError("The uploaded text file is not valid UTF-8") from exc


def validate_resume_upload(file: UploadFile, *, profile_id: str | None = None) -> Path:
    """Validate an uploaded resume and store it in the upload directory.

    Args:
        file: The uploaded file.
        profile_id: The id the stored file is named after. When omitted, one
            is generated; the caller reads it back from the returned path's
            stem.

    Returns:
        The path of the stored file, named ``{profile_id}{extension}``.

    Raises:
        UploadValidationError: The file is of a disallowed type, too large,
            empty, malformed, or carries a filename that cannot be used.
    """
    from src.db.profiles import generate_profile_id

    extension = _extension_of(file.filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            f"Unsupported resume type {extension!r}; allowed: "
            f"{', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    payload = _read_capped(file)

    if extension == ".docx":
        _validate_docx(payload)
    else:
        _validate_text(payload)

    active_profile_id = profile_id or generate_profile_id()
    upload_dir = ensure_dir(get_settings().resume_upload_dir)
    # The stored name is generated, never the uploaded one: a hostile
    # filename can neither escape the directory nor collide with a path.
    file_path = upload_dir / f"{active_profile_id}{extension}"
    file_path.write_bytes(payload)
    return file_path
