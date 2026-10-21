"""The scope a request acts as (WS-14 · A2).

One dependency, one place. Every route that touches user-scoped data
takes its scope from here, and the scope is what carries the *owner*
filter down into :mod:`src.db.access`.

**A0 landed the shape; A2 flipped the behaviour.** Before this change
the dependency returned the **legacy scope** — the single owner that the
WS-13 migration backfilled the pre-existing rows to — so the routes
filtered by owner but the scope that carried the filter did not come
from an identity. Now it comes from the **authenticated principal**, and
every route is tenant-scoped at the moment this function is read.

**The rule that makes this safe (R2): the scope is built from the
verified session and from nothing else.** No ``user_id`` in a body, a
header, a query parameter or a path is ever read here. The principal is
the only source, and the principal is what the server resolved from a
session row.

A request with no credential never reaches a route at all: the
dependency raises a 401 before the route body runs. That is why this is a
dependency and not a lookup inside the route — a route that forgot to ask
for the scope would silently act as nobody.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from src.auth.routes import current_active_user
from src.db.access import LEGACY_SCOPE, UserScope
from src.db.users import UserDB

__all__ = ["LEGACY_SCOPE", "UserScope", "current_scope"]


def current_scope(
    user: Annotated[UserDB, Depends(current_active_user)],
) -> UserScope:
    """The scope the current request acts as.

    WS-14 · A2: the scope of the **authenticated** principal — never a
    scope built from the request body, a header, or a path parameter.
    The principal is either an ordinary user (who sees only their own
    rows) or a superuser (the platform's own audit view, which is the one
    deliberate exception in :mod:`src.db.access`).
    """
    return UserScope(user_id=user.id, is_superuser=bool(user.is_superuser))
