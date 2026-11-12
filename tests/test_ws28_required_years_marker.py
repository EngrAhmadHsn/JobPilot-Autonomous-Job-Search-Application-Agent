"""WS-28 · NULL cannot mean two things.

`jobs.required_years` is NULL both for a row written before WS-23b and for a
row that was mined and states no bar. The read path re-mines both, which is
20.6 s of every cold start on the 8,558-listing corpus. A separate marker says
which is which, so a decided row is decided once.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _listing(**overrides):
    from src.jobs.contracts import JobListing

    data = {
        "id": "test:1",
        "source": "test",
        "source_job_id": "1",
        "title": "Engineer",
        "company": "Acme",
        "description": "",
    }
    data.update(overrides)
    return JobListing(**data)


def test_a_written_row_is_marked_mined(factory):
    """`merge_jobs` is the only writer, so it always sets the marker."""
    from src.db.jobs import JobDB, merge_jobs

    with factory() as session:
        merge_jobs(session, [_listing()])
        session.commit()
    with factory() as session:
        assert session.get(JobDB, "test:1").required_years_mined is True


def test_a_mined_row_with_no_bar_keeps_its_null_value(factory):
    """The marker records the attempt; the value stays honest."""
    from src.db.jobs import JobDB, merge_jobs

    with factory() as session:
        merge_jobs(session, [_listing(description="No numbers here.")])
        session.commit()
    with factory() as session:
        row = session.get(JobDB, "test:1")
        assert row.required_years is None
        assert row.required_years_mined is True


def test_a_zero_bar_is_preserved(factory):
    """`0` is a real bar (an intern listing), not 'nothing stated'."""
    from src.db.jobs import JobDB, merge_jobs

    with factory() as session:
        merge_jobs(session, [_listing(description="0 years of experience required.")])
        session.commit()
    with factory() as session:
        row = session.get(JobDB, "test:1")
        assert row.required_years == 0.0
        assert row.required_years_mined is True


def test_an_unmarked_row_is_still_mined(factory):
    """A database written before this migration must read as 'never mined'."""
    from src.db.jobs import JobDB
    from src.matching.corpus_cache import get_corpus_artifacts

    with factory() as session:
        session.add(
            JobDB(
                id="legacy:1",
                source="legacy",
                source_job_id="1",
                title="Engineer",
                company="Acme",
                description="Minimum 6 years of engineering experience.",
                required_years=None,
                required_years_mined=False,
            )
        )
        session.commit()

    artifacts = get_corpus_artifacts(session_factory=factory)
    assert artifacts.required_years["legacy:1"] == 6.0


def test_a_marked_row_states_no_bar_and_is_not_mined(factory):
    """The 20.6 s: a marked row must never reach the miner."""
    from src.db.jobs import JobDB
    from src.matching import corpus_cache

    with factory() as session:
        # The description *does* state a bar; the marker says it was already
        # decided. If the read path re-mines, it returns 6.0 and this fails.
        session.add(
            JobDB(
                id="mined:1",
                source="mined",
                source_job_id="1",
                title="Engineer",
                company="Acme",
                description="Minimum 6 years of engineering experience.",
                required_years=None,
                required_years_mined=True,
            )
        )
        session.commit()

    corpus_cache.clear_corpus_cache()
    artifacts = corpus_cache.get_corpus_artifacts(session_factory=factory)
    assert artifacts.required_years["mined:1"] is None
