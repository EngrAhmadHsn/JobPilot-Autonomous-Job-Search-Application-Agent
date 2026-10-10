"""WS-02 tests: multi-source orchestration (src/jobs/registry.py) + persistence.

Dedup across sources, upsert-on-research persistence (acceptance: row count
stable in the jobs table), graceful degradation when one source fails, and
persistence toggling. Persistence tests bind an in-memory SQLite database —
no file DB, no network, no Postgres.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.jobs import JobDB, save_jobs
from src.jobs import registry
from src.jobs.contracts import JobListing
from src.jobs.search_planner import SourceQuery


def _listing(
    job_id: str, source: str, title: str = "Engineer", company: str = "Acme"
) -> JobListing:
    return JobListing(
        id=f"{source}:{job_id}",
        source=source,
        source_job_id=job_id,
        title=title,
        company=company,
        description="Python and Kubernetes.",
    )


class FakeSource:
    """Minimal JobSource stand-in returning canned listings."""

    def __init__(self, results: list[JobListing] | Exception) -> None:
        self._results = results
        self.search_calls = 0

    async def search(self, query: str, location: str | None = None) -> list[JobListing]:
        self.search_calls += 1
        if isinstance(self._results, Exception):
            raise self._results
        return list(self._results)

    async def get_job(self, job_id: str) -> JobListing | None:
        return None


@pytest.fixture()
def tmp_session_factory():
    """Sessionmaker bound to a throwaway in-memory SQLite with schema created."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    engine.dispose()


def _job_rows(factory) -> list[dict]:
    with factory() as session:
        rows = session.execute(text("SELECT id, title, company FROM jobs ORDER BY id")).fetchall()
    return [{"id": r[0], "title": r[1], "company": r[2]} for r in rows]


# ---------------------------------------------------------------- dedup


@pytest.mark.asyncio
async def test_search_all_deduplicates_within_source():
    """Two queries hitting the same source return overlapping listings once."""
    source = FakeSource([_listing("1", "greenhouse"), _listing("2", "greenhouse")])
    queries = [
        SourceQuery(source="greenhouse", query="python"),
        SourceQuery(source="greenhouse", query="engineer"),
    ]
    result = await registry.search_all(queries, sources={"greenhouse": source}, persist=False)
    assert len(result) == 2  # not 4
    assert source.search_calls == 2


@pytest.mark.asyncio
async def test_search_all_merges_across_sources():
    sources = {
        "greenhouse": FakeSource([_listing("1", "greenhouse")]),
        "lever": FakeSource([_listing("9", "lever")]),
        "remotive": FakeSource([_listing("9", "remotive")]),
    }
    queries = [SourceQuery(source=name, query="python") for name in sources]
    result = await registry.search_all(queries, sources=sources, persist=False)

    assert len(result) == 3  # same numeric id on different sources is NOT a dupe
    assert {listing.source for listing in result} == {"greenhouse", "lever", "remotive"}


@pytest.mark.asyncio
async def test_search_all_validates_acceptance_fields():
    """Every returned listing has non-empty id/source/title/company."""
    sources = {
        "greenhouse": FakeSource([_listing("1", "greenhouse", title="Backend")]),
        "remotive": FakeSource([_listing("2", "remotive", company="RemoteCo")]),
    }
    queries = [SourceQuery(source=name, query="x") for name in sources]
    result = await registry.search_all(queries, sources=sources, persist=False)

    assert len(result) == 2
    for listing in result:
        assert listing.id
        assert listing.source
        assert listing.title.strip()
        assert listing.company.strip()


# ------------------------------------------------------- partial failure


@pytest.mark.asyncio
async def test_search_all_survives_one_source_failing(caplog):
    sources = {
        "greenhouse": FakeSource([_listing("1", "greenhouse")]),
        "lever": FakeSource(RuntimeError("connection refused")),
        "remotive": FakeSource([_listing("3", "remotive")]),
    }
    queries = [SourceQuery(source=name, query="x") for name in sources]

    with caplog.at_level(logging.WARNING, logger="src.jobs.registry"):
        result = await registry.search_all(queries, sources=sources, persist=False)

    # The failed source contributes nothing; the others' results return.
    assert [listing.source for listing in result] == ["greenhouse", "remotive"]
    assert any("lever" in record.message.lower() for record in caplog.records)


@pytest.mark.asyncio
async def test_search_all_all_sources_failing_returns_empty():
    sources = {
        "greenhouse": FakeSource(RuntimeError("down")),
        "remotive": FakeSource(RuntimeError("down")),
    }
    queries = [SourceQuery(source=name, query="x") for name in sources]
    result = await registry.search_all(queries, sources=sources, persist=False)
    assert result == []


@pytest.mark.asyncio
async def test_search_all_skips_unregistered_source(caplog):
    sources = {"greenhouse": FakeSource([_listing("1", "greenhouse")])}
    queries = [
        SourceQuery(source="greenhouse", query="x"),
        SourceQuery(source="nonexistent", query="y"),
    ]
    with caplog.at_level(logging.WARNING, logger="src.jobs.registry"):
        result = await registry.search_all(queries, sources=sources, persist=False)
    assert [listing.source for listing in result] == ["greenhouse"]
    assert any("nonexistent" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_search_all_empty_queries_returns_empty():
    result = await registry.search_all([], sources={}, persist=False)
    assert result == []


# ------------------------------------------------------------ persistence


def test_save_jobs_inserts_and_upserts(tmp_session_factory):
    first = [
        _listing("1", "greenhouse", title="Old Title"),
        _listing("2", "remotive", company="RemoteCo"),
    ]
    assert save_jobs(first, session_factory=tmp_session_factory) == 2
    rows = {row["id"]: row for row in _job_rows(tmp_session_factory)}
    assert len(rows) == 2
    assert rows["greenhouse:1"]["title"] == "Old Title"

    # Re-save with one changed listing and one new: merge, no duplicates.
    second = [
        _listing("1", "greenhouse", title="New Title"),
        _listing("3", "lever", company="LeverCo"),
    ]
    assert save_jobs(second, session_factory=tmp_session_factory) == 2
    rows = {row["id"]: row for row in _job_rows(tmp_session_factory)}
    assert len(rows) == 3  # upserted, not duplicated
    assert rows["greenhouse:1"]["title"] == "New Title"  # update landed


def test_save_jobs_preserves_all_fields(tmp_session_factory):
    listing = JobListing(
        id="remotive:42",
        source="remotive",
        source_job_id="42",
        title="ML Engineer",
        company="RemoteCo",
        description="PyTorch and RAG.",
        location="Worldwide",
        remote_policy="remote",
        employment_type="full-time",
        salary="USD 120k",
        required_skills=["python"],
        preferred_skills=["rust"],
        application_url="https://remotive.com/42",
        company_url="https://remotive.com",
        posted_at="2026-10-08T21:47:32+00:00",
        metadata={"k": "v"},
    )
    save_jobs([listing], session_factory=tmp_session_factory)

    with tmp_session_factory() as session:
        row = session.get(JobDB, "remotive:42")

    assert row.title == "ML Engineer"
    assert row.source == "remotive"
    assert row.source_job_id == "42"
    assert row.description == "PyTorch and RAG."
    assert row.location == "Worldwide"
    assert row.remote_policy == "remote"
    assert row.employment_type == "full-time"
    assert row.salary == "USD 120k"
    assert row.required_skills == ["python"]
    assert row.preferred_skills == ["rust"]
    assert row.application_url == "https://remotive.com/42"
    assert row.company_url == "https://remotive.com"
    assert row.posted_at == "2026-10-08T21:47:32+00:00"
    assert row.extra_metadata == {"k": "v"}  # JobListing.metadata -> extra_metadata


@pytest.mark.asyncio
async def test_search_all_persists_and_upserts_on_rerun(tmp_session_factory, monkeypatch):
    """Acceptance: re-running a search keeps the jobs row count stable."""
    monkeypatch.setattr("src.db.session.SessionLocal", tmp_session_factory)
    source = FakeSource([_listing("1", "greenhouse"), _listing("2", "greenhouse")])
    queries = [SourceQuery(source="greenhouse", query="python")]

    await registry.search_all(queries, sources={"greenhouse": source}, persist=True)
    assert len(_job_rows(tmp_session_factory)) == 2

    # Second run returns the same jobs: merge leaves exactly two rows.
    await registry.search_all(queries, sources={"greenhouse": source}, persist=True)
    assert len(_job_rows(tmp_session_factory)) == 2


@pytest.mark.asyncio
async def test_search_all_persist_false_touches_no_db(monkeypatch):
    def _boom():
        raise AssertionError("SessionLocal must not be used when persist=False")

    monkeypatch.setattr("src.db.session.SessionLocal", _boom)
    source = FakeSource([_listing("1", "greenhouse")])
    result = await registry.search_all(
        [SourceQuery(source="greenhouse", query="x")], sources={"greenhouse": source}, persist=False
    )
    assert len(result) == 1


@pytest.mark.asyncio
async def test_search_all_persistence_failure_returns_listings_anyway(
    tmp_session_factory, monkeypatch, caplog
):
    """A DB outage must not discard an in-memory search result."""
    monkeypatch.setattr("src.db.session.SessionLocal", tmp_session_factory)

    def _broken_save(listings, session_factory=None):
        raise RuntimeError("db down")

    monkeypatch.setattr("src.db.jobs.save_jobs", _broken_save)
    source = FakeSource([_listing("1", "greenhouse")])

    with caplog.at_level(logging.ERROR, logger="src.jobs.registry"):
        result = await registry.search_all(
            [SourceQuery(source="greenhouse", query="x")], sources={"greenhouse": source}
        )

    assert len(result) == 1  # results survive the persistence failure
    assert any("persist" in record.message.lower() for record in caplog.records)
