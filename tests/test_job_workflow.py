"""WS-04 tests: the real job-search pipeline (src/graph/job_workflow.py + executor).

The graph runs end-to-end offline: fixture JobSource for retrieval, a
FakeEmbeddingFn-backed Chroma store for semantics, and an in-memory SQLite
session factory for persistence. Covers node ordering via the stats counters,
dedup across queries, incomplete-listing dropping, top-N slicing, per-source
error tolerance (plan §35), degraded matching, and persistence upserts.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.jobs import JobDB
from src.graph.job_executor import JobSearchReport, run_job_search
from src.graph.job_state import JobSearchState
from src.graph.job_workflow import build_job_workflow
from src.jobs.contracts import JobListing
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
)
from tests.fixtures.fake_embeddings import FakeEmbeddingFn, make_store
from tests.fixtures.fake_source import (
    FIXTURE_JOBS,
    FailingJobSource,
    FakeJobSource,
    make_listing,
)


@pytest.fixture()
def tmp_session_factory():
    """Sessionmaker bound to a throwaway in-memory SQLite with schema created."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    engine.dispose()


@pytest.fixture()
def profile() -> CandidateProfile:
    return CandidateProfile(
        personal_information=PersonalInformation(
            name="Ahmad Hassan",
            title="AI Engineer",
            email="ahmad@example.com",
        ),
        skills=["Python", "FastAPI", "SQL", "AWS", "Docker", "PyTorch"],
        experience=[
            ExperienceEntry(
                title="Senior AI Engineer", company="Tech Corp", dates="2021 - present", years=5
            )
        ],
    )


def run(
    profile: CandidateProfile,
    sources: dict,
    tmp_session_factory,
    tmp_path,
    **kwargs,
) -> JobSearchReport:
    """run_job_search with every external dependency faked offline."""
    return run_job_search(
        profile,
        sources=sources,
        store_factory=lambda: make_store(tmp_path / "chroma"),
        session_factory=tmp_session_factory,
        **kwargs,
    )


# ---------------------------------------------------------------- e2e happy path


def test_pipeline_end_to_end_with_fixture_source(profile, tmp_session_factory, tmp_path):
    """Full pipeline: 3 planner queries x 1 fixture source -> dedup -> match -> rank."""
    report = run(profile, {"fixture": FakeJobSource()}, tmp_session_factory, tmp_path)

    assert isinstance(report, JobSearchReport)
    assert report.stats.found == len(FIXTURE_JOBS) * 3  # 3 queries, same 5 listings each
    assert report.stats.deduped == len(FIXTURE_JOBS)  # dedup collapsed them
    assert report.stats.persisted == len(FIXTURE_JOBS)
    assert report.source_errors == {}
    assert report.degraded is False

    scores = [pair.match.overall_score for pair in report.results]
    assert scores == sorted(scores, reverse=True), "results must be ranked descending"
    assert len(report.results) == len(FIXTURE_JOBS)  # fewer jobs than the top-N
    assert all(pair.match.explanation for pair in report.results)
    # Every fixture job survived normalize+dedup and got a semantic score.
    assert {pair.job.id for pair in report.results} == {job.id for job in FIXTURE_JOBS}
    assert all(pair.match.semantic_score > 0 for pair in report.results)


def test_node_ordering_via_state(profile, tmp_session_factory, tmp_path):
    """The compiled graph executes search->normalize->deduplicate->persist->match->rank."""
    graph = build_job_workflow(
        sources={"fixture": FakeJobSource()},
        store_factory=lambda: make_store(tmp_path / "chroma"),
        session_factory=tmp_session_factory,
    )
    final_state: dict = graph.invoke(
        {"profile": profile.model_copy(deep=True), "top_n": 3},
        config={"configurable": {"thread_id": "ordering"}},
    )
    # 3 planner queries hit the same 5 fixture listings -> 15 raw -> 5 unique.
    assert len(final_state["raw_jobs"]) == len(final_state["jobs"]) * 3
    assert len(final_state["top"]) == 3
    assert final_state["dropped"] == 0
    assert final_state["persisted"] == len(final_state["jobs"])


def test_graph_builds():
    graph = build_job_workflow()
    assert graph is not None
    assert hasattr(graph, "invoke")


# ---------------------------------------------------------------- normalize


def test_normalize_drops_incomplete_listings(profile, tmp_session_factory, tmp_path):
    """Listings missing title, company, or id are dropped and counted."""
    incomplete = [
        make_listing("10", "Complete Engineer", "Acme"),
        make_listing("11", "", "No Title Corp"),  # no title
        make_listing("12", "No Company Engineer", ""),  # no company
        JobListing(id=" ", source="fixture", title="Blank Id", company="Acme"),
    ]
    report = run(
        profile,
        {"fixture": FakeJobSource(listings=incomplete)},
        tmp_session_factory,
        tmp_path,
    )

    # The source answers each of the 3 planner queries, so the 3 incomplete
    # listings are dropped once per query (normalize runs before dedup).
    assert report.stats.dropped == 9
    assert report.stats.deduped == 1
    assert [pair.job.id for pair in report.results] == ["fixture:10"]


# ---------------------------------------------------------------- degradation


def test_failing_source_recorded_not_fatal(profile, tmp_session_factory, tmp_path):
    """A failing source lands in source_errors; the other source still answers."""
    report = run(
        profile,
        {"fixture": FakeJobSource(), "broken": FailingJobSource()},
        tmp_session_factory,
        tmp_path,
    )

    assert "broken" in report.source_errors
    assert "fixture" not in report.source_errors
    assert "fixture source unavailable" in report.source_errors["broken"]
    assert report.stats.deduped == len(FIXTURE_JOBS)
    assert len(report.results) > 0  # the search itself still succeeded


def test_all_sources_failing_yields_empty_report(profile, tmp_session_factory, tmp_path):
    """Every source failing: empty ranked results, populated errors, no crash."""
    report = run(
        profile,
        {"a": FailingJobSource(), "b": FailingJobSource(RuntimeError("down"))},
        tmp_session_factory,
        tmp_path,
    )

    assert report.results == []
    assert set(report.source_errors) == {"a", "b"}
    assert report.stats.found == 0


def test_degraded_mode_when_store_factory_fails(profile, tmp_session_factory, tmp_path):
    """A failing vector store flips the degraded flag; matching still returns."""

    def broken_factory():
        raise RuntimeError("no embeddings available")

    report = run_job_search(
        profile,
        sources={"fixture": FakeJobSource()},
        store_factory=broken_factory,
        session_factory=tmp_session_factory,
    )

    assert report.degraded is True
    assert len(report.results) == len(FIXTURE_JOBS)
    assert all(pair.match.semantic_score == 0.0 for pair in report.results)
    assert all("degraded mode" in pair.match.explanation for pair in report.results)


def test_degraded_mode_when_embedding_fails_mid_run(profile, tmp_session_factory, tmp_path):
    """A store whose embed call raises degrades the report, not the search."""

    class ExplodingEmbedding(FakeEmbeddingFn):
        def embed_documents(self, texts):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

    store = make_store(tmp_path / "chroma", embedding_fn=ExplodingEmbedding())
    report = run_job_search(
        profile,
        sources={"fixture": FakeJobSource()},
        store_factory=lambda: store,
        session_factory=tmp_session_factory,
    )

    assert report.degraded is True
    assert len(report.results) == len(FIXTURE_JOBS)


# ---------------------------------------------------------------- rank/top-N


def test_top_n_slice_respected(profile, tmp_session_factory, tmp_path):
    report = run(profile, {"fixture": FakeJobSource()}, tmp_session_factory, tmp_path, top_n=2)
    assert len(report.results) == 2
    scores = [pair.match.overall_score for pair in report.results]
    assert scores == sorted(scores, reverse=True)


def test_top_n_clamped_to_bounds(profile, tmp_session_factory, tmp_path):
    """top_n is clamped to 1..MAX_TOP_N rather than slicing to zero."""
    report = run(profile, {"fixture": FakeJobSource()}, tmp_session_factory, tmp_path, top_n=0)
    assert len(report.results) == 1


# ---------------------------------------------------------------- persistence


def test_persist_upserts_to_injected_session_factory(profile, tmp_session_factory, tmp_path):
    """Rows land in the injected DB; re-running merges instead of duplicating."""
    run(profile, {"fixture": FakeJobSource()}, tmp_session_factory, tmp_path)
    run(profile, {"fixture": FakeJobSource()}, tmp_session_factory, tmp_path)

    with tmp_session_factory() as session:
        rows = session.query(JobDB).all()
    assert {row.id for row in rows} == {job.id for job in FIXTURE_JOBS}

    count = tmp_session_factory().execute(text("SELECT COUNT(*) FROM jobs")).scalar()
    assert count == len(FIXTURE_JOBS)


def test_persist_failure_tolerated(profile, tmp_session_factory, tmp_path):
    """A broken session factory zeroes the persisted stat without failing."""

    def broken_factory():
        raise RuntimeError("db down")

    report = run_job_search(
        profile,
        sources={"fixture": FakeJobSource()},
        store_factory=lambda: make_store(tmp_path / "chroma"),
        session_factory=broken_factory,
    )
    assert report.stats.persisted == 0
    assert len(report.results) == len(FIXTURE_JOBS)


# ---------------------------------------------------------------- query planning


def test_explicit_query_overrides_planned_queries(profile, tmp_session_factory, tmp_path):
    """A caller query replaces the derived strings and flows to every source."""
    source = FakeJobSource()
    report = run_job_search(
        profile,
        query="python engineer",
        location="Remote",
        sources={"fixture": source},
        store_factory=lambda: make_store(tmp_path / "chroma"),
        session_factory=tmp_session_factory,
    )

    assert source.search_calls == 1
    assert source.last_query == "python engineer"
    assert source.last_location == "Remote"
    assert report.stats.found == len(FIXTURE_JOBS)


def test_planned_queries_target_injected_sources(profile):
    """Fixture sources get queries planned for them, not just the prod trio."""
    from src.graph.job_workflow import _planned_queries

    state = JobSearchState(profile=profile)
    planned = _planned_queries(state, ("fixture", "broken"))
    assert {q.source for q in planned} == {"fixture", "broken"}
    assert planned  # profile has a title, so query strings are non-empty
    assert all(q.query for q in planned)
