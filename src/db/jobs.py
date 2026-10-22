"""Database model for normalized job listings."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, String
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
    persisted = 0
    # WS-15: one sighting time for the whole batch, so the eviction order
    # does not depend on the order the boards happened to answer in.
    seen_at = datetime.now(UTC)
    with factory() as session:
        for listing in listings:
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
                last_seen_at=seen_at,
            )
            session.merge(row)
            persisted += 1
        session.commit()
    return persisted


def prune_stale_jobs(
    session_factory: sessionmaker | None = None,
    *,
    keep: int,
    limit: int,
) -> list[str]:
    """Delete the listings that have not been seen for the longest.

    WS-15: the corpus is capped, and the cap used to be a one-way door —
    once the corpus was full, **nothing** was admitted again, from any
    source, ever. A flood could therefore end the application's life with
    five refreshes and no way back.

    The corpus now evicts. The listing that has not been seen on a board
    for the longest goes first (a row that has never been seen goes before
    one that has, because there is no evidence it is still live), so a
    listing the boards keep serving stays and a flood's rows age out.

    Args:
        session_factory: Sessionmaker override (tests bind this to a tmp
            database); defaults to the application ``SessionLocal``.
        keep: How many listings to keep, at the very least.
        limit: The most rows this call may delete. The eviction is bounded
            so one refresh cannot turn into a mass delete.

    Returns:
        The ids of the deleted rows, so the caller can drop their vectors.
    """
    from src.db.session import SessionLocal

    if keep < 0 or limit < 1:
        return []
    factory = session_factory or SessionLocal
    with factory() as session:
        total = int(session.query(JobDB).count())
        excess = total - keep
        if excess <= 0:
            return []
        excess = min(excess, limit)
        # The oldest sighting first; a row that was never seen has no
        # sighting at all, and NULL sorts first.
        stale = (
            session.query(JobDB.id)
            .order_by(JobDB.last_seen_at.asc(), JobDB.id.asc())
            .limit(excess)
            .all()
        )
        removed = [row[0] for row in stale]
        if not removed:
            return []
        session.query(JobDB).filter(JobDB.id.in_(removed)).delete(synchronize_session=False)
        session.commit()
    logger.info("Evicted %d stale listings from the corpus (keep %d)", len(removed), keep)
    return removed
