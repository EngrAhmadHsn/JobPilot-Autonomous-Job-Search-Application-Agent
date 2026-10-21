"""The LLM error taxonomy (WS-10).

Every provider failure — the Gemini SDK, an HTTP status from an
OpenAI-compatible endpoint, a transport error — is mapped onto one of these
classes, so the client can decide *what to do* about a failure without
pattern-matching on a provider's message. The rule each class encodes:

- :class:`LLMConfigError` — the configuration is wrong. Retrying cannot help.
- :class:`LLMRateLimited` — the provider is throttling. Retry with backoff.
- :class:`LLMDailyQuotaExhausted` — today's budget is gone. **Not** retryable
  in seconds; the caller should stop and resume after the daily reset.
- :class:`LLMUnavailable` / :class:`LLMTimeout` — the provider is briefly
  unreachable. Retry with backoff.
- :class:`LLMInvalidOutput` — the answer broke its contract. Repair once
  locally, then give up.
- :class:`LLMError` — anything else. Do not guess; do not retry.

The hierarchy lives in its own module so the provider adapters can use it
without importing the client facade (which imports them). The facade
re-exports every name, so ``from src.llm.client import LLMRateLimited`` keeps
working for the rest of the repository.
"""

from __future__ import annotations

__all__ = [
    "LLMConfigError",
    "LLMDailyQuotaExhausted",
    "LLMError",
    "LLMInvalidOutput",
    "LLMRateLimited",
    "LLMTimeout",
    "LLMUnavailable",
    "classify_provider_error",
    "scrub_secret",
]


class LLMError(RuntimeError):
    """Raised when the LLM provider is unconfigured or a call fails."""


class LLMConfigError(LLMError):
    """Unconfigured or unsupported provider — do not retry."""


class LLMRateLimited(LLMError):
    """429 / quota exhausted — retryable with backoff."""


class LLMDailyQuotaExhausted(LLMRateLimited):
    """The per-DAY quota is spent (distinct from per-minute throttling).

    Still retryable — tomorrow, after the daily window resets. Callers use
    the subclass to stop cleanly and resume the next day instead of
    retry-spamming until reset (FU-4).
    """


class LLMUnavailable(LLMError):
    """5xx / transport failure — retryable with backoff."""


class LLMTimeout(LLMUnavailable):
    """The call exceeded its timeout — retryable, and worth distinguishing."""


class LLMInvalidOutput(LLMError):
    """Provider returned output violating the contract (e.g. bad JSON)."""


# Tokens identifying retryable provider failures. HTTP status codes surface in
# SDK exception strings in varying forms (code, code_desc, gRPC status), so we
# classify on message content — never on anything request-related.
_RATE_LIMIT_TOKENS = (
    "429",
    "quota",
    "rate limit",
    "rate_limit",
    "resource_exhausted",
    "too many requests",
)
# A 429 naming the per-day quota id means the whole day's budget is spent —
# checked before the generic rate-limit tokens (both match "quota").
_DAILY_QUOTA_TOKENS = ("perday", "per_day", "per day")
# A timeout is retryable like a 5xx, but worth naming: it is the one failure
# a longer timeout would actually fix.
_TIMEOUT_TOKENS = ("timeout", "timed out", "deadline exceeded")
_UNAVAILABLE_TOKENS = (
    "500",
    "502",
    "503",
    "504",
    "unavailable",
    "deadline",
    "timeout",
    "connection",
    "internal",
)


def scrub_secret(text: str, secret: str | None) -> str:
    """Remove ``secret`` from ``text`` if it appears.

    A provider's error message comes from the provider, and the provider does
    not echo the request — but "the provider would not echo it" is a hope, not
    a guarantee, and a leaked key in an exception message ends up in a log
    file. The key is therefore removed from every message the client raises.
    """
    if not secret:
        return text
    return text.replace(secret, "<redacted>")


def classify_provider_error(exc: Exception, *, secret: str | None = None) -> LLMError:
    """Map a provider SDK exception onto the retryable-error taxonomy.

    The key is never included: exception text comes from the SDK, which does
    not echo request contents, and we add no request data of our own. Quota
    metadata (e.g. ``GenerateRequestsPerDay…`` quota ids in Google SDK 429
    details) is provider-generated, not request data, and drives the
    daily-vs-minute split the embedding budget relies on (FU-4).

    Args:
        exc: The provider's exception.
        secret: The API key, removed from the message if the provider echoed
            it. Pass it whenever one is known.
    """
    text = f"{type(exc).__name__}: {exc}"
    text = scrub_secret(text, secret)
    lowered = text.lower()
    if any(token in lowered for token in _DAILY_QUOTA_TOKENS):
        return LLMDailyQuotaExhausted(f"LLM daily quota exhausted: {text}")
    if any(token in lowered for token in _RATE_LIMIT_TOKENS):
        return LLMRateLimited(f"LLM rate limited: {text}")
    if any(token in lowered for token in _TIMEOUT_TOKENS):
        return LLMTimeout(f"LLM call timed out: {text}")
    if any(token in lowered for token in _UNAVAILABLE_TOKENS):
        return LLMUnavailable(f"LLM unavailable: {text}")
    return LLMError(f"LLM call failed: {text}")
