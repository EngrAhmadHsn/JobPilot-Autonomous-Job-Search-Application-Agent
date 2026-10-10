"""Executor for the application workflow: glues adapter + graph + result handling."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from src.graph.application_workflow import build_application_workflow
from src.graph.state import ApplicationWorkflowState

if TYPE_CHECKING:
    from src.applications.contracts import ApplicationAdapter, ApplicationRequest, ApplicationResult

logger = logging.getLogger(__name__)


def execute_application_workflow(
    request: ApplicationRequest,
    adapter: ApplicationAdapter,
    approval: bool = False,
) -> ApplicationResult:
    """Execute the complete application workflow for a single job.

    Orchestrates the full pipeline:
    1. Selects adapter based on job_url (already done by caller)
    2. Builds the LangGraph workflow
    3. Initializes state with request and approval decision
    4. Runs graph from prepare → approval → (conditional) → submit → verify
    5. Returns final ApplicationResult

    Args:
        request: The ApplicationRequest with job details and candidate info
        adapter: The ApplicationAdapter to use (selected by job_url)
        approval: Whether to auto-approve the application for submission
                  (False = reject at approval gate, True = proceed to submit)

    Returns:
        ApplicationResult with final success/failure status, evidence, and metadata

    Raises:
        RuntimeError if the workflow encounters an unrecoverable error
    """
    workflow_id = str(uuid.uuid4())[:8]
    logger.info(
        f"[{workflow_id}] Starting application workflow for {request.company_name}",
        extra={
            "workflow_id": workflow_id,
            "company": request.company_name,
            "job_url": request.job_url,
        },
    )

    try:
        # Build the compiled graph
        graph = build_application_workflow(adapter)

        # Initialize state
        state = ApplicationWorkflowState(
            request=request,
            approval_status=approval,
            workflow_id=workflow_id,
            adapter_name=adapter.name,
        )

        logger.debug(
            f"[{workflow_id}] Initial state: {state.to_dict()}",
            extra={"workflow_id": workflow_id},
        )

        # Execute graph (blocking/synchronous for now)
        # LangGraph runs nodes sequentially; final_result is populated by workflow
        # Note: with a checkpointer attached, invoke requires a thread_id config;
        # it returns a dict of state fields, which we cast back to the dataclass.
        raw_result = graph.invoke(state, config={"configurable": {"thread_id": workflow_id}})
        final_state: ApplicationWorkflowState = (
            raw_result
            if isinstance(raw_result, ApplicationWorkflowState)
            else ApplicationWorkflowState(**raw_result)
        )

        # Extract and return final result
        if final_state.final_result is None:
            logger.error(
                f"[{workflow_id}] Workflow completed but no final_result was set",
                extra={"workflow_id": workflow_id},
            )
            from src.applications.contracts import ApplicationResult

            return ApplicationResult(
                success=False,
                status="workflow_error",
                message="Workflow completed without producing a result",
                metadata={"workflow_id": workflow_id, "adapter": adapter.name},
            )

        logger.info(
            f"[{workflow_id}] Workflow completed successfully: {final_state.final_result.status}",
            extra={
                "workflow_id": workflow_id,
                "status": final_state.final_result.status,
                "success": final_state.final_result.success,
            },
        )

        return final_state.final_result

    except Exception as e:
        logger.exception(
            "[workflow] Workflow execution failed",
            extra={"workflow_id": workflow_id},
        )

        from src.applications.contracts import ApplicationResult

        return ApplicationResult(
            success=False,
            status="workflow_error",
            message=f"Workflow execution failed: {e!s}",
            metadata={"workflow_id": workflow_id, "adapter": adapter.name, "error": str(e)},
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
        RuntimeError if no adapter supports the URL
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
