"""The secret that signs the account tokens (WS-14 · A1).

``fastapi-users`` signs the password-reset and the e-mail-verification
tokens with a secret. That secret is **not** a session secret — the
sessions are server-side rows — but a leaked one would let an attacker
mint a reset token for any account, which is a complete account
takeover.

**What happens when it is unset.** A production deployment refuses to
start without it (``Settings._validate_production_identity``), so the
question is only ever asked in development. There, this module mints an
**ephemeral** secret: a random value held in memory for the life of the
process.

The consequences are deliberate and worth stating:

- the development deployment works out of the box, with no setup step
  and no secret in a file that someone might commit;
- the secret changes on every restart, so a password-reset token issued
  before the restart is no longer valid afterwards. In development that
  is a non-event; in production the secret is configured and stable, and
  a restart does **not** invalidate outstanding tokens.
- a warning is logged, because a deployment that *thinks* it has a
  stable secret and does not is exactly the kind of mismatch that
  matters.
"""

from __future__ import annotations

import logging
import secrets

from src.config.settings import get_settings

logger = logging.getLogger(__name__)

__all__ = ["auth_secret"]

#: The ephemeral development secret. Process-local and never written
#: anywhere.
_EPHEMERAL: str | None = None


def auth_secret() -> str:
    """The secret that signs the reset and verification tokens."""
    global _EPHEMERAL

    settings = get_settings()
    if settings.auth_secret:
        return settings.auth_secret

    if settings.app_env == "production":
        # The settings check refuses to start in this case, so reaching
        # this line means the check was bypassed. Refusing here is the
        # belt to that braces.
        raise RuntimeError("AUTH_SECRET must be set in production. Refusing to mint a token.")

    if _EPHEMERAL is None:
        _EPHEMERAL = secrets.token_urlsafe(48)
        logger.warning(
            "AUTH_SECRET is not set; using an ephemeral development secret. "
            "Password-reset and verification tokens will not survive a restart."
        )
    return _EPHEMERAL
