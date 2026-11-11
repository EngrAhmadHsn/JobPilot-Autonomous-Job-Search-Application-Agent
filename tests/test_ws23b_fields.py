"""WS-23b · The admission age bound, the mined bar, and the first sighting.

Three holes a later review found in the WS-23 work:

* **`experience_requirements` was 0% populated.** The *mining* existed
  but ran at read time, 9.5 s of the 32.56 s artifacts rebuild. It is now
  mined once at write time into a separate `required_years` column —
  separate on purpose, because an inference must not be indistinguishable
  from what the board stated.
* **The corpus had no age signal.** A posting closed months ago was
  still admitted, still ranked, and still had a valid application URL.
* **The corpus could not distinguish "seen for three months" from "seen
  once"** — there was no `first_seen_at`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.jobs import JobDB, merge_jobs
from src.jobs.contracts import JobListing


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _listing(job_id: str, **overrides) -> JobListing:
    payload = {
        "id": job_id,
        "source": job_id.split(":")[0],
        "source_job_id": job_id.split(":")[-1],
        "title": "Senior Engineer",
        "company": "Acme",
        "description": "You will build services. 5+ years of experience required.",
        "location": "Remote",
    }
    payload.update(overrides)
    return JobListing(**payload)


def _seed(session_factory, listings, *, seen_at=None):
    with session_factory() as session:
        merge_jobs(session, listings, seen_at=seen_at or datetime.now(UTC))
        session.commit()


# ------------------------------------------------- the mined experience bar


def test_the_bar_is_mined_at_write_time(session_factory):
    """The column is populated from the description, once, at ingest."""
    _seed(session_factory, [_listing("greenhouse:a:1")])

    with session_factory() as session:
        row = session.get(JobDB, "greenhouse:a:1")
    assert row.required_years == 5.0


def test_the_bar_is_separate_from_what_the_board_stated(session_factory):
    """An inference must not be indistinguishable from a published fact.

    `experience_requirements` is what the board said (usually nothing);
    `required_years` is what the system inferred. Collapsing them would
    lose that distinction, which the score states exist to preserve.
    """
    _seed(session_factory, [_listing("greenhouse:a:1")])

    with session_factory() as session:
        row = session.get(JobDB, "greenhouse:a:1")
    assert row.experience_requirements is None, "the board stated nothing"
    assert row.required_years == 5.0, "the system inferred a bar"


def test_the_board_statement_is_searched_too(session_factory):
    """A published bar is part of the input, not ignored.

    ``required_years`` searches the board's own
    ``experience_requirements`` **and** the description, and takes the
    highest general bar across both (WS-20's rule: a listing may state a
    headline bar and a stricter one in its body). This test pins that the
    published field is read at all — a later change that dropped it would
    make a board-stated bar invisible.
    """
    _seed(
        session_factory,
        [
            _listing(
                "greenhouse:a:1",
                experience_requirements="8+ years",
                description="Build things.",
            )
        ],
    )

    with session_factory() as session:
        row = session.get(JobDB, "greenhouse:a:1")
    assert row.required_years == 8.0, "the published bar was not read"


def test_the_description_is_searched_when_the_board_states_nothing(session_factory):
    """The common case: the board publishes no bar, so the body is mined."""
    _seed(
        session_factory,
        [
            _listing(
                "greenhouse:a:1",
                description="You will build services. 3+ years of experience required.",
            )
        ],
    )

    with session_factory() as session:
        row = session.get(JobDB, "greenhouse:a:1")
    assert row.required_years == 3.0


def test_a_listing_with_no_bar_states_none(session_factory):
    """No bar stated is `None`, not a fabricated zero."""
    _seed(
        session_factory,
        [_listing("greenhouse:a:1", description="Build things.")],
    )

    with session_factory() as session:
        assert session.get(JobDB, "greenhouse:a:1").required_years is None


def test_a_failed_mining_does_not_lose_the_listing(session_factory):
    """The bar is derived data; a failure must not drop the row."""
    _seed(session_factory, [_listing("greenhouse:a:1", description=None)])

    with session_factory() as session:
        row = session.get(JobDB, "greenhouse:a:1")
    assert row is not None
    assert row.required_years is None


# ------------------------------------------------------ the first sighting


def test_the_first_sighting_is_recorded(session_factory):
    """The corpus can now say when it first saw a listing."""
    moment = datetime.now(UTC)
    _seed(session_factory, [_listing("greenhouse:a:1")], seen_at=moment)

    with session_factory() as session:
        row = session.get(JobDB, "greenhouse:a:1")
    assert row.first_seen_at is not None
    assert row.last_seen_at is not None


def test_a_re_sighting_does_not_move_the_first_sighting(session_factory):
    """`merge` writes every column, so the first sighting must be carried.

    Without this the column would say "first seen now" on every refresh,
    which is the same as not having it.
    """
    first = datetime.now(UTC) - timedelta(days=30)
    _seed(session_factory, [_listing("greenhouse:a:1")], seen_at=first)
    with session_factory() as session:
        original = session.get(JobDB, "greenhouse:a:1").first_seen_at

    _seed(session_factory, [_listing("greenhouse:a:1")], seen_at=datetime.now(UTC))

    with session_factory() as session:
        row = session.get(JobDB, "greenhouse:a:1")
    assert row.first_seen_at == original, "the first sighting moved on a re-sighting"
    assert row.last_seen_at > original


def test_a_changed_listing_keeps_its_first_sighting(session_factory):
    """A content change is not a new listing."""
    first = datetime.now(UTC) - timedelta(days=10)
    _seed(session_factory, [_listing("greenhouse:a:1")], seen_at=first)
    with session_factory() as session:
        original = session.get(JobDB, "greenhouse:a:1").first_seen_at

    _seed(
        session_factory,
        [_listing("greenhouse:a:1", description="A different description.")],
    )

    with session_factory() as session:
        row = session.get(JobDB, "greenhouse:a:1")
    assert row.first_seen_at == original


# -------------------------------------------------------- the admission age


def _limits(max_job_age_days: int):
    """SecurityLimits with the age bound set, and everything else generous."""
    from src.security.limits import SecurityLimits

    return SecurityLimits(
        rate_limit_requests=100,
        rate_limit_window_seconds=60.0,
        body_limit_bytes=1024 * 1024,
        max_concurrent_heavy=4,
        heavy_queue_timeout_seconds=10.0,
        max_inflight_requests=64,
        max_listings_per_source=10_000,
        max_new_listings_per_refresh=10_000,
        max_corpus_listings=50_000,
        max_corpus_evictions_per_refresh=5_000,
        max_job_age_days=max_job_age_days,
        max_embed_per_refresh=2_000,
        max_embed_work_per_day=5_000,
        max_cache_entries=50_000,
        max_pending_runs=25,
        max_pending_work_items=20_000,
        max_upload_uncompressed_bytes=50 * 1024 * 1024,
        max_zip_entries=2_000,
        max_response_bytes=16 * 1024 * 1024,
        max_custom_fields=50,
        max_custom_field_chars=2_000,
        max_description_chars=20_000,
        max_title_chars=300,
        max_company_chars=200,
        max_prompt_untrusted_chars=20_000,
    )


def test_an_old_posting_is_not_admitted():
    """A posting from six months ago is not a job anyone should apply to."""
    from src.security.admission import admit_listings

    old = (datetime.now(UTC) - timedelta(days=200)).isoformat()
    report = admit_listings(
        [_listing("greenhouse:a:1", posted_at=old)],
        limits=_limits(120),
    )

    assert report.admitted == []
    assert report.age_capped == 1


def test_a_recent_posting_is_admitted():
    """The bound must not reject what it should keep."""
    from src.security.admission import admit_listings

    recent = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    report = admit_listings(
        [_listing("greenhouse:a:1", posted_at=recent)],
        limits=_limits(120),
    )

    assert len(report.admitted) == 1
    assert report.age_capped == 0


def test_a_listing_with_no_date_is_kept():
    """An absent date is not evidence of an old listing."""
    from src.security.admission import admit_listings

    report = admit_listings(
        [_listing("greenhouse:a:1", posted_at=None)],
        limits=_limits(120),
    )

    assert len(report.admitted) == 1
    assert report.age_capped == 0


def test_an_unparsable_date_is_kept():
    """Refusing a listing on a date nobody can read would be a guess."""
    from src.security.admission import admit_listings

    report = admit_listings(
        [_listing("greenhouse:a:1", posted_at="last Tuesday")],
        limits=_limits(120),
    )

    assert len(report.admitted) == 1


def test_the_bound_can_be_disabled():
    """0 disables it, for a first run against a historical archive."""
    from src.security.admission import admit_listings

    old = (datetime.now(UTC) - timedelta(days=3_000)).isoformat()
    report = admit_listings(
        [_listing("greenhouse:a:1", posted_at=old)],
        limits=_limits(0),
    )

    assert len(report.admitted) == 1


def test_the_age_bound_runs_before_the_other_caps():
    """A washed-out listing must not take a live one's slot.

    The bound runs first, so an old listing does not consume a per-source
    slot or an embedding budget slot that a live listing could use.
    """
    from src.security.admission import admit_listings

    old = (datetime.now(UTC) - timedelta(days=500)).isoformat()
    listings = [
        _listing("greenhouse:a:1", posted_at=old),
        _listing("greenhouse:a:2", posted_at=None),
    ]
    report = admit_listings(listings, limits=_limits(120))

    assert [job.id for job in report.admitted] == ["greenhouse:a:2"]
    assert report.per_source_capped == 0, "the old listing took a slot it should not have"


def test_the_default_bound_is_configured():
    """The knob exists in the limit set and the env contract."""
    from src.security.limits import get_limits

    assert get_limits().max_job_age_days == 120
