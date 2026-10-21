"""The two authentication backends (WS-14 · A1).

**One identity, two transports.** The browser gets a cookie; the CLI and
the repo's own scripts get a bearer token. Both present the **same**
credential — a row in ``access_tokens`` — so a session is a session, and
a revocation ends both.

Why both:

- cookie only would break every script in ``scripts/`` that calls the
  API over HTTP (``verify_ws06.py``, ``refresh_jobs.py``);
- bearer only would put a token in JavaScript, where any injected script
  can read it. The console uses the cookie, which is ``HttpOnly`` and
  therefore unreadable by a script.

The two backends are told apart by their **name** (``cookie`` and
``bearer``), because the library uses the name to build the route names
and to key the OpenAPI tags.

**The strategy is the server-side store**, not a signed JWT. A signed
token cannot be revoked before it expires, and "log me out everywhere"
has to work now, not in twenty-four hours. The cost is a table and one
lookup per request.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    CookieTransport,
)
from fastapi_users.authentication.strategy import DatabaseStrategy
from sqlalchemy.orm import Session

from src.auth.manager import UserManager
from src.auth.tokens import SqlAlchemyAccessTokenDatabase
from src.config.settings import get_settings
from src.db.session import get_db
from src.db.users import UserDB

__all__ = [
    "bearer_backend",
    "cookie_backend",
    "get_access_token_database",
    "get_database_strategy",
    "get_user_manager_dependency",
]


async def get_user_manager_dependency(
    db: Annotated[Session, Depends(get_db)],
) -> AsyncGenerator[UserManager]:
    """The user manager, bound to the request's database session."""
    from src.auth.manager import get_user_manager

    yield get_user_manager(db)


def get_access_token_database(
    db: Annotated[Session, Depends(get_db)],
) -> SqlAlchemyAccessTokenDatabase:
    """The session store, bound to the request's database session."""
    return SqlAlchemyAccessTokenDatabase(db)


async def get_database_strategy(
    database: Annotated[SqlAlchemyAccessTokenDatabase, Depends(get_access_token_database)],
) -> DatabaseStrategy:
    """The strategy both transports share."""
    return DatabaseStrategy(
        database=database,
        lifetime_seconds=get_settings().auth_session_ttl_seconds,
    )


def _cookie_transport() -> CookieTransport:
    settings = get_settings()
    return CookieTransport(
        cookie_name=settings.auth_session_cookie_name,
        cookie_max_age=settings.auth_session_ttl_seconds,
        cookie_path="/",
        cookie_secure=settings.cookie_secure(),
        # HttpOnly: the console's JavaScript must not be able to read the
        # session cookie. The CSRF cookie is the opposite (readable), and
        # it is not a credential.
        cookie_httponly=True,
        # Lax, not Strict: a link from an e-mail to the console would be
        # blocked by Strict, and the console is a tool people follow
        # links to.
        cookie_samesite="lax",
    )


def _bearer_transport() -> BearerTransport:
    return BearerTransport(tokenUrl="api/auth/token/login")


cookie_backend: AuthenticationBackend[UserDB, str] = AuthenticationBackend(
    name="cookie",
    transport=_cookie_transport(),
    get_strategy=get_database_strategy,
)

bearer_backend: AuthenticationBackend[UserDB, str] = AuthenticationBackend(
    name="bearer",
    transport=_bearer_transport(),
    get_strategy=get_database_strategy,
)
