"""Job-search pipeline (WS-04): search → normalize → deduplicate → persist → match → rank.

Wires the Phase-6 pipeline to the real modules: the source registry fans
planned queries out to the adapters, listings are filtered for minimal
completeness, deduplicated, persisted to the ``jobs`` table, embedded and
matched against the candidate profile by the hybrid match engine, and the
ranked top-N is returned with per-component explanations.

Failure semantics (plan §35): a job source that fails is recorded in
``source_errors`` and skipped; persistence and vector-store failures degrade
the report (matching continues without semantics or without persistence)
instead of failing the search. Nodes are synchronous and return partial state
updates (LangGraph merges them field-by-field into the Pydantic state); the
search node bridges into the adapters' async world with ``asyncio.run``, which
is safe because callers (the executor, sync FastAPI endpoints) run without a
running event loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.graph.job_state import JobMatchPair, JobSearchState
from src.jobs.contracts import JobListing, JobSource
from src.jobs.deduplicate import deduplicate
from src.jobs.registry import SOURCES
from src.jobs.search_planner import SourceQuery, plan_queries
from src.matching.engine import calculate_match

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from src.rag.chroma_store import ChromaVectorStore

logger = logging.getLogger(__name__)

# Factory returning the vector store for the match node; injected by tests and
# the offline demo (FakeEmbeddingFn-backed store), defaults to the real one.
StoreFactory = Callable[[], "ChromaVectorStore"]


def build_job_workflow(
    sources: Mapping[str, JobSource] | None = None,
    store_factory: StoreFactory | None = None,
    session_factory: sessionmaker | None = None,
):
    """Build the compiled job-search pipeline graph.

    Args:
        sources: Source-name -> adapter mapping for the search node; defaults
            to the production registry (``src.jobs.registry.SOURCES``).
        store_factory: Builds the Chroma vector store for the match node;
            defaults to a real ``ChromaVectorStore``. ``None``/failing factory
            → degraded matching (semantic component neutralized per WS-03).
        session_factory: SQLAlchemy sessionmaker for the persist node;
            defaults to the application ``SessionLocal`` (tests bind a tmp
            database here so no file DB is touched).
    """
    graph = StateGraph(JobSearchState)
    graph.add_node("search", lambda state: _search_node(state, sources))
    graph.add_node("normalize", _normalize_node)
    graph.add_node("deduplicate", _deduplicate_node)
    graph.add_node("persist", lambda state: _persist_node(state, session_factory))
    graph.add_node("match", lambda state: _match_node(state, store_factory))
    graph.add_node("rank", _rank_node)

    graph.set_entry_point("search")
    graph.add_edge("search", "normalize")
    graph.add_edge("normalize", "deduplicate")
    graph.add_edge("deduplicate", "persist")
    graph.add_edge("persist", "match")
    graph.add_edge("match", "rank")
    graph.add_edge("rank", END)

    compiled = graph.compile(checkpointer=MemorySaver())
    logger.info("Job-search pipeline graph built")
    return compiled


# -- nodes -------------------------------------------------------------------


def _planned_queries(state: JobSearchState, source_names: tuple[str, ...]) -> list[SourceQuery]:
    """Queries for the search node: caller override or profile-derived plan."""
    if state.query is not None and state.query.strip():
        # An explicit query replaces the derived query strings for every
        # planned source (deterministic: same input, same query set).
        return [
            SourceQuery(source=source, query=state.query.strip(), location=state.location)
            for source in source_names
        ]
    # Plan for the actually-registered sources (fixtures/injected adapters get
    # queries too, not just the default greenhouse/lever/remotive trio).
    queries = plan_queries(state.profile, sources=source_names)
    if state.location:
        return [query.model_copy(update={"location": state.location}) for query in queries]
    return queries


def _search_node(state: JobSearchState, sources: Mapping[str, JobSource] | None) -> dict:
    """Fan planned queries out to the sources; record per-source failures."""
    active_sources = sources if sources is not None else SOURCES
    queries = _planned_queries(state, tuple(active_sources))

    from src.jobs.registry import search_all_detailed

    listings, source_errors = asyncio.run(search_all_detailed(queries, active_sources))
    logger.info(
        "Search node: %d queries across %d sources -> %d raw listings (%d failed sources)",
        len(queries),
        len(active_sources),
        len(listings),
        len(source_errors),
    )
    return {"queries": queries, "raw_jobs": listings, "source_errors": source_errors}


def _normalize_node(state: JobSearchState) -> dict:
    """Drop listings without the minimal completeness fields and count them."""
    kept: list[JobListing] = []
    dropped = 0
    for job in state.raw_jobs:
        if job.id.strip() and job.title.strip() and job.company.strip():
            kept.append(job)
        else:
            dropped += 1
    if dropped:
        logger.info("Normalize node: dropped %d incomplete listing(s)", dropped)
    return {"jobs": kept, "dropped": dropped}


def _deduplicate_node(state: JobSearchState) -> dict:
    """Collapse duplicate listings (same source id / URL / title+company)."""
    unique = deduplicate(state.jobs)
    if len(unique) != len(state.jobs):
        logger.info("Deduplicate node: %d -> %d unique listings", len(state.jobs), len(unique))
    return {"jobs": unique}


def _persist_node(state: JobSearchState, session_factory) -> dict:
    """Upsert the deduplicated listings into the jobs table (best effort)."""
    if not state.jobs:
        return {"persisted": 0}
    from src.db.jobs import save_jobs  # lazy: model-only imports never build an engine

    try:
        persisted = save_jobs(state.jobs, session_factory=session_factory)
    except Exception:
        # Persistence failure must not discard an in-memory search result.
        logger.exception("Persisting %d listings failed; continuing unpersisted", len(state.jobs))
        persisted = 0
    logger.info("Persist node: %d/%d listings upserted", persisted, len(state.jobs))
    return {"persisted": persisted}


def _match_node(state: JobSearchState, store_factory: StoreFactory | None) -> dict:
    """Score every job with the hybrid engine, semantics from the vector store.

    The store is built lazily on first use. Any store failure (construction,
    embedding, query) degrades every match to WS-03's degraded mode instead of
    failing the search; ``degraded`` records that on the state.
    """
    if not state.jobs:
        return {"matches": [], "degraded": False}

    store = _get_store(store_factory)
    similarities: dict[str, float] = {}
    degraded = store is None
    if store is not None:
        from src.rag.chroma_store import candidate_query_text

        try:
            store.upsert_jobs(state.jobs)
            hits = store.query_similar(candidate_query_text(state.profile), n=store.count())
            similarities = dict(hits)
            degraded = any(job.id not in similarities for job in state.jobs)
            if degraded:
                logger.warning("Vector store returned no similarity for some job(s)")
        except Exception:
            logger.exception("Vector store unavailable; matching in degraded mode")
            similarities = {}
            degraded = True

    matches = [
        JobMatchPair(job=job, match=calculate_match(job, state.profile, semantic_score=sim))
        for job, sim in ((job, similarities.get(job.id)) for job in state.jobs)
    ]
    logger.info("Match node: scored %d job(s)%s", len(matches), " (degraded)" if degraded else "")
    return {"matches": matches, "degraded": degraded}


def _rank_node(state: JobSearchState) -> dict:
    """Sort by overall score (stable) and keep the top-N slice."""
    ranked = sorted(state.matches, key=lambda pair: pair.match.overall_score, reverse=True)
    top = ranked[: max(1, state.top_n)]
    logger.info("Rank node: %d matches -> top %d", len(ranked), len(top))
    return {"top": top}


def _get_store(store_factory: StoreFactory | None) -> ChromaVectorStore | None:
    """Build the vector store, mapping any failure to None (degraded mode)."""
    if store_factory is None:
        from src.rag.chroma_store import ChromaVectorStore

        store_factory = ChromaVectorStore
    try:
        return store_factory()
    except Exception:
        logger.exception("Vector store construction failed; matching in degraded mode")
        return None


__all__ = ["build_job_workflow"]
