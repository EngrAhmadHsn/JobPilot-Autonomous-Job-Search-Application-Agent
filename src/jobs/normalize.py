"""Shared normalization helpers for job-source adapters.

Pure functions only: every adapter maps raw provider payloads through these
helpers so field formatting stays identical across sources (plan §22.1 —
normalize everything into one canonical shape at the source boundary).
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.security.html import neutralize_html


def html_to_text(raw: str | None) -> str:
    """Convert an HTML job description to plain text.

    The conversion itself lives in :func:`src.security.html.neutralize_html`
    (WS-12), so the boards that serve HTML and the contract-level guard
    that every listing passes through share **one** implementation. That
    matters: two HTML-to-text implementations drift, and the one that
    drifts is the one that leaves a `<script>` behind.

    The whitespace is collapsed here (the WS-02 behaviour) so a posting
    arrives as one reflowed block of text.
    """
    return neutralize_html(raw, collapse_whitespace=True)


def job_records(payload: object, key: str = "jobs") -> list[dict]:
    """The list of job records in a provider payload, as dictionaries.

    WS-12: a board is untrusted input, so the shape of its JSON is
    untrusted too. ``payload.get("jobs") or []`` looks defensive but is
    not: when ``jobs`` is a **string**, the ``or []`` keeps the string and
    the loop iterates its *characters*, and the first ``job.get(...)``
    raises ``AttributeError``. A board that returns ``{"jobs": "boom"}``
    would take the whole search down with a 500.

    This accessor returns only the entries that really are dictionaries
    and ignores everything else, so a malformed board yields no listings
    (a degraded source) rather than an exception.
    """
    if not isinstance(payload, dict):
        return []
    raw = payload.get(key)
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


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
