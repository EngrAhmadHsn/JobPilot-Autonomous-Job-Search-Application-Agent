"""Audit/evidence recording models for application submissions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class ApplicationEvidence(Base):
    """Audit record for a submitted application with captured evidence."""

    __tablename__ = "application_evidence"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
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
