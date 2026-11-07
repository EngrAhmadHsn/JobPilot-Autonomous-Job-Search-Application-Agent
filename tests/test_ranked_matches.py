"""WS-21: the ranked match view — relevance, not a trail.

The defect these tests pin down: the Tailor picker consumed the raw match
history (worst-of-newest-batch first, duplicated per search) and sliced it
client-side, so the displayed order had nothing to do with relevance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db import access
from src.db.access import UserScope
from src.db.base import Base
from src.db.matches import JobMatchDB

OWNER = UserScope(user_id="owner")
OTHER = UserScope(user_id="other")
PROFILE = "profile-1"


def _timestamp(hour: int) -> datetime:
    return datetime(2026, 11, 8, hour, 0, 0, tzinfo=UTC).replace(tzinfo=None)


@pytest.fixture
def session(tmp_path: Path):
    """A throwaway database with the WS-21 ranking scenario."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'ranked.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:

        def add(job_id: str, score: object, created: datetime, owner: str = OWNER.user_id):
            db.add(
                JobMatchDB(
                    owner_id=owner,
                    profile_id=PROFILE,
                    job_id=job_id,
                    scores={"overall_score": score} if score is not None else {},
                    explanation="",
                    created_at=created,
                )
            )

        # An earlier search scored job-b at 95; the newer search scored it 91.
        # The newer score is the current one — the older high score must not
        # win.
        add("job-b", 95, _timestamp(8))
        add("job-a", 45, _timestamp(9))
        add("job-c", 72, _timestamp(10))
        add("job-d", 84, _timestamp(11))
        add("job-b", 91, _timestamp(12))
        # A row the payload malformed: safely last, never a crash.
        add("job-e", "not-a-number", _timestamp(13))
        # Another owner's history for the same profile id.
        add("job-x", 99, _timestamp(14), owner=OTHER.user_id)
        db.commit()
    yield factory
    engine.dispose()


def _ids(rows: list[JobMatchDB]) -> list[str]:
    return [row.job_id for row in rows]


def test_newest_score_per_job_in_descending_order(session):
    with session() as db:
        rows = access.list_ranked_job_matches(db, OWNER, PROFILE)
    # The brief's fixture shape: B(91), D(84), C(72), A(45) — and the older
    # B(95) row is not the current score.
    assert _ids(rows) == ["job-b", "job-d", "job-c", "job-a", "job-e"]


def test_the_limit_applies_after_deduplication(session):
    with session() as db:
        rows = access.list_ranked_job_matches(db, OWNER, PROFILE, limit=2)
    assert _ids(rows) == ["job-b", "job-d"]


def test_missing_and_malformed_scores_sort_last(session):
    with session() as db:
        rows = access.list_ranked_job_matches(db, OWNER, PROFILE)
    by_job = {row.job_id: row for row in rows}
    assert by_job["job-e"].scores.get("overall_score") == "not-a-number"
    assert _ids(rows)[-1] == "job-e"


def test_ties_break_by_newest_then_job_id(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'ties.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for job_id, hour in (("job-z", 8), ("job-a", 8), ("job-m", 9)):
            db.add(
                JobMatchDB(
                    owner_id=OWNER.user_id,
                    profile_id=PROFILE,
                    job_id=job_id,
                    scores={"overall_score": 70},
                    created_at=_timestamp(hour),
                )
            )
        db.commit()
        rows = access.list_ranked_job_matches(db, OWNER, PROFILE)
    # job-m is newer; job-a and job-z share a timestamp, so the job id decides.
    assert _ids(rows) == ["job-m", "job-a", "job-z"]
    engine.dispose()


def test_another_scope_sees_only_its_own_rows(session):
    with session() as db:
        owner_rows = access.list_ranked_job_matches(db, OWNER, PROFILE)
        other_rows = access.list_ranked_job_matches(db, OTHER, PROFILE)
    # The other owner's row never leaks into this owner's view…
    assert "job-x" not in _ids(owner_rows)
    # …and the other scope sees exactly its own row for the same profile id.
    assert _ids(other_rows) == ["job-x"]


def test_the_default_limit_is_twenty_five(session):
    with session() as db:
        rows = access.list_ranked_job_matches(db, OWNER, PROFILE)
    assert len(rows) <= 25
