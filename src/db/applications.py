"""Persisted application lifecycle and its append-only event log (WS-07).

An *application* is the thing a human tracks: one job, one candidate, one
resume version, and everything that happened to it. Before WS-07 the only
persisted trace of a submission was an ``application_evidence`` row that knew
the job URL and nothing else — which job, which candidate, which status, and
who acted on it were all lost on restart.

Two tables:

- ``applications`` — one row per tracked application, carrying its current
  status and the timestamps of the milestones it reached.
- ``application_events`` — the **append-only** history. One row per state
  change, ordered by its autoincrement id, carrying the actor that caused it.

The status column holds an :class:`src.applications.tracking.ApplicationStatus`
value. The enum lives in the domain layer, so this module does not import it
(and the domain layer imports this module, not the other way round); the
tracking layer is the only writer, and it always writes a valid value.

No foreign keys by design, matching ``approval_requests``, ``audit_events``,
``job_matches`` and ``tailored_resumes``: a tracking record must outlive the
rows it refers to, so the trail survives the deletion of the object it
describes. The columns are indexed instead, and ``job_id`` always *resolves*
— a stub listing row is created for a URL that has no stored listing (see
``src.applications.tracking.ensure_job_row``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.users import LEGACY_OWNER_ID


class ApplicationDB(Base):
    """One tracked application."""

    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    #: The principal that owns this row (WS-13 · A0). NOT NULL and
    #: indexed: ownership is a column, not a convention a route has to
    #: remember. Every access goes through ``src.db.access``.
    owner_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        index=True,
        default=LEGACY_OWNER_ID,
        server_default=LEGACY_OWNER_ID,
    )
    # The candidate profile this application belongs to. Nullable: the
    # prepare flow has no profile until the caller supplies one.
    profile_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # The normalized listing id. Always resolves to a ``jobs`` row.
    job_id: Mapped[str] = mapped_column(String, index=True)
    # The application workflow this application belongs to.
    workflow_id: Mapped[str] = mapped_column(String, index=True)
    # The WS-06 approval request that gates it.
    approval_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    adapter_name: Mapped[str] = mapped_column(String)
    job_url: Mapped[str] = mapped_column(String)
    job_title: Mapped[str] = mapped_column(String)
    company_name: Mapped[str] = mapped_column(String)
    # An ``ApplicationStatus`` value.
    status: Mapped[str] = mapped_column(String, index=True)
    # The WS-05 tailoring this application used, when there was one.
    tailored_resume_id: Mapped[str | None] = mapped_column(String, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # The URL the submission landed on (from the evidence).
    application_url: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ApplicationEventDB(Base):
    """One entry in an application's append-only history."""

    __tablename__ = "application_events"

    # The autoincrement id *is* the ordering: the history is read in append
    # order, never in timestamp order.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    #: The principal that owns this row (WS-13 · A0). An event belongs to
    #: the same owner as the application it records, so the history can
    #: never be read by someone who cannot read the application.
    owner_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        index=True,
        default=LEGACY_OWNER_ID,
        server_default=LEGACY_OWNER_ID,
    )
    application_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    # ``agent`` | ``system`` | ``human:<who>``.
    actor: Mapped[str] = mapped_column(String, index=True)
    from_status: Mapped[str | None] = mapped_column(String, nullable=True)
    to_status: Mapped[str | None] = mapped_column(String, nullable=True)
    # ``metadata`` is a reserved attribute name on SQLAlchemy declarative
    # classes; the column itself keeps the plain name (the same pattern as
    # ``src.db.jobs`` and ``src.db.evidence``).
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


def generate_application_id() -> str:
    """Short opaque id used as the primary key of a tracked application."""
    return uuid.uuid4().hex[:12]


def build_application_row(
    *,
    owner_id: str = LEGACY_OWNER_ID,
    workflow_id: str,
    job_id: str,
    adapter_name: str,
    job_url: str,
    job_title: str,
    company_name: str,
    status: str,
    approval_id: str | None = None,
    profile_id: str | None = None,
    tailored_resume_id: str | None = None,
) -> ApplicationDB:
    """Map a new application onto a row (the caller owns the session)."""
    return ApplicationDB(
        id=generate_application_id(),
        owner_id=owner_id,
        profile_id=profile_id,
        job_id=job_id,
        workflow_id=workflow_id,
        approval_id=approval_id,
        adapter_name=adapter_name,
        job_url=job_url,
        job_title=job_title,
        company_name=company_name,
        status=status,
        tailored_resume_id=tailored_resume_id,
    )
