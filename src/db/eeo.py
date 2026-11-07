"""Database model for EEO / voluntary self-identification data (WS-20).

Sensitive data gets its own table. It is **not** a column on
``candidate_profiles``, so it is never serialized by the résumé read, never
returned by the apply/search paths, and never joined into anything the matcher
touches. Ownership is a column, so access goes through ``src.db.access`` and a
foreign row is invisible (404, not 403).

Rows are one-per-profile (the profile id is the primary key) and owner-scoped.
Deletion is a real delete: the retention purge and the owner's own delete both
remove the row outright.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.users import LEGACY_OWNER_ID


class CandidateEeoDB(Base):
    """One principal's EEO/self-identification answers for one profile."""

    __tablename__ = "candidate_eeo"

    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        index=True,
        default=LEGACY_OWNER_ID,
        server_default=LEGACY_OWNER_ID,
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
