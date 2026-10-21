"""The scope a request acts as (WS-13 · A0).

One dependency, one place. Every route that touches user-scoped data
takes its scope from here, and the scope is what carries the *owner*
filter down into :mod:`src.db.access`.

Today the dependency returns the **legacy scope** — the single owner that
the WS-13 migration backfilled the pre-existing rows to. That is the
single-tenant behaviour the application has always had, expressed through
the shape the multi-user system will use. Phase A2 replaces the body of
:func:`current_scope` with the authenticated principal's scope, and every
route becomes tenant-scoped at that moment — without touching a single
call site.

That is the whole point of the split: the shape lands first, the
behaviour flips second, and the flip is one function.
"""

from __future__ import annotations

from src.db.access import LEGACY_SCOPE, UserScope

__all__ = ["LEGACY_SCOPE", "UserScope", "current_scope"]


def current_scope() -> UserScope:
    """The scope the current request acts as.

    WS-13 · A0: the legacy scope, which owns the rows that predate the
    identity work. WS-13 · A2 replaces this with the scope of the
    **authenticated** principal — never a scope built from the request
    body, a header, or a path parameter.
    """
    return LEGACY_SCOPE
