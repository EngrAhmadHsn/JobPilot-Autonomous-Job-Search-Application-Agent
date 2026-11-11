"""WS-23 · The corpus correctness tests.

Every test here corresponds to a defect measured against the live corpus
on 2026-11-09. The defects are listed in
``docs/implementation/23-corpus-correctness.md``; the short version:

* three live boards were **silently dropped whole** by the 8 MiB response
  cap (anthropic 9.83 MiB, databricks 9.58 MiB, ashby/openai 13.58 MiB),
  taking 1,696 listings with them;
* the eviction ordered by ``last_seen_at`` and SQLite sorts NULL first,
  so it was selecting **exactly the rows that had failed to refresh** —
  45.4% of the corpus;
* the field columns were 0% populated for the fields the matching layer
  weighs;
* Remotive's query parameters were inert, so a query returned the whole
  board;
* the location component **asserted** a value of 40 for a listing that
  stated nothing.

The reproducing tests come first: each one fails against the code as it
was before this workstream.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.jobs import JobDB, content_version_for, prune_stale_jobs, touch_jobs
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
        "title": "Senior Backend Engineer",
        "company": "Acme",
        "description": "Build services in Python and Go.",
        "location": "Berlin, Germany",
        "application_url": f"https://boards.greenhouse.io/acme/jobs/{job_id}",
    }
    payload.update(overrides)
    return JobListing(**payload)


def _seed(session_factory, listings, seen_at=None):
    from src.db.jobs import merge_jobs

    with session_factory() as session:
        merge_jobs(session, listings, seen_at=seen_at or datetime.now(UTC))
        session.commit()


# ---------------------------------------------------------------- eviction


def test_a_never_seen_row_is_never_evicted(session_factory):
    """A row with no sighting is unknown, not dead.

    This is the acute half of the defect: 3,042 of 6,696 rows (45.4%)
    carried a NULL sighting, and SQLite sorts NULL first in
    ``ORDER BY last_seen_at ASC``, so the eviction queue selected them
    first.
    """
    _seed(
        session_factory,
        [_listing("greenhouse:a:1"), _listing("greenhouse:a:2")],
        seen_at=datetime.now(UTC) - timedelta(days=10),
    )
    # One row has never been seen.
    with session_factory() as session:
        session.query(JobDB).filter(JobDB.id == "greenhouse:a:1").update(
            {JobDB.last_seen_at: None}, synchronize_session=False
        )
        session.commit()

    removed = prune_stale_jobs(session_factory, keep=0, limit=10)

    with session_factory() as session:
        remaining = {row.id for row in session.query(JobDB).all()}
    assert "greenhouse:a:1" in remaining, "a never-seen row must not be evicted"
    assert "greenhouse:a:2" not in remaining, "the stale row should have been evicted"
    assert removed == ["greenhouse:a:2"]


def test_a_failing_sources_rows_are_not_evicted(session_factory):
    """A source that is failing must not age out its own coverage.

    The eviction is global by design, so without this the rows of a board
    that started returning 403 would be the oldest sightings in the
    corpus and would be deleted wholesale — the failure would destroy the
    very data it is about.
    """
    old = datetime.now(UTC) - timedelta(days=30)
    _seed(session_factory, [_listing("greenhouse:a:1")], seen_at=old)
    _seed(session_factory, [_listing("ashby:b:1")], seen_at=old)

    removed = prune_stale_jobs(
        session_factory,
        keep=0,
        limit=10,
        protected_sources=["ashby"],
    )

    with session_factory() as session:
        remaining = {row.id for row in session.query(JobDB).all()}
    assert remaining == {"ashby:b:1"}, "only the healthy source's rows should go"
    assert removed == ["greenhouse:a:1"]


def test_a_referenced_row_is_not_evicted(session_factory):
    """A listing an application points at must survive the eviction.

    There is no foreign key from ``applications`` to ``jobs``, so an
    application can point at a listing that no longer exists.
    """
    old = datetime.now(UTC) - timedelta(days=30)
    _seed(session_factory, [_listing("greenhouse:a:1"), _listing("greenhouse:a:2")], seen_at=old)

    removed = prune_stale_jobs(
        session_factory,
        keep=0,
        limit=10,
        protected_job_ids=["greenhouse:a:1"],
    )

    with session_factory() as session:
        remaining = {row.id for row in session.query(JobDB).all()}
    assert remaining == {"greenhouse:a:1"}
    assert removed == ["greenhouse:a:2"]


def test_the_eviction_is_still_bounded(session_factory):
    """One refresh may not turn into a mass delete."""
    old = datetime.now(UTC) - timedelta(days=30)
    _seed(session_factory, [_listing(f"greenhouse:a:{i}") for i in range(20)], seen_at=old)

    removed = prune_stale_jobs(session_factory, keep=0, limit=5)

    assert len(removed) == 5
    with session_factory() as session:
        assert session.query(JobDB).count() == 15


# ------------------------------------------------------- the sighting step


def test_touch_records_a_sighting_without_touching_the_content(session_factory):
    """The delta refresh stamps the unchanged listings as seen.

    Without this step the delta refresh would **shrink** the corpus: every
    unchanged listing would look stale, and the eviction would remove the
    ones it had not re-fetched.
    """
    _seed(session_factory, [_listing("greenhouse:a:1")])
    with session_factory() as session:
        row = session.get(JobDB, "greenhouse:a:1")
        original_content = row.content_version
        row.last_seen_at = None
        session.commit()

    touched = touch_jobs(session_factory, job_ids=["greenhouse:a:1"])

    assert touched == 1
    with session_factory() as session:
        row = session.get(JobDB, "greenhouse:a:1")
        assert row.last_seen_at is not None
        # The content version is what the corpus cache fingerprint reads,
        # so a sighting must not move it.
        assert row.content_version == original_content


# ------------------------------------------------------- the content version


def test_the_content_version_changes_only_with_the_content(session_factory):
    """The fingerprint must move when the content changes, and not otherwise.

    The digest is written by the merge — the same place the row is — so
    the test goes through that path rather than poking the column.
    """
    _seed(session_factory, [_listing("greenhouse:a:1")])

    with session_factory() as session:
        original = session.get(JobDB, "greenhouse:a:1").content_version
    assert original == content_version_for(_listing("greenhouse:a:1"))

    # A re-sighting of the same listing does not change the content.
    _seed(session_factory, [_listing("greenhouse:a:1")], seen_at=datetime.now(UTC))
    with session_factory() as session:
        assert session.get(JobDB, "greenhouse:a:1").content_version == original

    # A changed description does.
    _seed(session_factory, [_listing("greenhouse:a:1", description="A different description.")])
    with session_factory() as session:
        assert session.get(JobDB, "greenhouse:a:1").content_version != original


def test_a_refetched_listing_keeps_its_content_version(session_factory):
    """Re-serving an unchanged listing must not invalidate the cache."""
    listing = _listing("greenhouse:a:1")
    _seed(session_factory, [listing], seen_at=datetime.now(UTC))
    with session_factory() as session:
        first = session.get(JobDB, "greenhouse:a:1").content_version

    _seed(session_factory, [listing], seen_at=datetime.now(UTC) + timedelta(hours=1))
    with session_factory() as session:
        assert session.get(JobDB, "greenhouse:a:1").content_version == first


# ---------------------------------------------------------- the corpus cache


def test_the_fingerprint_survives_a_sighting_only_refresh(session_factory):
    """A refresh that re-sees unchanged listings keeps the cache.

    The fingerprint used to include ``max(last_seen_at)``, so every
    refresh invalidated the whole artifacts cache and the first search
    afterwards paid the 32.56 s rebuild again.
    """
    from src.matching.corpus_cache import clear_corpus_cache, corpus_fingerprint

    clear_corpus_cache()
    _seed(session_factory, [_listing("greenhouse:a:1"), _listing("greenhouse:a:2")])
    first = corpus_fingerprint(session_factory)

    # A refresh re-sees the same listings.
    _seed(
        session_factory,
        [_listing("greenhouse:a:1"), _listing("greenhouse:a:2")],
        seen_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert corpus_fingerprint(session_factory) == first

    # A content change does move it.
    _seed(
        session_factory,
        [
            _listing("greenhouse:a:1", description="changed"),
            _listing("greenhouse:a:2"),
        ],
    )
    assert corpus_fingerprint(session_factory) != first
    clear_corpus_cache()


# --------------------------------------------------------------- the fields


def test_seniority_is_classified_from_the_title():
    """The seniority column was 0% populated and carries weight 0.08."""
    from src.jobs.seniority import classify_seniority

    assert classify_seniority("Senior Backend Engineer") == "senior"
    assert classify_seniority("Sr. Software Engineer") == "senior"
    assert classify_seniority("Staff Engineer") == "staff"
    assert classify_seniority("Principal Engineer") == "principal"
    assert classify_seniority("Engineering Intern") == "intern"
    assert classify_seniority("Director of Engineering") == "director"
    assert classify_seniority("Head of Platform") == "head"
    assert classify_seniority("Product Manager") == "manager"
    # A title that states no level stays unknown — a wrong seniority is
    # worse than a missing one.
    assert classify_seniority("Software Engineer") is None
    assert classify_seniority("") is None
    assert classify_seniority(None) is None


def test_the_location_component_reports_unknown_instead_of_asserting_forty():
    """A listing that states no location or work mode is **unknown**.

    The fallback used to assert ``value = 40.0`` — a *measured* partial
    match — which under a fixed denominator was a 5.4-point penalty on
    78.5% of the corpus, including listings that were fully remote.
    """
    from src.matching.engine import _location_component
    from src.matching.scores import ScoreState
    from src.resume.profile import CandidateProfile, WorkPreferences

    profile = CandidateProfile(
        skills=["python"],
        work_preferences=WorkPreferences(
            remote_preference="remote",
            preferred_locations=["Berlin"],
        ),
    )
    listing = _listing("greenhouse:a:1", location=None, remote_policy=None)

    component = _location_component(listing, profile)
    assert component.state is ScoreState.JOB_REQUIREMENT_MISSING
    assert component.value == 0.0


def test_a_stated_location_is_still_a_measurement():
    """A location the candidate did not name is a mismatch, not an unknown."""
    from src.matching.engine import _location_component
    from src.resume.profile import CandidateProfile, WorkPreferences

    profile = CandidateProfile(
        skills=["python"],
        work_preferences=WorkPreferences(
            remote_preference="onsite",
            preferred_locations=["Berlin"],
        ),
    )
    listing = _listing("greenhouse:a:1", location="Tokyo, Japan", remote_policy=None)

    component = _location_component(listing, profile)
    assert component.value == 40.0


# ------------------------------------------------------------------ salary


@pytest.mark.parametrize(
    ("raw", "expected_salary", "expected_currency"),
    [
        ("$25k - $35k", "25000 - 35000", "USD"),
        ("$50-$75 /hour", "104000 - 156000", "USD"),
        ("$14/hour", "29120", "USD"),
        ("$3.5k–$5k/month", "42000 - 60000", "USD"),
        ("70K-80K", "70000 - 80000", None),
        ("$35,3k- $52k", "35300 - 52000", "USD"),
        ("", None, None),
        (None, None, None),
    ],
)
def test_the_free_text_salary_is_parsed(raw, expected_salary, expected_currency):
    """Remotive's salary is free text and must be parsed tolerantly."""
    from src.jobs.salary import parse_salary_range

    salary, currency = parse_salary_range(raw)
    assert salary == expected_salary
    assert currency == expected_currency


def test_the_greenhouse_pay_ranges_are_projected():
    """Greenhouse's pay is already structured: integer cents."""
    from src.jobs.salary import salary_from_greenhouse_pay_ranges

    salary, currency = salary_from_greenhouse_pay_ranges(
        [{"min_cents": 14650000, "max_cents": 19830000, "currency_type": "USD"}]
    )
    assert salary == "146500 - 198300"
    assert currency == "USD"

    # A board that publishes no range is a fact about the board, not a failure.
    assert salary_from_greenhouse_pay_ranges([]) == (None, None)
    assert salary_from_greenhouse_pay_ranges(None) == (None, None)


# ------------------------------------------------------------- the metadata


def test_the_board_metadata_keys_are_read_per_board():
    """The key names are **per board**, not standardized.

    The adapter used to look for a key called ``"employmentType"``,
    which appears zero times across the 11 boards and 4,406 jobs in the
    registry. The board that publishes it calls it ``"Employee Type"``.
    """
    from src.jobs.board_metadata import metadata_value, remote_policy_from_metadata

    block_metadata = [{"name": "Employee Type", "value": "Full Time"}]
    assert metadata_value(block_metadata, ("Employee Type",)) == "Full Time"

    airbnb_metadata = [{"name": "Workplace Type", "value": "Remote"}]
    assert remote_policy_from_metadata(airbnb_metadata, "airbnb") == "remote"

    block_remote = [{"name": "Position open to remote", "value": "Yes"}]
    assert remote_policy_from_metadata(block_remote, "block") == "remote"

    # A board that publishes nothing leaves the field unknown.
    assert remote_policy_from_metadata([], "figma") is None
    assert remote_policy_from_metadata(None, "figma") is None


def test_a_remote_policy_is_not_inferred_from_a_location_name():
    """A value that says nothing about remoteness stays unknown."""
    from src.jobs.board_metadata import remote_policy_from_metadata

    metadata = [{"name": "Job Posting Location", "value": "San Francisco, CA"}]
    assert remote_policy_from_metadata(metadata, "cloudflare") is None


# --------------------------------------------------------------- the delta


@pytest.mark.asyncio
async def test_the_delta_refresh_fetches_only_the_changed_listings():
    """The refresh costs O(changed jobs), not O(all jobs)."""
    import httpx

    requests: list[str] = []

    board = {
        "jobs": [
            {"id": 1, "title": "One", "updated_at": "2026-01-01T00:00:00Z"},
            {"id": 2, "title": "Two", "updated_at": "2026-01-01T00:00:00Z"},
            {"id": 3, "title": "Three", "updated_at": "2026-01-01T00:00:00Z"},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requests.append(url)
        path = url.split("?")[0].rstrip("/")
        if path.endswith("/jobs"):
            return httpx.Response(200, json=board)
        job_id = path.rsplit("/", 1)[-1]
        for job in board["jobs"]:
            if str(job["id"]) == job_id:
                return httpx.Response(200, json={**job, "content": "<p>Body</p>"})
        return httpx.Response(404)

    from src.jobs.greenhouse_adapter import GreenhouseJobAdapter

    known = {
        "greenhouse:board:1": "2026-01-01T00:00:00Z",
        "greenhouse:board:2": "2026-01-01T00:00:00Z",
        "greenhouse:board:3": "2026-01-01T00:00:00Z",
    }

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = GreenhouseJobAdapter(client=client, boards=["board"])
        listings = await adapter.fetch_changed(known, client=client)

    assert listings == [], "nothing changed, so nothing is fetched"
    assert len(requests) == 1, "only the light list is fetched"

    # Now one job has changed.
    requests.clear()
    changed_known = dict(known)
    changed_known["greenhouse:board:2"] = "2025-12-31T00:00:00Z"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = GreenhouseJobAdapter(client=client, boards=["board"])
        listings = await adapter.fetch_changed(changed_known, client=client)

    assert len(listings) == 1
    assert listings[0].id == "greenhouse:board:2"
    assert len(requests) == 2, "the light list plus one content fetch"


@pytest.mark.asyncio
async def test_the_remotive_filter_is_client_side():
    """Remotive ignores its query parameters, so the filter is ours."""
    import httpx

    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "Inside Sales",
                "company_name": "Acme",
                "description": "Selling things.",
                "tags": [],
            },
            {
                "id": 2,
                "title": "Python Engineer",
                "company_name": "Globex",
                "description": "Write Python.",
                "tags": [],
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    from src.jobs.remotive_adapter import RemotiveJobAdapter

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = RemotiveJobAdapter(client=client)
        listings = await adapter.search("python")

    assert [listing.id for listing in listings] == ["remotive:2"]
