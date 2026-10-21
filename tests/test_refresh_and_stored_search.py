"""FU-1 tests: decoupled refresh + store-only search (src/graph/job_executor.py).

The refresh runs against fixture JobSources, an in-memory SQLite session
factory, and a tmp-dir Chroma store; the store-only search proves zero source
contact, corpus filtering, and degraded handling for not-yet-embedded rows.
The Gemini-cache idempotence claim is exercised with a real GeminiEmbedding
whose API is a recording fake: the second refresh must make zero API calls.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.jobs import save_jobs
from src.graph.job_executor import (
    JobSearchReport,
    refresh_jobs,
    run_job_search,
    search_stored_jobs,
)
from src.llm.client import LLMDailyQuotaExhausted
from src.resume.profile import CandidateProfile, PersonalInformation
from tests.fixtures.fake_embeddings import FakeEmbeddingFn, make_store
from tests.fixtures.fake_source import (
    FIXTURE_JOBS,
    FailingJobSource,
    FakeJobSource,
    make_listing,
)


@pytest.fixture()
def tmp_session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    engine.dispose()


@pytest.fixture()
def profile() -> CandidateProfile:
    return CandidateProfile(
        personal_information=PersonalInformation(name="Ahmad Hassan", title="AI Engineer"),
        skills=["Python", "FastAPI", "AWS"],
    )


class _ArrayFakeAPI:
    """Duck-typed client.models returning fixed 64-dim vectors, call-counting."""

    def __init__(self) -> None:
        self.calls = 0

    def embed_content(self, model, contents, config=None):
        self.calls += 1
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1] * 64) for _ in contents])


class QuotaExhaustedEmbedding:
    """EmbeddingFn double whose document embed always hits the daily wall."""

    def estimate_api_requests(self, texts):
        return 5

    def remaining_daily_budget(self):
        return 0

    def embed_documents(self, texts):
        raise LLMDailyQuotaExhausted("daily budget spent")

    def embed_query(self, text):
        raise LLMDailyQuotaExhausted("daily budget spent")


class LocalProviderEmbedding:
    """FU-7 double: budget-less local provider (no accounting hooks at all)."""

    def embed_documents(self, texts):
        return [[0.0] * 8 for _ in texts]

    def embed_query(self, text):
        return [0.0] * 8


def test_refresh_with_local_provider_reports_zero_api_accounting(tmp_path, tmp_session_factory):
    """FU-7 acceptance: the fastembed path plans/spends no API batch requests
    and can never trip the quota flag — the getattr-guarded hooks stay 0."""
    store = make_store(tmp_path / "chroma", FakeEmbeddingFn())
    report = refresh_jobs(
        sources={"fixture": FakeJobSource()},
        store_factory=lambda: store,
        session_factory=tmp_session_factory,
        embedding_fn=LocalProviderEmbedding(),
    )

    assert report.stats.embedded == len(FIXTURE_JOBS)
    assert report.embedding_requests_planned == 0
    assert report.embedding_requests_used == 0
    assert report.quota_exhausted is False
    assert report.degraded_embedding is False


# ----------------------------------------------------------------- refresh --


def test_refresh_persists_and_embeds_fixture_jobs(tmp_path, tmp_session_factory):
    store = make_store(tmp_path / "chroma", FakeEmbeddingFn())
    report = refresh_jobs(
        sources={"fixture": FakeJobSource()},
        store_factory=lambda: store,
        session_factory=tmp_session_factory,
    )

    assert report.stats.found == len(FIXTURE_JOBS)
    assert report.stats.deduped == len(FIXTURE_JOBS)
    assert report.stats.persisted == len(FIXTURE_JOBS)
    assert report.stats.embedded == len(FIXTURE_JOBS)
    assert report.source_errors == {}
    assert store.count() == len(FIXTURE_JOBS)


def test_refresh_is_idempotent_second_run_makes_zero_api_calls(tmp_path, tmp_session_factory):
    """FU-1 acceptance: the content-hash cache makes the second run free."""
    api = _ArrayFakeAPI()
    from src.llm.embeddings import GeminiEmbedding

    embedding = GeminiEmbedding(
        model="test-model",
        dimensionality=64,
        cache_path=tmp_path / "cache.sqlite",
        api_key="test-key-not-real",
        client=SimpleNamespace(models=api),
    )
    store = make_store(tmp_path / "chroma", embedding)

    first = refresh_jobs(
        sources={"fixture": FakeJobSource()},
        store_factory=lambda: store,
        session_factory=tmp_session_factory,
        embedding_fn=embedding,
    )
    calls_after_first = api.calls

    second = refresh_jobs(
        sources={"fixture": FakeJobSource()},
        store_factory=lambda: store,
        session_factory=tmp_session_factory,
        embedding_fn=embedding,
    )

    assert calls_after_first > 0  # the first run really embedded
    assert api.calls == calls_after_first  # second run: pure cache hits
    assert second.stats.persisted == first.stats.persisted  # merge, no duplicates
    assert second.embedding_requests_used == 0
    assert second.quota_exhausted is False


def test_refresh_records_failing_source_and_continues(tmp_path, tmp_session_factory):
    report = refresh_jobs(
        sources={"fixture": FakeJobSource(), "broken": FailingJobSource()},
        store_factory=lambda: make_store(tmp_path / "chroma", FakeEmbeddingFn()),
        session_factory=tmp_session_factory,
    )

    assert "broken" in report.source_errors
    assert report.stats.persisted == len(FIXTURE_JOBS)  # the healthy source ran


def test_refresh_daily_quota_stop_is_partial_and_resumable(tmp_path, tmp_session_factory):
    report = refresh_jobs(
        sources={"fixture": FakeJobSource()},
        store_factory=lambda: make_store(tmp_path / "chroma", QuotaExhaustedEmbedding()),
        session_factory=tmp_session_factory,
        embedding_fn=QuotaExhaustedEmbedding(),
    )

    assert report.quota_exhausted is True
    assert report.degraded_embedding is False
    assert report.stats.persisted == len(FIXTURE_JOBS)  # rows survived
    assert report.stats.embedded == 0  # no vectors written
    assert report.embedding_requests_planned == 5  # from the embedding's estimate


def test_refresh_vector_store_failure_degrades_not_raises(tmp_path, tmp_session_factory):
    def broken_factory():
        raise RuntimeError("chroma unavailable")

    report = refresh_jobs(
        sources={"fixture": FakeJobSource()},
        store_factory=broken_factory,
        session_factory=tmp_session_factory,
    )

    assert report.degraded_embedding is True
    assert report.quota_exhausted is False
    assert report.stats.persisted == len(FIXTURE_JOBS)
    assert report.stats.embedded == 0


def test_refresh_drops_incomplete_listings(tmp_path, tmp_session_factory):
    incomplete = [
        make_listing("9", "", "NoTitle"),  # empty title
        make_listing("10", "Valid Role", "Acme"),
    ]
    report = refresh_jobs(
        sources={"fixture": FakeJobSource(listings=incomplete)},
        store_factory=lambda: make_store(tmp_path / "chroma", FakeEmbeddingFn()),
        session_factory=tmp_session_factory,
    )

    assert report.stats.found == 2
    assert report.stats.dropped == 1
    assert report.stats.deduped == 1


# -------------------------------------------------------- store-only search --


def test_search_stored_jobs_contacts_no_sources_ranks_persisted_corpus(
    tmp_path, tmp_session_factory, profile
):
    store = make_store(tmp_path / "chroma", FakeEmbeddingFn())
    refresh_jobs(
        sources={"fixture": FakeJobSource()},
        store_factory=lambda: store,
        session_factory=tmp_session_factory,
    )

    report = search_stored_jobs(
        profile, store_factory=lambda: store, session_factory=tmp_session_factory
    )

    assert report.stats.found == 0  # store-only: no source stats
    assert report.stats.stored == len(FIXTURE_JOBS)
    assert 0 < len(report.results) <= 10
    assert report.degraded is False  # every stored job had a vector
    # Ranked: the Python-heavy fixture jobs must outrank the DevOps-only one.
    top_titles = [pair.job.title for pair in report.results]
    assert "Senior Python Engineer" in top_titles
    assert top_titles.index("Senior Python Engineer") < top_titles.index("DevOps Engineer")


def test_search_stored_jobs_query_and_location_filters(tmp_path, tmp_session_factory, profile):
    store = make_store(tmp_path / "chroma", FakeEmbeddingFn())
    refresh_jobs(
        sources={"fixture": FakeJobSource()},
        store_factory=lambda: store,
        session_factory=tmp_session_factory,
    )

    filtered = search_stored_jobs(
        profile,
        query="devops",  # token matches the title (filter scans title+description)
        store_factory=lambda: store,
        session_factory=tmp_session_factory,
    )
    assert {pair.job.title for pair in filtered.results} == {"DevOps Engineer"}

    location_filtered = search_stored_jobs(
        profile,
        location="remote",
        store_factory=lambda: store,
        session_factory=tmp_session_factory,
    )
    assert location_filtered.stats.stored == len(FIXTURE_JOBS)  # all are Remote
    assert location_filtered.stats.deduped == len(FIXTURE_JOBS)

    no_match = search_stored_jobs(
        profile,
        query="java",
        store_factory=lambda: store,
        session_factory=tmp_session_factory,
    )
    assert no_match.results == []
    assert no_match.stats.stored == 0


def test_search_stored_jobs_missing_vectors_degrade_not_fail(
    tmp_path, tmp_session_factory, profile
):
    """A job in the DB without a vector (backfill in flight) -> degraded."""
    save_jobs(
        [make_listing("99", "Java Developer", "Unembedded Co")],
        session_factory=tmp_session_factory,
    )
    store = make_store(tmp_path / "chroma", FakeEmbeddingFn())

    report = search_stored_jobs(
        profile, store_factory=lambda: store, session_factory=tmp_session_factory
    )

    assert report.stats.stored == 1
    assert report.degraded is True
    assert len(report.results) == 1  # still scored, just without semantics


def test_search_stored_jobs_empty_database_returns_empty_report(tmp_session_factory, profile):
    report = search_stored_jobs(profile, session_factory=tmp_session_factory)

    assert report.results == []
    assert report.stats.stored == 0
    assert report.degraded is False


def test_run_job_search_keeps_original_shape_for_tests_and_demo(
    tmp_path, tmp_session_factory, profile
):
    """Backwards compatibility: the graph path still works end-to-end."""
    report = run_job_search(
        profile,
        sources={"fixture": FakeJobSource()},
        store_factory=lambda: make_store(tmp_path / "chroma", FakeEmbeddingFn()),
        session_factory=tmp_session_factory,
    )

    assert isinstance(report, JobSearchReport)
    # The planner derives 2 queries for this profile (title + first skill
    # trio) and every query hits the fixture source: found counts raw hits.
    assert report.stats.found == 2 * len(FIXTURE_JOBS)
    assert report.stats.deduped == len(FIXTURE_JOBS)
    assert report.results


class PartialQuotaEmbedding(FakeEmbeddingFn):
    """FakeEmbeddingFn that hits the daily wall after 2 successful chunks."""

    def __init__(self) -> None:
        super().__init__()
        self.budget = 20

    def embed_documents(self, texts):
        if self.document_calls >= 2:
            raise LLMDailyQuotaExhausted("daily budget spent")
        self.budget -= 1
        return super().embed_documents(texts)

    def remaining_daily_budget(self):
        return self.budget


def test_refresh_quota_stop_keeps_completed_chunks_in_store(tmp_path, tmp_session_factory):
    """250 listings -> 3 chunks of 100: two chunks embed+upsert, the third
    hits the wall. The store keeps the 200 completed listings and the report
    counts them as partial progress (FU-1 resumability).

    WS-12: the descriptions are distinct. The default fixture description
    is the same for every listing, and 250 listings sharing one body
    across 250 different companies is exactly the flood signature the
    spam screen detects — so the fixture would be measuring the screen
    instead of the chunking. Each listing gets its own body here, which is
    also what 250 real postings look like.
    """
    many = [
        make_listing(
            str(i),
            f"Role {i} python",
            f"Company {i}",
            source="fixture",
            description=f"Build backend services with Python. Team {i} owns service {i}.",
        )
        for i in range(250)
    ]
    embedding = PartialQuotaEmbedding()
    report = refresh_jobs(
        sources={"fixture": FakeJobSource(listings=many)},
        store_factory=lambda: make_store(tmp_path / "chroma", embedding),
        session_factory=tmp_session_factory,
        embedding_fn=embedding,
    )

    assert report.quota_exhausted is True
    assert report.stats.embedded == 200  # two completed chunks survive
    assert make_store(tmp_path / "chroma", FakeEmbeddingFn()).count() == 200
    assert report.stats.persisted == 250  # every row persisted regardless
    assert report.embedding_requests_used == 2  # two batches actually spent
