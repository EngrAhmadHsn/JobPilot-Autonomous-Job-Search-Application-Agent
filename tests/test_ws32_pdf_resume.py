"""WS-32 · A PDF résumé is parsed, and a PDF we cannot read says so.

`.pdf` is the format ATS upload fields expect — Greenhouse's own submission
example posts a PDF — and the parser refused it outright: a candidate whose
résumé is a PDF could not use the system at all.

The hard part is not extracting text; it is refusing to invent it. A scanned
PDF has no text layer and a CID-font PDF extracts as mojibake. Both must be
reported, because a profile built from mojibake is a fabricated profile.

The fixtures are **checked-in binaries** under `tests/fixtures/pdf/`, the same
convention `tests/fixtures/Ahmad_Hassan_AI_Engineer_Resume.docx` already
follows, and they are produced by the checked-in generator that sits beside
them (`make_fixtures.py`) — which prints what `pypdf` extracts from each file,
so a maintainer can see that a fixture does what its name claims. Four small
files, each one shape: `resume_with_text.pdf`, `resume_scanned.pdf` (an image
page, no text layer), `resume_mojibake.pdf`, `resume_encrypted.pdf`.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi import UploadFile

from src.api.validation import UploadValidationError, validate_resume_upload
from src.config.settings import get_settings
from src.resume.parser import parse_resume

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"


def test_a_pdf_resume_is_parsed() -> None:
    """The happy path: a real text layer extracts, and the profile is populated."""
    profile = parse_resume(str(FIXTURES / "resume_with_text.pdf"))

    assert profile.personal_information.name == "Ada Lovelace"
    assert profile.personal_information.email == "ada@example.com"
    # Not just the contact block — the body has to survive extraction, or the
    # profile has no experience and the matcher has nothing to work with.
    assert profile.experience


def test_a_scanned_pdf_is_refused_with_a_readable_reason() -> None:
    """No text layer means no profile — never an empty one presented as a parse.

    This is the failure a real user hits: a phone-scanned résumé is an image in
    a PDF wrapper, and silently returning a blank profile would have them
    believe the upload worked.
    """
    with pytest.raises(ValueError, match="no extractable text"):
        parse_resume(str(FIXTURES / "resume_scanned.pdf"))


def test_a_mojibake_pdf_is_refused_rather_than_parsed() -> None:
    """A text layer of replacement characters is not text.

    A profile built from ``\\ufffd`` runs would pass every downstream validator
    and produce a résumé full of rubbish, so the refusal belongs here. The
    fixture is the *mapped-to-FFFD* shape: the CID font ships a ``/ToUnicode``
    table that says its glyphs are not Unicode.
    """
    with pytest.raises(ValueError, match="not readable text"):
        parse_resume(str(FIXTURES / "resume_mojibake.pdf"))


def test_a_pdf_with_no_unicode_mapping_is_refused_rather_than_parsed() -> None:
    """A CID font with no `/ToUnicode` at all is the shape that fabricates a profile.

    This is the same broken font as the mojibake fixture with its ``/ToUnicode``
    entry **omitted** — a font that was never embedded, or was embedded without
    its Unicode table. There is no mapping to honour, so pypdf passes the raw
    text codes through and extraction yields control characters (U+0001…U+001F)
    and not one U+FFFD.

    A reader that watched only for the replacement character would accept this
    and build a profile whose name is a run of control characters — a
    fabricated candidate, which the project rule forbids outright. So the
    refusal must fire on this shape too.
    """
    with pytest.raises(ValueError, match="not readable text"):
        parse_resume(str(FIXTURES / "resume_no_tounicode.pdf"))


def test_a_corrupt_pdf_is_refused_not_raised_as_a_crash(tmp_path: Path) -> None:
    """`pypdf`'s own exception must not surface to the user as a 500."""
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nthis is not a valid pdf body")

    with pytest.raises(ValueError, match="could not be read"):
        parse_resume(str(path))


def test_an_encrypted_pdf_is_refused_with_its_own_reason() -> None:
    """A password-protected résumé is a user problem with a user fix, and it
    must not read the same as a corrupt file."""
    with pytest.raises(ValueError, match="password"):
        parse_resume(str(FIXTURES / "resume_encrypted.pdf"))


def test_the_docx_and_text_paths_are_unchanged(tmp_path: Path) -> None:
    """The new reader must not become the only one."""
    docx = Path(__file__).parent / "fixtures" / "Ahmad_Hassan_AI_Engineer_Resume.docx"
    assert parse_resume(str(docx)).personal_information.name

    txt = tmp_path / "resume.txt"
    txt.write_text("Ada Lovelace\nada@example.com\n", encoding="utf-8")
    assert parse_resume(str(txt)).personal_information.email == "ada@example.com"


@pytest.fixture()
def isolated_upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the stored uploads out of the developer's data directory."""
    target = tmp_path / "uploads"
    monkeypatch.setattr(get_settings(), "resume_upload_dir", str(target))
    return target


def test_the_upload_boundary_accepts_a_pdf(isolated_upload_dir: Path) -> None:
    """The parser is not the boundary — the upload validation is.

    A parser that accepts `.pdf` behind a validator that rejects it is worse
    than neither: the user is refused a format the system can now read. This
    drives the real validator (`src/api/validation.py`) with a real payload,
    because the extension is a claim the content has to support.
    """
    payload = (FIXTURES / "resume_with_text.pdf").read_bytes()

    stored = [
        validate_resume_upload(
            UploadFile(filename=name, file=io.BytesIO(payload)), profile_id=f"p{i}"
        )
        for i, name in enumerate(("resume.pdf", "RESUME.PDF"))
    ]

    assert [path.suffix for path in stored] == [".pdf", ".pdf"]
    assert all(path.exists() and path.parent == isolated_upload_dir for path in stored)


def test_the_upload_boundary_still_refuses_what_it_always_did() -> None:
    """`.exe`, no extension and `.doc` are not résumés, and case never decides."""
    for name in ("resume.exe", "resume", "resume.doc"):
        with pytest.raises(UploadValidationError, match="Unsupported resume type"):
            validate_resume_upload(UploadFile(filename=name, file=io.BytesIO(b"payload")))


def test_a_non_pdf_payload_named_pdf_is_refused(isolated_upload_dir: Path) -> None:
    """A renamed ZIP must not pass as a PDF: the magic number is the evidence."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "not a document")

    with pytest.raises(UploadValidationError, match="not a PDF document"):
        validate_resume_upload(
            UploadFile(filename="resume.pdf", file=io.BytesIO(buffer.getvalue()))
        )
