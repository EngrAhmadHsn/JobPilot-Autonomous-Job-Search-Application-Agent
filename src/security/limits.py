"""Security limits for the runtime (WS-12).

Every number that bounds **how much work an untrusted caller can cause this
process to do** lives here, in one reviewable place. A limit that is defined
next to the code it guards is easy to find; a limit scattered across five
modules is a limit nobody re-checks when it needs raising.

The values are read from the environment and validated at first use. A knob
that decides how much memory a request may consume is a typo waiting to
happen (``0`` would mean "no limit" for some knobs and "refuse everything"
for others), so an invalid value fails loudly instead of silently degrading
the protection.

The categories, and what each one defends against:

============================  ==============================================
``rate_limit_*``             API abuse / DDoS — requests per client window.
``body_limit_bytes``         Oversized request bodies (memory exhaustion).
``max_concurrent_heavy``     Request pile-up on the expensive endpoints.
``max_listings_per_source``  One hostile board flooding the corpus.
``max_new_listings_per_refresh``  A refresh admitting an unbounded batch.
``max_corpus_listings``      The persisted corpus (and therefore every
                             full-corpus read) staying bounded.
``max_embed_per_refresh``    Embedding work — and the provider quota — spent
                             per refresh.
``max_cache_entries``        The on-disk embedding cache staying bounded.
``max_upload_*``             Zip-bomb and file-count guards on uploads.
``max_response_bytes``       A hostile job board returning a huge body.
``max_custom_*``             Unbounded per-request form data.
============================  ==============================================

The defaults are chosen for a single-operator deployment on a laptop: they are
high enough that a legitimate daily refresh never trips them, and low enough
that a flood fails fast instead of exhausting the machine.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

__all__ = ["SecurityLimits", "get_limits", "reset_limits"]


@dataclass(frozen=True)
class SecurityLimits:
    """The runtime limits. Immutable: one value set for the process."""

    # -- API layer ---------------------------------------------------------
    rate_limit_requests: int
    rate_limit_window_seconds: float
    body_limit_bytes: int
    max_concurrent_heavy: int
    heavy_queue_timeout_seconds: float

    # -- corpus admission --------------------------------------------------
    max_listings_per_source: int
    max_new_listings_per_refresh: int
    max_corpus_listings: int

    # -- embedding ---------------------------------------------------------
    max_embed_per_refresh: int
    max_cache_entries: int

    # -- uploads -----------------------------------------------------------
    max_upload_uncompressed_bytes: int
    max_zip_entries: int

    # -- outbound HTTP -----------------------------------------------------
    max_response_bytes: int

    # -- request payloads --------------------------------------------------
    max_custom_fields: int
    max_custom_field_chars: int

    # -- text --------------------------------------------------------------
    max_description_chars: int
    max_title_chars: int
    max_company_chars: int
    max_prompt_untrusted_chars: int


def _int_env(name: str, default: int, *, minimum: int) -> int:
    """Read an integer knob, failing loudly on a bad value.

    A non-numeric or out-of-range value is a configuration error, never a
    reason to fall back to the default: a limit that silently reverts to a
    permissive value is a limit that is not doing its job.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}. Refusing to start.") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}, got {value!r}. Refusing to start.")
    return value


def _float_env(name: str, default: float, *, minimum: float) -> float:
    """Read a float knob, failing loudly on a bad value."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number, got {raw!r}. Refusing to start.") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}, got {value!r}. Refusing to start.")
    return value


def _build() -> SecurityLimits:
    return SecurityLimits(
        # 60 requests/minute per client: a human driving the API by hand, and
        # the daily refresh, never approach it; a flood does.
        rate_limit_requests=_int_env("RATE_LIMIT_REQUESTS", 60, minimum=1),
        rate_limit_window_seconds=_float_env("RATE_LIMIT_WINDOW_SECONDS", 60.0, minimum=0.001),
        # 8 MiB. The resume upload is capped at 5 MB of file; the multipart
        # envelope around it needs headroom, and nothing else should be large.
        body_limit_bytes=_int_env("BODY_LIMIT_BYTES", 8 * 1024 * 1024, minimum=1024),
        # Two at a time: the refresh and the search both walk the corpus, and
        # a third concurrent one only queues work behind them.
        max_concurrent_heavy=_int_env("MAX_CONCURRENT_HEAVY", 2, minimum=1),
        heavy_queue_timeout_seconds=_float_env("HEAVY_QUEUE_TIMEOUT_SECONDS", 5.0, minimum=0.0),
        # Per source per refresh. A board that suddenly returns 50,000
        # listings is either broken or hostile; either way it may not
        # dictate the size of the corpus.
        max_listings_per_source=_int_env("MAX_LISTINGS_PER_SOURCE", 5_000, minimum=1),
        max_new_listings_per_refresh=_int_env("MAX_NEW_LISTINGS_PER_REFRESH", 10_000, minimum=1),
        # The corpus cap bounds every full-corpus read (the SQL scan in the
        # search and the vector scan in the store).
        max_corpus_listings=_int_env("MAX_CORPUS_LISTINGS", 50_000, minimum=1),
        # Embedding work per refresh. This is the knob that stops a flood of
        # unique fake listings from spending the provider's whole daily quota
        # on texts nobody will ever search for.
        max_embed_per_refresh=_int_env("MAX_EMBED_PER_REFRESH", 2_000, minimum=1),
        # The embedding cache is a permanent SQLite table; without a bound it
        # grows until the disk is full.
        max_cache_entries=_int_env("MAX_CACHE_ENTRIES", 50_000, minimum=1),
        # A 5 MB DOCX may expand to this much uncompressed. Beyond it the
        # upload is a zip bomb.
        max_upload_uncompressed_bytes=_int_env(
            "MAX_UPLOAD_UNCOMPRESSED_BYTES", 50 * 1024 * 1024, minimum=1024
        ),
        max_zip_entries=_int_env("MAX_ZIP_ENTRIES", 2_000, minimum=1),
        # A hostile board returning a 2 GB JSON body must not be buffered.
        max_response_bytes=_int_env("MAX_RESPONSE_BYTES", 8 * 1024 * 1024, minimum=1024),
        max_custom_fields=_int_env("MAX_CUSTOM_FIELDS", 50, minimum=0),
        max_custom_field_chars=_int_env("MAX_CUSTOM_FIELD_CHARS", 2_000, minimum=1),
        # 20,000 characters of description: far beyond a real posting, and
        # comfortably inside what the embedding model will read anyway.
        max_description_chars=_int_env("MAX_DESCRIPTION_CHARS", 20_000, minimum=100),
        max_title_chars=_int_env("MAX_TITLE_CHARS", 300, minimum=1),
        max_company_chars=_int_env("MAX_COMPANY_CHARS", 200, minimum=1),
        # The untrusted block in a prompt is capped so a huge listing cannot
        # blow the model's context or the bill.
        max_prompt_untrusted_chars=_int_env("MAX_PROMPT_UNTRUSTED_CHARS", 20_000, minimum=100),
    )


@lru_cache(maxsize=1)
def get_limits() -> SecurityLimits:
    """The process-wide limits (built once, then cached)."""
    return _build()


def reset_limits() -> None:
    """Drop the cached limits so the next call re-reads the environment.

    Tolerates a monkeypatched ``get_limits``: a test that replaces the
    function to supply its own values would otherwise break the reset and
    leave a stale cached value behind for the rest of the session.
    """
    cache_clear = getattr(get_limits, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()
