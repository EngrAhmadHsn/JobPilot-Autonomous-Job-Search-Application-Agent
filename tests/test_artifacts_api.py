"""WS-13 tests: the artifact download endpoints (src/api/routes/artifacts.py).

The operator console has to be able to *show* the evidence: the rendered
DOCX of a tailoring and the screenshot of a tracked application. Both are
server-side files, so two read-only endpoints serve them.

The property these tests protect is the containment: a request may name
one of the artifacts, and nothing else. A file name with a separator, a
parent reference, or a stored path that points outside the directories this
application owns is refused.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.db.applications
import src.db.evidence
import src.db.tailored
from src.config.settings import get_settings
from src.db.applications import build_application_row
from src.db.base import Base
from src.db.evidence import ApplicationEvidence
from src.db.session import get_db
from src.db.tailored import build_tailored_row
from src.main import app
from src.research.engine import JobInsights
from src.resume.ats import AtsReport, KeywordCoverage
from src.resume.tailor import FactualityReport, TailoredResume

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32
DOCX_BYTES = b"PK\x03\x04" + b"0" * 32


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient with a throwaway database and throwaway data directories."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'artifacts.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))
    monkeypatch.setattr(get_settings(), "tailored_dir", str(tmp_path / "tailored"))
    monkeypatch.setattr(get_settings(), "evidence_dir", str(tmp_path / "evidence"))
    monkeypatch.setattr(get_settings(), "resume_upload_dir", str(tmp_path / "uploads"))
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _store_tailoring(api: TestClient, docx_path: Path) -> str:
    """Write a tailoring row whose DOCX lives at *docx_path*."""
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(DOCX_BYTES)
    with next(api.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
        row = build_tailored_row(
            profile_id="profile-1",
            job_id="greenhouse:1",
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
            insights=JobInsights(),
            docx_path=str(docx_path),
        )
        db.add(row)
        db.commit()
        return row.id


def test_download_returns_the_rendered_docx(api: TestClient, tmp_path: Path) -> None:
    tailored = tmp_path / "tailored" / "profile-1.docx"
    tailoring_id = _store_tailoring(api, tailored)

    response = api.get(f"/api/tailored/{tailoring_id}/download")

    assert response.status_code == 200
    assert response.content == DOCX_BYTES
    assert "wordprocessingml" in response.headers["content-type"]


def test_download_of_an_unknown_tailoring_is_404(api: TestClient) -> None:
    assert api.get("/api/tailored/nope/download").status_code == 404


def test_download_of_a_missing_file_is_404(api: TestClient, tmp_path: Path) -> None:
    missing = tmp_path / "tailored" / "gone.docx"
    tailoring_id = _store_tailoring(api, missing)
    missing.unlink()

    assert api.get(f"/api/tailored/{tailoring_id}/download").status_code == 404


def test_download_of_a_path_outside_the_allowed_roots_is_404(
    api: TestClient, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.docx"
    tailoring_id = _store_tailoring(api, outside)
    # The data dir is the tmp dir, so move the file out of every allowed root.
    secret = tmp_path.parent / "secret.docx"
    secret.write_bytes(DOCX_BYTES)
    with next(api.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
        row = db.get(src.db.tailored.TailoredResumeDB, tailoring_id)
        row.docx_path = str(secret)
        db.commit()

    response = api.get(f"/api/tailored/{tailoring_id}/download")

    assert response.status_code == 404
    assert "not available" in response.json()["detail"]


def test_evidence_download_returns_the_screenshot(api: TestClient, tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    screenshot = evidence_dir / "workflow-1.png"
    screenshot.write_bytes(PNG_BYTES)

    with next(api.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
        application = build_application_row(
            workflow_id="workflow-1",
            job_id="greenhouse:1",
            adapter_name="fake-ats",
            job_url="http://127.0.0.1:8901/basic",
            job_title="AI Engineer",
            company_name="Acme",
            status="verified",
        )
        db.add(application)
        db.add(
            ApplicationEvidence(
                workflow_id="workflow-1",
                adapter_name="fake-ats",
                job_url="http://127.0.0.1:8901/basic",
                application_id=application.id,
                confirmation_text="Application submitted",
                screenshot_path=str(screenshot),
                trace_path=None,
                status="submitted",
            )
        )
        db.commit()
        application_id = application.id

    response = api.get(f"/api/applications/{application_id}/evidence/workflow-1.png")

    assert response.status_code == 200
    assert response.content == PNG_BYTES
    assert response.headers["content-type"] == "image/png"


def test_evidence_download_refuses_a_traversal_file_name(api: TestClient) -> None:
    response = api.get("/api/applications/whatever/evidence/..%2F..%2F.env")

    assert response.status_code in (400, 404)


def test_evidence_download_of_an_unknown_application_is_404(api: TestClient) -> None:
    response = api.get("/api/applications/nope/evidence/workflow-1.png")

    assert response.status_code == 404


def test_evidence_list_returns_the_confirmation_text(api: TestClient, tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    screenshot = evidence_dir / "workflow-2.png"
    screenshot.write_bytes(PNG_BYTES)

    with next(api.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
        application = build_application_row(
            workflow_id="workflow-2",
            job_id="greenhouse:1",
            adapter_name="fake-ats",
            job_url="http://127.0.0.1:8901/basic",
            job_title="AI Engineer",
            company_name="Acme",
            status="verified",
        )
        db.add(application)
        db.add(
            ApplicationEvidence(
                workflow_id="workflow-2",
                adapter_name="fake-ats",
                job_url="http://127.0.0.1:8901/basic",
                application_id=application.id,
                confirmation_text="Application submitted",
                screenshot_path=str(screenshot),
                trace_path="workflow-2.trace.json",
                status="submitted",
            )
        )
        db.commit()
        application_id = application.id

    response = api.get(f"/api/applications/{application_id}/evidence")

    assert response.status_code == 200
    evidence = response.json()["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["confirmation_text"] == "Application submitted"
    assert evidence[0]["screenshot_path"].endswith("workflow-2.png")


def test_evidence_list_of_an_unknown_application_is_404(api: TestClient) -> None:
    assert api.get("/api/applications/nope/evidence").status_code == 404


def test_evidence_download_resolves_a_bare_file_name(api: TestClient, tmp_path: Path) -> None:
    """The browser layer stores an evidence artifact as a bare file name.

    The stored value is ``b3046adb.png`` — relative to the evidence
    directory, not a path. The endpoint has to resolve it there, or the
    console shows a broken image for every real submission.
    """
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "workflow-3.png").write_bytes(PNG_BYTES)

    with next(api.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
        application = build_application_row(
            workflow_id="workflow-3",
            job_id="greenhouse:1",
            adapter_name="fake-ats",
            job_url="http://127.0.0.1:8901/basic",
            job_title="AI Engineer",
            company_name="Acme",
            status="verified",
        )
        db.add(application)
        db.add(
            ApplicationEvidence(
                workflow_id="workflow-3",
                adapter_name="fake-ats",
                job_url="http://127.0.0.1:8901/basic",
                application_id=application.id,
                confirmation_text="Application submitted",
                screenshot_path="workflow-3.png",
                trace_path="workflow-3.trace.json",
                status="verified",
            )
        )
        db.commit()
        application_id = application.id

    response = api.get(f"/api/applications/{application_id}/evidence/workflow-3.png")

    assert response.status_code == 200
    assert response.content == PNG_BYTES
