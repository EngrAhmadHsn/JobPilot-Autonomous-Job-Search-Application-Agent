"""LangGraph graph builder for the application workflow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.graph.conditionals import should_submit_conditional, should_verify_conditional
from src.graph.state import ApplicationWorkflowState

if TYPE_CHECKING:
    from src.applications.contracts import ApplicationAdapter

logger = logging.getLogger(__name__)


def build_application_workflow(adapter: ApplicationAdapter):
    """Build the application workflow graph.

    Creates a LangGraph StateGraph with the following structure:

    prepare_node
        ↓
    approval_node
        ↓
    [should_submit_conditional] ↙--reject------→ [END with rejection]
        ↙--submit
    submit_node
        ↓
    [should_verify_conditional] ↙--end--------→ [END with submission status]
        ↙--verify
    verify_node
        ↓
    [END with verified result]

    The workflow enforces:
    1. Request validation and payload preparation via prepare_node
    2. Human approval gate via approval_node (configurable)
    3. Conditional routing based on approval decision
    4. Application submission via submit_node (only if approved)
    5. Verification of submission via verify_node

    Args:
        adapter: The ApplicationAdapter instance to use for prepare/submit/verify

    Returns:
        Compiled StateGraph ready for execution
    """
    # Import node functions here to avoid circular imports
    from src.graph.nodes import approval_node, prepare_node, submit_node, verify_node

    graph = StateGraph(ApplicationWorkflowState)

    # Add nodes
    graph.add_node(
        "prepare",
        lambda state: prepare_node(cast(ApplicationWorkflowState, state), adapter),
    )
    graph.add_node(
        "approval",
        approval_node,
    )
    graph.add_node(
        "submit",
        lambda state: submit_node(cast(ApplicationWorkflowState, state), adapter),
    )
    graph.add_node(
        "verify",
        lambda state: verify_node(cast(ApplicationWorkflowState, state), adapter),
    )

    # Add special nodes for rejection and verification failure
    graph.add_node(
        "reject",
        lambda state: _rejection_node(cast(ApplicationWorkflowState, state)),
    )

    # Set entry point
    graph.set_entry_point("prepare")

    # Add edges
    graph.add_edge("prepare", "approval")
    graph.add_conditional_edges(
        "approval",
        should_submit_conditional,
        {
            "submit": "submit",
            "reject": "reject",
        },
    )
    graph.add_conditional_edges(
        "submit",
        should_verify_conditional,
        {
            "verify": "verify",
            "end": "reject",
        },
    )
    graph.add_edge("verify", END)
    graph.add_edge("reject", END)

    # Compile with in-memory checkpointer for now
    # (Phase 2 #4 will add database persistence)
    compiled = graph.compile(checkpointer=MemorySaver())

    logger.info("Application workflow graph built and compiled successfully")
    return compiled


def _rejection_node(state: ApplicationWorkflowState) -> ApplicationWorkflowState:
    """Handle rejection cases (approval denied or submission failed).

    Sets final_result to a rejection ApplicationResult to ensure the workflow
    always produces a consistent final result.
    """
    from src.applications.contracts import ApplicationResult

    # Always set final_result to ensure consistent output
    if state.final_result is None:
        status = "rejected"
        evidence = None
        reason = ""

        if state.submission_result is not None and not state.submission_result.success:
            # The submission already carries the specific reason (permission
            # denied, unsafe navigation, blocked challenge, missing
            # evidence). Keep it instead of flattening every failure into
            # "rejected".
            status = state.submission_result.status
            reason = state.submission_result.message
            evidence = state.submission_result.evidence
            logger.info(
                f"[{state.workflow_id}] Submission ended with status {status}",
                extra={"workflow_id": state.workflow_id, "status": status},
            )
        elif state.approval_status is False:
            reason = "Application was rejected at approval gate"
            logger.info(
                f"[{state.workflow_id}] Application rejected at approval gate",
                extra={"workflow_id": state.workflow_id},
            )
        elif state.error:
            reason = f"Workflow error: {state.error}"
            logger.error(
                f"[{state.workflow_id}] Workflow ended with error: {state.error}",
                extra={"workflow_id": state.workflow_id, "error": state.error},
            )
        else:
            reason = "Application was not approved"
            logger.info(
                f"[{state.workflow_id}] Application rejected (no approval)",
                extra={"workflow_id": state.workflow_id},
            )

        if not reason:
            reason = "Application was not approved"

        state.final_result = ApplicationResult(
            success=False,
            status=status,
            message=reason,
            evidence=evidence,
            metadata={"workflow_id": state.workflow_id, "adapter": state.adapter_name},
        )

    return state
