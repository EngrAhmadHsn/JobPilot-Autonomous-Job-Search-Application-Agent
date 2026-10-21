"""WS-06 · the applications API: prepare → approve → execute (SEC-05 / SEC-06).

The API is the outer edge of the approval gate, so the tests are written from
the outside: what a caller can and cannot do over HTTP.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.api.routes import applications as applications_route
from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.db.approval import ApprovalRequestDB, ApprovalStatus
from src.db.base import Base
from src.db.session import get_db
from src.main import app


class StubAdapter(ApplicationAdapter):
    """A fake ATS that never opens a browser."""

    name = "fake-ats-playwright"

    def __init__(self) -> None:
        self.submitted: PreparedApplication | None = None

    def supports_url(self, url: str) -> bool:
        return url.startswith("http://localhost")

    def prepare(self, request: ApplicationRequest) -> PreparedApplication:
        return PreparedApplication(
            request=request,
            prepared_fields={"candidate_name": request.candidate_name},
        )

    def submit(self, prepared: PreparedApplication) -> ApplicationResult:
        self.submitted = prepared
        return ApplicationResult(
            success=True,
            status="submitted",
            message="stub submission",
            evidence=SubmissionEvidence(
                url=prepared.request.job_url,
                confirmation_text="Application submitted",
                status="submitted",
            ),
        )

    def verify(self, result: ApplicationResult) -> ApplicationResult:
        return ApplicationResult(
            success=True,
            status="verified",
            message="verified",
            evidence=result.evidence,
        )


class DeniedAdapter(StubAdapter):
    """An adapter the registry holds no submit capability for."""

    name = "greenhouse"


@pytest.fixture
def session_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An isolated database for the approval records and the audit trail."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    # The audit writer and the evidence writer open their own session; point
    # them at the same isolated database.
    monkeypatch.setattr("src.db.session.SessionLocal", factory)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def stub_adapter(monkeypatch: pytest.MonkeyPatch) -> StubAdapter:
    adapter = StubAdapter()
    monkeypatch.setattr(applications_route, "AVAILABLE_ADAPTERS", [adapter])
    return adapter


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _payload(job_url: str = "http://localhost:8000/jobs/123/apply") -> dict:
    return {
        "job_title": "Senior Python Engineer",
        "company_name": "Acme Labs",
        "job_url": job_url,
        "candidate_name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+1 555 0101",
    }


class TestPrepareEndpoint:
    """Preparing records a pending approval and submits nothing."""

    def test_prepare_creates_a_pending_approval(
        self, client, session_factory, stub_adapter
    ) -> None:
        response = client.post("/api/applications/prepare", json=_payload())

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "awaiting_approval"
        assert body["approval_id"]
        assert body["workflow_id"]
        assert body["adapter_name"] == "fake-ats-playwright"
        assert body["prepared_summary"]["job_title"] == "Senior Python Engineer"
        # The summary lists the field names, not the candidate's values.
        assert body["prepared_summary"]["field_names"] == ["candidate_name"]
        assert "ada@example.com" not in response.text

        with session_factory() as session:
            row = session.scalars(select(ApprovalRequestDB)).one()
            assert row.status == ApprovalStatus.PENDING
            assert row.approver is None

    def test_prepare_does_not_submit(self, client, session_factory, stub_adapter) -> None:
        client.post("/api/applications/prepare", json=_payload())

        assert stub_adapter.submitted is None

    def test_prepare_rejects_a_non_allowlisted_host(
        self, client, session_factory, stub_adapter
    ) -> None:
        response = client.post(
            "/api/applications/prepare",
            json=_payload("https://evil-greenhouse.io.attacker.com/jobs/1"),
        )

        assert response.status_code == 400
        assert "allowlist" in response.json()["detail"].lower()

    def test_prepare_rejects_a_host_no_adapter_supports(
        self, client, session_factory, stub_adapter
    ) -> None:
        response = client.post(
            "/api/applications/prepare",
            json=_payload("https://boards.greenhouse.io/acme/jobs/1"),
        )

        assert response.status_code == 400
        assert "No adapter available" in response.json()["detail"]

    def test_the_old_submit_route_is_gone(self, client, session_factory, stub_adapter) -> None:
        """``POST /api/applications/submit`` no longer submits anything.

        The path now resolves to the read-only approval-status route, so the
        POST is rejected (405) and no adapter is ever asked to submit.
        """
        response = client.post("/api/applications/submit", json=_payload())

        assert response.status_code in (404, 405)
        assert stub_adapter.submitted is None


class TestApproveEndpoint:
    """Only an approved record may execute."""

    def test_approve_executes_the_approved_payload(
        self, client, session_factory, stub_adapter
    ) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        response = client.post(
            f"/api/applications/{prepared['approval_id']}/approve",
            json={"approver": "operator", "reason": "looks good"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is True
        assert body["status"] == "verified"
        assert body["evidence"]["confirmation_text"] == "Application submitted"
        # The submitted payload is the approved one.
        assert stub_adapter.submitted is not None
        assert stub_adapter.submitted.prepared_fields == {"candidate_name": "Ada Lovelace"}

        with session_factory() as session:
            row = session.get(ApprovalRequestDB, prepared["approval_id"])
            assert row.status == ApprovalStatus.EXECUTED
            assert row.approver == "operator"
            assert row.decision_reason == "looks good"
            assert row.decided_at is not None

    def test_approve_is_refused_without_an_approver(
        self, client, session_factory, stub_adapter
    ) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        response = client.post(
            f"/api/applications/{prepared['approval_id']}/approve", json={"approver": ""}
        )

        assert response.status_code == 422
        assert stub_adapter.submitted is None

    def test_a_second_decision_is_refused(self, client, session_factory, stub_adapter) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()
        client.post(
            f"/api/applications/{prepared['approval_id']}/approve", json={"approver": "operator"}
        )

        response = client.post(
            f"/api/applications/{prepared['approval_id']}/approve", json={"approver": "operator"}
        )

        assert response.status_code == 409
        assert "already decided" in response.json()["detail"]

    def test_approve_of_an_unknown_id_is_404(self, client, session_factory, stub_adapter) -> None:
        response = client.post(
            "/api/applications/does-not-exist/approve", json={"approver": "operator"}
        )

        assert response.status_code == 404

    def test_an_adapter_without_submit_permission_is_denied(
        self, client, session_factory, monkeypatch
    ) -> None:
        denied = DeniedAdapter()
        monkeypatch.setattr(applications_route, "AVAILABLE_ADAPTERS", [denied])

        prepared = client.post("/api/applications/prepare", json=_payload()).json()
        response = client.post(
            f"/api/applications/{prepared['approval_id']}/approve", json={"approver": "operator"}
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is False
        assert body["status"] == "permission_denied"
        assert denied.submitted is None


class TestRejectEndpoint:
    """A rejection ends the flow without a submission."""

    def test_reject_records_the_decision(self, client, session_factory, stub_adapter) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        response = client.post(
            f"/api/applications/{prepared['approval_id']}/reject",
            json={"approver": "operator", "reason": "wrong role"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == ApprovalStatus.REJECTED
        assert body["success"] is False
        assert stub_adapter.submitted is None

        with session_factory() as session:
            row = session.get(ApprovalRequestDB, prepared["approval_id"])
            assert row.status == ApprovalStatus.REJECTED
            assert row.approver == "operator"
            assert row.decision_reason == "wrong role"

    def test_a_rejected_request_cannot_be_approved_afterwards(
        self, client, session_factory, stub_adapter
    ) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()
        client.post(
            f"/api/applications/{prepared['approval_id']}/reject", json={"approver": "operator"}
        )

        response = client.post(
            f"/api/applications/{prepared['approval_id']}/approve", json={"approver": "operator"}
        )

        assert response.status_code == 409
        assert stub_adapter.submitted is None


class TestApprovalStatusEndpoint:
    """The stored state of an approval request is readable."""

    def test_status_of_a_pending_request(self, client, session_factory, stub_adapter) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        response = client.get(f"/api/applications/{prepared['approval_id']}")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == ApprovalStatus.PENDING
        assert body["job_title"] == "Senior Python Engineer"
        assert body["approver"] is None

    def test_status_of_an_unknown_request_is_404(
        self, client, session_factory, stub_adapter
    ) -> None:
        assert client.get("/api/applications/nope").status_code == 404
