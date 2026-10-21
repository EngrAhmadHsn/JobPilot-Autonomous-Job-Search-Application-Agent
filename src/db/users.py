"""Database model for platform users (WS-13 · A0).

WS-13 changes the threat model: the caller is no longer assumed to be the
operator, so the system needs a **principal** to attribute data and
actions to. This table is that principal.

The schema is deliberately shaped to match what ``fastapi-users`` expects
(WS-13 Phase A1 adopts it as the identity backend, so the identity rows
and the owner rows are the same rows and no second migration is needed):
``id`` / ``email`` / ``hashed_password`` / ``is_active`` /
``is_superuser`` / ``is_verified``, plus the two timestamps.

The password is stored only as a **hash**. The column is named
``hashed_password`` for that reason, so no reader can mistake it for a
plaintext field, and the account-lifecycle work in A1 is where the
hashing policy (argon2) is applied.

There is no ``owner_id`` on this table: a user owns itself, and the
self-reference would be a cycle rather than a constraint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base

#: The id of the single account that owns the rows that predate WS-13.
#:
#: WS-13 adds a NOT NULL ``owner_id`` to every user-scoped table. The
#: rows that already exist have no owner, so the migration assigns them
#: all to this account rather than inventing a per-row owner it cannot
#: justify. The account is marked inactive and cannot authenticate; it
#: exists so the existing data stays coherent and reachable until the
#: operator either claims it (A1) or purges it (D).
LEGACY_OWNER_ID = "legacy"


def generate_user_id() -> str:
    """A short opaque id for a user account."""
    return uuid.uuid4().hex[:12]


class UserDB(Base):
    """One platform user — the principal that owns data and acts."""

    __tablename__ = "users"

    #: The account id. The Python-side default is what the identity stack
    #: relies on: ``fastapi-users`` creates a row without supplying an
    #: id (``create_update_dict`` excludes it), so the column has to
    #: generate one. It is a *Python* default on purpose — the id is an
    #: application-level opaque string, and the database never needs to
    #: mint one.
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_user_id)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    #: The password hash, never the password. A plaintext password must
    #: never reach this column: the account-lifecycle code (A1) hashes it
    #: with argon2 before it is stored.
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    #: An inactive user cannot authenticate. Deactivating is the
    #: reversible half of account deletion; the purge is the irreversible
    #: half (Phase D).
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: A superuser may read across owners. The platform's own audit view
    #: is the legitimate use; a user-facing one is not.
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


def build_user_row(
    *,
    email: str,
    hashed_password: str,
    full_name: str | None = None,
    is_active: bool = True,
    is_superuser: bool = False,
    is_verified: bool = False,
    user_id: str | None = None,
) -> UserDB:
    """Map a new account onto a row (the caller owns the session/commit)."""
    return UserDB(
        id=user_id or generate_user_id(),
        email=email,
        hashed_password=hashed_password,
        full_name=full_name,
        is_active=is_active,
        is_superuser=is_superuser,
        is_verified=is_verified,
    )
