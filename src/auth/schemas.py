"""The wire schemas of the identity API (WS-14 · A1).

``fastapi-users`` v15 ships the **base** schemas (``BaseUser``,
``BaseUserCreate``, ``BaseUserUpdate``) and expects the application to
define the concrete ones. These are ours.

The rules the concrete schemas follow:

- the **hash never leaves**. ``UserRead`` carries the id, the e-mail, the
  flags and the name — never ``hashed_password``. A schema that could
  serialise the hash is a schema that will eventually serialise it.
- a registration may not set ``is_superuser`` or ``is_active``. The
  schemas are declared with ``extra="forbid"``, so a request that tries
  is **refused** (422) rather than silently ignored — a silently ignored
  privilege field reads like it worked.
- the update schema carries only what a user may change about **their own**
  account: the e-mail, the password and the display name.
"""

from __future__ import annotations

from fastapi_users import schemas
from pydantic import ConfigDict, EmailStr


class UserRead(schemas.BaseUser[str]):
    """The public view of an account."""

    model_config = ConfigDict(from_attributes=True)

    full_name: str | None = None


class UserCreate(schemas.BaseUserCreate):
    """What a registration may specify."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None


class UserUpdate(schemas.CreateUpdateDictModel):
    """What a user may change about their own account.

    Declared from :class:`~fastapi_users.schemas.CreateUpdateDictModel`
    rather than from ``BaseUserUpdate`` so that ``is_active``,
    ``is_superuser`` and ``is_verified`` are **not fields at all**. The
    endpoint this schema serves is "me": a user may change their own
    e-mail and their own password, and nothing else. With
    ``extra="forbid"`` a request that tries to promote itself is refused
    with a 422 instead of being quietly dropped.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    password: str | None = None
    full_name: str | None = None


__all__ = ["UserCreate", "UserRead", "UserUpdate"]
