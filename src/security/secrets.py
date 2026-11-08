"""Encryption at rest for user-supplied provider keys (WS-22).

**What this protects.** A user's registered model key is a credential the
platform stores on the user's behalf. It never needs to be read back to a
human, only to a provider call, so it is stored **encrypted** and the
plaintext exists only in memory for the duration of a call.

**Where the encryption key comes from** (resolved once per process):

1. ``BYOK_ENCRYPTION_KEY`` — an explicit urlsafe-base64 32-byte key. The
   deployment's own choice, and the only accepted source in production.
2. otherwise **HKDF-SHA256 over ``AUTH_SECRET``** — the secret the deployment
   already keeps for identity tokens, stretched into a distinct key with its
   own salt and info string, so the two uses cannot collide.
3. otherwise, **development only**, a generated key file under the data tree
   (``data/secrets/byok.key``, created 0600 where the platform supports it).

**What (3) is and is not.** A local key file protects against database
exfiltration — a copied ``app.db`` is useless without it — but not against an
attacker who already reads the host's filesystem. That is stated here rather
than implied: a deployment that needs more must set (1). A production
deployment with no (1) and no (2) **refuses to start** when BYOK is enabled
(``Settings._validate_production_byok``).

**The cipher.** Fernet — AES-128-CBC with an HMAC-SHA256 authenticator, from
the ``cryptography`` package. Nothing is hand-rolled: a bespoke scheme here
would be the one thing worse than storing the key in the clear.
"""

from __future__ import annotations

import base64
import logging
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from src.config.settings import ensure_dir, get_settings

logger = logging.getLogger(__name__)

__all__ = [
    "SecretBoxUnavailable",
    "decrypt_secret",
    "encrypt_secret",
    "key_material_source",
    "resolve_box",
]

#: Domain separation for the AUTH_SECRET derivation. Changing either string
#: changes every derived key, so they are constants, not preferences.
_HKDF_SALT = b"aja-byok-v1"
_HKDF_INFO = b"llm-credential-encryption"

#: The generated development key file, relative to the data directory.
_KEY_FILE_NAME = "byok.key"


class SecretBoxUnavailable(RuntimeError):
    """No usable encryption key material is configured."""


def _key_from_auth_secret(secret: str) -> bytes:
    """Stretch ``AUTH_SECRET`` into a Fernet key with HKDF-SHA256."""
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    ).derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(derived)


def _local_key_file() -> Path:
    """Where the development key file lives (inside the data tree)."""
    return Path(get_settings().data_dir) / "secrets" / _KEY_FILE_NAME


def _read_or_create_local_key() -> bytes:
    """The local key file's material, generated on first use (development)."""
    path = _local_key_file()
    if path.exists():
        return path.read_bytes().strip()
    ensure_dir(path.parent)
    material = base64.urlsafe_b64encode(os.urandom(32))
    path.write_bytes(material)
    try:  # best effort: meaningless on Windows, real on POSIX
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - platform dependent
        logger.debug("Could not restrict permissions on %s", path)
    logger.info("Generated a local BYOK encryption key at %s (development)", path)
    return material


def key_material_source() -> str:
    """Where the encryption key comes from, for the status endpoint.

    One of ``explicit``, ``auth_secret``, ``local_file``, ``none`` — never
    the key itself.
    """
    settings = get_settings()
    if settings.byok_encryption_key:
        return "explicit"
    if settings.auth_secret:
        return "auth_secret"
    if settings.app_env != "production":
        return "local_file"
    return "none"


@lru_cache(maxsize=1)
def resolve_box() -> Fernet:
    """The process-wide Fernet instance for the credential store.

    Raises:
        SecretBoxUnavailable: no key material exists for this deployment
            (production with neither ``BYOK_ENCRYPTION_KEY`` nor
            ``AUTH_SECRET``). The caller answers "BYOK is not configured"
            rather than storing anything.
    """
    settings = get_settings()
    if settings.byok_encryption_key:
        try:
            material = settings.byok_encryption_key.encode("ascii")
            return Fernet(material)
        except (ValueError, TypeError) as exc:
            raise SecretBoxUnavailable(
                "BYOK_ENCRYPTION_KEY is not a valid urlsafe base64 32-byte key"
            ) from exc
    if settings.auth_secret:
        return Fernet(_key_from_auth_secret(settings.auth_secret))
    if settings.app_env != "production":
        return Fernet(_read_or_create_local_key())
    raise SecretBoxUnavailable(
        "BYOK is enabled but this deployment has no encryption key material "
        "(set BYOK_ENCRYPTION_KEY or AUTH_SECRET)"
    )


def reset_box() -> None:
    """Drop the cached box (tests change the settings)."""
    resolve_box.cache_clear()


def encrypt_secret(plaintext: str) -> str:
    """Encrypt *plaintext* for storage; returns a Fernet token."""
    return resolve_box().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    """Decrypt a stored token.

    Raises:
        SecretBoxUnavailable: the token cannot be decrypted with the current
            key material — a rotated or lost key, or a tampered row. The
            message never contains the token or the underlying error detail
            beyond its type.
    """
    try:
        return resolve_box().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretBoxUnavailable(
            "The stored credential could not be decrypted with this "
            "deployment's current key material; re-register the key"
        ) from exc
