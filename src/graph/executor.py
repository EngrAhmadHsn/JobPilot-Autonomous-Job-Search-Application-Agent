"""Executor for the application workflow: glues adapter + graph + result handling.

The executor has two entry points, and the split is the point (WS-06 · SEC-05):

- :func:`prepare_application` — builds the payload a human is asked to
  review. It never submits.
- :func:`execute_approved` — executes a **previously approved** payload. The
  payload is the one that was persisted with the approval record, so *the
  approved payload is the submitted payload*.

There is deliberately no "submit with a boolean flag" entry point any more:
a submission always follows a recorded human decision.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from src.graph.application_workflow import build_application_workflow
from src.graph.state import ApplicationWorkflowState
from src.security.audit import (
    ACTION_PREPARE,
    ACTION_SUBMIT,
    ACTION_VERIFY,
    OUTCOME_ERROR,
    OUTCOME_SUCCESS,
    SYSTEM_ACTOR,
    record_audit,
)
from src.security.registry_setup import get_registry

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.applications.contracts import (
        ApplicationAdapter,
        ApplicationRequest,
        ApplicationResult,
        PreparedApplication,
    )

logger = logging.getLogger(__name__)


def new_workflow_id() -> str:
    """A short, human-quotable id for one application workflow."""
    return str(uuid.uuid4())[:8]


def prepare_application(
    request: ApplicationRequest,
    adapter: ApplicationAdapter,
    *,
    workflow_id: str | None = None,
    owner_id: str | None = None,
) -> PreparedApplication:
    """Prepare an application for review — nothing is submitted here.

    Args:
        request: The application request with the job and candidate details.
        adapter: The adapter that builds the payload.
        workflow_id: Optional workflow id; a new one is generated when absent.
        owner_id: The account the run belongs to (WS-14 · Phase B). The
            evidence artifacts are written into that account's directory.

    Returns:
        The prepared application, stamped with the workflow id.

    Raises:
        PermissionError: The adapter holds no prepare capability.
    """
    if not get_registry().can_prepare(adapter.name):
        raise PermissionError(f"Adapter {adapter.name!r} is not permitted to prepare applications")

    active_workflow_id = workflow_id or new_workflow_id()
    logger.info(
        f"[{active_workflow_id}] Preparing application for {request.company_name}",
        extra={
            "workflow_id": active_workflow_id,
            "company": request.company_name,
            "job_url": request.job_url,
            "adapter": adapter.name,
        },
    )
    prepared = adapter.prepare(request)
    prepared.workflow_id = active_workflow_id
    prepared.owner_id = owner_id
    return prepared


def execute_approved(
    prepared: PreparedApplication,
    adapter: ApplicationAdapter,
    *,
    workflow_id: str,
    approval_id: str,
    approver: str,
    decision_reason: str = "",
    session: Session | None = None,
    application_id: str | None = None,
) -> ApplicationResult:
    """Execute an application that a human has already approved.

    The graph runs prepare → approval → submit → verify. The prepared payload
    is restored from the approval record, so the prepare node reuses it
    instead of rebuilding it, and the approval node sees the recorded
    decision.

    Args:
        prepared: The payload that was approved.
        adapter: The adapter to execute with.
        workflow_id: The workflow id of this execution.
        approval_id: The approval record this execution belongs to.
        approver: Who approved it.
        decision_reason: Why they approved it (recorded in the audit trail).
        session: An optional session for the WS-07 tracking writes. The API
            hands over its request-scoped session, so the tracking rows are
            written in the same transaction as the rest of the request.
        application_id: The tracked application this execution belongs to,
            when it is known.

    Returns:
        The final application result. A failure is a result, never an
        exception: an unexpected error becomes ``status="workflow_error"``.
    """
    from src.applications.contracts import ApplicationResult

    logger.info(
        f"[{workflow_id}] Executing approved application (approval {approval_id})",
        extra={
            "workflow_id": workflow_id,
            "approval_id": approval_id,
            "adapter": adapter.name,
            "approver": approver,
        },
    )

    try:
        graph = build_application_workflow(adapter, session=session)

        state = ApplicationWorkflowState(
            request=prepared.request,
            prepared_application=prepared,
            approval_status=True,
            approval_metadata={
                "approval_id": approval_id,
                "approver": approver,
                "reason": decision_reason,
            },
            workflow_id=workflow_id,
            adapter_name=adapter.name,
            approval_id=approval_id,
            approver=approver,
            application_id=application_id,
        )

        raw_result = graph.invoke(state, config={"configurable": {"thread_id": workflow_id}})
        final_state: ApplicationWorkflowState = (
            raw_result
            if isinstance(raw_result, ApplicationWorkflowState)
            else ApplicationWorkflowState(**raw_result)
        )

        if final_state.final_result is None:
            logger.error(
                f"[{workflow_id}] Workflow completed but no final_result was set",
                extra={"workflow_id": workflow_id},
            )
            return ApplicationResult(
                success=False,
                status="workflow_error",
                message="Workflow completed without producing a result",
                metadata={"workflow_id": workflow_id, "adapter": adapter.name},
            )

        result = final_state.final_result
        record_audit(
            ACTION_SUBMIT,
            actor=approver,
            resource=approval_id,
            outcome=OUTCOME_SUCCESS if result.success else "blocked",
            metadata={
                "workflow_id": workflow_id,
                "adapter": adapter.name,
                "status": result.status,
                "job_url": prepared.request.job_url,
            },
            workflow_id=workflow_id,
        )
        record_audit(
            ACTION_VERIFY,
            actor=approver,
            resource=approval_id,
            outcome=OUTCOME_SUCCESS if result.success else OUTCOME_ERROR,
            metadata={
                "workflow_id": workflow_id,
                "adapter": adapter.name,
                "status": result.status,
            },
            workflow_id=workflow_id,
        )
        return result

    except Exception as e:
        logger.exception(
            "[workflow] Approved workflow execution failed",
            extra={"workflow_id": workflow_id, "approval_id": approval_id},
        )
        record_audit(
            ACTION_SUBMIT,
            actor=approver,
            resource=approval_id,
            outcome=OUTCOME_ERROR,
            metadata={"workflow_id": workflow_id, "adapter": adapter.name, "error": str(e)},
            workflow_id=workflow_id,
        )
        return ApplicationResult(
            success=False,
            status="workflow_error",
            message=f"Workflow execution failed: {e!s}",
            metadata={"workflow_id": workflow_id, "adapter": adapter.name, "error": str(e)},
        )


def record_prepare_audit(
    prepared: PreparedApplication,
    adapter: ApplicationAdapter,
    *,
    workflow_id: str,
    approval_id: str,
    actor: str = SYSTEM_ACTOR,
) -> None:
    """Record the prepare step in the audit trail."""
    record_audit(
        ACTION_PREPARE,
        actor=actor,
        resource=approval_id,
        outcome=OUTCOME_SUCCESS,
        metadata={
            "workflow_id": workflow_id,
            "adapter": adapter.name,
            "job_url": prepared.request.job_url,
            "company": prepared.request.company_name,
        },
        workflow_id=workflow_id,
    )


def select_adapter_for_url(job_url: str, adapters: list[ApplicationAdapter]) -> ApplicationAdapter:
    """Select the appropriate adapter for a given job URL.

    Iterates through available adapters and returns the first one that
    supports the URL via adapter.supports_url(job_url).

    Args:
        job_url: The job URL to match
        adapters: List of ApplicationAdapter instances to check

    Returns:
        The first adapter that supports the URL

    Raises:
        RuntimeError: If no adapter supports the URL
    """
    for adapter in adapters:
        if adapter.supports_url(job_url):
            logger.info(
                f"Selected adapter '{adapter.name}' for URL {job_url}",
                extra={"url": job_url, "adapter": adapter.name},
            )
            return adapter

    supported = ", ".join(a.name for a in adapters)
    raise RuntimeError(f"No adapter supports URL {job_url}. Available: {supported}")
