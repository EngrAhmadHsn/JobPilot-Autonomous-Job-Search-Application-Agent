"""End-to-end integration tests for the application workflow with fake-ATS adapter."""

import pytest

from src.applications.contracts import ApplicationRequest
from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter
from src.graph.application_workflow import build_application_workflow
from src.graph.state import ApplicationWorkflowState


def _invoke(graph, state: ApplicationWorkflowState) -> ApplicationWorkflowState:
    """Invoke the graph and rebuild the state dataclass from the returned dict.

    LangGraph 1.x returns invoke results as a dict of state fields and,
    with a checkpointer attached, requires a thread_id config.
    """
    raw = graph.invoke(state, config={"configurable": {"thread_id": state.workflow_id}})
    return ApplicationWorkflowState(**raw)


@pytest.fixture
def fake_ats_url():
    """Return a localhost URL for fake ATS testing."""
    return "http://localhost:8000/jobs/123"


@pytest.fixture
def sample_request(fake_ats_url):
    """Create a sample ApplicationRequest for fake-ATS testing."""
    return ApplicationRequest(
        job_title="Software Engineer",
        company_name="Tech Corp",
        job_url=fake_ats_url,
        candidate_name="Jane Doe",
        email="jane@example.com",
        phone="555-1234",
        resume_path="/path/to/resume.pdf",
        cover_letter="I am interested in this role",
        custom_fields={},
    )


@pytest.fixture
def fake_ats_adapter():
    """Create a FakeAtsPlaywrightAdapter instance."""
    return FakeAtsPlaywrightAdapter()


class TestWorkflowE2E:
    """End-to-end integration tests for the full workflow."""

    def test_workflow_graph_builds_successfully(self, fake_ats_adapter):
        """Test that the workflow graph builds and compiles."""
        graph = build_application_workflow(fake_ats_adapter)

        assert graph is not None
        # Compiled graph has an invoke method
        assert hasattr(graph, "invoke")

    def test_workflow_with_approval_false(self, sample_request, fake_ats_adapter):
        """Test workflow execution with approval=False (rejection at approval gate)."""
        graph = build_application_workflow(fake_ats_adapter)

        state = ApplicationWorkflowState(
            request=sample_request,
            approval_status=False,
            workflow_id="test-e2e-001",
            adapter_name="fake-ats-playwright",
        )

        # Execute workflow
        result_state = _invoke(graph, state)

        assert result_state.final_result is not None
        assert result_state.final_result.success is False
        assert result_state.final_result.status == "rejected"

    def test_workflow_prepare_node_called(self, sample_request, fake_ats_adapter):
        """Test that prepare node is called and updates state."""
        graph = build_application_workflow(fake_ats_adapter)

        state = ApplicationWorkflowState(
            request=sample_request,
            approval_status=False,  # Reject early to avoid submit
            workflow_id="test-e2e-02",
            adapter_name="fake-ats-playwright",
        )

        result_state = _invoke(graph, state)

        # Even with rejection, prepare should have run
        assert result_state.prepared_application is not None
        assert result_state.prepared_application.prepared_fields["candidate_name"] == "Jane Doe"

    def test_workflow_approval_gate_enforces_rejection(self, sample_request, fake_ats_adapter):
        """Test that approval gate blocks submission when approval=False."""
        graph = build_application_workflow(fake_ats_adapter)

        state = ApplicationWorkflowState(
            request=sample_request,
            approval_status=False,
            workflow_id="test-e2e-03",
            adapter_name="fake-ats-playwright",
        )

        result_state = _invoke(graph, state)

        # Submission should never be attempted if approval is False
        assert result_state.submission_result is None
        assert result_state.final_result is not None
        assert result_state.final_result.status == "rejected"

    def test_workflow_state_has_workflow_id_and_adapter_name(
        self, sample_request, fake_ats_adapter
    ):
        """Test that workflow state retains workflow_id and adapter_name."""
        graph = build_application_workflow(fake_ats_adapter)

        state = ApplicationWorkflowState(
            request=sample_request,
            approval_status=False,
            workflow_id="test-e2e-04",
            adapter_name="fake-ats-playwright",
        )

        result_state = _invoke(graph, state)

        assert result_state.workflow_id == "test-e2e-04"
        assert result_state.adapter_name == "fake-ats-playwright"

    def test_workflow_to_dict_serialization(self, sample_request):
        """Test that workflow state can be serialized to dict."""
        state = ApplicationWorkflowState(
            request=sample_request,
            approval_status=False,
            workflow_id="test-e2e-05",
            adapter_name="fake-ats-playwright",
        )

        state_dict = state.to_dict()

        assert state_dict["workflow_id"] == "test-e2e-05"
        assert state_dict["adapter_name"] == "fake-ats-playwright"
        assert state_dict["approval_status"] is False
        assert state_dict["request"]["job_title"] == "Software Engineer"

    def test_workflow_rejection_path_produces_final_result(self, sample_request, fake_ats_adapter):
        """Test that rejection path produces a consistent final result."""
        graph = build_application_workflow(fake_ats_adapter)

        state = ApplicationWorkflowState(
            request=sample_request,
            approval_status=False,
            workflow_id="test-e2e-06",
            adapter_name="fake-ats-playwright",
        )

        result_state = _invoke(graph, state)

        # Verify final_result is always set
        assert result_state.final_result is not None
        assert hasattr(result_state.final_result, "success")
        assert hasattr(result_state.final_result, "status")
        assert hasattr(result_state.final_result, "message")
