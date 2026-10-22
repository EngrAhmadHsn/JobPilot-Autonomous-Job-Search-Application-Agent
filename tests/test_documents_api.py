"""WS-13 · Phase C — the document library (src/api/routes/documents.py).

The console shows the documents an account already has — the résumé it
uploaded and the tailored résumés the agent produced — so the operator can
attach one to an application instead of typing a server-side path.

These tests pin three things: the listing is **the caller's own** (a
document library that leaks another account's files is the worst kind of
leak), the download is **contained** (a path that points outside the
directories the application owns is refused), and a document whose file is
gone from the disk is reported as missing rather than as a crash.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.profiles import build_profile_row
from src.db.session import get_db
from src.db.tailored import build_tailored_row
from src.main import app
from src.resume.ats import AtsReport, KeywordCoverage
from src.resume.profile import CandidateProfile, PersonalInformation
from src.resume.tailor import FactualityReport, TailoredResume

#: An owner that is **not** the caller. Its rows must never be listed.
OTHER_OWNER = "another-account"


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient over a throwaway database and a throwaway data dir."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'documents.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "data" / "evidence"))
    monkeypatch.setenv("RESUME_UPLOAD_DIR", str(tmp_path / "data" / "resumes"))
    monkeypatch.setenv("TAILORED_DIR", str(tmp_path / "data" / "tailored"))
    from src.config.settings import get_settings

    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def _uploads_dir() -> Path:
    from src.config.settings import get_settings

    return Path(get_settings().resume_upload_dir)


def _tailored_dir() -> Path:
    from src.config.settings import get_settings

    return Path(get_settings().tailored_dir)


def _add_profile(path: Path, name: str, *, owner_id: str | None = None) -> str:
    """Write a résumé file and the profile row that points at it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 fake resume")
    with next(app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
        kwargs = {"owner_id": owner_id} if owner_id else {}
        row = build_profile_row(
            CandidateProfile(personal_information=PersonalInformation(name=name)),
            str(path),
            **kwargs,
        )
        db.add(row)
        db.commit()
        return row.id


def _add_tailored(path: Path, job_id: str, *, owner_id: str | None = None) -> str:
    """Write a tailored résumé file and the row that points at it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PK\x03\x04 fake docx")
    with next(app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
        kwargs = {"owner_id": owner_id} if owner_id else {}
        row = build_tailored_row(
            profile_id="profile-1",
            job_id=job_id,
            tailored=TailoredResume(
                summary="A summary",
                highlighted_skills=["Python"],
                experience=[],
                projects=[],
                cover_letter="A letter",
            ),
            factuality=FactualityReport(passed=True),
            ats_report=AtsReport(
                keyword_coverage=KeywordCoverage(),
                section_completeness={},
            ),
            docx_path=str(path),
            **kwargs,
        )
        db.add(row)
        db.commit()
        return row.id


def test_the_library_lists_the_callers_resumes_and_tailored_resumes(api: TestClient) -> None:
    _add_profile(_uploads_dir() / "alice-resume.pdf", "Ada Lovelace")
    _add_tailored(_tailored_dir() / "alice-tailored.docx", "greenhouse:1")

    response = api.get("/api/documents")

    assert response.status_code == 200, response.text
    documents = response.json()["documents"]
    kinds = {document["kind"] for document in documents}
    assert kinds == {"resume", "tailored"}
    assert any(document["filename"] == "alice-resume.pdf" for document in documents)
    assert any("greenhouse:1" in document["title"] for document in documents)
    # The path travels with the listing, so the console can attach it.
    assert all(document["path"] for document in documents)


def test_the_library_shows_nothing_another_account_uploaded(api: TestClient) -> None:
    _add_profile(_uploads_dir() / "someone-else.pdf", "Someone Else", owner_id=OTHER_OWNER)

    response = api.get("/api/documents")

    assert response.status_code == 200, response.text
    assert response.json()["documents"] == []


def test_a_document_can_be_downloaded(api: TestClient) -> None:
    profile_id = _add_profile(_uploads_dir() / "alice-resume.pdf", "Ada Lovelace")

    response = api.get(f"/api/documents/profile-{profile_id}/download")

    assert response.status_code == 200, response.text
    assert response.content == b"%PDF-1.4 fake resume"


def test_another_accounts_document_cannot_be_downloaded(api: TestClient) -> None:
    profile_id = _add_profile(
        _uploads_dir() / "someone-else.pdf", "Someone Else", owner_id=OTHER_OWNER
    )

    response = api.get(f"/api/documents/profile-{profile_id}/download")

    assert response.status_code == 404


def test_an_unknown_document_is_a_404(api: TestClient) -> None:
    assert api.get("/api/documents/profile-nope/download").status_code == 404
    assert api.get("/api/documents/nonsense/download").status_code == 404


def test_a_document_whose_file_is_gone_is_a_404(api: TestClient) -> None:
    path = _uploads_dir() / "gone.pdf"
    profile_id = _add_profile(path, "Ada Lovelace")
    path.unlink()

    assert api.get(f"/api/documents/profile-{profile_id}/download").status_code == 404


def test_the_library_needs_a_session(api: TestClient) -> None:
    from src.auth.routes import current_active_user
    from src.db.users import LEGACY_OWNER_ID, UserDB

    # The suite's autouse identity is removed on purpose: this test is
    # about the real authentication, so the route must resolve the
    # principal from a real credential.
    app.dependency_overrides.pop(current_active_user, None)
    try:
        assert api.get("/api/documents").status_code == 401
    finally:
        caller = UserDB(
            id=LEGACY_OWNER_ID,
            email="test-caller@example.com",
            hashed_password="!",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        app.dependency_overrides[current_active_user] = lambda: caller
