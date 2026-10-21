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


class AuditEventDB(Base):
    """One recorded action."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    actor: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    resource: Mapped[str] = mapped_column(String)
    outcome: Mapped[str] = mapped_column(String, index=True)
    workflow_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # ``metadata`` is a reserved attribute name on SQLAlchemy declarative
    # classes; the column itself keeps the plain name (same pattern as
    # ``src.db.jobs`` and ``src.db.evidence``).
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
