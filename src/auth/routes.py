"""The identity API (WS-14 · A1).

Every route here is under ``/api/auth``. The library provides most of
them; the ones that are **ours** are the ones the library does not have:
the "me" routes, the session-revocation routes and the deletion request.

The route map:

============================================  ======  ==============================
Route                                         Method What it does
============================================  ======  ==============================
``/api/auth/register``                         POST   Create an account
``/api/auth/cookie/login``                     POST   Log in (browser transport)
``/api/auth/cookie/logout``                    POST   End the current session
``/api/auth/token/login``                      POST   Log in (bearer transport)
``/api/auth/token/logout``                     POST   End the current session
``/api/auth/forgot-password``                  POST   Request a reset token
``/api/auth/reset-password``                   POST   Set a new password
``/api/auth/request-verify-token``             POST   Request a verification token
``/api/auth/verify``                           POST   Verify the account
``/api/auth/me``                               GET    The authenticated principal
``/api/auth/me``                               PATCH  Change e-mail / password
``/api/auth/sessions``                         GET    The caller's live sessions
``/api/auth/sessions/revoke``                  POST   End every session
``/api/auth/sessions/{token}``                 DELETE End one session
``/api/auth/me``                               DELETE Request the account's deletion
============================================  ======  ==============================

Every one of these routes is about **the caller's own account**. None of
them takes an account id from the request, because the account is the
principal, and the principal is not a parameter.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_users import FastAPIUsers
from fastapi_users.exceptions import UserAlreadyExists
from fastapi_users.router import ErrorCode
from sqlalchemy.orm import Session

from src.auth.backends import (
    bearer_backend,
    cookie_backend,
    get_user_manager_dependency,
)
from src.auth.manager import UserManager
from src.auth.schemas import UserCreate, UserRead, UserUpdate
from src.auth.sessions import (
    list_sessions,
    revoke_all_sessions,
    revoke_other_sessions,
    revoke_session,
)
from src.config.settings import get_settings
from src.db.session import get_db
from src.db.users import UserDB

logger = logging.getLogger(__name__)

__all__ = ["current_active_user", "current_user", "router", "users_api"]


users_api: FastAPIUsers[UserDB, str] = FastAPIUsers(
    get_user_manager_dependency,
    [cookie_backend, bearer_backend],
)

#: The authenticated user, active or not.
current_user = users_api.authenticator.current_user()
#: The authenticated user, who must also be active. This is what the
#: protected routes use: a deactivated account (the first half of an
#: account deletion, Phase A3) must not be able to act.
current_active_user = users_api.authenticator.current_user(active=True)
#: The authenticated user **and** the token that authenticated it. The
#: token is what "revoke every session except this one" needs.
current_user_token = users_api.authenticator.current_user_token(active=True)
#: The platform's own administrative view.
current_superuser = users_api.authenticator.current_user(active=True, superuser=True)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# -- the library's routers ----------------------------------------------------


def _register_library_routers(target: APIRouter) -> None:
    """Mount the ``fastapi-users`` routers onto *target*.

    They are mounted as sub-routers rather than included on the
    application directly so that everything under ``/api/auth`` lives in
    one place, with one prefix, and one tag.
    """
    settings = get_settings()
    requires_verification = settings.auth_require_verified

    target.include_router(
        users_api.get_register_router(UserRead, UserCreate),
        tags=["auth"],
    )
    target.include_router(
        users_api.get_auth_router(cookie_backend, requires_verification=requires_verification),
        prefix="/cookie",
        tags=["auth"],
    )
    target.include_router(
        users_api.get_auth_router(bearer_backend, requires_verification=requires_verification),
        prefix="/token",
        tags=["auth"],
    )
    target.include_router(users_api.get_reset_password_router(), prefix="", tags=["auth"])
    target.include_router(users_api.get_verify_router(UserRead), prefix="", tags=["auth"])


_register_library_routers(router)


# -- the "me" routes ----------------------------------------------------------


@router.get("/me", response_model=UserRead)
def read_me(user: Annotated[UserDB, Depends(current_active_user)]) -> UserRead:
    """The authenticated principal.

    This is the endpoint that turns "the caller is anonymous" into "the
    caller is somebody", and it is the one the console calls first.
    """
    return UserRead.model_validate(user, from_attributes=True)


@router.patch("/me", response_model=UserRead)
async def update_me(
    request: Request,
    user_update: UserUpdate,
    user: Annotated[UserDB, Depends(current_active_user)],
    user_manager: Annotated[UserManager, Depends(get_user_manager_dependency)],
) -> UserRead:
    """Change the caller's own e-mail, password or display name.

    A password change ends the caller's **other** sessions: the session
    the change was made from stays, every other one goes. That is the
    point of changing a password.
    """
    try:
        updated = await user_manager.update(user_update, user, safe=True, request=request)
    except UserAlreadyExists as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorCode.UPDATE_USER_EMAIL_ALREADY_EXISTS,
        ) from exc
    return UserRead.model_validate(updated, from_attributes=True)


@router.get("/sessions")
def read_sessions(
    authenticated: Annotated[tuple[UserDB, str], Depends(current_user_token)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """The caller's live sessions.

    The token itself is **not** returned — only a short prefix of it, so
    the operator can tell two sessions apart in a list without the list
    being a set of credentials.
    """
    user, token = authenticated
    sessions = list_sessions(db, user.id)
    return {
        "sessions": [
            {
                "prefix": row.token[:8],
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "current": row.token == token,
            }
            for row in sessions
        ]
    }


@router.post("/sessions/revoke")
def revoke_every_session(
    user: Annotated[UserDB, Depends(current_active_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """End **every** session of the caller, including this one.

    This is "log me out everywhere", and the caller ends up logged out —
    which is the point.
    """
    revoked = revoke_all_sessions(db, user.id)
    return {"revoked": revoked}


@router.post("/sessions/revoke-others")
def revoke_the_other_sessions(
    authenticated: Annotated[tuple[UserDB, str], Depends(current_user_token)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """End every session of the caller **except** the current one."""
    user, token = authenticated
    revoked = revoke_other_sessions(db, user.id, keep_token=token)
    return {"revoked": revoked}


@router.delete("/sessions/{token}")
def revoke_one_session(
    token: str,
    user: Annotated[UserDB, Depends(current_active_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """End one session of the caller.

    A token that is not the caller's is **not found** — the same answer
    as a token that does not exist, so the endpoint is not an existence
    oracle.
    """
    revoked = revoke_session(db, user.id, token)
    if not revoked:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"revoked": 1}


@router.delete("/me")
def request_account_deletion(
    user: Annotated[UserDB, Depends(current_active_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Request the deletion of the caller's account.

    **This is the reversible half.** The account is deactivated and every
    session is ended, so it cannot authenticate and cannot resolve its
    resources any more. The irreversible half — the purge of the rows
    and the files — is Phase D's job, and it is deliberately not done
    from an HTTP request: a purge that runs on a click is a purge that
    runs on a mistake.
    """
    user.is_active = False
    db.add(user)
    db.commit()
    revoked = revoke_all_sessions(db, user.id)

    from src.security.audit import (
        ACTION_AUTH,
        OUTCOME_SUCCESS,
        record_audit,
    )

    record_audit(
        ACTION_AUTH,
        actor=f"user:{user.id}",
        resource=user.id,
        outcome=OUTCOME_SUCCESS,
        owner_id=user.id,
        metadata={"event": "deletion_requested", "revoked_sessions": revoked},
    )
    return {"deactivated": True, "revoked_sessions": revoked}


__all__ = [
    "current_active_user",
    "current_superuser",
    "current_user",
    "current_user_token",
    "router",
    "users_api",
]
