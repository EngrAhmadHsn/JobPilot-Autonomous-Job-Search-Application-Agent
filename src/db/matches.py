"""Database model for persisted job-match results (WS-04).

One row per (profile, job) match returned by a search run, so match history
survives restarts and can be listed per profile. Component scores live in a
JSON column (``scores``) keyed exactly like ``JobMatchResult``'s fields; the
row is intentionally free of foreign keys so match history can outlive the
referenced profile/job rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.users import LEGACY_OWNER_ID

if TYPE_CHECKING:
    from src.graph.job_state import JobMatchPair


class JobMatchDB(Base):
    """A persisted match between one candidate profile and one job listing."""

    __tablename__ = "job_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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
    profile_id: Mapped[str] = mapped_column(String, index=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    scores: Mapped[dict] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


_SCORE_FIELDS = (
    "overall_score",
    "semantic_score",
    "skill_score",
    "experience_score",
    "seniority_score",
    "location_score",
    "preference_score",
)


def build_match_rows(
    profile_id: str, pairs: list[JobMatchPair], *, owner_id: str = LEGACY_OWNER_ID
) -> list[JobMatchDB]:
    """Map (job, match) pairs onto new rows (caller owns the session/commit)."""
    rows: list[JobMatchDB] = []
    for pair in pairs:
        match = pair.match
        scores = {field: getattr(match, field) for field in _SCORE_FIELDS}
        scores["missing_requirements"] = list(match.missing_requirements)
        scores["matched_requirements"] = list(match.matched_requirements)
        rows.append(
            JobMatchDB(
                owner_id=owner_id,
                profile_id=profile_id,
                job_id=pair.job.id,
                scores=scores,
                explanation=match.explanation,
            )
        )
    return rows


def match_row_to_dict(row: JobMatchDB) -> dict:
    """Serialize one row for the matches-history API response."""
    return {
        "profile_id": row.profile_id,
        "job_id": row.job_id,
        "scores": row.scores,
        "explanation": row.explanation,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
