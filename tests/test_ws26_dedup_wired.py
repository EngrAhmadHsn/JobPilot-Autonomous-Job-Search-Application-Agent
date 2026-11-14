"""WS-26 Phase 2 · The merge must run on both admission paths, not one.

``search_all`` and ``fetch_and_persist`` are two ways a listing becomes a row:
the WS-02 orchestrator (``/api/jobs/refresh`` in-process) and the WS-18 durable
refresh. A cross-source merge wired into one of them makes the corpus depend
on which path ran — the kind of split that produces a bug report nobody can
reproduce, because the reporter's refresh went the other way.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.jobs import registry
from src.jobs.contracts import JobListing
from src.jobs.search_planner import SourceQuery


def _listing(job_id: str, source: str, *, title: str = "Senior Backend Engineer") -> JobListing:
    return JobListing(
        id=f"{source}:{job_id}",
        source=source,
        source_job_id=job_id,
        title=title,
        company="Acme",
        location="London",
        description="Python and Kubernetes.",
    )


class FakeSource:
    """Minimal JobSource stand-in returning canned listings."""

    def __init__(self, results: list[JobListing]) -> None:
        self._results = results
        self.search_calls = 0

    async def search(self, query: str, location: str | None = None) -> list[JobListing]:
        self.search_calls += 1
        return list(self._results)

    async def get_job(self, job_id: str) -> JobListing | None:
        return None


@pytest.fixture()
def tmp_session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    engine.dispose()


def _row_ids(factory) -> list[str]:
    with factory() as session:
        rows = session.execute(text("SELECT id FROM jobs ORDER BY id")).fetchall()
    return [row[0] for row in rows]


@pytest.mark.asyncio
async def test_search_all_collapses_a_cross_source_posting(tmp_session_factory, monkeypatch):
    monkeypatch.setattr("src.db.session.SessionLocal", tmp_session_factory)
    sources = {
        "greenhouse": FakeSource([_listing("1", "greenhouse")]),
        "ashby": FakeSource([_listing("9", "ashby")]),
    }
    queries = [SourceQuery(source=name, query="") for name in sources]

    result = await registry.search_all(queries, sources=sources, persist=True)

    assert len(result) == 1
    assert result[0].id == "greenhouse:1"
    assert _row_ids(tmp_session_factory) == ["greenhouse:1"]


@pytest.mark.asyncio
async def test_search_all_keeps_two_genuinely_different_postings(tmp_session_factory, monkeypatch):
    monkeypatch.setattr("src.db.session.SessionLocal", tmp_session_factory)
    sources = {
        "greenhouse": FakeSource([_listing("1", "greenhouse")]),
        "ashby": FakeSource([_listing("9", "ashby", title="Data Engineer")]),
    }
    queries = [SourceQuery(source=name, query="") for name in sources]

    result = await registry.search_all(queries, sources=sources, persist=True)

    assert len(result) == 2
    assert _row_ids(tmp_session_factory) == ["ashby:9", "greenhouse:1"]


@pytest.mark.asyncio
async def test_search_all_keeps_a_second_source_row_for_a_different_location(
    tmp_session_factory, monkeypatch
):
    """The same title and company in two cities is two postings, not one."""
    monkeypatch.setattr("src.db.session.SessionLocal", tmp_session_factory)
    other = _listing("9", "ashby")
    other.location = "Berlin"
    sources = {
        "greenhouse": FakeSource([_listing("1", "greenhouse")]),
        "ashby": FakeSource([other]),
    }
    queries = [SourceQuery(source=name, query="") for name in sources]

    result = await registry.search_all(queries, sources=sources, persist=True)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_search_all_persist_false_still_merges_in_memory(monkeypatch):
    """The merge is part of the result shape, not a persistence side effect."""
    sources = {
        "greenhouse": FakeSource([_listing("1", "greenhouse")]),
        "ashby": FakeSource([_listing("9", "ashby")]),
    }
    queries = [SourceQuery(source=name, query="") for name in sources]

    result = await registry.search_all(queries, sources=sources, persist=False)
    assert len(result) == 1


def test_fetch_and_persist_collapses_a_cross_source_posting(tmp_session_factory, monkeypatch):
    """The durable refresh path merges too — it is the path the worker runs."""
    from src.graph import job_executor

    monkeypatch.setattr("src.db.session.SessionLocal", tmp_session_factory)
    sources = {
        "greenhouse": FakeSource([_listing("1", "greenhouse")]),
        "ashby": FakeSource([_listing("9", "ashby")]),
    }

    job_executor.fetch_and_persist(
        sources=sources,
        session_factory=tmp_session_factory,
        embedding_fn=_no_embedding,
        delta=False,
    )

    assert _row_ids(tmp_session_factory) == ["greenhouse:1"]


class _NoEmbeddingStore:
    """A vector store that accepts writes and answers nothing."""

    def upsert_jobs(self, jobs, **_kwargs):
        return len(jobs)

    def delete_jobs(self, job_ids):
        return len(list(job_ids))

    def similarities_for_all(self, _query_text):
        return {}


def _no_embedding():
    return _NoEmbeddingStore()
