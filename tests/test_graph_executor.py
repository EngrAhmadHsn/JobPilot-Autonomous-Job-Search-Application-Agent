"""Tests for the workflow executor and adapter selection logic (WS-06).

The executor has two entry points since WS-06: ``prepare_application`` builds
the payload for review, ``execute_approved`` executes a payload a human has
already approved. The second one must submit *the persisted payload* — the
prepare node is idempotent precisely so that a re-preparation cannot swap the
payload under the approver's feet.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.applications.contracts import (
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
)
from src.graph.executor import (
    execute_approved,
    prepare_application,
    select_adapter_for_url,
)
from src.graph.state import ApplicationWorkflowState


@pytest.fixture
def sample_request():
    """Create a sample ApplicationRequest."""
    return ApplicationRequest(
        job_title="Software Engineer",
        company_name="Tech Corp",
        job_url="http://localhost:8000/jobs/123",
        candidate_name="Jane Doe",
        email="jane@example.com",
        phone="555-1234",
        resume_path="/path/to/resume.pdf",
        cover_letter="Test letter",
        custom_fields={},
    )


@pytest.fixture
def mock_adapter():
    """Create a mock ApplicationAdapter."""
    adapter = MagicMock()
    adapter.name = "fake-ats-playwright"
    adapter.supports_url = MagicMock(return_value=True)
    return adapter


@pytest.fixture
def adapter_list():
    """Create a list of mock adapters."""
    adapter1 = MagicMock()
    adapter1.name = "adapter-1"
    adapter1.supports_url = MagicMock(return_value=False)

    adapter2 = MagicMock()
    adapter2.name = "adapter-2"
    adapter2.supports_url = MagicMock(return_value=True)

    adapter3 = MagicMock()
    adapter3.name = "adapter-3"
    adapter3.supports_url = MagicMock(return_value=False)

    return [adapter1, adapter2, adapter3]


class TestSelectAdapterForUrl:
    """Tests for the select_adapter_for_url function."""

    def test_select_adapter_first_match(self, adapter_list):
        """Test that select_adapter_for_url returns the first adapter that supports URL."""
        url = "http://example.com/jobs/123"

        adapter = select_adapter_for_url(url, adapter_list)

        assert adapter.name == "adapter-2"
        # Verify all adapters were checked in order
        adapter_list[0].supports_url.assert_called_once_with(url)
        adapter_list[1].supports_url.assert_called_once_with(url)
        # adapter-2 matched, so adapter-3 was never checked
        adapter_list[2].supports_url.assert_not_called()

    def test_select_adapter_no_match_raises_error(self, adapter_list):
        """Test that select_adapter_for_url raises RuntimeError if no adapter supports URL."""
        # Set all adapters to not support the URL
        for adapter in adapter_list:
            adapter.supports_url.return_value = False

        url = "http://unsupported.com/jobs/123"

        with pytest.raises(RuntimeError, match="No adapter supports URL"):
            select_adapter_for_url(url, adapter_list)

    def test_select_adapter_empty_list_raises_error(self):
        """Test that select_adapter_for_url raises if adapters list is empty."""
        url = "http://example.com/jobs/123"

        with pytest.raises(RuntimeError, match="No adapter supports URL"):
            select_adapter_for_url(url, [])

    def test_select_adapter_returns_correct_adapter(self, adapter_list):
        """Test that the returned adapter is the correct one."""
        for adapter in adapter_list:
            adapter.supports_url.return_value = False
        adapter_list[1].supports_url.return_value = True

        url = "http://example.com/jobs/123"

        adapter = select_adapter_for_url(url, adapter_list)

        assert adapter is adapter_list[1]


class TestPrepareApplication:
    """Preparing builds a payload; it never submits."""

    def test_prepare_stamps_the_workflow_id(self, sample_request, mock_adapter):
        mock_adapter.prepare.return_value = PreparedApplication(request=sample_request)

        result = prepare_application(sample_request, mock_adapter, workflow_id="wf-123")

        assert result.workflow_id == "wf-123"
        mock_adapter.prepare.assert_called_once_with(sample_request)

    def test_prepare_generates_a_workflow_id(self, sample_request, mock_adapter):
        mock_adapter.prepare.return_value = PreparedApplication(request=sample_request)

        result = prepare_application(sample_request, mock_adapter)

        assert result.workflow_id

    def test_prepare_is_refused_without_the_capability(self, sample_request):
        adapter = MagicMock()
        adapter.name = "rogue-adapter"

        with pytest.raises(PermissionError):
            prepare_application(sample_request, adapter)

        adapter.prepare.assert_not_called()


class TestExecuteApproved:
    """Execution runs the graph with the persisted, approved payload."""

    def test_execution_returns_result(self, sample_request, mock_adapter):
        with patch("src.graph.executor.build_application_workflow") as mock_build:
            mock_graph = MagicMock()
            mock_result_state = ApplicationWorkflowState(
                request=sample_request,
                final_result=ApplicationResult(
                    success=True,
                    status="verified",
                    message="Application submitted successfully",
                    metadata={"workflow_id": "test-001"},
                ),
            )
            mock_graph.invoke = MagicMock(return_value=mock_result_state)
            mock_build.return_value = mock_graph

            prepared = PreparedApplication(request=sample_request, workflow_id="wf-1")
            result = execute_approved(
                prepared,
                mock_adapter,
                workflow_id="wf-1",
                approval_id="ap-1",
                approver="operator",
            )

            assert isinstance(result, ApplicationResult)
            assert result.success is True
            assert result.status == "verified"

    def test_execution_restores_the_approved_payload(self, sample_request, mock_adapter):
        """The adapter must not re-prepare: the approved payload is submitted."""
        with patch("src.graph.executor.build_application_workflow") as mock_build:
            mock_graph = MagicMock()
            mock_result_state = ApplicationWorkflowState(
                request=sample_request,
                final_result=ApplicationResult(success=True, status="verified", message="ok"),
            )
            mock_graph.invoke = MagicMock(return_value=mock_result_state)
            mock_build.return_value = mock_graph

            prepared = PreparedApplication(request=sample_request, workflow_id="wf-1")
            execute_approved(
                prepared,
                mock_adapter,
                workflow_id="wf-1",
                approval_id="ap-1",
                approver="operator",
            )

            mock_adapter.prepare.assert_not_called()
            invoked_state = mock_graph.invoke.call_args.args[0]
            assert invoked_state.prepared_application is prepared
            assert invoked_state.approval_status is True
            assert invoked_state.approval_metadata["approver"] == "operator"
            assert invoked_state.approval_id == "ap-1"

    def test_execution_handles_no_final_result(self, sample_request, mock_adapter):
        with patch("src.graph.executor.build_application_workflow") as mock_build:
            mock_graph = MagicMock()
            mock_result_state = ApplicationWorkflowState(request=sample_request)
            mock_graph.invoke = MagicMock(return_value=mock_result_state)
            mock_build.return_value = mock_graph

            result = execute_approved(
                PreparedApplication(request=sample_request),
                mock_adapter,
                workflow_id="wf-1",
                approval_id="ap-1",
                approver="operator",
            )

            assert result.success is False
            assert result.status == "workflow_error"
            assert "without producing" in result.message

    def test_execution_handles_exception(self, sample_request, mock_adapter):
        with patch("src.graph.executor.build_application_workflow") as mock_build:
            mock_graph = MagicMock()
            mock_graph.invoke = MagicMock(side_effect=ValueError("Test error"))
            mock_build.return_value = mock_graph

            result = execute_approved(
                PreparedApplication(request=sample_request),
                mock_adapter,
                workflow_id="wf-1",
                approval_id="ap-1",
                approver="operator",
            )

            assert result.success is False
            assert result.status == "workflow_error"
            assert "Test error" in result.message

    def test_execution_uses_the_given_adapter(self, sample_request, mock_adapter):
        with patch("src.graph.executor.build_application_workflow") as mock_build:
            mock_graph = MagicMock()
            mock_result_state = ApplicationWorkflowState(
                request=sample_request,
                final_result=ApplicationResult(success=True, status="verified", message="Success"),
            )
            mock_graph.invoke = MagicMock(return_value=mock_result_state)
            mock_build.return_value = mock_graph

            execute_approved(
                PreparedApplication(request=sample_request),
                mock_adapter,
                workflow_id="wf-1",
                approval_id="ap-1",
                approver="operator",
            )

            mock_build.assert_called_once_with(mock_adapter, session=None)
