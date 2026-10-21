"""Redaction of secrets and PII (WS-06 · SEC-03 / SEC-12).

Nothing that reaches an audit row or a log line may contain a credential, and
personal data is masked on the way in. Two rules:

1. **A secret key is dropped, not masked.** A masked secret is still a hint
   about its shape, its length, and its prefix, so the whole key/value pair
   is removed.
2. **Personal data is masked.** Emails and phone numbers are replaced with
   ``<email>`` / ``<phone>``; every other value is kept, because the audit
   trail is only useful if it still says what happened.

The email and phone patterns are the ones the resume parser uses
(``src/resume/parser.py``), so the audit trail and the parser agree on what
personal data looks like. The phone pattern additionally requires at least
seven digits, so an ISO date is not mistaken for a phone number.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Key names whose values never reach the audit store.
SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|token"
    r"|password|passwd|secret|cookie|authorization|credential|private[_-]?key|"
    r"session[_-]?id)",
    re.IGNORECASE,
)

# Longest string kept verbatim in an audit row.
MAX_VALUE_CHARS = 500

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")

# An ISO date or timestamp is digits and separators too, so it is excluded
# explicitly: ``2026-10-21`` must stay readable in the audit trail.
DATE_LIKE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}(:\d{2})?)?$")

REDACTED_EMAIL = "<email>"
REDACTED_PHONE = "<phone>"


def _looks_like_phone(match: re.Match[str]) -> bool:
    """True when the match holds enough digits to be a phone number.

    The parser's pattern also matches an ISO date (``2026-10-21``). Requiring
    seven digits and excluding date-like values keeps timestamps readable.
    """
    text = match.group(0)
    if DATE_LIKE_RE.match(text.strip()):
        return False
    return sum(character.isdigit() for character in text) >= 7


def mask_pii(text: str) -> str:
    """Replace emails and phone numbers in *text* with placeholders."""
    if not text:
        return text
    masked = EMAIL_RE.sub(REDACTED_EMAIL, text)
    masked = PHONE_RE.sub(
        lambda match: REDACTED_PHONE if _looks_like_phone(match) else match.group(0), masked
    )
    return masked


def _sanitize_value(value: Any) -> Any:
    """Recursively sanitize one metadata value."""
    if isinstance(value, str):
        masked = mask_pii(value)
        if len(masked) > MAX_VALUE_CHARS:
            return masked[:MAX_VALUE_CHARS] + f"…[truncated {len(masked) - MAX_VALUE_CHARS} chars]"
        return masked
    if isinstance(value, Mapping):
        return sanitize_metadata(value)
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(item) for item in value]
    return value


def sanitize_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a sanitized copy of *metadata*.

    Keys whose name looks like a credential are dropped entirely; every string
    value has its personal data masked and is truncated to
    :data:`MAX_VALUE_CHARS`; nested mappings and sequences are sanitized
    recursively. Non-string scalars are preserved as they are.
    """
    if not metadata:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        name = str(key)
        if SECRET_KEY_RE.search(name):
            continue
        sanitized[name] = _sanitize_value(value)
    return sanitized


def is_secret_key(key: str) -> bool:
    """True when *key* names a credential and its value must be dropped."""
    return bool(SECRET_KEY_RE.search(key))
