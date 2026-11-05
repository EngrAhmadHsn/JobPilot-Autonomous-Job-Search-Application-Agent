"""Persistent execution state for background work (WS-18).

Five tables, one purpose each:

- ``job_runs`` — one row per accepted execution. It is the identity an
  operator, a log line and an API response all refer to.
- ``job_work_items`` — the individually claimable units of a run. An item
  carries its own lease, attempt count and next-attempt time, so a crash
  loses at most the item that was in flight.
- ``job_run_events`` — the append-only history. Current state stays in
  ``job_runs``; the history is here. This is not event sourcing: the events
  explain transitions, they do not *define* them.
- ``worker_heartbeats`` — whether a worker is alive, which is the one thing
  a healthy API cannot tell you by answering requests.
- ``circuit_breakers`` — optional shared breaker state, for a deployment
  that runs more than one worker against the same provider limits.

``metadata`` is a reserved attribute name on a SQLAlchemy declarative class,
so the attribute is ``extra_metadata`` and the column keeps the plain name.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.runs.state import (
    RUN_QUEUED,
    WORK_QUEUED,
    utcnow,
)

__all__ = [
    "CircuitBreakerDB",
    "JobRunDB",
    "JobRunEventDB",
    "JobWorkItemDB",
    "WorkerHeartbeatDB",
    "new_run_id",
    "new_work_item_id",
]


def new_run_id() -> str:
    """A durable, opaque execution id."""
    return uuid.uuid4().hex


def new_work_item_id() -> str:
    """A durable, opaque work-item id."""
    return uuid.uuid4().hex


class JobRunDB(Base):
    """One accepted execution: a refresh, an embedding pass or a reconciliation."""

    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_run_id)
    #: ``refresh`` | ``embedding`` | ``reconcile``.
    job_type: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True, default=RUN_QUEUED)
    #: Lower runs first. Recovery 10, accepted embedding 20, refresh 30,
    #: reconciliation 40. An administrator's resume lowers the value, so the
    #: work the operator explicitly asked for is not stuck behind new work.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    #: The principal that requested the run, when a person did. A scheduled
    #: platform run has no owner and is visible to administrators only.
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    #: Ties an HTTP request, a worker's logs and the run's events together.
    correlation_id: Mapped[str] = mapped_column(String, index=True)
    #: The run that created this one (a refresh creates its embedding child).
    parent_run_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    #: Identity of the embedding space an embedding run was planned for. The
    #: resume path refuses to continue into a different space.
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    last_error_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )

    __table_args__ = (
        Index("ix_job_runs_status_priority", "status", "priority", "created_at"),
        Index("ix_job_runs_type_status", "job_type", "status"),
    )


class JobWorkItemDB(Base):
    """One individually claimable unit of a run."""

    __tablename__ = "job_work_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_work_item_id)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("job_runs.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str] = mapped_column(String, index=True)
    #: ``embed`` | ``refresh`` | ``reconcile``.
    work_type: Mapped[str] = mapped_column(String, index=True)
    #: ``sha256`` of the exact document text. A changed description is a
    #: different content version, so it is different work.
    content_hash: Mapped[str] = mapped_column(String, nullable=False, default="")
    embedding_model: Mapped[str] = mapped_column(String, nullable=False, default="")
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String, index=True, default=WORK_QUEUED)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    #: The fence. Every completion is conditioned on it, so a worker whose
    #: lease was reclaimed cannot write a stale result.
    lease_token: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    #: ``retryable`` | ``permanent`` | ``quota``.
    last_error_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )

    __table_args__ = (
        # An identical (job, content version, model, dimension) is one piece
        # of work within a run. A retry reuses the row; it never creates a
        # second one.
        UniqueConstraint(
            "run_id",
            "job_id",
            "work_type",
            "content_hash",
            "embedding_model",
            "embedding_dimension",
            name="uq_job_work_items_identity",
        ),
        Index("ix_job_work_items_claim", "status", "next_attempt_at"),
        Index("ix_job_work_items_run_status", "run_id", "status"),
        Index("ix_job_work_items_lease", "lease_expires_at"),
    )


class JobRunEventDB(Base):
    """One entry in a run's append-only history."""

    __tablename__ = "job_run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    work_item_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    event: Mapped[str] = mapped_column(String, index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor: Mapped[str] = mapped_column(String, nullable=False, default="system")
    actor_kind: Mapped[str] = mapped_column(String, nullable=False, default="system")
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    message: Mapped[str | None] = mapped_column(String, nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class WorkerHeartbeatDB(Base):
    """A worker's liveness record.

    One row per worker id. ``starts`` is incremented by every registration,
    so "this worker restarted" is visible without reading the process log.
    """

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String, primary_key=True)
    #: ``running`` | ``stopping`` | ``stopped`` | ``crashed``.
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hostname: Mapped[str] = mapped_column(String, nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    processed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    starts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CircuitBreakerDB(Base):
    """Optional shared breaker state (more than one worker process)."""

    __tablename__ = "circuit_breakers"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="CLOSED")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
