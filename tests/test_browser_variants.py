"""WS-08 · Phase E — every fake-ATS variant through the full workflow.

The acceptance criterion is not "the adapter can fill a form". It is that each
page variant survives the **whole** flow — prepare → approve → submit →
verify — with the right status, the evidence on disk and the database rows
WS-06 and WS-07 wrote.

The negative variants assert the *absence* of things: the challenge page was
never posted to, the unknown question was never answered, and the rejected
form carries the server's own message.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.applications.tracking import ApplicationStatus
from src.config.settings import get_settings
from src.db.applications import ApplicationDB, ApplicationEventDB
from src.db.base import Base
from src.db.evidence import ApplicationEvidence
from src.db.session import get_db
from src.main import app
from tests.fixtures.fake_ats import serve_fake_ats_variants


@pytest.fixture(scope="module")
def ats():
    """The fake ATS, running for the whole module."""
    with serve_fake_ats_variants() as base_url:
        yield base_url


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated evidence directory and a development environment."""
    settings = get_settings()
    evidence = tmp_path / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "evidence_dir", str(evidence))
    # The local fake ATS is reachable only outside production.
    monkeypatch.setattr(settings, "app_env", "development")
    return evidence


@pytest.fixture
def session_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An isolated database for the approvals, the tracking and the evidence."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'variants.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("src.db.session.SessionLocal", factory)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture(scope="module")
def client() -> TestClient:
    """The API client.

    Module-scoped on purpose: the application's lifespan warms the local
    embedding model, and paying for that once per test would dominate the
    runtime of a module that is about the browser.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A file the fake ATS can accept as a resume.

    WS-12: the prepare endpoint refuses a resume path that is not inside a
    directory this application owns, because the browser layer uploads that
    file to a third-party site — an uncontained path is an exfiltration
    channel. The temporary directory is therefore declared as the resume
    upload directory for the duration of the test, so the file is inside an
    allowed root.
    """
    from src.config.settings import get_settings

    monkeypatch.setattr(get_settings(), "resume_upload_dir", str(tmp_path))
    path = tmp_path / "resume.txt"
    path.write_text("Ada Lovelace — Senior Python Engineer\n", encoding="utf-8")
    return str(path)


def _payload(job_url: str, **extra) -> dict:
    payload = {
        "job_title": "Senior Python Engineer",
        "company_name": "Acme Labs",
        "job_url": job_url,
        "candidate_name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+1 555 0101",
    }
    payload.update(extra)
    return payload


def _run(client: TestClient, job_url: str, **extra) -> dict:
    """The whole flow: prepare, then approve (which executes the submission)."""
    prepared = client.post("/api/applications/prepare", json=_payload(job_url, **extra))
    assert prepared.status_code == 200, prepared.text
    approval_id = prepared.json()["approval_id"]

    approved = client.post(
        f"/api/applications/{approval_id}/approve",
        json={"approver": "human:ada", "reason": "reviewed"},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


class TestSuccessfulVariants:
    """The variants the agent can complete on its own."""

    @pytest.mark.parametrize(
        ("path", "extra"),
        [
            ("/basic", {}),
            ("/multipage", {"years_of_experience": "7", "work_authorization": "yes"}),
            (
                "/widgets",
                {
                    "country": "Germany",
                    "years_of_experience": "7",
                    "work_authorization": "yes",
                    "work_mode": "remote",
                },
            ),
            ("/validation-recoverable", {}),
        ],
    )
    def test_the_variant_is_submitted_and_verified(
        self, client, session_factory, workspace, ats, path, extra
    ) -> None:
        result = _run(client, f"{ats}{path}", custom_fields=extra)

        assert result["success"] is True, result
        assert result["status"] == "verified", result
        # The evidence is on disk (WS-06 · SEC-14).
        assert result["evidence"]["screenshot_path"]
        assert result["evidence"]["trace_path"]
        assert (workspace / result["evidence"]["screenshot_path"]).exists()

        with session_factory() as session:
            evidence = session.scalars(select(ApplicationEvidence)).one()
            assert evidence.status == "verified"
            assert (workspace / evidence.screenshot_path).exists()

            application = session.scalars(select(ApplicationDB)).one()
            assert application.status == ApplicationStatus.VERIFIED

            events = session.scalars(
                select(ApplicationEventDB).order_by(ApplicationEventDB.id)
            ).all()
            assert [event.to_status for event in events if event.to_status] == [
                ApplicationStatus.PREPARED.value,
                ApplicationStatus.AWAITING_APPROVAL.value,
                ApplicationStatus.SUBMITTED.value,
                ApplicationStatus.VERIFIED.value,
            ]

    def test_the_widget_values_reach_the_server(self, client, session_factory, ats) -> None:
        _run(
            client,
            f"{ats}/widgets",
            custom_fields={
                "country": "Germany",
                "years_of_experience": "7",
                "work_authorization": "yes",
                "work_mode": "remote",
            },
        )

        submissions = httpx.get(f"{ats}/_submissions", timeout=10).json()

        assert submissions[-1]["country"] == "Germany"
        assert submissions[-1]["years_of_experience"] == "7"
        assert submissions[-1]["work_authorization"] == "yes"
        assert submissions[-1]["work_mode"] == "remote"

    def test_the_multipage_values_reach_the_server(self, client, session_factory, ats) -> None:
        _run(
            client,
            f"{ats}/multipage",
            custom_fields={"years_of_experience": "7", "work_authorization": "yes"},
        )

        submissions = httpx.get(f"{ats}/_submissions", timeout=10).json()

        assert submissions[-1]["candidate_name"] == "Ada Lovelace"
        assert submissions[-1]["years_of_experience"] == "7"
        assert submissions[-1]["work_authorization"] == "yes"

    def test_the_upload_variant_attaches_the_resume(
        self, client, session_factory, workspace, ats, resume
    ) -> None:
        result = _run(client, f"{ats}/upload-required", resume_path=resume)

        assert result["success"] is True, result
        assert result["status"] == "verified", result

        last = httpx.get(f"{ats}/_last", timeout=10).json()
        assert last["files"] == ["resume.txt"]


class TestNeedsHuman:
    """An unknown question stops the run before anything is sent."""

    def test_the_unknown_question_is_surfaced(
        self, client, session_factory, workspace, ats
    ) -> None:
        result = _run(client, f"{ats}/unknown")

        assert result["success"] is False
        assert result["status"] == "needs_human"
        assert result["metadata"]["questions"] == ["Have you served on a submarine?"]
        # The evidence of the pause is on disk.
        assert result["evidence"]["screenshot_path"]
        assert (workspace / result["evidence"]["screenshot_path"]).exists()

    def test_nothing_was_submitted(self, client, session_factory, ats) -> None:
        _run(client, f"{ats}/unknown")

        last = httpx.get(f"{ats}/_last", timeout=10).json()

        assert last["method"] == "GET"
        assert last["path"] == "/unknown"

    def test_the_application_is_not_marked_as_submitted(self, client, session_factory, ats) -> None:
        _run(client, f"{ats}/unknown")

        with session_factory() as session:
            application = session.scalars(select(ApplicationDB)).one()
            # The submission never happened, so the tracking never claimed it.
            assert application.status == ApplicationStatus.AWAITING_APPROVAL
            assert application.submitted_at is None

            evidence = session.scalars(select(ApplicationEvidence)).one()
            assert evidence.status == "needs_human"


class TestChallenge:
    """A challenge stops the run before the page is touched."""

    def test_the_challenge_stops_the_submission(
        self, client, session_factory, workspace, ats
    ) -> None:
        result = _run(client, f"{ats}/captcha")

        assert result["success"] is False
        assert result["status"] == "blocked_human_review"
        assert result["metadata"]["challenge"]
        assert (workspace / result["evidence"]["screenshot_path"]).exists()

    def test_the_challenge_was_never_posted_to(self, client, session_factory, ats) -> None:
        _run(client, f"{ats}/captcha")

        last = httpx.get(f"{ats}/_last", timeout=10).json()

        assert last["method"] == "GET"
        assert last["path"] == "/captcha"


class TestFormError:
    """A rejected form is retried once, and then fails with the message."""

    def test_the_rejection_is_captured(self, client, session_factory, workspace, ats) -> None:
        result = _run(client, f"{ats}/validation")

        assert result["success"] is False
        assert result["status"] == "form_error"
        assert result["metadata"]["errors"] == [
            "We could not verify your email address. Please use your personal address."
        ]
        assert (workspace / result["evidence"]["screenshot_path"]).exists()

    def test_the_application_is_not_marked_as_submitted(self, client, session_factory, ats) -> None:
        _run(client, f"{ats}/validation")

        with session_factory() as session:
            application = session.scalars(select(ApplicationDB)).one()
            assert application.status == ApplicationStatus.AWAITING_APPROVAL
            assert application.submitted_at is None
