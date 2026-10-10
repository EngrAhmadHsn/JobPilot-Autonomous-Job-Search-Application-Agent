"""Database model for normalized job listings."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from src.jobs.contracts import JobListing


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
            )
            session.merge(row)
            persisted += 1
        session.commit()
    return persisted
