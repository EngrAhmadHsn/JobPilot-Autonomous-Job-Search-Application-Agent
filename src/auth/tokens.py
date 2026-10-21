"""The server-side session store (WS-14 · A1).

**Why the sessions are rows and not signed blobs.** A stateless token
cannot be revoked before it expires, and "log me out everywhere" has to
work — a user who suspects their account was used elsewhere must be able
to end every session *now*, not in twenty-four hours. The cost of the
server-side store is one table and one lookup per request.

The table is deliberately minimal: the token itself is the primary key
(43 characters of ``secrets.token_urlsafe``), the owner is a column, and
the creation time is what the lifetime is measured from. There is no
refresh token and no idle timeout: a session either exists or it does
not, and "does not" is decided by the age and by an explicit revocation.

The model implements ``fastapi_users``'s ``AccessTokenProtocol``, so the
library's ``DatabaseStrategy`` can drive it.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base

__all__ = [
    "AccessTokenDB",
    "SqlAlchemyAccessTokenDatabase",
    "generate_access_token",
]


def generate_access_token() -> str:
    """A fresh, unguessable session token."""
    return secrets.token_urlsafe()


class AccessTokenDB(Base):
    """One live session."""

    __tablename__ = "access_tokens"

    #: The token itself. It is the primary key and it is a *secret*: it
    #: is the credential the bearer transport and the cookie transport
    #: both present.
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: The account this session belongs to. Indexed, because "revoke every
    #: session of this user" is a query on it.
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: When the session was created. The lifetime is measured from here.
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC), index=True
    )


class SqlAlchemyAccessTokenDatabase:
    """The ``AccessTokenDatabase`` protocol over the application's session.

    ``fastapi-users`` ships an async-only implementation; this one is
    synchronous, because the whole data layer of this application is
    synchronous and a second engine would have been a large change for
    one narrow benefit.
    """

    def __init__(self, session, access_token_table: type[AccessTokenDB] = AccessTokenDB) -> None:
        self.session = session
        self.access_token_table = access_token_table

    async def get_by_token(
        self, token: str, max_age: datetime | None = None
    ) -> AccessTokenDB | None:
        """The session with this token, if it exists and is not too old."""
        statement = self.session.query(self.access_token_table).filter(
            self.access_token_table.token == token
        )
        if max_age is not None:
            statement = statement.filter(self.access_token_table.created_at >= max_age)
        return statement.one_or_none()

    async def create(self, create_dict: dict) -> AccessTokenDB:
        """Insert a session row and return it."""
        access_token = self.access_token_table(**create_dict)
        self.session.add(access_token)
        self.session.commit()
        self.session.refresh(access_token)
        return access_token

    async def update(self, access_token: AccessTokenDB, update_dict: dict) -> AccessTokenDB:
        """Update a session row."""
        for key, value in update_dict.items():
            setattr(access_token, key, value)
        self.session.add(access_token)
        self.session.commit()
        self.session.refresh(access_token)
        return access_token

    async def delete(self, access_token: AccessTokenDB) -> None:
        """Remove a session row — this is what a logout and a revocation are."""
        self.session.delete(access_token)
        self.session.commit()
