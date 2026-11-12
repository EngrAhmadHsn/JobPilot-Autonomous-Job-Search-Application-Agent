"""Database model for normalized job listings."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.jobs.contracts import JobListing

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


class JobDB(Base):
    """Normalized job listing stored in PostgreSQL."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, index=True)
    source_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String)
    company: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    remote_policy: Mapped[str | None] = mapped_column(String, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String, nullable=True)
    salary: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
    seniority: Mapped[str | None] = mapped_column(String, nullable=True)
    required_skills: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    preferred_skills: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    experience_requirements: Mapped[str | None] = mapped_column(String, nullable=True)
    education_requirements: Mapped[str | None] = mapped_column(String, nullable=True)
    application_url: Mapped[str | None] = mapped_column(String, nullable=True)
    company_url: Mapped[str | None] = mapped_column(String, nullable=True)
    posted_at: Mapped[str | None] = mapped_column(String, nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # WS-15: when the listing was last seen on a board. The corpus is
    # bounded, and a bound that can only be reached once and never left
    # is an outage waiting for a flood. This column is what makes the
    # corpus *evictable*: the listing that has not been seen for the
    # longest is the one that goes, so a listing the boards keep serving
    # stays and a flood's rows age out.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # WS-24: a digest of the fields the search artifacts are derived from
    # (title, description, the two skill lists, the two requirement
    # strings). It is computed once, here, at write time.
    #
    # The corpus cache fingerprint used to be keyed on ``max(last_seen_at)``
    # — a *sighting* time. A refresh that re-sees unchanged listings moves
    # it, so every refresh invalidated the whole cache and the first search
    # afterwards paid the full rebuild again (32.56 s measured on the
    # 6,696-listing corpus). Hashing the content instead means a refresh
    # that changed nothing keeps the cache.
    #
    # Storing the digest rather than hashing the text at search time is
    # what makes the check cheap: hashing 6,696 rows of full description
    # text cost ~1 s per search; hashing the stored 64-character digests
    # costs milliseconds and scales with the corpus, not with its text.
    content_version: Mapped[str | None] = mapped_column(
        String(length=64), nullable=True, index=True
    )
    #: The experience bar the description states, mined once at write time.
    #:
    #: WS-23b. ``experience_requirements`` is what the **board** stated, and
    #: it is 0% populated because most boards publish nothing. This column
    #: is what the system **inferred** from the description, by the same
    #: ``required_years`` function the search used to run per listing — at
    #: 9.5 s of the 32.56 s artifacts rebuild, the most expensive
    #: per-listing item.
    #:
    #: It is a **separate** column on purpose: collapsing it into
    #: ``experience_requirements`` would make an inference
    #: indistinguishable from a published fact, and the score states exist
    #: to keep exactly that distinction honest.
    required_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: When the system first saw this listing (WS-23b).
    #:
    #: ``last_seen_at`` says when it was last seen. The corpus could not
    #: distinguish "seen for three months" from "seen once", and could
    #: compute no age at all for the rows whose ``posted_at`` is missing.
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


def listing_from_row(row: JobDB) -> JobListing:
    """Rebuild the canonical JobListing from a stored row."""
    return JobListing(
        id=row.id,
        source=row.source,
        source_job_id=row.source_job_id,
        title=row.title,
        company=row.company,
        description=row.description,
        location=row.location,
        remote_policy=row.remote_policy,
        employment_type=row.employment_type,
        salary=row.salary,
        currency=row.currency,
        seniority=row.seniority,
        required_skills=list(row.required_skills or []),
        preferred_skills=list(row.preferred_skills or []),
        experience_requirements=row.experience_requirements,
        education_requirements=row.education_requirements,
        application_url=row.application_url,
        company_url=row.company_url,
        posted_at=row.posted_at,
        metadata=dict(row.extra_metadata or {}),
    )


def content_version_for(listing: JobListing) -> str:
    """The digest of the fields the search artifacts depend on (WS-24, WS-24c).

    The corpus cache is keyed on this, so it must change when — and only
    when — the content that the BM25 index, the important terms, the
    experience bar and the seniority rank are derived from changes. A
    sighting (the refresh re-serving an unchanged listing) must **not**
    change it.

    WS-24c added ``seniority``. Every artifact field before it was derived
    from the fields already hashed here, but the cached seniority rank reads
    ``job.seniority`` (then falls back to the title), so without this a
    refresh that changed only the seniority column would keep the
    fingerprint and serve a stale rank.

    The two skill lists are serialized with sorted keys so the digest does
    not depend on the order the adapter happened to produce them in.
    """
    skills = json.dumps(list(listing.required_skills or []), sort_keys=True)
    preferred = json.dumps(list(listing.preferred_skills or []), sort_keys=True)
    parts = [
        listing.title or "",
        listing.description or "",
        skills,
        preferred,
        listing.experience_requirements or "",
        listing.education_requirements or "",
        listing.seniority or "",
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8", errors="replace")).hexdigest()


def _mined_required_years(listing: JobListing) -> float | None:
    """The experience bar the listing states, mined once at write time.

    WS-23b. Uses the board's own ``experience_requirements`` when it
    states one, and otherwise mines the description — the same function
    the matching layer calls, moved from read time to write time.

    A failure here must not lose the listing: the bar is derived data,
    and a listing without it simply scores with the component unknown,
    which is a state the engine already understands.
    """
    try:
        from src.matching.experience import required_years

        return required_years(listing)
    except Exception:
        logger.debug("Could not mine the experience bar for %s", listing.id, exc_info=True)
        return None


def merge_jobs(
    session,
    listings: Iterable[JobListing],
    *,
    seen_at: datetime | None = None,
) -> int:
    """Merge listings into ``session`` without committing (WS-18).

    The outbox needs job rows and their embedding work items in **one**
    transaction, so the merge is split out of :func:`save_jobs` and takes the
    caller's session. A failure in either half rolls both back, and the
    caller sees one consistent state: either the listing and its work exist,
    or neither does.
    """
    moment = seen_at or datetime.now(UTC)
    persisted = 0
    for listing in listings:
        # WS-23b: the mined experience bar, computed once here instead of
        # per listing per search. ``required_years`` reads the board's own
        # ``experience_requirements`` when it states one and otherwise
        # mines the description.
        mined_years = _mined_required_years(listing)
        # ``first_seen_at`` must survive a re-sighting, and ``merge``
        # writes every column — so an existing row's first sighting is
        # looked up and carried forward. A listing that has never been
        # seen is first seen now.
        existing = session.get(JobDB, listing.id)
        first_seen = existing.first_seen_at if existing is not None else moment
        row = JobDB(
            id=listing.id,
            source=listing.source,
            source_job_id=listing.source_job_id,
            title=listing.title,
            company=listing.company,
            description=listing.description,
            location=listing.location,
            remote_policy=listing.remote_policy,
            employment_type=listing.employment_type,
            salary=listing.salary,
            currency=listing.currency,
            seniority=listing.seniority,
            required_skills=listing.required_skills,
            preferred_skills=listing.preferred_skills,
            experience_requirements=listing.experience_requirements,
            education_requirements=listing.education_requirements,
            application_url=listing.application_url,
            company_url=listing.company_url,
            posted_at=listing.posted_at,
            extra_metadata=dict(listing.metadata),
            last_seen_at=moment,
            content_version=content_version_for(listing),
            required_years=mined_years,
            first_seen_at=first_seen or moment,
        )
        session.merge(row)
        persisted += 1
    return persisted


def save_jobs(listings: Iterable[JobListing], session_factory: sessionmaker | None = None) -> int:
    """Upsert normalized listings into the ``jobs`` table by primary key.

    Canonical ids are ``"{source}:{source_job_id}"`` (Greenhouse/Lever embed
    their board token/company slug), so re-running a search merges into the
    same rows instead of duplicating them. Uses ``Session.merge`` semantics:
    rows that do not exist are inserted, existing rows are updated in place.

    Args:
        listings: Normalized listings to persist.
        session_factory: Optional sessionmaker override (tests bind this to a
            tmp database); defaults to the application ``SessionLocal``,
            imported lazily so model-only imports never build the engine.

    Returns:
        Number of listings persisted (one row each).
    """
    from src.db.session import SessionLocal

    factory = session_factory or SessionLocal
    # WS-15: one sighting time for the whole batch, so the eviction order
    # does not depend on the order the boards happened to answer in.
    with factory() as session:
        persisted = merge_jobs(session, listings, seen_at=datetime.now(UTC))
        session.commit()
    return persisted


def touch_jobs(
    session_factory: sessionmaker | None = None,
    *,
    job_ids: Iterable[str],
    seen_at: datetime | None = None,
) -> int:
    """Record a sighting for listings that were re-served but did not change.

    WS-23, Phase 4. The delta refresh fetches the **content** only for the
    listings whose change stamp moved. The listings the board still serves
    unchanged are not fetched — but they *were* seen, and the eviction
    orders by sighting time, so they must be stamped or they would age out
    and be deleted while the board is happily serving them.

    This is the step that makes the delta refresh safe. Without it, a
    refresh would **shrink** the corpus: every unchanged listing would
    look stale, and the eviction would remove the ones it had not
    re-fetched.

    Only the sighting is written. The content columns are untouched, so
    the corpus cache fingerprint (which hashes the content) does not move.
    """
    from src.db.session import SessionLocal

    ids = [job_id for job_id in job_ids if job_id]
    if not ids:
        return 0
    factory = session_factory or SessionLocal
    moment = seen_at or datetime.now(UTC)
    with factory() as session:
        touched = (
            session.query(JobDB)
            .filter(JobDB.id.in_(ids))
            .update({JobDB.last_seen_at: moment}, synchronize_session=False)
        )
        session.commit()
    return int(touched or 0)


def prune_stale_jobs(
    session_factory: sessionmaker | None = None,
    *,
    keep: int,
    limit: int,
    protected_sources: Iterable[str] | None = None,
    protected_job_ids: Iterable[str] | None = None,
) -> list[str]:
    """Delete the listings that have not been seen for the longest.

    WS-15: the corpus is capped, and the cap used to be a one-way door —
    once the corpus was full, **nothing** was admitted again, from any
    source, ever. A flood could therefore end the application's life with
    five refreshes and no way back.

    The corpus now evicts. The listing that has not been seen on a board
    for the longest goes first, so a listing the boards keep serving stays
    and a flood's rows age out.

    WS-23: three rules make the eviction safe. Before, the ordering was
    ``last_seen_at ASC`` and SQLite sorts NULL **first**, so the rows the
    eviction picked first were exactly the rows that had *never been
    successfully re-fetched* — the rows whose board was too large to
    fetch, or whose board was failing. Measured on the live corpus on
    2026-11-09: 3,042 of 6,696 rows (45.4%) carried a NULL sighting, and
    the first 5,000 eviction candidates included **all 1,069 Ashby rows**
    and 3,864 Greenhouse rows. The policy was selecting for the data it
    was supposed to protect.

    The three rules:

    1. **A row with no sighting is never evicted.** A NULL means "we have
       no evidence this listing is live" — an argument for investigating,
       not for deleting. It is also the state a board's rows fall into
       when the board stops responding.
    2. **A row belonging to a failing source is not evicted.** A board
       that starts returning 403 must not age out its own coverage; the
       rows are unknown, not dead. The caller passes the failing sources
       (``protected_sources``).
    3. **A row that something references is never evicted.** There is no
       foreign key from ``applications`` to ``jobs`` (``PRAGMA
       foreign_key_list`` is empty for all three referencing tables), so
       an application can point at a listing that no longer exists. The
       caller passes the referenced ids (``protected_job_ids``).

    Args:
        session_factory: Sessionmaker override (tests bind this to a tmp
            database); defaults to the application ``SessionLocal``.
        keep: How many listings to keep, at the very least.
        limit: The most rows this call may delete. The eviction is bounded
            so one refresh cannot turn into a mass delete.
        protected_sources: Sources whose rows are not eviction candidates
            this pass — the sources that are currently failing.
        protected_job_ids: Job ids that are not eviction candidates this
            pass — the rows an application, match or approval refers to.

    Returns:
        The ids of the deleted rows, so the caller can drop their vectors.
    """
    from src.db.session import SessionLocal

    if keep < 0 or limit < 1:
        return []
    factory = session_factory or SessionLocal
    protected_source_set = {s for s in (protected_sources or []) if s}
    protected_id_set = {j for j in (protected_job_ids or []) if j}

    with factory() as session:
        total = int(session.query(JobDB).count())
        if total <= keep:
            return []

        # The candidate set is the rows that **may** be evicted. The
        # excess is measured against it, not against the whole corpus: a
        # protected row is not "excess" that must be freed, it is a row
        # that stays. Counting it as excess would evict a healthy
        # source's row to make room for a protected one.
        statement = session.query(JobDB.id).filter(JobDB.last_seen_at.is_not(None))
        if protected_source_set:
            statement = statement.filter(JobDB.source.notin_(protected_source_set))
        if protected_id_set:
            statement = statement.filter(JobDB.id.notin_(protected_id_set))

        eligible_total = int(
            session.query(JobDB.id)
            .filter(JobDB.last_seen_at.is_not(None))
            .filter(JobDB.source.notin_(protected_source_set) if protected_source_set else True)
            .filter(JobDB.id.notin_(protected_id_set) if protected_id_set else True)
            .count()
        )
        excess = min(eligible_total - keep, limit)
        if excess <= 0:
            logger.info(
                "Eviction had no eligible candidates (keep %d, %d eligible of %d rows)",
                keep,
                eligible_total,
                total,
            )
            return []

        # The oldest sighting first. A row with no sighting is excluded
        # above, so NULL no longer sorts to the front of the queue.
        stale = statement.order_by(JobDB.last_seen_at.asc(), JobDB.id.asc()).limit(excess).all()
        removed = [row[0] for row in stale]
        if not removed:
            logger.info(
                "Eviction had no eligible candidates (keep %d, %d rows not evictable)",
                keep,
                total,
            )
            return []
        session.query(JobDB).filter(JobDB.id.in_(removed)).delete(synchronize_session=False)
        session.commit()
    logger.info(
        "Evicted %d stale listings from the corpus (keep %d, %d protected sources)",
        len(removed),
        keep,
        len(protected_source_set),
    )
    return removed
