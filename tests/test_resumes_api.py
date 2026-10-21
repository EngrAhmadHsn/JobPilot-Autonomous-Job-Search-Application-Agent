"""WS-04 tests: resume upload + retrieval API (src/api/routes/resumes.py).

Runs the real FastAPI app against a tmp-file SQLite database and a tmp upload
directory — no file DB, no network. Covers the upload happy path (the repo's
DOCX fixture), the rejection matrix (wrong extension, oversize, empty,
corrupt DOCX), persistence, and profile round-trip through the JSON column.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.db.matches
import src.db.profiles  # noqa: F401
from src.config.settings import get_settings
from src.db.base import Base
from src.db.session import get_db
from src.main import app

FIXTURE_DOCX = Path(__file__).parent / "fixtures" / "Ahmad_Hassan_AI_Engineer_Resume.docx"

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient bound to a throwaway DB + upload dir; dependencies restored."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(get_settings(), "resume_upload_dir", str(tmp_path / "uploads"))
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _upload(client: TestClient, *, filename: str, content: bytes, mime: str = "text/plain"):
    return client.post("/api/resumes", files={"file": (filename, content, mime)})


def test_upload_docx_happy_path(api: TestClient) -> None:
    with FIXTURE_DOCX.open("rb") as fh:
        response = _upload(api, filename="resume.docx", content=fh.read(), mime=DOCX_MIME)

    assert response.status_code == 200
    body = response.json()
    assert body["profile_id"]
    assert body["profile"]["personal_information"]["name"].strip()
    assert body["profile"]["skills"], "fixture resume must yield skills"
    assert isinstance(body["warnings"], list)


def test_uploaded_profile_persisted_and_fetchable(api: TestClient) -> None:
    with FIXTURE_DOCX.open("rb") as fh:
        created = _upload(api, filename="resume.docx", content=fh.read(), mime=DOCX_MIME).json()

    response = api.get(f"/api/resumes/{created['profile_id']}")
    assert response.status_code == 200
    fetched = response.json()
    assert fetched["profile_id"] == created["profile_id"]
    # The stored JSON round-trips to an identical profile.
    assert fetched["profile"] == created["profile"]


def test_get_unknown_profile_404(api: TestClient) -> None:
    assert api.get("/api/resumes/does-not-exist").status_code == 404


@pytest.mark.parametrize("filename", ["resume.pdf", "resume.exe", "resume", "resume.doc"])
def test_upload_wrong_extension_rejected(api: TestClient, filename: str) -> None:
    response = _upload(api, filename=filename, content=b"hello")
    assert response.status_code == 400
    assert "Unsupported resume type" in response.json()["detail"]


def test_upload_oversized_rejected(api: TestClient) -> None:
    oversized = b"x" * (5 * 1024 * 1024 + 1)
    response = _upload(api, filename="resume.txt", content=oversized)
    assert response.status_code == 400
    assert "5 MB limit" in response.json()["detail"]


def test_upload_empty_file_rejected(api: TestClient) -> None:
    response = _upload(api, filename="resume.txt", content=b"")
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_upload_corrupt_docx_rejected(api: TestClient, tmp_path: Path) -> None:
    """A .docx that is not a real Office package is rejected by the validator.

    WS-06 · SEC-10: the upload validator refuses the file before it is
    stored, so the message names the problem instead of echoing the content.
    """
    response = _upload(
        api, filename="corrupt.docx", content=b"this is definitely not a docx", mime=DOCX_MIME
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "not a valid Office document" in detail or "could not be parsed" in detail
    assert "definitely not a docx" not in detail


def test_upload_txt_resume_round_trips(api: TestClient) -> None:
    """A plain-text resume uploads, parses, and persists like DOCX."""
    content = (Path(__file__).parent / "fixtures" / "demo_resume.txt").read_bytes()
    response = _upload(api, filename="resume.txt", content=content)

    assert response.status_code == 200
    profile_id = response.json()["profile_id"]
    fetched = api.get(f"/api/resumes/{profile_id}")
    assert fetched.status_code == 200
    assert fetched.json()["profile"] == response.json()["profile"]
