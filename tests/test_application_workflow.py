"""Unit tests for LangGraph application workflow nodes and routing."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.applications.contracts import (
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.applications.tracking import (
    EVENT_EVIDENCE_RECORDED,
    EVENT_VERIFICATION_FAILED,
    ApplicationStatus,
    create_application,
)
from src.db.applications import ApplicationEventDB
from src.db.base import Base
from src.db.evidence import ApplicationEvidence
from src.graph.conditionals import should_submit_conditional, should_verify_conditional
from src.graph.nodes import approval_node, prepare_node, submit_node, verify_node
from src.graph.state import ApplicationWorkflowState


@pytest.fixture
def sample_request():
    """Create a sample ApplicationRequest for testing."""
    return ApplicationRequest(
        job_title="Software Engineer",
        company_name="Tech Corp",
        job_url="http://localhost:8000/jobs/123",
        candidate_name="Jane Doe",
        email="jane@example.com",
        phone="555-1234",
        resume_path="/path/to/resume.pdf",
        cover_letter="I am interested in this role",
        custom_fields={"location_preference": "Remote"},
    )


@pytest.fixture
def initial_state(sample_request):
    """Create initial workflow state."""
    return ApplicationWorkflowState(
        request=sample_request,
        workflow_id="test-001",
        adapter_name="fake-ats-playwright",
    )


@pytest.fixture
def mock_adapter(sample_request):
    """Create a mock ApplicationAdapter."""
    adapter = MagicMock()
    adapter.name = "fake-ats-playwright"

    # Mock prepare to return a PreparedApplication
    prepared = PreparedApplication(
        request=sample_request,
        prepared_fields={
            "candidate_name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "555-1234",
        },
        resume_path="/path/to/resume.pdf",
        cover_letter="I am interested in this role",
        requires_manual_review=False,
    )
    adapter.prepare = MagicMock(return_value=prepared)

    # Mock submit to return an ApplicationResult
    evidence = SubmissionEvidence(
        url="http://localhost:8000/confirmation",
        confirmation_text="Application submitted successfully",
        status="submitted",
    )
    submit_result = ApplicationResult(
        success=True,
        status="submitted",
        message="Form submitted successfully",
        evidence=evidence,
        metadata={"job_url": "http://localhost:8000/jobs/123"},
    )
    adapter.submit = MagicMock(return_value=submit_result)

    # Mock verify to return verified result
    verify_result = ApplicationResult(
        success=True,
        status="verified",
        message="Submission verified by confirmation page",
        evidence=evidence,
        metadata={"job_url": "http://localhost:8000/jobs/123"},
    )
    adapter.verify = MagicMock(return_value=verify_result)

    return adapter


class TestPrepareNode:
    """Tests for the prepare_node function."""

    def test_prepare_node_success(self, initial_state, mock_adapter, sample_request):
        """Test that prepare_node calls adapter.prepare and updates state."""
        mock_adapter.prepare.return_value = PreparedApplication(
            request=sample_request,
            prepared_fields={"candidate_name": "Jane Doe"},
            resume_path="/path/to/resume.pdf",
            cover_letter="Test letter",
            requires_manual_review=False,
        )

        result_state = prepare_node(initial_state, mock_adapter)

        assert result_state.prepared_application is not None
        assert result_state.prepared_application.prepared_fields["candidate_name"] == "Jane Doe"
        mock_adapter.prepare.assert_called_once_with(sample_request)

    def test_prepare_node_failure(self, initial_state, mock_adapter):
        """Test that prepare_node handles adapter errors gracefully."""
        mock_adapter.prepare.side_effect = ValueError("Invalid request")

        with pytest.raises(ValueError):
            prepare_node(initial_state, mock_adapter)

        assert initial_state.error is not None
        assert "Preparation failed" in initial_state.error


class TestApprovalNode:
    """Tests for the approval_node function."""

    def test_approval_node_already_approved(self, initial_state):
        """Test approval_node with pre-set approval_status=True."""
        initial_state.approval_status = True
        result_state = approval_node(initial_state)

        assert result_state.approval_status is True

    def test_approval_node_already_rejected(self, initial_state):
        """Test approval_node with pre-set approval_status=False."""
        initial_state.approval_status = False
        result_state = approval_node(initial_state)

        assert result_state.approval_status is False

    def test_approval_node_no_decision_defaults_to_reject(self, initial_state):
        """Test that approval_node defaults to rejection if no decision is set."""
        initial_state.approval_status = None
        result_state = approval_node(initial_state)

        assert result_state.approval_status is False
        assert "No explicit approval" in result_state.approval_metadata["reason"]


class TestSubmitNode:
    """Tests for the submit_node function."""

    def test_submit_node_success(self, initial_state, mock_adapter, sample_request):
        """Test that submit_node calls adapter.submit and captures result."""
        prepared = PreparedApplication(
            request=sample_request,
            prepared_fields={"candidate_name": "Jane Doe"},
            resume_path="/path/to/resume.pdf",
            cover_letter="Test",
            requires_manual_review=False,
        )
        initial_state.prepared_application = prepared

        evidence = SubmissionEvidence(
            url="http://localhost:8000/confirmation",
            confirmation_text="Application submitted",
            status="submitted",
        )
        submit_result = ApplicationResult(
            success=True,
            status="submitted",
            message="Form submitted",
            evidence=evidence,
            metadata={},
        )
        mock_adapter.submit.return_value = submit_result

        result_state = submit_node(initial_state, mock_adapter)

        assert result_state.submission_result is not None
        assert result_state.submission_result.status == "submitted"

    def test_submit_node_missing_prepared_application(self, initial_state, mock_adapter):
        """Test that submit_node raises if prepared_application is missing."""
        initial_state.prepared_application = None

        with pytest.raises(ValueError, match="requires a prepared application"):
            submit_node(initial_state, mock_adapter)


class TestVerifyNode:
    """Tests for the verify_node function."""

    def test_verify_node_success(self, initial_state, mock_adapter):
        """Test that verify_node calls adapter.verify and updates final_result."""
        evidence = SubmissionEvidence(
            url="http://localhost:8000/confirmation",
            confirmation_text="Application submitted",
            status="submitted",
        )
        submission_result = ApplicationResult(
            success=True,
            status="submitted",
            message="Form submitted",
            evidence=evidence,
            metadata={},
        )
        initial_state.submission_result = submission_result

        verified_result = ApplicationResult(
            success=True,
            status="verified",
            message="Submission verified",
            evidence=evidence,
            metadata={},
        )
        mock_adapter.verify.return_value = verified_result

        result_state = verify_node(initial_state, mock_adapter)

        assert result_state.final_result is not None
        assert result_state.final_result.status == "verified"

    def test_verify_node_missing_submission_result(self, initial_state, mock_adapter):
        """Test that verify_node raises if submission_result is missing."""
        initial_state.submission_result = None

        with pytest.raises(ValueError, match="requires a submission result"):
            verify_node(initial_state, mock_adapter)


class TestTrackingWiring:
    """WS-07: the nodes move the tracked application and record the evidence."""

    @pytest.fixture
    def db_session(self, tmp_path):
        engine = create_engine(f"sqlite:///{(tmp_path / 'workflow.db').as_posix()}")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            yield session
        engine.dispose()

    @pytest.fixture
    def tracked(self, db_session, sample_request):
        """A tracked application in AWAITING_APPROVAL, bound to the state."""
        app = create_application(
            db_session,
            workflow_id="test-001",
            adapter_name="fake-ats-playwright",
            job_url=sample_request.job_url,
            job_title=sample_request.job_title,
            company_name=sample_request.company_name,
        )
        from src.applications.tracking import transition

        transition(
            app,
            ApplicationStatus.AWAITING_APPROVAL,
            actor="agent",
            db=db_session,
        )
        return app

    def _prepared(self, sample_request):
        return PreparedApplication(
            request=sample_request,
            prepared_fields={"candidate_name": "Jane Doe"},
        )

    def _events(self, db_session, application_id):
        return list(
            db_session.scalars(
                select(ApplicationEventDB)
                .where(ApplicationEventDB.application_id == application_id)
                .order_by(ApplicationEventDB.id)
            )
        )

    def test_a_successful_submission_moves_the_application_to_submitted(
        self, db_session, tracked, initial_state, mock_adapter, sample_request
    ):
        initial_state.prepared_application = self._prepared(sample_request)
        initial_state.application_id = tracked.id

        submit_node(initial_state, mock_adapter, session=db_session)

        db_session.expire_all()
        assert tracked.status == ApplicationStatus.SUBMITTED.value
        assert tracked.submitted_at is not None
        assert tracked.application_url == "http://localhost:8000/confirmation"

    def test_the_submission_appends_one_event_per_move(
        self, db_session, tracked, initial_state, mock_adapter, sample_request
    ):
        initial_state.prepared_application = self._prepared(sample_request)
        initial_state.application_id = tracked.id

        submit_node(initial_state, mock_adapter, session=db_session)

        events = self._events(db_session, tracked.id)
        # One event per state change: created, awaiting approval, submitted.
        # The fourth entry is the evidence record, which is not a state change.
        moves = [event.to_status for event in events if event.to_status is not None]
        assert moves == [
            ApplicationStatus.PREPARED.value,
            ApplicationStatus.AWAITING_APPROVAL.value,
            ApplicationStatus.SUBMITTED.value,
        ]
        assert all(event.actor == "agent" for event in events)

    def test_the_evidence_row_is_linked_to_the_application(
        self, db_session, tracked, initial_state, mock_adapter, sample_request
    ):
        initial_state.prepared_application = self._prepared(sample_request)
        initial_state.application_id = tracked.id

        submit_node(initial_state, mock_adapter, session=db_session)

        evidence = db_session.scalars(select(ApplicationEvidence)).one()
        assert evidence.application_id == tracked.id
        assert evidence.workflow_id == "test-001"

    def test_the_evidence_row_carries_the_result_metadata(
        self, db_session, tracked, initial_state, mock_adapter, sample_request
    ):
        initial_state.prepared_application = self._prepared(sample_request)
        initial_state.application_id = tracked.id

        submit_node(initial_state, mock_adapter, session=db_session)

        evidence = db_session.scalars(select(ApplicationEvidence)).one()
        assert evidence.extra_metadata == {"job_url": "http://localhost:8000/jobs/123"}

    def test_the_evidence_is_recorded_as_an_event(
        self, db_session, tracked, initial_state, mock_adapter, sample_request
    ):
        initial_state.prepared_application = self._prepared(sample_request)
        initial_state.application_id = tracked.id

        submit_node(initial_state, mock_adapter, session=db_session)

        events = self._events(db_session, tracked.id)
        evidence_events = [e for e in events if e.event_type == EVENT_EVIDENCE_RECORDED]
        assert len(evidence_events) == 1
        assert evidence_events[0].extra_metadata["status"] == "submitted"

    def test_a_failed_submission_is_not_recorded_as_submitted(
        self, db_session, tracked, initial_state, mock_adapter, sample_request
    ):
        initial_state.prepared_application = self._prepared(sample_request)
        initial_state.application_id = tracked.id
        mock_adapter.submit.return_value = ApplicationResult(
            success=False,
            status="blocked_human_review",
            message="a CAPTCHA stood in the way",
            metadata={},
        )

        submit_node(initial_state, mock_adapter, session=db_session)

        db_session.expire_all()
        assert tracked.status == ApplicationStatus.AWAITING_APPROVAL.value
        assert tracked.submitted_at is None

    def test_a_successful_verification_moves_the_application_to_verified(
        self, db_session, tracked, initial_state, mock_adapter, sample_request
    ):
        initial_state.prepared_application = self._prepared(sample_request)
        initial_state.application_id = tracked.id
        submit_node(initial_state, mock_adapter, session=db_session)

        verify_node(initial_state, mock_adapter, session=db_session)

        db_session.expire_all()
        assert tracked.status == ApplicationStatus.VERIFIED.value
        assert tracked.verified_at is not None

    def test_a_failed_verification_moves_it_back_with_the_reason(
        self, db_session, tracked, initial_state, mock_adapter, sample_request
    ):
        initial_state.prepared_application = self._prepared(sample_request)
        initial_state.application_id = tracked.id
        submit_node(initial_state, mock_adapter, session=db_session)
        mock_adapter.verify.return_value = ApplicationResult(
            success=False,
            status="verification_failed",
            message="the confirmation text was not found",
            metadata={},
        )

        verify_node(initial_state, mock_adapter, session=db_session)

        db_session.expire_all()
        assert tracked.status == ApplicationStatus.AWAITING_APPROVAL.value
        events = self._events(db_session, tracked.id)
        failure = events[-1]
        assert failure.event_type == EVENT_VERIFICATION_FAILED
        assert failure.from_status == ApplicationStatus.SUBMITTED.value
        assert failure.to_status == ApplicationStatus.AWAITING_APPROVAL.value
        assert "confirmation text" in failure.extra_metadata["reason"]

    def test_the_nodes_work_without_a_database(self, initial_state, mock_adapter, sample_request):
        """A run outside the API is simply not tracked — and never breaks."""
        initial_state.prepared_application = self._prepared(sample_request)
        initial_state.submission_result = ApplicationResult(
            success=True, status="submitted", message="sent", metadata={}
        )

        result = submit_node(initial_state, mock_adapter)

        assert result.submission_result is not None
        result = verify_node(initial_state, mock_adapter)
        assert result.final_result is not None

    def test_an_untracked_run_writes_no_application(
        self, db_session, initial_state, mock_adapter, sample_request
    ):
        initial_state.prepared_application = self._prepared(sample_request)
        initial_state.application_id = "does-not-exist"

        submit_node(initial_state, mock_adapter, session=db_session)

        assert db_session.scalars(select(ApplicationEvidence)).one().application_id is None


class TestConditionals:
    def test_should_submit_conditional_approved(self, initial_state):
        """Test should_submit_conditional routes to submit when approved."""
        initial_state.approval_status = True
        result = should_submit_conditional(initial_state)

        assert result == "submit"

    def test_should_submit_conditional_rejected(self, initial_state):
        """Test should_submit_conditional routes to reject when not approved."""
        initial_state.approval_status = False
        result = should_submit_conditional(initial_state)

        assert result == "reject"

    def test_should_verify_conditional_success(self, initial_state):
        """Test should_verify_conditional routes to verify after successful submit."""
        evidence = SubmissionEvidence(
            url="http://localhost:8000/confirmation",
            confirmation_text="Application submitted",
            status="submitted",
        )
        initial_state.submission_result = ApplicationResult(
            success=True,
            status="submitted",
            message="Submitted",
            evidence=evidence,
            metadata={},
        )

        result = should_verify_conditional(initial_state)
        assert result == "verify"

    def test_should_verify_conditional_error(self, initial_state):
        """Test should_verify_conditional routes to end on submission error."""
        initial_state.error = "Submission failed"

        result = should_verify_conditional(initial_state)
        assert result == "end"

    def test_should_verify_conditional_no_submission(self, initial_state):
        """Test should_verify_conditional routes to end if no submission result."""
        initial_state.submission_result = None

        result = should_verify_conditional(initial_state)
        assert result == "end"
