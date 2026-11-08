"""WS-21 follow-up: the corpus-artifact cache — rebuilt exactly when the corpus changes.

The cache exists because a search re-derived, per request, things that depend
only on the corpus: the listings, the BM25 index, every posting's important
terms, and every posting's stated experience bar (measured: ~40 s of a
request at 6,696 listings). Its key is the corpus's own bookkeeping — row
count plus the newest ``last_seen_at`` — so a refresh invalidates it without
an explicit call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.jobs import JobDB
from src.jobs.contracts import JobListing
from src.matching.corpus_cache import (
    clear_corpus_cache,
    corpus_fingerprint,
    get_corpus_artifacts,
)
from src.matching.experience import experience_score, required_years
from src.matching.lexical import Bm25Index, _important_terms, lexical_score
from src.resume.profile import CandidateProfile, ExperienceEntry, PersonalInformation

DESCRIPTION = (
    "Build responsive web applications with React and Node. 3+ years of experience required."
)


@pytest.fixture
def factory(tmp_path: Path):
    clear_corpus_cache()
    engine = create_engine(f"sqlite:///{(tmp_path / 'corpus.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()
    clear_corpus_cache()


def add_job(
    factory,
    job_id: str = "job-1",
    title: str = "Web Developer",
    seen: datetime | None = None,
) -> None:
    if seen is None:
        seen = datetime(2026, 11, 8, 9, 0, 0, tzinfo=UTC)
    with factory() as session:
        session.add(
            JobDB(
                id=job_id,
                source="greenhouse",
                title=title,
                company="Acme",
                description=DESCRIPTION,
                required_skills=["React"],
                preferred_skills=[],
                last_seen_at=seen,
            )
        )
        session.commit()


def test_artifacts_are_built_once_per_corpus_state(factory):
    add_job(factory)
    first = get_corpus_artifacts(session_factory=factory)
    second = get_corpus_artifacts(session_factory=factory)
    assert first is second  # one build, reused
    assert len(first.jobs) == 1
    assert first.index is not None and len(first.index) == 1
    assert "job-1" in first.lexical_terms
    assert first.required_years["job-1"] == 3.0


def test_a_new_listing_moves_the_fingerprint(factory):
    add_job(factory)
    before = get_corpus_artifacts(session_factory=factory)
    add_job(factory, job_id="job-2", title="Data Analyst")
    after = get_corpus_artifacts(session_factory=factory)
    assert after is not before
    assert len(after.jobs) == 2


def test_a_re_seen_listing_moves_the_fingerprint(factory):
    """A refresh that touches rows without adding any must still invalidate."""
    add_job(factory)
    before = corpus_fingerprint(factory)
    before_artifacts = get_corpus_artifacts(session_factory=factory)
    with factory() as session:
        row = session.get(JobDB, "job-1")
        row.last_seen_at = datetime(2026, 11, 8, 12, 0, 0, tzinfo=UTC)
        session.commit()
    assert corpus_fingerprint(factory) != before
    assert get_corpus_artifacts(session_factory=factory) is not before_artifacts


def test_two_databases_never_share_an_entry(factory, tmp_path: Path):
    """The fingerprint names the database: same shape, different corpus."""
    add_job(factory)
    first = get_corpus_artifacts(session_factory=factory)

    other_engine = create_engine(f"sqlite:///{(tmp_path / 'other.db').as_posix()}")
    Base.metadata.create_all(other_engine)
    other = sessionmaker(bind=other_engine, autoflush=False)
    add_job(other)  # same count, same last_seen_at — different rows
    second = get_corpus_artifacts(session_factory=other)
    assert second is not first
    other_engine.dispose()


def test_clearing_rebuilds(factory):
    add_job(factory)
    first = get_corpus_artifacts(session_factory=factory)
    clear_corpus_cache()
    assert get_corpus_artifacts(session_factory=factory) is not first


def test_precomputed_lexical_terms_are_equivalent(factory):
    add_job(factory)
    artifacts = get_corpus_artifacts(session_factory=factory)
    listing = artifacts.jobs[0]
    index = Bm25Index([listing])
    tokens = ["react", "node", "javascript"]
    text = "react node javascript"

    with_cache = lexical_score(
        listing,
        index=index,
        candidate_token_list=tokens,
        candidate_text=text,
        important_terms=artifacts.lexical_terms[listing.id],
    )
    fresh = lexical_score(listing, index=index, candidate_token_list=tokens, candidate_text=text)
    assert with_cache == fresh
    assert artifacts.lexical_terms[listing.id] == _important_terms(listing)


def test_precomputed_requirement_is_equivalent(factory):
    add_job(factory)
    artifacts = get_corpus_artifacts(session_factory=factory)
    listing = artifacts.jobs[0]
    profile = CandidateProfile(
        personal_information=PersonalInformation(),
        experience=[ExperienceEntry(title="Developer", company="A", years=5)],
    )
    assert required_years(listing) == 3.0
    with_cache = experience_score(
        listing, profile, requirement=artifacts.required_years[listing.id]
    )
    fresh = experience_score(listing, profile)
    assert with_cache == fresh == 100.0


def test_an_uncached_listing_computes_as_before(factory):
    """A listing that is not in the artifacts still scores correctly.

    The engine distinguishes "not in the cache" from a cached ``None`` with a
    sentinel — a plain ``dict.get`` would read a missing key as "no stated
    requirement", which is a real (different) value. This mirrors the engine's
    exact contract: look up with a sentinel, parse only when it comes back.
    """
    add_job(factory)
    artifacts = get_corpus_artifacts(session_factory=factory)
    outsider = JobListing(
        id="job-outside",
        source="greenhouse",
        title="Backend Engineer",
        company="Acme",
        description=DESCRIPTION,
    )
    profile = CandidateProfile(
        personal_information=PersonalInformation(),
        experience=[ExperienceEntry(title="Developer", company="A", years=5)],
    )
    uncached = object()
    requirement = artifacts.required_years.get(outsider.id, uncached)
    assert requirement is uncached
    if requirement is uncached:
        requirement = required_years(outsider)
    assert experience_score(outsider, profile, requirement=requirement) == experience_score(
        outsider, profile
    )
