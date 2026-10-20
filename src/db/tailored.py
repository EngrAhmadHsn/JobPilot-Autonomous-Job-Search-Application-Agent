"""Persisted tailoring results (WS-05).

A tailoring result is the deliverable: the validated tailored content, its
factuality report, the ATS report, the grounded job insights and the path of
the rendered DOCX. The whole record is stored so it survives a restart and
can be served again without re-running the model.

The JSON columns are portable ``sa.JSON()`` (SQLite and PostgreSQL), matching
the WS-01/WS-04 convention: the payloads are Pydantic models that evolve, so
they are stored as documents rather than as columns.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.research.engine import JobInsights
from src.resume.ats import AtsReport
from src.resume.tailor import FactualityReport, TailoredResume


class TailoredResumeDB(Base):
    """One tailored resume produced for one (profile, job) pair."""

    __tablename__ = "tailored_resumes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(String, index=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    tailored: Mapped[dict] = mapped_column(JSON, nullable=False)
    factuality: Mapped[dict] = mapped_column(JSON, nullable=False)
    ats_report: Mapped[dict] = mapped_column(JSON, nullable=False)
    insights: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    docx_path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class StoredTailoring(BaseModel):
    """A stored tailoring result, rebuilt from the database row."""

    tailoring_id: str
    profile_id: str
    job_id: str
    tailored: TailoredResume
    factuality: FactualityReport
    ats_report: AtsReport
    insights: JobInsights | None = None
    docx_path: str
    created_at: datetime


def generate_tailoring_id() -> str:
    """Short opaque id used as the primary key of a tailoring record."""
    return uuid.uuid4().hex[:12]


def build_tailored_row(
    *,
    profile_id: str,
    job_id: str,
    tailored: TailoredResume,
    factuality: FactualityReport,
    ats_report: AtsReport,
    docx_path: str,
    insights: JobInsights | None = None,
) -> TailoredResumeDB:
    """Map a tailoring result onto a new row (the caller owns the session)."""
    return TailoredResumeDB(
        id=generate_tailoring_id(),
        profile_id=profile_id,
        job_id=job_id,
        tailored=tailored.model_dump(mode="json"),
        factuality=factuality.model_dump(mode="json"),
        ats_report=ats_report.model_dump(mode="json"),
        insights=insights.model_dump(mode="json") if insights is not None else None,
        docx_path=docx_path,
    )


def stored_from_row(row: TailoredResumeDB) -> StoredTailoring:
    """Rebuild the stored tailoring result from its row."""
    return StoredTailoring(
        tailoring_id=row.id,
        profile_id=row.profile_id,
        job_id=row.job_id,
        tailored=TailoredResume.model_validate(row.tailored),
        factuality=FactualityReport.model_validate(row.factuality),
        ats_report=AtsReport.model_validate(row.ats_report),
        insights=JobInsights.model_validate(row.insights) if row.insights else None,
        docx_path=row.docx_path,
        created_at=row.created_at,
    )
