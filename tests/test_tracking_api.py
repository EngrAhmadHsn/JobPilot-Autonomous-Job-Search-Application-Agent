"""WS-07 · the tracking API: list, detail, and human status updates.

The tests are written from the outside: what a caller can list, read, and
change over HTTP — and, just as importantly, what they cannot.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.applications.tracking import (
    AGENT_ACTOR,
    HUMAN_OUTCOME_STATUSES,
    ApplicationStatus,
    create_application,
    human_actor,
    transition,
)
from src.db.base import Base
from src.db.session import get_db
from src.main import app

JOB_URL = "http://localhost:8000/jobs/123/apply"


@pytest.fixture
def session_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An isolated database for the tracked applications."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'tracking_api.db').as_posix()}")
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


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


#: The legal path from PREPARED to each status a test may ask for.
_LEGAL_PATH: dict[ApplicationStatus, list[ApplicationStatus]] = {
    ApplicationStatus.AWAITING_APPROVAL: [ApplicationStatus.AWAITING_APPROVAL],
    ApplicationStatus.SUBMITTED: [ApplicationStatus.AWAITING_APPROVAL, ApplicationStatus.SUBMITTED],
    ApplicationStatus.VERIFIED: [
        ApplicationStatus.AWAITING_APPROVAL,
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.VERIFIED,
    ],
    ApplicationStatus.INTERVIEW: [
        ApplicationStatus.AWAITING_APPROVAL,
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.VERIFIED,
        ApplicationStatus.INTERVIEW,
    ],
    ApplicationStatus.OFFER: [
        ApplicationStatus.AWAITING_APPROVAL,
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.VERIFIED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
    ],
    ApplicationStatus.REJECTED: [ApplicationStatus.AWAITING_APPROVAL, ApplicationStatus.REJECTED],
    ApplicationStatus.WITHDRAWN: [
        ApplicationStatus.AWAITING_APPROVAL,
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.VERIFIED,
        ApplicationStatus.WITHDRAWN,
    ],
}


def _track(factory, *, status=ApplicationStatus.PREPARED, job_url=JOB_URL, title="Engineer"):
    """Create a tracked application in *status* and return its id.

    The application is walked through the legal path to *status*, so the test
    starts from a state the machine can actually reach.
    """
    with factory() as session:
        app_row = create_application(
            session,
            workflow_id=f"wf-{title}",
            adapter_name="fake-ats-playwright",
            job_url=job_url,
            job_title=title,
            company_name="Acme Labs",
        )
        for step in _LEGAL_PATH.get(status, []):
            actor = human_actor("ada") if step in HUMAN_OUTCOME_STATUSES else AGENT_ACTOR
            transition(app_row, step, actor=actor, db=session)
        return app_row.id


class TestListEndpoint:
    """The tracked applications are listable."""

    def test_an_empty_list_is_not_an_error(self, client, session_factory):
        response = client.get("/api/applications")

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0

    def test_the_applications_are_listed(self, client, session_factory):
        application_id = _track(session_factory)

        response = client.get("/api/applications")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == application_id
        assert body["items"][0]["status"] == ApplicationStatus.PREPARED.value
        assert body["items"][0]["job_title"] == "Engineer"

    def test_the_status_filter_narrows_the_list(self, client, session_factory):
        _track(session_factory, title="One", status=ApplicationStatus.VERIFIED)
        _track(
            session_factory, title="Two", status=ApplicationStatus.PREPARED, job_url=JOB_URL + "2"
        )

        response = client.get("/api/applications", params={"status": "verified"})

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["status"] == "verified"

    def test_the_status_filter_accepts_several_values(self, client, session_factory):
        _track(session_factory, title="One", status=ApplicationStatus.VERIFIED)
        _track(
            session_factory, title="Two", status=ApplicationStatus.PREPARED, job_url=JOB_URL + "2"
        )

        response = client.get("/api/applications?status=verified&status=prepared")

        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_an_unknown_status_is_a_400(self, client, session_factory):
        response = client.get("/api/applications", params={"status": "nonsense"})

        assert response.status_code == 400
        assert "Unknown status" in response.json()["detail"]

    def test_the_page_size_is_bounded(self, client, session_factory):
        response = client.get("/api/applications", params={"limit": 5000})

        assert response.status_code == 422

    def test_the_pagination_reports_the_total(self, client, session_factory):
        for index in range(3):
            _track(session_factory, title=f"Job {index}", job_url=f"{JOB_URL}{index}")

        response = client.get("/api/applications", params={"limit": 2, "offset": 0})

        body = response.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0

    def test_the_offset_skips_applications(self, client, session_factory):
        for index in range(3):
            _track(session_factory, title=f"Job {index}", job_url=f"{JOB_URL}{index}")

        first = client.get("/api/applications", params={"limit": 1}).json()["items"][0]["id"]
        second = client.get("/api/applications", params={"limit": 1, "offset": 1}).json()["items"][
            0
        ]["id"]

        assert first != second


class TestDetailEndpoint:
    """One application, with its full history."""

    def test_the_detail_carries_the_history(self, client, session_factory):
        application_id = _track(session_factory)

        response = client.get(f"/api/applications/{application_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == application_id
        assert len(body["events"]) == 1
        assert body["events"][0]["event_type"] == "application_created"
        assert body["events"][0]["to_status"] == ApplicationStatus.PREPARED.value

    def test_the_history_is_ordered_by_the_event_id(self, client, session_factory):
        application_id = _track(session_factory, status=ApplicationStatus.AWAITING_APPROVAL)

        response = client.get(f"/api/applications/{application_id}")

        events = response.json()["events"]
        assert [event["id"] for event in events] == sorted(event["id"] for event in events)
        assert [event["to_status"] for event in events] == [
            ApplicationStatus.PREPARED.value,
            ApplicationStatus.AWAITING_APPROVAL.value,
        ]

    def test_an_unknown_application_is_a_404(self, client, session_factory):
        response = client.get("/api/applications/does-not-exist")

        assert response.status_code == 404


class TestStatusUpdateEndpoint:
    """A human records an outcome; the machine refuses what it must."""

    def test_a_human_can_record_an_interview(self, client, session_factory):
        application_id = _track(session_factory, status=ApplicationStatus.VERIFIED)

        response = client.patch(
            f"/api/applications/{application_id}/status",
            json={"status": "interview", "actor": human_actor("ada")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "interview"
        assert body["events"][-1]["actor"] == "human:ada"
        assert body["events"][-1]["to_status"] == "interview"

    def test_the_notes_are_stored(self, client, session_factory):
        application_id = _track(session_factory, status=ApplicationStatus.VERIFIED)

        response = client.patch(
            f"/api/applications/{application_id}/status",
            json={"status": "offer", "actor": human_actor("ada"), "notes": "offer received"},
        )

        assert response.status_code == 200
        assert response.json()["notes"] == "offer received"

    def test_an_illegal_transition_is_a_409(self, client, session_factory):
        application_id = _track(session_factory, status=ApplicationStatus.PREPARED)

        response = client.patch(
            f"/api/applications/{application_id}/status",
            json={"status": "offer", "actor": human_actor("ada")},
        )

        assert response.status_code == 409
        assert "cannot move" in response.json()["detail"]

    def test_the_agent_cannot_record_a_human_outcome(self, client, session_factory):
        application_id = _track(session_factory, status=ApplicationStatus.VERIFIED)

        response = client.patch(
            f"/api/applications/{application_id}/status",
            json={"status": "offer", "actor": "agent"},
        )

        assert response.status_code == 403
        assert "human outcome" in response.json()["detail"]

    def test_a_plain_name_is_refused_for_a_human_outcome(self, client, session_factory):
        application_id = _track(session_factory, status=ApplicationStatus.VERIFIED)

        response = client.patch(
            f"/api/applications/{application_id}/status",
            json={"status": "offer", "actor": "ada"},
        )

        assert response.status_code == 403

    def test_an_unknown_status_is_a_400(self, client, session_factory):
        application_id = _track(session_factory, status=ApplicationStatus.VERIFIED)

        response = client.patch(
            f"/api/applications/{application_id}/status",
            json={"status": "hired", "actor": human_actor("ada")},
        )

        assert response.status_code == 400
        assert "Unknown status" in response.json()["detail"]

    def test_an_unknown_application_is_a_404(self, client, session_factory):
        response = client.patch(
            "/api/applications/does-not-exist/status",
            json={"status": "interview", "actor": human_actor("ada")},
        )

        assert response.status_code == 404

    def test_a_refused_update_changes_nothing(self, client, session_factory):
        application_id = _track(session_factory, status=ApplicationStatus.VERIFIED)
        before = client.get(f"/api/applications/{application_id}").json()

        client.patch(
            f"/api/applications/{application_id}/status",
            json={"status": "offer", "actor": "agent", "notes": "should not be stored"},
        )

        body = client.get(f"/api/applications/{application_id}").json()
        assert body["status"] == "verified"
        assert body["notes"] is None
        # No event was appended either.
        assert len(body["events"]) == len(before["events"])

    def test_a_missing_actor_is_refused(self, client, session_factory):
        application_id = _track(session_factory, status=ApplicationStatus.VERIFIED)

        response = client.patch(
            f"/api/applications/{application_id}/status",
            json={"status": "interview"},
        )

        assert response.status_code == 422
