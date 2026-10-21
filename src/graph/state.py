"""LangGraph state definition for the application workflow."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.applications.contracts import (
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
)


@dataclass
class ApplicationWorkflowState:
    """State object passed through the LangGraph workflow.

    Tracks the progression of a single job application from request through
    preparation, approval, submission, and verification.
    """

    # Input: the original application request from the user
    request: ApplicationRequest

    # After prepare node: validated and structured payload
    prepared_application: PreparedApplication | None = None

    # Human approval gate: True = submit, False = reject, None = pending
    approval_status: bool | None = None

    # Approval decision metadata: who approved, when, reason
    approval_metadata: dict = field(default_factory=dict)

    # After submit node: the submitted application result (may not be verified yet)
    submission_result: ApplicationResult | None = None

    # After verify node: final verified result
    final_result: ApplicationResult | None = None

    # Workflow metadata
    workflow_id: str = ""
    adapter_name: str = ""
    # WS-06: the persisted approval this run is (or was) bound to.
    approval_id: str | None = None
    approver: str | None = None
    error: str | None = None
    error_details: dict | None = None

    def to_dict(self) -> dict:
        """Convert state to dictionary for serialization."""
        return {
            "workflow_id": self.workflow_id,
            "adapter_name": self.adapter_name,
            "request": {
                "job_title": self.request.job_title,
                "company_name": self.request.company_name,
                "job_url": self.request.job_url,
            },
            "approval_status": self.approval_status,
            "approval_metadata": self.approval_metadata,
            "has_prepared_application": self.prepared_application is not None,
            "has_submission_result": self.submission_result is not None,
            "has_final_result": self.final_result is not None,
            "error": self.error,
        }
