"""The user manager: hashing, tokens, and the lifecycle hooks (WS-14 · A1).

``fastapi-users``'s ``BaseUserManager`` does the protocol work — it
verifies a password, mints a reset token, and calls the hooks below. What
it deliberately does not decide is the **policy**, and the policy is
where this application differs from the library's defaults:

- the password is hashed with **argon2 only** (the library's default is
  argon2 with a bcrypt fallback for verification, which is fine for
  reading old hashes but is not what a new hash should be);
- a password that is too short is refused at registration, at login
  (change) and at reset — the same rule everywhere, so there is one
  definition of "strong enough";
- the **legacy corpus claim**: the first account to register takes
  ownership of the rows that pre-date the identity work, so an operator's
  existing resumes, matches and applications reach the operator's own
  account instead of being orphaned;
- the lifecycle hooks write to the **audit trail**, so a registration, a
  login, a password reset and a session revocation are all attributable.

The manager is where a password change revokes the account's **other**
sessions. That is a security property, not a convenience: a password
change is what a user does *because* they think somebody else has the
account, so leaving the other sessions alive would defeat the point.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi_users import BaseUserManager, exceptions
from fastapi_users.password import PasswordHelper
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy.orm import Session

from src.auth.db_adapter import SqlAlchemyUserDatabase
from src.auth.delivery import KIND_PASSWORD_RESET, KIND_VERIFICATION, deliver_token
from src.auth.secrets import auth_secret
from src.config.settings import get_settings
from src.db.users import UserDB
from src.security.audit import (
    ACTION_AUTH,
    OUTCOME_SUCCESS,
    record_audit,
)

logger = logging.getLogger(__name__)

__all__ = ["UserManager", "get_user_manager", "password_helper"]

#: The minimum length of a password. Argon2 makes guessing expensive, but
#: a long password is still the cheapest defence there is.
MIN_PASSWORD_LENGTH = 8

#: Argon2 only. The library's default mixes in bcrypt for reading legacy
#: hashes; this deployment has no legacy hashes, and every new password
#: should be hashed with the memory-hard KDF.
password_helper = PasswordHelper(password_hash=PasswordHash((Argon2Hasher(),)))


class UserManager(BaseUserManager[UserDB, str]):
    """The application's user manager."""

    reset_password_token_lifetime_seconds = 3600
    verification_token_lifetime_seconds = 3600

    @property
    def reset_password_token_secret(self) -> str:
        """The secret that signs a password-reset token.

        A property rather than a class attribute, because the secret is
        resolved **per call**: the configured value when there is one,
        and an ephemeral development secret when there is not (see
        :mod:`src.auth.secrets`).
        """
        return auth_secret()

    @property
    def verification_token_secret(self) -> str:
        """The secret that signs an e-mail-verification token."""
        return auth_secret()

    def __init__(self, user_db) -> None:
        super().__init__(user_db, password_helper)

    def parse_id(self, value: Any) -> str:
        """Turn a string into an account id.

        The library ships mixins for UUID and integer ids; this
        application's ids are opaque hex strings, so the mixin is here.
        An id that is not a string is an **invalid id**, not a lookup that
        happens to miss.
        """
        if isinstance(value, str):
            return value
        raise exceptions.InvalidID()

    # -- policy ------------------------------------------------------------

    async def validate_password(self, password: str, user: UserDB) -> None:
        """Refuse a password that is too short.

        The same rule at registration, at reset and at change, so there
        is exactly one definition of "strong enough" in the codebase.
        """
        if len(password) < MIN_PASSWORD_LENGTH:
            raise exceptions.InvalidPasswordException(
                f"The password must be at least {MIN_PASSWORD_LENGTH} characters long."
            )

    # -- lifecycle hooks ----------------------------------------------------

    async def on_after_register(self, user: UserDB, request=None) -> None:
        """Record the registration, and let the first account claim the corpus."""
        from src.db.access import claim_legacy_rows

        claimed = 0
        if get_settings().auth_claim_legacy:
            claimed = claim_legacy_rows(self.user_db.session, user.id)
        record_audit(
            ACTION_AUTH,
            actor=f"user:{user.id}",
            resource=user.id,
            outcome=OUTCOME_SUCCESS,
            owner_id=user.id,
            metadata={"event": "register", "claimed_legacy_rows": claimed},
        )
        logger.info("Account registered", extra={"user_id": user.id})

    async def on_after_login(self, user: UserDB, request=None, response=None) -> None:
        """Record the login."""
        record_audit(
            ACTION_AUTH,
            actor=f"user:{user.id}",
            resource=user.id,
            outcome=OUTCOME_SUCCESS,
            owner_id=user.id,
            metadata={"event": "login"},
        )

    async def on_after_update(
        self, user: UserDB, update_dict: dict[str, Any], request=None
    ) -> None:
        """Record the change, and end the other sessions on a password change."""
        from src.auth.sessions import revoke_other_sessions, token_from_request

        changed = sorted(update_dict)
        if "password" in update_dict:
            # The session the change was made **from** stays alive —
            # otherwise securing the account logs the user out of it. Every
            # other session goes, because that is the one an attacker
            # might be holding.
            revoked = revoke_other_sessions(
                self.user_db.session, user.id, keep_token=token_from_request(request)
            )
            metadata = {"event": "password_change", "revoked_sessions": revoked}
        else:
            metadata = {"event": "update", "fields": changed}
        record_audit(
            ACTION_AUTH,
            actor=f"user:{user.id}",
            resource=user.id,
            outcome=OUTCOME_SUCCESS,
            owner_id=user.id,
            metadata=metadata,
        )

    async def on_after_forgot_password(self, user: UserDB, token: str, request=None) -> None:
        """Record the reset request and the token it issued.

        **Sending the token is out of scope**: this deployment has no SMTP
        provider, so the token is written to the audit trail (and to the
        log in development) instead of to an inbox. A deployment that
        adds mail replaces this hook; the token's lifetime and its
        audience are already correct.
        """
        deliver_token(KIND_PASSWORD_RESET, user.email, token, user.id)
        record_audit(
            ACTION_AUTH,
            actor=f"user:{user.id}",
            resource=user.id,
            outcome=OUTCOME_SUCCESS,
            owner_id=user.id,
            metadata={"event": "forgot_password"},
        )

    async def on_after_request_verify(self, user: UserDB, token: str, request=None) -> None:
        """Record the verification request and the token it issued."""
        record_audit(
            ACTION_AUTH,
            actor=f"user:{user.id}",
            resource=user.id,
            outcome=OUTCOME_SUCCESS,
            owner_id=user.id,
            metadata={"event": "request_verify"},
        )
        deliver_token(KIND_VERIFICATION, user.email, token, user.id)

    async def on_after_verify(self, user: UserDB, request=None) -> None:
        record_audit(
            ACTION_AUTH,
            actor=f"user:{user.id}",
            resource=user.id,
            outcome=OUTCOME_SUCCESS,
            owner_id=user.id,
            metadata={"event": "verify"},
        )

    async def on_after_reset_password(self, user: UserDB, request=None) -> None:
        """Record the reset and end every session the account had."""
        from src.auth.sessions import revoke_all_sessions

        revoked = revoke_all_sessions(self.user_db.session, user.id)
        record_audit(
            ACTION_AUTH,
            actor=f"user:{user.id}",
            resource=user.id,
            outcome=OUTCOME_SUCCESS,
            owner_id=user.id,
            metadata={"event": "reset_password", "revoked_sessions": revoked},
        )

    async def on_after_delete(self, user: UserDB, request=None) -> None:
        record_audit(
            ACTION_AUTH,
            actor=f"user:{user.id}",
            resource=user.id,
            outcome=OUTCOME_SUCCESS,
            owner_id=user.id,
            metadata={"event": "delete"},
        )


def get_user_manager(db: Session):
    """Build a manager over the request's database session."""
    
    return UserManager(SqlAlchemyUserDatabase(db, UserDB))


__all__ = [
    "MIN_PASSWORD_LENGTH",
    "UserManager",
    "get_user_manager",
    "password_helper",
]
