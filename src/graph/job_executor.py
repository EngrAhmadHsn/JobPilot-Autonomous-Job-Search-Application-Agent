"""Executor for the job-search pipeline (WS-04): graph + report assembly.

Runs the compiled pipeline (``src.graph.job_workflow``) synchronously and
wraps the outcome in a serializable ``JobSearchReport``. Per plan §35 the
executor degrades instead of raising: source failures land in
``source_errors``, vector-store/persistence failures flip the report's
``degraded``/stats fields — an empty result set with a populated error map is
a valid, successful report.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from src.graph.job_state import JobMatchPair
from src.graph.job_workflow import StoreFactory, build_job_workflow
from src.resume.profile import CandidateProfile

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import sessionmaker

    from src.jobs.contracts import JobSource

logger = logging.getLogger(__name__)

DEFAULT_TOP_N = 10
MAX_TOP_N = 50


class JobSearchStats(BaseModel):
    """Pipeline counters for one search run."""

    found: int = 0  # raw listings returned by the sources (pre-normalize)
    dropped: int = 0  # listings dropped by the normalize node
    deduped: int = 0  # unique listings that reached matching
    persisted: int = 0  # rows upserted into the jobs table


class JobSearchReport(BaseModel):
    """Result of one end-to-end job search run."""

    results: list[JobMatchPair] = Field(default_factory=list)
    source_errors: dict[str, str] = Field(default_factory=dict)
    stats: JobSearchStats = Field(default_factory=JobSearchStats)
    degraded: bool = False  # semantic scoring was unavailable (WS-03 mode)


def run_job_search(
    profile: CandidateProfile,
    query: str | None = None,
    location: str | None = None,
    top_n: int = DEFAULT_TOP_N,
    *,
    sources: dict[str, JobSource] | None = None,
    store_factory: StoreFactory | None = None,
    session_factory: sessionmaker | None = None,
) -> JobSearchReport:
    """Run the full search→rank pipeline for one profile.

    Args:
        profile: Parsed candidate profile driving query planning and matching.
        query: Optional explicit search query; replaces the planner-derived
            query strings for every planned source when given.
        location: Optional location filter passed through to the sources.
        top_n: Size of the ranked slice returned (clamped to 1..MAX_TOP_N).
        sources: Source-name -> adapter override (tests/demo inject fixtures).
        store_factory: Vector-store override (tests/demo inject
            FakeEmbeddingFn-backed stores); ``None`` uses the real store.
        session_factory: Sessionmaker override for the persist node.

    Returns:
        JobSearchReport with ranked (job, match) pairs, per-source errors,
        pipeline stats, and the degraded flag. Never raises for source,
        vector-store, or persistence failures.
    """
    workflow_id = uuid.uuid4().hex[:8]
    clamped_top_n = max(1, min(int(top_n), MAX_TOP_N))
    logger.info(
        "Job search started",
        extra={
            "workflow_id": workflow_id,
            "query": query,
            "location": location,
            "top_n": clamped_top_n,
            "has_explicit_query": query is not None,
        },
    )

    graph = build_job_workflow(
        sources=sources,
        store_factory=store_factory,
        session_factory=session_factory,
    )
    initial_state = {
        "profile": profile,
        "query": query,
        "location": location,
        "top_n": clamped_top_n,
    }
    # With a checkpointer attached, invoke requires a thread_id config; the
    # final state comes back as a dict of field values.
    final_state: dict = graph.invoke(
        initial_state, config={"configurable": {"thread_id": workflow_id}}
    )

    stats = JobSearchStats(
        found=len(final_state.get("raw_jobs", [])),
        dropped=final_state.get("dropped", 0),
        deduped=len(final_state.get("jobs", [])),
        persisted=final_state.get("persisted", 0),
    )
    report = JobSearchReport(
        results=final_state.get("top", []),
        source_errors=final_state.get("source_errors", {}),
        stats=stats,
        degraded=final_state.get("degraded", False),
    )
    logger.info(
        "Job search complete",
        extra={
            "workflow_id": workflow_id,
            "found": stats.found,
            "deduped": stats.deduped,
            "persisted": stats.persisted,
            "returned": len(report.results),
            "failed_sources": sorted(report.source_errors),
            "degraded": report.degraded,
        },
    )
    return report


def default_store_factory() -> StoreFactory:
    """Lazily build the production vector store factory.

    Kept as a function (not a lambda) so callers can pass it without paying
    the chromadb import until a search actually needs the store.
    """
    from src.rag.chroma_store import ChromaVectorStore

    return ChromaVectorStore


__all__ = [
    "DEFAULT_TOP_N",
    "MAX_TOP_N",
    "JobSearchReport",
    "JobSearchStats",
    "default_store_factory",
    "run_job_search",
]

# Callable re-export used by type annotations in the API layer.
ExecutorFn = Callable[..., JobSearchReport]
