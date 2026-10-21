"""WS-06 · Phase E — the two-phase approval flow (SEC-05).

The property under test: **no submission happens without a recorded human
decision, and the payload that is submitted is the payload that was
approved.**
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.db.approval import (
    ApprovalRequestDB,
    ApprovalStatus,
    build_approval_row,
)
from src.db.base import Base
from src.graph.executor import execute_approved, prepare_application
from src.graph.nodes import approval_node
from src.graph.state import ApplicationWorkflowState


class RecordingAdapter(ApplicationAdapter):
    """An adapter that records the payload it was asked to submit."""

    name = "fake-ats-playwright"

    def __init__(self) -> None:
        self.submitted: PreparedApplication | None = None
        self.prepare_calls = 0

    def supports_url(self, url: str) -> bool:
        return url.startswith("http://localhost")

    def prepare(self, request: ApplicationRequest) -> PreparedApplication:
        self.prepare_calls += 1
        return PreparedApplication(
            request=request,
            prepared_fields={"candidate_name": request.candidate_name, "email": request.email},
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


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{(tmp_path / 'approval.db').as_posix()}")
    Base.metadata.create_all(engine, tables=[ApprovalRequestDB.__table__])
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def sample_request() -> ApplicationRequest:
    return ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url="http://localhost:8000/jobs/123/apply",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
    )


class TestApprovalRecord:
    """The approval record holds the payload a human reviewed."""

    def test_prepare_creates_a_pending_record(self, sample_request, db_session):
        adapter = RecordingAdapter()
        prepared = prepare_application(sample_request, adapter, workflow_id="wf-1")

        row = build_approval_row(workflow_id="wf-1", adapter_name=adapter.name, prepared=prepared)
        db_session.add(row)
        db_session.commit()

        assert row.status == ApprovalStatus.PENDING
        assert row.approver is None
        assert row.decided_at is None
        assert row.result is None
        assert row.job_url == sample_request.job_url
        assert row.adapter_name == "fake-ats-playwright"

    def test_the_payload_survives_a_round_trip(self, sample_request, db_session):
        adapter = RecordingAdapter()
        prepared = prepare_application(sample_request, adapter, workflow_id="wf-1")
        row = build_approval_row(workflow_id="wf-1", adapter_name=adapter.name, prepared=prepared)
        db_session.add(row)
        db_session.commit()
        db_session.expire_all()

        stored = db_session.get(ApprovalRequestDB, row.id)
        restored = PreparedApplication.model_validate(stored.payload)

        assert restored.request.job_url == prepared.request.job_url
        assert restored.prepared_fields == prepared.prepared_fields
        assert restored.workflow_id == "wf-1"


class TestApprovedExecution:
    """The approved payload is the submitted payload."""

    def test_execution_submits_the_persisted_payload(self, sample_request, db_session):
        adapter = RecordingAdapter()
        prepared = prepare_application(sample_request, adapter, workflow_id="wf-1")
        row = build_approval_row(workflow_id="wf-1", adapter_name=adapter.name, prepared=prepared)
        db_session.add(row)
        db_session.commit()

        restored = PreparedApplication.model_validate(row.payload)
        result = execute_approved(
            restored,
            adapter,
            workflow_id="wf-1",
            approval_id=row.id,
            approver="operator",
            decision_reason="looks good",
        )

        assert result.success is True
        assert result.status == "verified"
        # The adapter received the persisted payload, not a fresh one.
        assert adapter.submitted is not None
        assert adapter.submitted.prepared_fields == prepared.prepared_fields
        # And the payload was not rebuilt behind the approver's back.
        assert adapter.prepare_calls == 1

    def test_the_result_is_stored_on_the_record(self, sample_request, db_session):
        adapter = RecordingAdapter()
        prepared = prepare_application(sample_request, adapter, workflow_id="wf-3")
        row = build_approval_row(workflow_id="wf-3", adapter_name=adapter.name, prepared=prepared)
        db_session.add(row)
        db_session.commit()

        result = execute_approved(
            PreparedApplication.model_validate(row.payload),
            adapter,
            workflow_id="wf-3",
            approval_id=row.id,
            approver="operator",
        )

        row.result = result.model_dump(mode="json")
        row.status = ApprovalStatus.EXECUTED if result.success else ApprovalStatus.FAILED
        db_session.commit()
        db_session.expire_all()

        stored = db_session.scalars(select(ApprovalRequestDB)).one()
        assert stored.status == ApprovalStatus.EXECUTED
        assert stored.result is not None
        assert stored.result["success"] is True
        assert stored.result["status"] == "verified"


class TestApprovalNodeFailsClosed:
    """The in-graph approval node still rejects a missing decision."""

    def test_no_decision_means_rejection(self, sample_request):
        state = ApplicationWorkflowState(request=sample_request, workflow_id="wf-4")

        result_state = approval_node(state)

        assert result_state.approval_status is False
        assert "No explicit approval" in result_state.approval_metadata["reason"]

    def test_an_explicit_approval_is_honoured(self, sample_request):
        state = ApplicationWorkflowState(
            request=sample_request, workflow_id="wf-5", approval_status=True
        )

        result_state = approval_node(state)

        assert result_state.approval_status is True
