"""The board registry and its health (WS-23, Phase 5).

The three environment lists (``GREENHOUSE_BOARDS``, ``LEVER_COMPANIES``,
``ASHBY_ORGS``) say *which* boards to watch. They cannot say whether a
board is **healthy**, and that is what the corpus needs:

* the WS-23 eviction is **source-scoped** — a board that is failing must
  not age out its own coverage — and that needs a per-board health
  record;
* an operator watching forty boards needs to know which three are broken,
  and the env list cannot say;
* an env list does not scale past a few dozen entries, and it has no
  place to record a company's display name, when it was first seen, or
  how many listings it contributed.

So the registry is a table and the env lists become its **seed**. The
table is **shared**, not owner-scoped, exactly like ``jobs``: the board
list and the listings it produces are the same for every operator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base

logger = logging.getLogger(__name__)

__all__ = ["BoardDB", "BoardHealth", "list_boards", "record_board_failure", "record_board_success"]


class BoardDB(Base):
    """One watched job board and its health."""

    __tablename__ = "job_boards"

    #: The canonical identity, ``"{ats}:{slug}"`` — the same shape the
    #: canonical job ids use.
    id: Mapped[str] = mapped_column(String(length=128), primary_key=True)
    #: The provider: greenhouse, lever, ashby, remotive.
    ats: Mapped[str] = mapped_column(String(length=32), nullable=False, index=True)
    #: The board token (a Greenhouse board token, a Lever company slug, an
    #: Ashby org slug).
    slug: Mapped[str] = mapped_column(String(length=128), nullable=False, index=True)
    #: The company's display name, when it is known.
    company_name: Mapped[str | None] = mapped_column(String(length=200), nullable=True)
    #: Whether the refresh watches this board.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    #: The last successful fetch.
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: The last failure, sanitized and truncated.
    last_error: Mapped[str | None] = mapped_column(String(length=500), nullable=True)
    #: How many fetches have failed in a row.
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: How many listings the board contributed at the last fetch.
    listings_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: When the board entered the registry.
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


@dataclass
class BoardHealth:
    """One board's health, as the admin surface reads it."""

    id: str
    ats: str
    slug: str
    company_name: str | None
    enabled: bool
    last_ok_at: datetime | None
    last_error: str | None
    consecutive_failures: int
    listings_seen: int

    @property
    def is_failing(self) -> bool:
        """Whether the board has failed repeatedly."""
        return self.consecutive_failures >= 3


def _sanitize_error(message: str | None) -> str | None:
    """A failure message safe to store and show.

    A board's error text is untrusted input, and the console renders it.
    It is truncated and stripped of control characters; it never carries a
    credential (the boards are key-less, so there is nothing to leak).
    """
    if not message:
        return None
    cleaned = "".join(ch if ch.isprintable() else " " for ch in message)
    return cleaned[:500]


def list_boards(session_factory=None, *, enabled_only: bool = True) -> list[BoardHealth]:
    """The boards in the registry, with their health."""
    from src.db.session import SessionLocal

    factory = session_factory or SessionLocal
    with factory() as session:
        statement = session.query(BoardDB)
        if enabled_only:
            statement = statement.filter(BoardDB.enabled.is_(True))
        rows = statement.order_by(BoardDB.ats, BoardDB.slug).all()
    return [
        BoardHealth(
            id=row.id,
            ats=row.ats,
            slug=row.slug,
            company_name=row.company_name,
            enabled=bool(row.enabled),
            last_ok_at=row.last_ok_at,
            last_error=row.last_error,
            consecutive_failures=int(row.consecutive_failures or 0),
            listings_seen=int(row.listings_seen or 0),
        )
        for row in rows
    ]


def record_board_success(session_factory=None, *, ats: str, slug: str, listings: int = 0) -> None:
    """Record that a board answered."""
    from src.db.session import SessionLocal

    factory = session_factory or SessionLocal
    now = datetime.now(UTC)
    with factory() as session:
        row = session.get(BoardDB, f"{ats}:{slug}")
        if row is None:
            row = BoardDB(
                id=f"{ats}:{slug}",
                ats=ats,
                slug=slug,
                company_name=slug.replace("-", " ").replace("_", " ").title(),
                enabled=True,
                first_seen_at=now,
            )
            session.add(row)
        row.last_ok_at = now
        row.last_error = None
        row.consecutive_failures = 0
        if listings:
            row.listings_seen = listings
        session.commit()


def record_board_failure(session_factory=None, *, ats: str, slug: str, error: str | None) -> None:
    """Record that a board failed.

    A failing board is **not** removed from the registry and its
    coverage is **not** evicted: the rows are unknown, not dead. The
    streak is what the source-scoped eviction reads.
    """
    from src.db.session import SessionLocal

    factory = session_factory or SessionLocal
    now = datetime.now(UTC)
    with factory() as session:
        row = session.get(BoardDB, f"{ats}:{slug}")
        if row is None:
            row = BoardDB(
                id=f"{ats}:{slug}",
                ats=ats,
                slug=slug,
                company_name=slug.replace("-", " ").replace("_", " ").title(),
                enabled=True,
                first_seen_at=now,
            )
            session.add(row)
        row.last_error = _sanitize_error(error)
        row.consecutive_failures = int(row.consecutive_failures or 0) + 1
        session.commit()
