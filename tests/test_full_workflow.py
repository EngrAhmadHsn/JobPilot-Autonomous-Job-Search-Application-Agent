"""Tests for Phase 6 full end-to-end job workflow."""

from src.graph.job_workflow import build_full_workflow
from src.jobs.linkedin_adapter import LinkedInAdapter


def test_full_workflow_builds():
    adapter = LinkedInAdapter()
    graph = build_full_workflow(adapter)
    assert graph is not None
    assert hasattr(graph, "invoke")
