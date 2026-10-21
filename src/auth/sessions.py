"""Session management (WS-14 · A1, extended by A3).

A session is a row in ``access_tokens``. These helpers are the only
supported way to end one, and they are deliberately small: "end every
session", "end every session but this one", "end this one".

**Why the helpers exist rather than a route doing the DELETE itself.** A
revocation is a security action, and the ways it can go wrong are
predictable: forgetting the ``WHERE user_id = ...`` and revoking
*everyone's* sessions, or forgetting the commit and revoking nothing.
One implementation, used by the password-change hook, the
reset-password hook, the logout route and the "log me out everywhere"
route, is the way to make the wrong thing hard to write.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.auth.tokens import AccessTokenDB
from src.config.settings import get_settings

__all__ = [
    "list_sessions",
    "revoke_all_sessions",
    "revoke_other_sessions",
    "revoke_session",
    "token_from_request",
]


def token_from_request(request) -> str | None:
    """The session token the request presented, if it presented one.

    The token may have arrived in the session cookie (the browser
    transport) or in an ``Authorization: Bearer`` header (the CLI
    transport). Either way, this is the token of the session the request
    is *currently* using — which is the one a "revoke all the others"
    operation has to keep.
    """
    if request is None:
        return None
    settings = get_settings()
    cookie_token = request.cookies.get(settings.auth_session_cookie_name)
    if cookie_token:
        return cookie_token
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[len("bearer ") :].strip() or None
    return None


def list_sessions(db: Session, user_id: str) -> list[AccessTokenDB]:
    """The live sessions of one account, newest first."""
    return list(
        db.query(AccessTokenDB)
        .filter(AccessTokenDB.user_id == user_id)
        .order_by(AccessTokenDB.created_at.desc())
        .all()
    )


def revoke_session(db: Session, user_id: str, token: str) -> bool:
    """End one session of one account.

    The ``user_id`` is part of the filter on purpose: a caller may only
    end **its own** sessions, so the id is not taken from the request.
    """
    deleted = (
        db.query(AccessTokenDB)
        .filter(AccessTokenDB.token == token, AccessTokenDB.user_id == user_id)
        .delete()
    )
    db.commit()
    return bool(deleted)


def revoke_all_sessions(db: Session, user_id: str) -> int:
    """End **every** session of one account. Returns how many were ended."""
    deleted = db.query(AccessTokenDB).filter(AccessTokenDB.user_id == user_id).delete()
    db.commit()
    return int(deleted)


def revoke_other_sessions(db: Session, user_id: str, keep_token: str | None = None) -> int:
    """End every session of one account **except** the one named.

    This is what a password change does: the session the change was made
    from stays alive (otherwise the user is logged out by the act of
    securing their account), every other session — the one an attacker
    might be holding — does not.
    """
    query = db.query(AccessTokenDB).filter(AccessTokenDB.user_id == user_id)
    if keep_token:
        query = query.filter(AccessTokenDB.token != keep_token)
    deleted = query.delete()
    db.commit()
    return int(deleted)


def purge_expired_sessions(db: Session, older_than: datetime | None = None) -> int:
    """End the sessions that are past their lifetime. Returns how many."""
    cutoff = older_than or datetime.now(UTC)
    deleted = db.query(AccessTokenDB).filter(AccessTokenDB.created_at < cutoff).delete()
    db.commit()
    return int(deleted)
