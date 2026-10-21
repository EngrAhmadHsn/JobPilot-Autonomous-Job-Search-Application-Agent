"""Where the account tokens are delivered (WS-14 · A1).

The password-reset and the e-mail-verification tokens have to reach
somebody. **Sending mail is out of scope** for this deployment — it
needs an SMTP provider, and a deployment concern is not a security
control.

Until then, the tokens are delivered to a **local mailbox directory**:
one file per token, in a directory the operator can read. That is the
same idea as the ``mailhog``/``mailpit`` containers a development
deployment usually runs, implemented in a file so the deployment has no
extra process.

**Why not the log, and why not the audit trail.** Both were considered
and both are wrong:

- the **log** is the wrong place for a credential. It is collected, it is
  shipped, it is readable by anyone who can read the log, and it is
  routinely pasted into a bug report;
- the **audit trail** is wrong for a sharper reason: the redaction
  policy drops any value whose key looks like a token — which is the
  right policy — so the token would never arrive anyway. Putting a
  credential in the audit trail would mean weakening that policy.

So the token goes to a file, and the file is written with owner-only
permissions on the platforms that have them. A deployment that adds an
SMTP provider replaces this module; the flow around it — the token's
lifetime, its audience, and the fact that a password change invalidates
outstanding reset tokens — is already correct.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

from src.config.settings import get_settings

logger = logging.getLogger(__name__)

__all__ = ["deliver_token", "mailbox_dir", "read_token"]

#: The token kinds. The name is part of the file name, so the operator
#: can tell them apart.
KIND_PASSWORD_RESET = "password-reset"
KIND_VERIFICATION = "verification"

#: A file name stem must be safe on every platform, so it is built from
#: a strict character set rather than from the address itself.
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def mailbox_dir() -> Path:
    """The directory the tokens are delivered to."""
    settings = get_settings()
    return Path(settings.auth_token_mailbox_dir)


def _safe_stem(value: str) -> str:
    """A file-name-safe stem for *value*."""
    cleaned = _SAFE.sub("-", value).strip("-")
    return cleaned[:48] or "unknown"


def deliver_token(kind: str, email: str, token: str, user_id: str) -> Path | None:
    """Deliver one token to the mailbox, and return the file it went to.

    Args:
        kind: What the token is for (see ``KIND_*``).
        email: The address the token is for.
        token: The token itself.
        user_id: The account the token belongs to.

    Returns:
        The file the token was written to, or ``None`` when the mailbox
        could not be written. A failure to deliver is **logged, never
        raised**: a mailbox that cannot be written must not turn a
        password-reset request into a 500, and it must not tell a
        stranger that the account exists.
    """
    try:
        directory = mailbox_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        name = f"{_safe_stem(kind)}-{_safe_stem(user_id)}-{stamp}-{secrets.token_hex(4)}.token"
        target = directory / name
        target.write_text(
            f"kind: {kind}\n"
            f"email: {email}\n"
            f"user: {user_id}\n"
            f"issued: {datetime.now(UTC).isoformat()}\n"
            f"\n"
            f"{token}\n",
            encoding="utf-8",
        )
        # Owner-only, where the platform has such a thing.
        try:
            os.chmod(target, 0o600)
        except OSError:  # pragma: no cover - Windows has no POSIX mode
            pass
        logger.info("A %s token was delivered to the mailbox (%s)", kind, target.name)
        return target
    except OSError as exc:
        logger.error("The token mailbox could not be written: %s", exc)
        return None


def read_token(directory: Path, kind: str, user_id: str) -> str | None:
    """The most recent token of *kind* for *user_id* in *directory*.

    This is what an operator (and the test suite) reads. It is not part
    of the API: nothing in the application reads a delivered token back.
    """
    if not directory.exists():
        return None
    prefix = f"{_safe_stem(kind)}-{_safe_stem(user_id)}-"
    candidates = sorted(directory.glob(f"{prefix}*.token"))
    if not candidates:
        return None
    text = candidates[-1].read_text(encoding="utf-8")
    parts = text.split("\n\n", 1)
    if len(parts) != 2:
        return None
    return parts[1].strip() or None
