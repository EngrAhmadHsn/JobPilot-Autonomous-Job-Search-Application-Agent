"""The user store, over the application's synchronous session (WS-14 · A1).

``fastapi-users`` defines the store as a protocol
(:class:`fastapi_users.db.BaseUserDatabase`) and ships an **async-only**
SQLAlchemy implementation of it. This application is synchronous from the
ORM down, so the adapter is written here instead: it speaks the same
protocol, over the same :class:`~sqlalchemy.orm.Session` the routes use.

Two things are worth stating, because they are the properties the rest of
WS-14 rests on:

- **the e-mail lookup is case-insensitive.** Two accounts that differ only
  in the case of their e-mail would be two accounts, and the "forgot
  password" flow would then leak which of them exists.
- **the OAuth methods are not implemented.** This deployment has no OAuth
  provider, and an adapter that raised ``NotImplementedError`` at the
  right place is better than one that half-worked.
"""

from __future__ import annotations

from typing import Any

from fastapi_users.db import BaseUserDatabase
from sqlalchemy import func

from src.db.users import UserDB

__all__ = ["SqlAlchemyUserDatabase"]


class SqlAlchemyUserDatabase(BaseUserDatabase[UserDB, str]):
    """The user store, over a synchronous SQLAlchemy session."""

    def __init__(self, session, user_table: type[UserDB] = UserDB) -> None:
        self.session = session
        self.user_table = user_table

    async def get(self, id: str) -> UserDB | None:
        """The account with this id, if it exists."""
        return self.session.get(self.user_table, id)

    async def get_by_email(self, email: str) -> UserDB | None:
        """The account with this e-mail, compared case-insensitively."""
        statement = self.session.query(self.user_table).filter(
            func.lower(self.user_table.email) == func.lower(email)
        )
        return statement.one_or_none()

    async def get_by_oauth_account(self, oauth: str, account_id: str) -> UserDB | None:
        """Not implemented: this deployment has no OAuth provider."""
        raise NotImplementedError("This deployment does not support OAuth accounts")

    async def create(self, create_dict: dict[str, Any]) -> UserDB:
        """Insert an account."""
        user = self.user_table(**create_dict)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    async def update(self, user: UserDB, update_dict: dict[str, Any]) -> UserDB:
        """Update an account."""
        for key, value in update_dict.items():
            setattr(user, key, value)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    async def delete(self, user: UserDB) -> None:
        """Remove an account."""
        self.session.delete(user)
        self.session.commit()

    async def add_oauth_account(self, user: UserDB, create_dict: dict[str, Any]) -> Any:
        """Not implemented: this deployment has no OAuth provider."""
        raise NotImplementedError("This deployment does not support OAuth accounts")

    async def update_oauth_account(
        self, user: UserDB, oauth_account: Any, update_dict: dict[str, Any]
    ) -> Any:
        """Not implemented: this deployment has no OAuth provider."""
        raise NotImplementedError("This deployment does not support OAuth accounts")
