"""Tests for the workflow executor and adapter selection logic."""

from unittest.mock import MagicMock, patch

import pytest

from src.applications.contracts import ApplicationRequest, ApplicationResult
from src.graph.executor import execute_application_workflow, select_adapter_for_url
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
    adapter.name = "test-adapter"
    adapter.supports_url = MagicMock(return_value=True)

    # Make it an async context manager mock if needed
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
        # Only adapter-2 supports the URL
        for adapter in adapter_list:
            adapter.supports_url.return_value = False
        adapter_list[1].supports_url.return_value = True

        url = "http://example.com/jobs/123"
        adapter = select_adapter_for_url(url, adapter_list)

        assert adapter is adapter_list[1]


class TestExecuteApplicationWorkflow:
    """Tests for the execute_application_workflow function."""

    def test_workflow_execution_returns_result(self, sample_request, mock_adapter):
        """Test that execute_application_workflow returns an ApplicationResult."""
        # Mock the build_application_workflow to return a simple graph
        with patch("src.graph.executor.build_application_workflow") as mock_build:
            mock_graph = MagicMock()

            # Real state instance: the executor distinguishes state vs dict results
            mock_result_state = ApplicationWorkflowState(
                request=sample_request,
                final_result=ApplicationResult(
                    success=True,
                    status="verified",
                    message="Application submitted successfully",
                    metadata={"workflow_id": "test-001"},
                ),
            )

            # Configure the graph.invoke() to return our mock state
            mock_graph.invoke = MagicMock(return_value=mock_result_state)
            mock_build.return_value = mock_graph

            result = execute_application_workflow(
                request=sample_request,
                adapter=mock_adapter,
                approval=True,
            )

            assert result is not None
            assert isinstance(result, ApplicationResult)
            assert result.success is True
            assert result.status == "verified"

    def test_workflow_execution_with_rejection(self, sample_request, mock_adapter):
        """Test workflow execution when application is rejected."""
        with patch("src.graph.executor.build_application_workflow") as mock_build:
            mock_graph = MagicMock()

            mock_result_state = ApplicationWorkflowState(
                request=sample_request,
                final_result=ApplicationResult(
                    success=False,
                    status="rejected",
                    message="Application rejected at approval gate",
                    metadata={},
                ),
            )

            mock_graph.invoke = MagicMock(return_value=mock_result_state)
            mock_build.return_value = mock_graph

            result = execute_application_workflow(
                request=sample_request,
                adapter=mock_adapter,
                approval=False,
            )

            assert result.success is False
            assert result.status == "rejected"

    def test_workflow_execution_handles_no_final_result(self, sample_request, mock_adapter):
        """Test that executor handles case where final_result is not set."""
        with patch("src.graph.executor.build_application_workflow") as mock_build:
            mock_graph = MagicMock()

            # Simulate a workflow that doesn't set final_result (should not happen, but defensive)
            mock_result_state = ApplicationWorkflowState(request=sample_request)

            mock_graph.invoke = MagicMock(return_value=mock_result_state)
            mock_build.return_value = mock_graph

            result = execute_application_workflow(
                request=sample_request,
                adapter=mock_adapter,
                approval=True,
            )

            assert result.success is False
            assert result.status == "workflow_error"
            assert "without producing" in result.message

    def test_workflow_execution_handles_exception(self, sample_request, mock_adapter):
        """Test that executor handles exceptions gracefully."""
        with patch("src.graph.executor.build_application_workflow") as mock_build:
            # Simulate graph.invoke() raising an exception
            mock_graph = MagicMock()
            mock_graph.invoke = MagicMock(side_effect=ValueError("Test error"))
            mock_build.return_value = mock_graph

            result = execute_application_workflow(
                request=sample_request,
                adapter=mock_adapter,
                approval=True,
            )

            assert result.success is False
            assert result.status == "workflow_error"
            assert "Test error" in result.message

    def test_workflow_execution_uses_correct_adapter(self, sample_request, mock_adapter):
        """Test that execute_application_workflow uses the provided adapter."""
        with patch("src.graph.executor.build_application_workflow") as mock_build:
            mock_graph = MagicMock()

            mock_result_state = ApplicationWorkflowState(
                request=sample_request,
                final_result=ApplicationResult(
                    success=True,
                    status="verified",
                    message="Success",
                    metadata={},
                ),
            )

            mock_graph.invoke = MagicMock(return_value=mock_result_state)
            mock_build.return_value = mock_graph

            result = execute_application_workflow(
                request=sample_request,
                adapter=mock_adapter,
                approval=True,
            )

            assert result.success is True

            # Verify build_application_workflow was called with the adapter
            mock_build.assert_called_once_with(mock_adapter)
