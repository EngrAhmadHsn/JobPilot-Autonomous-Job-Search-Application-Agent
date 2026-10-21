"""Identity for the platform (WS-14 · A1).

This package is the *principal* half of WS-14. Before it, the API had no
authentication at all: every endpoint was reachable by anyone who could
reach the port, and the data layer had an owner column with nothing to key
it on. A0 built the key (the ownership spine) and A1 builds the thing that
holds it (an identity).

**The shape of the design, and why.**

- The identity stack is ``fastapi-users`` — an established library — rather
  than a hand-rolled token scheme. A hand-rolled scheme is how subtle
  verification bugs get in, and this one is on the path to "an employer
  receives this person's resume".
- The password is hashed with **argon2**, a memory-hard KDF, through
  ``fastapi_users.password.PasswordHelper``. The plaintext never reaches
  the database, a log, or an audit row.
- **Two transports, one identity.** A cookie (HttpOnly, ``SameSite=Lax``)
  for the browser, a bearer token for the CLI and the repo's own scripts.
  Both resolve to the same user store and the same principal.
- The sessions are **server-side rows**, not signed blobs. That is a
  deliberate trade: a stateless JWT cannot be revoked before it expires,
  and "log me out everywhere" has to work. The cost is a table.
- The database adapters are **ours**, not the library's. ``fastapi-users``
  ships an async-only ``SQLAlchemyUserDatabase``; this codebase is
  synchronous end to end, and importing ``aiosqlite`` and a second engine
  to satisfy a library's async signature would have been a large change
  with one narrow benefit.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
