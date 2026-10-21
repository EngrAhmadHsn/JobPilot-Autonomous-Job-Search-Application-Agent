"""LangGraph nodes for the application workflow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.applications.contracts import ApplicationResult

if TYPE_CHECKING:
    from src.applications.contracts import ApplicationAdapter
    from src.graph.state import ApplicationWorkflowState

logger = logging.getLogger(__name__)


def prepare_node(
    state: ApplicationWorkflowState, adapter: ApplicationAdapter
) -> ApplicationWorkflowState:
    """Prepare node: validates request and builds structured payload via adapter.

    This node calls adapter.prepare() to transform the raw ApplicationRequest into
    a PreparedApplication with validated fields and structure.

    The node is **idempotent** (WS-06): when the state already carries a
    prepared application, that payload is reused instead of being rebuilt.
    Phase two of the approval flow restores the payload a human approved from
    the approval record; re-preparing it here could submit something the
    approver never saw.

    Args:
        state: Current workflow state
        adapter: The ApplicationAdapter instance (selected based on job URL)

    Returns:
        Updated state with prepared_application field populated

    Raises:
        ValueError if adapter.prepare() fails
    """
    if state.prepared_application is not None:
        logger.info(
            f"[{state.workflow_id}] Reusing the persisted prepared application",
            extra={"workflow_id": state.workflow_id, "adapter": adapter.name},
        )
        return state

    try:
        logger.info(
            f"[{state.workflow_id}] Preparing application for {state.request.company_name}",
            extra={"workflow_id": state.workflow_id, "job_url": state.request.job_url},
        )
        prepared = adapter.prepare(state.request)
        prepared.workflow_id = state.workflow_id or prepared.workflow_id
        state.prepared_application = prepared
        logger.info(
            f"[{state.workflow_id}] Application prepared successfully",
            extra={"workflow_id": state.workflow_id},
        )
        return state
    except Exception as e:
        logger.error(
            f"[{state.workflow_id}] Prepare node failed: {e!s}",
            extra={"workflow_id": state.workflow_id, "error": str(e)},
        )
        state.error = f"Preparation failed: {e!s}"
        state.error_details = {"exception": type(e).__name__, "message": str(e)}
        raise


def approval_node(state: ApplicationWorkflowState) -> ApplicationWorkflowState:
    """Approval node: implements human approval gate for submissions.

    This node checks the approval_status flag. In a real system, this would:
    - Call a webhook or check a queue for human approval
    - Wait for explicit approval from an authorized user
    - Record approval metadata (user, timestamp, reason for approval/rejection)

    For testing, the approval_status can be pre-set on the state or configured
    via approval_metadata.

    Args:
        state: Current workflow state

    Returns:
        Updated state with approval decision recorded
    """
    logger.info(
        f"[{state.workflow_id}] Approval node: checking approval status",
        extra={"workflow_id": state.workflow_id},
    )

    # If approval_status was already set (e.g., by test or preset), use it
    if state.approval_status is None:
        # In a production system, this would be a webhook call or queue check
        # For now, default to requiring explicit approval before proceeding
        logger.warning(
            f"[{state.workflow_id}] No approval decision found; defaulting to rejection",
            extra={"workflow_id": state.workflow_id},
        )
        state.approval_status = False
        state.approval_metadata["reason"] = "No explicit approval provided"
    else:
        logger.info(
            f"[{state.workflow_id}] Approval decision: {state.approval_status}",
            extra={"workflow_id": state.workflow_id, "approved": state.approval_status},
        )

    return state


def submit_node(
    state: ApplicationWorkflowState, adapter: ApplicationAdapter
) -> ApplicationWorkflowState:
    """Submit node: calls adapter.submit() to perform the actual submission.

    This node only runs if the application was approved by the approval gate.
    It calls adapter.submit(prepared_application) to execute the submission
    workflow (e.g., fill form, upload resume, click submit via Playwright).

    Args:
        state: Current workflow state (must include prepared_application and approval=True)
        adapter: The ApplicationAdapter instance

    Returns:
        Updated state with submission_result populated

    Raises:
        ValueError if prepared_application is missing
        RuntimeError if adapter.submit() fails
    """
    if state.prepared_application is None:
        raise ValueError("Submit node requires a prepared application")

    try:
        logger.info(
            f"[{state.workflow_id}] Submitting application...",
            extra={"workflow_id": state.workflow_id},
        )
        result = adapter.submit(state.prepared_application)
        # Evidence DB integration (Phase 2 #4): store submission evidence
        try:
            from src.db.evidence import ApplicationEvidence
            from src.db.session import SessionLocal

            with SessionLocal() as session:
                evidence_record = ApplicationEvidence(
                    workflow_id=state.workflow_id,
                    adapter_name=adapter.name,
                    job_url=state.prepared_application.request.job_url,
                    confirmation_text=result.evidence.confirmation_text
                    if result.evidence
                    else None,
                    screenshot_path=result.evidence.screenshot_path if result.evidence else None,
                    trace_path=result.evidence.trace_path if result.evidence else None,
                    status=result.status,
                    metadata=result.metadata,
                )
                session.add(evidence_record)
                session.commit()
                logger.info(
                    f"[{state.workflow_id}] Evidence recorded to DB (id={evidence_record.id})",
                    extra={
                        "workflow_id": state.workflow_id,
                        "evidence_id": evidence_record.id,
                    },
                )
        except Exception as db_exc:  # noqa: BLE001 - evidence storage must never block submission
            logger.warning(
                f"[{state.workflow_id}] Evidence DB storage failed (non-blocking): {db_exc!s}",
                extra={"workflow_id": state.workflow_id},
            )
        state.submission_result = result
        logger.info(
            f"[{state.workflow_id}] Submission completed with status: {result.status}",
            extra={"workflow_id": state.workflow_id, "status": result.status},
        )
        return state
    except Exception as e:
        logger.error(
            f"[{state.workflow_id}] Submit node failed: {e!s}",
            extra={"workflow_id": state.workflow_id, "error": str(e)},
        )
        state.error = f"Submission failed: {e!s}"
        state.error_details = {"exception": type(e).__name__, "message": str(e)}
        raise


def verify_node(
    state: ApplicationWorkflowState, adapter: ApplicationAdapter
) -> ApplicationWorkflowState:
    """Verify node: calls adapter.verify() to confirm successful submission.

    This node runs after submission and calls adapter.verify(submission_result)
    to confirm that the submission was successful based on confirmation page
    content, redirect behavior, or other verification signals.

    Args:
        state: Current workflow state (must include submission_result)
        adapter: The ApplicationAdapter instance

    Returns:
        Updated state with final_result populated and verified

    Raises:
        ValueError if submission_result is missing
    """
    if state.submission_result is None:
        raise ValueError("Verify node requires a submission result")

    try:
        logger.info(
            f"[{state.workflow_id}] Verifying submission...",
            extra={"workflow_id": state.workflow_id},
        )
        verified_result = adapter.verify(state.submission_result)

        state.final_result = verified_result
        logger.info(
            f"[{state.workflow_id}] Verification complete: success={verified_result.success}",
            extra={"workflow_id": state.workflow_id, "success": verified_result.success},
        )
        return state
    except Exception as e:
        logger.error(
            f"[{state.workflow_id}] Verify node failed: {e!s}",
            extra={"workflow_id": state.workflow_id, "error": str(e)},
        )
        state.error = f"Verification failed: {e!s}"
        state.error_details = {"exception": type(e).__name__, "message": str(e)}
        raise
