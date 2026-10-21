"""LangGraph conditional routing functions for the application workflow."""

from __future__ import annotations

import logging
from typing import Literal

# Imported at runtime (not TYPE_CHECKING): LangGraph 1.x resolves conditional-edge
# type hints at graph-build time, so the state annotation must be resolvable.
from src.graph.state import ApplicationWorkflowState

logger = logging.getLogger(__name__)


def should_submit_conditional(state: ApplicationWorkflowState) -> Literal["submit", "reject"]:
    """Conditional router: decides whether to proceed with submission or reject.

    This conditional is evaluated after the approval node:
    - If approval_status is True, route to submit_node
    - If approval_status is False, route to reject handling (end workflow with failure)

    Args:
        state: Current workflow state

    Returns:
        "submit" to proceed to submit_node, "reject" to end workflow
    """
    approved = state.approval_status is True
    logger.info(
        f"[{state.workflow_id}] Approval conditional decision: {'APPROVED' if approved else 'REJECTED'}",
        extra={"workflow_id": state.workflow_id, "approved": approved},
    )
    return "submit" if approved else "reject"


def should_verify_conditional(state: ApplicationWorkflowState) -> Literal["verify", "end"]:
    """Conditional router: decides whether to proceed to verification or end.

    This conditional is evaluated after the submit node:
    - If submission succeeded (submission_result.success or no error), route to verify_node
    - If submission failed, route to end workflow with failure status

    A submission that did not succeed is **not** verified: there is nothing
    to verify, and re-verifying it would flatten the reason (a blocked
    challenge, an unsafe navigation, a permission denial) into a generic
    failure. The submission's own status is the answer.

    Args:
        state: Current workflow state

    Returns:
        "verify" to proceed to verify_node, "end" to terminate workflow
    """
    has_submission = state.submission_result is not None
    submission_failed = state.error is not None

    if submission_failed:
        logger.warning(
            f"[{state.workflow_id}] Submission failed, skipping verification",
            extra={"workflow_id": state.workflow_id, "error": state.error},
        )
        return "end"

    if not has_submission:
        logger.warning(
            f"[{state.workflow_id}] No submission result found, ending workflow",
            extra={"workflow_id": state.workflow_id},
        )
        return "end"

    if state.submission_result is not None and not state.submission_result.success:
        logger.warning(
            f"[{state.workflow_id}] Submission did not succeed (%s), skipping verification",
            state.submission_result.status,
            extra={"workflow_id": state.workflow_id, "status": state.submission_result.status},
        )
        return "end"

    logger.info(
        f"[{state.workflow_id}] Submission successful, proceeding to verification",
        extra={"workflow_id": state.workflow_id},
    )
    return "verify"
