"""Audit/evidence recording models for application submissions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.users import LEGACY_OWNER_ID


class ApplicationEvidenceDB(Base):
    """Audit record for a submitted application with captured evidence."""

    __tablename__ = "application_evidence"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
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
    workflow_id: Mapped[str] = mapped_column(String, index=True)
    adapter_name: Mapped[str] = mapped_column(String)
    job_url: Mapped[str] = mapped_column(String)
    # WS-07: the tracked application this evidence belongs to. Nullable so
    # the evidence written before WS-07 stays readable; the submit node
    # fills it in for every new submission.
    application_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    confirmation_text: Mapped[str | None] = mapped_column(String, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(String, nullable=True)
    trace_path: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="unknown")
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


#: The former name of the model, kept so the callers that use it keep
#: working while the rename settles. The database layer names its models
#: after their tables (``ApplicationEvidenceDB`` <- ``application_evidence``).
ApplicationEvidence = ApplicationEvidenceDB
