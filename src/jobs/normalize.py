"""Shared normalization helpers for job-source adapters.

Pure functions only: every adapter maps raw provider payloads through these
helpers so field formatting stays identical across sources (plan §22.1 —
normalize everything into one canonical shape at the source boundary).
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def html_to_text(raw: str | None) -> str:
    """Convert an HTML job description to plain text.

    Regex-free tag stripping is intentionally avoided; ``re.sub`` with a
    simple tag pattern plus whitespace collapse is the deterministic
    approach agreed for WS-02 (no HTML parser dependency, no LLM). HTML
    entities are unescaped first so ``&amp;`` etc. render as text.
    """
    if not raw:
        return ""
    text = html.unescape(raw)
    text = _TAG_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def ms_epoch_to_iso(ms: float | str | None) -> str | None:
    """Convert a millisecond epoch timestamp (Lever ``createdAt``) to ISO 8601 UTC.

    Returns None for missing/invalid input — never fabricates a date.
    """
    if ms is None or ms == "":
        return None
    try:
        seconds = float(ms) / 1000.0
        return datetime.fromtimestamp(seconds, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def normalize_publication_date(value: str | None) -> str | None:
    """Normalize a provider publication date to ISO 8601.

    Handles the two shapes actually seen in the wild (verified against live
    payloads 2026-10-11):

    - naive ISO 8601 (Remotive: ``2026-10-08T21:47:32``) — Remotive publishes
      UTC times, so a naive stamp is interpreted as UTC and normalized with
      an explicit ``+00:00`` offset;
    - RFC 2822 (``Fri, 03 Oct 2026 09:15:22 GMT``) — parsed via
      ``email.utils`` and converted to UTC.

    Already-offset ISO stamps pass through unchanged. Returns None for
    missing/invalid input — never fabricates a date.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    from email.utils import parsedate_to_datetime

    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()
