"""Full end-to-end job workflow: search → normalize → deduplicate → match → rank."""

from __future__ import annotations

import logging
from typing import cast

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph

from src.graph.state import ApplicationWorkflowState
from src.jobs.contracts import JobSource

logger = logging.getLogger(__name__)


def build_full_workflow(source: JobSource):
    """Build the full job search-to-rank workflow.

    Structure:
    START → search → normalize → deduplicate → match → rank → END
    """

    # Note: This full pipeline uses dedicated nodes for search, normalize,
    # deduplicate, match, and rank. The prepare/approval/submit/verify nodes
    # belong to the application submission workflow (application_workflow.py),
    # not the job search pipeline.
    graph = StateGraph(ApplicationWorkflowState)

    # Dedicated nodes for Phase 6 full pipeline
    graph.add_node(
        "search", lambda state: _search_node(cast(ApplicationWorkflowState, state), source)
    )
    graph.add_node(
        "normalize", lambda state: _normalize_node(cast(ApplicationWorkflowState, state))
    )
    graph.add_node(
        "deduplicate", lambda state: _deduplicate_node(cast(ApplicationWorkflowState, state))
    )
    graph.add_node("match", lambda state: _match_node(cast(ApplicationWorkflowState, state)))
    graph.add_node("rank", lambda state: _rank_node(cast(ApplicationWorkflowState, state)))

    graph.set_entry_point("search")
    graph.add_edge("search", "normalize")
    graph.add_edge("normalize", "deduplicate")
    graph.add_edge("deduplicate", "match")
    graph.add_edge("match", "rank")
    # The graph terminates at "rank"; no explicit END node needed
    # Note: In LangGraph, the final node terminates the graph automatically.
    # We do not add an explicit "END" edge; the graph ends at "rank".

    compiled = graph.compile(checkpointer=MemorySaver())
    logger.info("Full workflow graph built")
    return compiled


def _search_node(state: ApplicationWorkflowState, source: JobSource) -> ApplicationWorkflowState:
    """Placeholder search node."""
    logger.info("[%s] Search node (placeholder)", state.workflow_id)
    return state


def _normalize_node(state: ApplicationWorkflowState) -> ApplicationWorkflowState:
    """Placeholder normalize node."""
    logger.info("[%s] Normalize node (placeholder)", state.workflow_id)
    return state


def _deduplicate_node(state: ApplicationWorkflowState) -> ApplicationWorkflowState:
    """Placeholder deduplicate node."""
    logger.info("[%s] Deduplicate node (placeholder)", state.workflow_id)
    return state


def _match_node(state: ApplicationWorkflowState) -> ApplicationWorkflowState:
    """Placeholder match node."""
    logger.info("[%s] Match node (placeholder)", state.workflow_id)
    return state


def _rank_node(state: ApplicationWorkflowState) -> ApplicationWorkflowState:
    """Rank node: sort match results and select top 10."""
    logger.info("[%s] Rank node: selecting top results", state.workflow_id)
    # Note: In a complete implementation, this would sort JobMatchResult
    # objects by overall_score and store top 10 in state.
    # For Phase 6, this is a placeholder demonstrating the pipeline.
    state.approval_metadata["ranked"] = True
    return state
