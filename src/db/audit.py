"""Append-only audit event store (WS-06 · SEC-13).

Every external action the agent takes writes one row here: a resume upload, a
job search, a match, an application prepare/approve/reject/submit/verify, and
every security guard that tripped.

The store is **append-only**. There is deliberately no update or delete
helper in this module — an audit trail that can be rewritten is not an audit
trail. The JSON column is portable ``sa.JSON()`` (SQLite and PostgreSQL).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.users import LEGACY_OWNER_ID


class AuditEventDB(Base):
    """One recorded action."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
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
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    #: The human-readable label of the actor. It is **derived** from the
    #: two columns below, never supplied, so the three can never
    #: disagree.
    actor: Mapped[str] = mapped_column(String, index=True)
    #: The kind of principal: ``user``, ``agent`` or ``system``
    #: (WS-14 · Phase C). NOT NULL, with a server default of ``system``:
    #: a row written by an older code path is attributed to the system,
    #: which is honest, rather than to nobody.
    actor_kind: Mapped[str] = mapped_column(
        String,
        nullable=False,
        index=True,
        default="system",
        server_default="system",
    )
    #: The principal's id: the account id for a user, the adapter's name
    #: for an agent, empty for the system.
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    resource: Mapped[str] = mapped_column(String)
    outcome: Mapped[str] = mapped_column(String, index=True)
    workflow_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # ``metadata`` is a reserved attribute name on SQLAlchemy declarative
    # classes; the column itself keeps the plain name (same pattern as
    # ``src.db.jobs`` and ``src.db.evidence``).
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
