"""Resume upload validation (WS-06 · SEC-10).

An uploaded resume is an untrusted file. It is checked before it is stored
and before it is parsed:

1. **Type** — only ``.docx``, ``.pdf``, ``.txt`` and ``.md`` are accepted.
2. **Size** — at most 5 MB. The payload is read with a cap, so an oversized
   upload is never fully materialised in memory.
3. **Content** — a ``.docx`` must be a real ZIP *and* open with
   ``python-docx`` (a renamed ZIP or a polyglot is rejected); a ``.txt`` /
   ``.md`` must decode as UTF-8; a ``.pdf`` must carry the ``%PDF-`` magic
   and open with ``pypdf`` (a renamed anything is rejected).
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

ALLOWED_EXTENSIONS = frozenset({".docx", ".pdf", ".txt", ".md"})
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

#: The magic number every PDF starts with (ISO 32000-1, 7.5.2), at byte zero.
#: A file named ``.pdf`` without it is not a PDF, whatever it says about
#: itself, and this is the same position pypdf reads when it opens the file.
_PDF_MAGIC = b"%PDF-"


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
    """A DOCX must be a real ZIP that python-docx can open.

    WS-12: the 5 MB cap is on the **compressed** upload, so a small file
    can still expand into gigabytes — the classic zip bomb. The archive's
    *uncompressed* total and its entry count are therefore checked before
    the document is opened, and a bomb is refused with the same 400 as any
    other malformed upload.
    """
    if not zipfile.is_zipfile(io.BytesIO(payload)):
        raise UploadValidationError("The uploaded .docx is not a valid Office document")

    _assert_not_a_zip_bomb(payload)

    try:
        from docx import Document

        Document(io.BytesIO(payload))
    except Exception as exc:
        raise UploadValidationError("The uploaded .docx could not be opened") from exc


def _assert_not_a_zip_bomb(payload: bytes) -> None:
    """Refuse an archive whose uncompressed size or entry count is absurd.

    The numbers come from the ZIP central directory, so they are known
    **before** a single byte is decompressed — the whole point of checking
    them here rather than after extraction.
    """
    from src.security.limits import get_limits

    limits = get_limits()
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise UploadValidationError("The uploaded .docx is not a valid Office document") from exc

    if len(entries) > limits.max_zip_entries:
        raise UploadValidationError(
            f"The uploaded .docx contains {len(entries)} entries, over the "
            f"{limits.max_zip_entries} limit"
        )

    total = sum(entry.file_size for entry in entries)
    if total > limits.max_upload_uncompressed_bytes:
        raise UploadValidationError(
            f"The uploaded .docx expands to {total} bytes, over the "
            f"{limits.max_upload_uncompressed_bytes} byte limit"
        )


def _validate_pdf(payload: bytes) -> None:
    """A PDF must start with the magic number *and* open with pypdf.

    The magic alone is a one-line forgery; opening it with the same reader
    the parser will use proves the file is a PDF this system can read. WS-32:
    a page count is not enumerated here — pypdf opens a document lazily and
    the parser's own extraction is capped by the 5 MB upload limit, so a
    hostile page count costs no more than the file it arrives in.
    """
    if not payload[: len(_PDF_MAGIC)].startswith(_PDF_MAGIC):
        raise UploadValidationError("The uploaded .pdf is not a PDF document")

    try:
        import pypdf

        pypdf.PdfReader(io.BytesIO(payload))
    except Exception as exc:
        raise UploadValidationError("The uploaded .pdf could not be opened") from exc


def _validate_text(payload: bytes) -> None:
    """A TXT/MD file must decode as UTF-8."""
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UploadValidationError("The uploaded text file is not valid UTF-8") from exc


def validate_resume_upload(
    file: UploadFile, *, profile_id: str | None = None, owner_id: str | None = None
) -> Path:
    """Validate an uploaded resume and store it in the upload directory.

    Args:
        file: The uploaded file.
        profile_id: The id the stored file is named after. When omitted, one
            is generated; the caller reads it back from the returned path's
            stem.
        owner_id: The account the file belongs to (WS-14 · Phase B). When
            given, the file is written into **that account's own**
            directory, so the file on the disk and the row in the database
            agree about who owns it. When omitted, the shared upload
            directory is used — which is what the evaluation harness and
            the scripts that pre-date the multi-user work do.

    Returns:
        The path of the stored file, named ``{profile_id}{extension}``.

    Raises:
        UploadValidationError: The file is of a disallowed type, too large,
            empty, malformed, or carries a filename that cannot be used.
    """
    from src.db.profiles import generate_profile_id
    from src.storage.paths import KIND_RESUMES, user_dir

    extension = _extension_of(file.filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            f"Unsupported resume type {extension!r}; allowed: "
            f"{', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    payload = _read_capped(file)

    if extension == ".docx":
        _validate_docx(payload)
    elif extension == ".pdf":
        _validate_pdf(payload)
    else:
        _validate_text(payload)

    active_profile_id = profile_id or generate_profile_id()
    if owner_id:
        upload_dir = ensure_dir(user_dir(owner_id, KIND_RESUMES))
    else:
        upload_dir = ensure_dir(get_settings().resume_upload_dir)
    # The stored name is generated, never the uploaded one: a hostile
    # filename can neither escape the directory nor collide with a path.
    file_path = upload_dir / f"{active_profile_id}{extension}"
    file_path.write_bytes(payload)
    return file_path
