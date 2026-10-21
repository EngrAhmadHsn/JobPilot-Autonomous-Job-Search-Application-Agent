"""Database model for persisted candidate profiles (WS-04).

The full parsed profile is stored as JSON (``profile_json``) alongside the
personal-information columns needed for cheap listing/query purposes, so the
schema survives CandidateProfile model evolution without migrations. Rows are
written by the resume-upload API; ``profile_json`` round-trips through
``CandidateProfile.model_validate``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.users import LEGACY_OWNER_ID
from src.resume.profile import CandidateProfile


class CandidateProfileDB(Base):
    """A parsed candidate profile persisted from an uploaded resume."""

    __tablename__ = "candidate_profiles"

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
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


def generate_profile_id() -> str:
    """Short opaque id used as the primary key and upload filename stem."""
    return uuid.uuid4().hex[:12]


def build_profile_row(
    profile: CandidateProfile, file_path: str, *, owner_id: str = LEGACY_OWNER_ID
) -> CandidateProfileDB:
    """Map a parsed profile onto a new row (caller owns the session/commit).

    ``owner_id`` is required: the row belongs to a principal, and a row
    that could be written without one would be a row nobody can be
    forbidden from reading (WS-13 · A0).
    """
    info = profile.personal_information
    return CandidateProfileDB(
        id=generate_profile_id(),
        owner_id=owner_id,
        name=info.name or None,
        email=info.email or None,
        phone=info.phone or None,
        location=info.location or None,
        title=info.title or None,
        profile_json=profile.model_dump(mode="json"),
        file_path=file_path,
    )


def profile_from_row(row: CandidateProfileDB) -> CandidateProfile:
    """Rebuild the validated CandidateProfile from the stored JSON."""
    return CandidateProfile.model_validate(row.profile_json)
