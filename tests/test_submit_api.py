"""WS-06 · the applications API: prepare → approve → execute (SEC-05 / SEC-06).

The API is the outer edge of the approval gate, so the tests are written from
the outside: what a caller can and cannot do over HTTP.

**WS-32 split the flow across two processes.** ``POST /approve`` records the
human decision and *accepts* the submission as durable work; the worker then
performs it. So the HTTP-level tests here assert the decision, the acceptance
and the guards, and the assertions that used to read the submission's result
off the approve response now read it off the approval row after the queue has
been drained (``_drain_submissions``). The properties they existed for — the
approved payload is the submitted payload, the decision is attributed to the
principal, a denied adapter never reaches submit — are all still asserted; only
the process that performs the call changed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.applications.tracking import ApplicationStatus
from src.db.applications import ApplicationDB, ApplicationEventDB
from src.db.approval import ApprovalRequestDB, ApprovalStatus
from src.db.base import Base
from src.db.evidence import ApplicationEvidence
from src.db.jobs import JobDB
from src.db.session import get_db
from src.db.users import LEGACY_OWNER_ID
from src.graph import executor as graph_executor
from src.main import app
from src.runs.worker import Worker


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
    """Install one stub as the whole adapter registry (WS-32).

    The registry lives in ``src.graph.executor`` now, and both the route and
    the worker resolve from it, so replacing it here is what makes the
    ``prepare`` request and the later ``drain`` call agree about the adapter —
    which is the property the two-call flow depends on.
    """
    adapter = StubAdapter()
    monkeypatch.setattr(graph_executor, "AVAILABLE_ADAPTERS", [adapter])
    return adapter


@pytest.fixture
def drain(session_factory):
    """Run the real worker once, performing any queued submission (WS-32).

    This is the second process the approve route now defers to. The tests call
    it explicitly so that "the request accepted the work" and "the work was
    done" stay separate assertions — the distinction the whole task exists for.
    """

    def run() -> None:
        worker = Worker(
            worker_id="w-submit-api",
            session_factory=session_factory,
            sleep=lambda _seconds: None,
            lease_seconds=0.0,
        )
        worker.run_once()

    return run


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
    """Only an approved record may execute — and the request only *accepts* it.

    WS-32: the approve returns 202 with the accepted run, and the submission
    happens when the worker drains the queue. The tests below therefore make
    two calls where they used to make one: ``approve`` (the decision) and
    ``drain`` (the execution).
    """

    def test_approve_accepts_the_submission_and_the_worker_executes_it(
        self, client, session_factory, stub_adapter, drain
    ) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        response = client.post(
            f"/api/applications/{prepared['approval_id']}/approve",
            json={"approver": "operator", "reason": "looks good"},
        )

        # The request accepts: 202 and a run id, and nothing has been submitted.
        assert response.status_code == 202, response.text
        accepted = response.json()
        assert accepted["run_id"]
        assert accepted["success"] is False
        assert "submitted" not in accepted["status"].lower()
        assert stub_adapter.submitted is None, (
            "the request thread submitted the application; that is the behaviour WS-32 removed"
        )

        # The decision is durable before the work is done.
        with session_factory() as session:
            row = session.get(ApprovalRequestDB, prepared["approval_id"])
            assert row.status == ApprovalStatus.APPROVED
            assert row.result is None
            # WS-14 · A2 (T2): the approver is the **authenticated
            # principal**, not the name the body supplied.
            assert row.approver == LEGACY_OWNER_ID
            assert row.decision_reason == "looks good"
            assert row.decided_at is not None

        drain()

        with session_factory() as session:
            row = session.get(ApprovalRequestDB, prepared["approval_id"])
            assert row.status == ApprovalStatus.EXECUTED
            assert row.result is not None
            assert row.result["status"] == "verified"
            assert row.result["evidence"]["confirmation_text"] == "Application submitted"
        # The submitted payload is the approved one — the worker restores the
        # payload from the approval row, so this is the WS-06 property intact.
        assert stub_adapter.submitted is not None
        assert stub_adapter.submitted.prepared_fields == {"candidate_name": "Ada Lovelace"}

    def test_a_body_supplied_approver_is_ignored(
        self, client, session_factory, stub_adapter
    ) -> None:
        """A caller cannot approve an application *as somebody else*.

        The approver is the authenticated principal. A body that names
        somebody else is ignored, and the approval is recorded under the
        principal.
        """
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        response = client.post(
            f"/api/applications/{prepared['approval_id']}/approve",
            json={"approver": "somebody-else", "reason": "looks good"},
        )

        assert response.status_code == 202, response.text
        with session_factory() as session:
            row = session.get(ApprovalRequestDB, prepared["approval_id"])
            assert row.approver == LEGACY_OWNER_ID
            assert row.approver != "somebody-else"

    def test_an_approval_without_a_body_approver_is_accepted(
        self, client, session_factory, stub_adapter, drain
    ) -> None:
        """The approver is no longer a required field: the principal is
        always there, so asking for it in the body is redundant."""
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        response = client.post(
            f"/api/applications/{prepared['approval_id']}/approve", json={"reason": "looks good"}
        )

        assert response.status_code == 202, response.text
        with session_factory() as session:
            row = session.get(ApprovalRequestDB, prepared["approval_id"])
            assert row.approver == LEGACY_OWNER_ID

        drain()
        assert stub_adapter.submitted is not None

    def test_a_second_decision_is_refused(self, client, session_factory, stub_adapter) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()
        first = client.post(
            f"/api/applications/{prepared['approval_id']}/approve", json={"approver": "operator"}
        )
        assert first.status_code == 202, first.text

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

    def test_an_adapter_without_submit_permission_never_reaches_submit(
        self, client, session_factory, monkeypatch, drain
    ) -> None:
        """The capability gate still refuses — now on the worker thread.

        WS-06 · SEC-08 is enforced in the submit node, which the worker runs,
        so this is where the refusal lands. The work is accepted (the queue
        does not know about capabilities) and the *submission* is refused: the
        approval row ends ``FAILED`` with the permission_denied status, and the
        adapter is never asked to submit.
        """
        denied = DeniedAdapter()
        monkeypatch.setattr(graph_executor, "AVAILABLE_ADAPTERS", [denied])

        prepared = client.post("/api/applications/prepare", json=_payload()).json()
        response = client.post(
            f"/api/applications/{prepared['approval_id']}/approve", json={"approver": "operator"}
        )

        assert response.status_code == 202, response.text
        assert denied.submitted is None

        drain()

        assert denied.submitted is None, "an adapter without the capability was asked to submit"
        with session_factory() as session:
            row = session.get(ApprovalRequestDB, prepared["approval_id"])
            assert row.status == ApprovalStatus.FAILED
            assert row.result is not None
            assert row.result["status"] == "permission_denied"


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
            # WS-14 · A2 (T2): the approver is the authenticated principal.
            assert row.approver == LEGACY_OWNER_ID
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


class TestTrackedApplication:
    """WS-07: the prepare → approve → submit → verify flow is tracked."""

    def test_the_prepare_response_carries_an_application_id(
        self, client, session_factory, stub_adapter
    ) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        assert prepared["application_id"]

        with session_factory() as session:
            row = session.get(ApplicationDB, prepared["application_id"])
            assert row is not None
            assert row.status == ApplicationStatus.AWAITING_APPROVAL.value
            assert row.approval_id == prepared["approval_id"]
            assert row.workflow_id == prepared["workflow_id"]
            assert row.job_title == "Senior Python Engineer"

    def test_the_job_row_always_resolves(self, client, session_factory, stub_adapter) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        with session_factory() as session:
            row = session.get(ApplicationDB, prepared["application_id"])
            job = session.get(JobDB, row.job_id)
            assert job is not None
            assert job.application_url == _payload()["job_url"]

    def test_the_application_traverses_the_whole_lifecycle(
        self, client, session_factory, stub_adapter, drain
    ) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        response = client.post(
            f"/api/applications/{prepared['approval_id']}/approve",
            json={"approver": "operator", "reason": "looks good"},
        )
        assert response.status_code == 202, response.text
        # The decision is recorded, but the application is not submitted yet:
        # the agent has not performed the submission, so it stays where it was
        # when the human approved it.
        with session_factory() as session:
            row = session.get(ApplicationDB, prepared["application_id"])
            assert row.status == ApplicationStatus.AWAITING_APPROVAL.value
            assert row.submitted_at is None

        drain()

        with session_factory() as session:
            row = session.get(ApplicationDB, prepared["application_id"])
            assert row.status == ApplicationStatus.VERIFIED.value
            assert row.submitted_at is not None
            assert row.verified_at is not None

            events = list(
                session.scalars(
                    select(ApplicationEventDB)
                    .where(ApplicationEventDB.application_id == row.id)
                    .order_by(ApplicationEventDB.id)
                )
            )
            moves = [event.to_status for event in events if event.to_status is not None]
            assert moves == [
                ApplicationStatus.PREPARED.value,
                ApplicationStatus.AWAITING_APPROVAL.value,
                ApplicationStatus.SUBMITTED.value,
                ApplicationStatus.VERIFIED.value,
            ]
            # The decision and the evidence are recorded too.
            assert any(event.event_type == "approval_granted" for event in events)
            assert any(event.event_type == "evidence_recorded" for event in events)

    def test_the_evidence_row_is_linked_to_the_application(
        self, client, session_factory, stub_adapter, drain
    ) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()
        client.post(
            f"/api/applications/{prepared['approval_id']}/approve",
            json={"approver": "operator"},
        )
        drain()

        with session_factory() as session:
            evidence = session.scalars(select(ApplicationEvidence)).one()
            assert evidence.application_id == prepared["application_id"]

    def test_a_rejection_moves_the_application_to_rejected(
        self, client, session_factory, stub_adapter
    ) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        response = client.post(
            f"/api/applications/{prepared['approval_id']}/reject",
            json={"approver": "operator", "reason": "wrong role"},
        )
        assert response.status_code == 200, response.text

        with session_factory() as session:
            row = session.get(ApplicationDB, prepared["application_id"])
            assert row.status == ApplicationStatus.REJECTED.value

            events = list(
                session.scalars(
                    select(ApplicationEventDB)
                    .where(ApplicationEventDB.application_id == row.id)
                    .order_by(ApplicationEventDB.id)
                )
            )
            rejection = events[-1]
            assert rejection.event_type == "approval_rejected"
            # WS-14 · A2 (T2): the human actor is the authenticated
            # principal, not the name the body supplied.
            assert rejection.actor == f"human:{LEGACY_OWNER_ID}"
            assert rejection.from_status == ApplicationStatus.AWAITING_APPROVAL.value
            assert rejection.to_status == ApplicationStatus.REJECTED.value

    def test_the_tracking_detail_is_readable_over_http(
        self, client, session_factory, stub_adapter
    ) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        response = client.get(f"/api/applications/{prepared['application_id']}")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == ApplicationStatus.AWAITING_APPROVAL.value
        assert len(body["events"]) == 2


class TestApprovalStatusEndpoint:
    """The stored state of an approval request is readable."""

    def test_status_of_a_pending_request(self, client, session_factory, stub_adapter) -> None:
        prepared = client.post("/api/applications/prepare", json=_payload()).json()

        response = client.get(f"/api/applications/approvals/{prepared['approval_id']}")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == ApprovalStatus.PENDING
        assert body["job_title"] == "Senior Python Engineer"
        assert body["approver"] is None

    def test_status_of_an_unknown_request_is_404(
        self, client, session_factory, stub_adapter
    ) -> None:
        assert client.get("/api/applications/approvals/nope").status_code == 404
