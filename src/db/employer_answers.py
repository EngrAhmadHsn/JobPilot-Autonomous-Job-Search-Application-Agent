"""Private employer answers shown in Profile, scoped to one posting revision."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class LocalFillGrantDB(Base):
    """One revocable, expiring, fill-only authorization per review. No plaintext code."""

    __tablename__ = "local_fill_grants"
    application_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EmployerAnswerDB(Base):
    __tablename__ = "employer_answers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex)
    owner_id: Mapped[str] = mapped_column(String, nullable=False)
    job_id: Mapped[str] = mapped_column(String, nullable=False)
    company_name: Mapped[str] = mapped_column(String, nullable=False)
    job_title: Mapped[str] = mapped_column(String, nullable=False)
    question_key: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[dict] = mapped_column(JSON, nullable=False)
    answer: Mapped[str | list[str]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("owner_id", "job_id", "question_key", name="uq_employer_answers_question"),
        Index("ix_employer_answers_owner_updated", "owner_id", "updated_at"),
    )
