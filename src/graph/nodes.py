"""LangGraph nodes for the application workflow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.applications.contracts import ApplicationResult
from src.applications.evidence import missing_evidence_files
from src.db.evidence import ApplicationEvidence
from src.security.registry_setup import get_registry

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.applications.contracts import ApplicationAdapter
    from src.db.applications import ApplicationDB
    from src.graph.state import ApplicationWorkflowState

logger = logging.getLogger(__name__)


def _tracking_session(session: Session | None) -> tuple[Session, bool]:
    """The session to write the tracking rows through, and whether we own it.

    The caller may inject a session (the API hands over its request-scoped
    one). When there is none, a short-lived session is opened — the WS-06
    fallback that lets the graph run without a request.
    """
    if session is not None:
        return session, False
    from src.db.session import SessionLocal

    return SessionLocal(), True


def _find_tracked_application(
    state: ApplicationWorkflowState, session: Session
) -> ApplicationDB | None:
    """The tracked application for this run, or ``None`` when it is not tracked.

    The lookup tries the ids the run carries: the application id, the
    approval id, then the workflow id. A run outside the API is simply not
    tracked — no error, and no invented row.
    """
    from src.applications.tracking import find_application

    for lookup in (
        {"application_id": state.application_id},
        {"approval_id": state.approval_id},
        {"workflow_id": state.workflow_id},
    ):
        if not any(lookup.values()):
            continue
        found = find_application(session, **lookup)
        if found is not None:
            return found
    return None


def _rollback_quietly(session: Session) -> None:
    """Discard a failed partial write without letting the rollback raise."""
    try:
        session.rollback()
    except Exception as exc:  # noqa: BLE001 - a failed rollback must not mask the cause
        logger.warning("Rollback after a tracking failure failed too: %s", exc)


def _tracked_application_or_none(
    state: ApplicationWorkflowState, session: Session
) -> ApplicationDB | None:
    """The tracked application for this run, or ``None``.

    A lookup failure is never fatal: the run simply is not tracked. The
    lookup is isolated from the writes that follow it, so a missing
    ``applications`` table can never cost a submission its evidence.
    """
    try:
        return _find_tracked_application(state, session)
    except Exception as exc:  # noqa: BLE001 - a failed lookup must not block the write
        logger.warning(
            f"[{state.workflow_id}] Tracking lookup failed (non-blocking): {exc!s}",
            extra={"workflow_id": state.workflow_id},
        )
        _rollback_quietly(session)
        return None


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
    state: ApplicationWorkflowState,
    adapter: ApplicationAdapter,
    *,
    session: Session | None = None,
) -> ApplicationWorkflowState:
    """Submit node: calls adapter.submit() to perform the actual submission.

    This node only runs if the application was approved by the approval gate.
    It calls adapter.submit(prepared_application) to execute the submission
    workflow (e.g., fill form, upload resume, click submit via Playwright).

    Args:
        state: Current workflow state (must include prepared_application and approval=True)
        adapter: The ApplicationAdapter instance
        session: An optional session for the WS-07 tracking writes. When it
            is omitted the node opens its own, as it always has.

    Returns:
        Updated state with submission_result populated

    Raises:
        ValueError if prepared_application is missing
        RuntimeError if adapter.submit() fails
    """
    if state.prepared_application is None:
        raise ValueError("Submit node requires a prepared application")

    # WS-06 · SEC-08: least privilege is enforced *before* the adapter is
    # called. An adapter without the submit capability is refused, and the
    # refusal is a result (never an exception escaping the node).
    if not get_registry().can_submit(adapter.name):
        message = f"Adapter {adapter.name!r} is not permitted to submit applications"
        logger.warning(
            f"[{state.workflow_id}] Permission denied for adapter {adapter.name}",
            extra={"workflow_id": state.workflow_id, "adapter": adapter.name},
        )
        state.submission_result = ApplicationResult(
            success=False,
            status="permission_denied",
            message=message,
            metadata={"workflow_id": state.workflow_id, "adapter": adapter.name},
        )
        state.error = message
        state.error_details = {"exception": "PermissionError", "message": message}
        return state

    try:
        logger.info(
            f"[{state.workflow_id}] Submitting application...",
            extra={"workflow_id": state.workflow_id},
        )
        result = adapter.submit(state.prepared_application)
        # Evidence DB integration (Phase 2 #4) + WS-07 tracking: store the
        # submission evidence and move the tracked application to SUBMITTED.
        # A failure here is logged and swallowed — a missing history must
        # never cost a submission.
        _record_submission(state, adapter, result, session)
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


def _record_submission(
    state: ApplicationWorkflowState,
    adapter: ApplicationAdapter,
    result: ApplicationResult,
    session: Session | None,
) -> None:
    """Store the submission evidence and move the application to SUBMITTED.

    A submission that did not succeed is **not** recorded as ``SUBMITTED``:
    the application stays where it is and the evidence of the attempt is
    recorded instead. Nothing here may raise — a tracking failure is logged,
    not propagated.

    The evidence write and the tracking writes are independent: neither can
    cost the other. The evidence is the record of what happened, and it must
    survive even when the tracking tables are unavailable.
    """
    tracking_session, owned = _tracking_session(session)
    try:
        app_row = _tracked_application_or_none(state, tracking_session)
        try:
            evidence_record = ApplicationEvidence(
                workflow_id=state.workflow_id,
                adapter_name=adapter.name,
                # The submit node refuses to run without a prepared payload.
                job_url=state.prepared_application.request.job_url,
                # WS-07: the evidence names the application it belongs to.
                application_id=app_row.id if app_row is not None else None,
                confirmation_text=result.evidence.confirmation_text if result.evidence else None,
                screenshot_path=result.evidence.screenshot_path if result.evidence else None,
                trace_path=result.evidence.trace_path if result.evidence else None,
                status=result.status,
                extra_metadata=result.metadata,
            )
            tracking_session.add(evidence_record)
            tracking_session.commit()
            logger.info(
                f"[{state.workflow_id}] Evidence recorded to DB (id={evidence_record.id})",
                extra={"workflow_id": state.workflow_id, "evidence_id": evidence_record.id},
            )
        except Exception as db_exc:  # noqa: BLE001 - evidence storage must never block submission
            logger.warning(
                f"[{state.workflow_id}] Evidence DB storage failed (non-blocking): {db_exc!s}",
                extra={"workflow_id": state.workflow_id},
            )
            _rollback_quietly(tracking_session)
            # The evidence write failed, but the **submission happened**.
            # Skipping the tracking writes would leave the application
            # claiming it was never submitted — an audit trail that
            # under-reports what the agent did. The two writes are
            # independent by contract, so the lifecycle is still recorded
            # and the event says the evidence is missing.
            evidence_record = None

        if app_row is None:
            return

        from src.applications.tracking import (
            AGENT_ACTOR,
            EVENT_EVIDENCE_RECORDED,
            ApplicationStatus,
            record_event,
            transition,
        )

        if result.success:
            transition(
                app_row,
                ApplicationStatus.SUBMITTED,
                actor=AGENT_ACTOR,
                db=tracking_session,
                application_url=result.evidence.url if result.evidence else None,
            )

        record_event(
            tracking_session,
            app_row.id,
            EVENT_EVIDENCE_RECORDED,
            actor=AGENT_ACTOR,
            metadata={
                "evidence_id": evidence_record.id if evidence_record is not None else None,
                "status": result.status,
                "success": result.success,
                "screenshot_path": (
                    evidence_record.screenshot_path if evidence_record is not None else None
                ),
                "trace_path": evidence_record.trace_path if evidence_record is not None else None,
                "evidence_stored": evidence_record is not None,
            },
        )
    except Exception as db_exc:  # noqa: BLE001 - tracking must never block submission
        logger.warning(
            f"[{state.workflow_id}] Tracking storage failed (non-blocking): {db_exc!s}",
            extra={"workflow_id": state.workflow_id},
        )
        _rollback_quietly(tracking_session)
    finally:
        if owned:
            tracking_session.close()


def verify_node(
    state: ApplicationWorkflowState,
    adapter: ApplicationAdapter,
    *,
    session: Session | None = None,
) -> ApplicationWorkflowState:
    """Verify node: calls adapter.verify() to confirm successful submission.

    This node runs after submission and calls adapter.verify(submission_result)
    to confirm that the submission was successful based on confirmation page
    content, redirect behavior, or other verification signals.

    Args:
        state: Current workflow state (must include submission_result)
        adapter: The ApplicationAdapter instance
        session: An optional session for the WS-07 tracking writes.

    Returns:
        Updated state with final_result populated and verified

    Raises:
        ValueError if submission_result is missing
    """
    if state.submission_result is None:
        raise ValueError("Verify node requires a submission result")

    # WS-06 · SEC-08: the verify capability is granted separately from submit.
    if not get_registry().can_verify(adapter.name):
        message = f"Adapter {adapter.name!r} is not permitted to verify applications"
        logger.warning(
            f"[{state.workflow_id}] Permission denied for adapter {adapter.name}",
            extra={"workflow_id": state.workflow_id, "adapter": adapter.name},
        )
        state.final_result = ApplicationResult(
            success=False,
            status="permission_denied",
            message=message,
            metadata={"workflow_id": state.workflow_id, "adapter": adapter.name},
        )
        state.error = message
        state.error_details = {"exception": "PermissionError", "message": message}
        return state

    try:
        logger.info(
            f"[{state.workflow_id}] Verifying submission...",
            extra={"workflow_id": state.workflow_id},
        )
        verified_result = adapter.verify(state.submission_result)

        # SEC-14: a result that claims evidence must have that evidence on
        # disk. A missing artifact downgrades the result — success is never
        # claimed without the artifacts that back it.
        missing = (
            missing_evidence_files(verified_result.evidence)
            if verified_result.evidence is not None
            else []
        )
        if missing:
            logger.error(
                "[%s] Verification failed: evidence artifacts are missing (%s)",
                state.workflow_id,
                ", ".join(missing),
                extra={"workflow_id": state.workflow_id},
            )
            verified_result = ApplicationResult(
                success=False,
                status="verification_failed",
                message=(
                    "The evidence artifacts are missing "
                    f"({', '.join(missing)}); the submission cannot be verified."
                ),
                evidence=verified_result.evidence,
                metadata=verified_result.metadata,
            )

        state.final_result = verified_result
    except Exception as e:
        logger.error(
            f"[{state.workflow_id}] Verify node failed: {e!s}",
            extra={"workflow_id": state.workflow_id, "error": str(e)},
        )
        state.error = f"Verification failed: {e!s}"
        state.error_details = {"exception": type(e).__name__, "message": str(e)}
        raise

    # WS-07: the tracked application follows the verification. A verified
    # application is VERIFIED; a failed verification moves it back to
    # AWAITING_APPROVAL with the reason attached. The tracking write is
    # outside the try above: it must never turn a result into a failure.
    _record_verification(state, verified_result, session)

    logger.info(
        f"[{state.workflow_id}] Verification complete: success={verified_result.success}",
        extra={"workflow_id": state.workflow_id, "success": verified_result.success},
    )
    return state


def _record_verification(
    state: ApplicationWorkflowState,
    result: ApplicationResult,
    session: Session | None,
) -> None:
    """Move the tracked application to VERIFIED, or back to AWAITING_APPROVAL."""
    tracking_session, owned = _tracking_session(session)
    try:
        app_row = _tracked_application_or_none(state, tracking_session)
        if app_row is None:
            return

        from src.applications.tracking import (
            AGENT_ACTOR,
            EVENT_VERIFICATION_FAILED,
            ApplicationStatus,
            transition,
        )

        if result.success:
            transition(
                app_row,
                ApplicationStatus.VERIFIED,
                actor=AGENT_ACTOR,
                db=tracking_session,
            )
        else:
            transition(
                app_row,
                ApplicationStatus.AWAITING_APPROVAL,
                actor=AGENT_ACTOR,
                db=tracking_session,
                event_type=EVENT_VERIFICATION_FAILED,
                metadata={"reason": result.message, "status": result.status},
            )
    except Exception as db_exc:  # noqa: BLE001 - tracking must never break the result
        logger.warning(
            f"[{state.workflow_id}] Verification tracking failed (non-blocking): {db_exc!s}",
            extra={"workflow_id": state.workflow_id},
        )
        _rollback_quietly(tracking_session)
    finally:
        if owned:
            tracking_session.close()
