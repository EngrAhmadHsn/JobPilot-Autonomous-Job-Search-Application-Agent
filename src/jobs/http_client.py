"""Guarded HTTP client for job-source adapters (WS-02 task 1).

Every outbound request made by the job-source layer goes through
:func:`guarded_get`, which enforces, in order:

1. **SSRF guard (SEC-11)** — the URL scheme must be ``http``/``https`` and
   every address the hostname resolves to must be public. Loopback, RFC 1918
   private, link-local (including cloud metadata ``169.254.169.254``),
   unique-local, unspecified, reserved, and IPv4-mapped-private addresses are
   rejected before any connection attempt. Unresolvable hostnames fail
   closed. Known limitation: the check runs before the request, so a DNS
   rebinding attack between check and connect is theoretically possible; the
   adapters additionally hard-code their own host allowlist constants, which
   bounds the reachable hosts to the three job-board API domains.
2. **Per-host rate limiting** — a :class:`HostRateLimiter` spaces requests
   to the same host at least ``settings.job_source_min_interval`` seconds
   apart (plan §28 politeness).
3. **Retries** — up to 2 retries on ``httpx.TransportError``, HTTP 429, and
   5xx with exponential backoff + jitter (hand-rolled, no ``tenacity`` per
   the no-unjustified-dependencies rule). Any other 4xx — and unexpected
   redirects, since the client never follows them — raises
   :class:`SourceError` immediately.

The adapter layer never fetches a URL that did not come from its own host
constants (Greenhouse calls only ever hit ``boards-api.greenhouse.io``, etc.).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import random
import socket
import time
from urllib.parse import urlparse

import httpx

from src.config.settings import get_settings

logger = logging.getLogger(__name__)

USER_AGENT = (
    "agentic-job-applier/0.1 (personal job-search agent; "
    "public board APIs only; contact via repository)"
)

_RETRYABLE_STATUS_START = 500


class SourceError(RuntimeError):
    """A job source could not be queried (network, HTTP, or timeout failure)."""


class SSRFBlockedError(SourceError):
    """A URL was refused by the SSRF guard before any request was made."""


# Indirection seam: tests monkeypatch this to stub DNS resolution instead of
# hitting real resolvers (fast, deterministic, no network).
_getaddrinfo = socket.getaddrinfo


def create_client(timeout: float | None = None) -> httpx.AsyncClient:
    """Create an AsyncClient configured for job-source calls.

    Timeouts come from ``settings.job_source_timeout``. Redirects are never
    followed: a redirect target would bypass the SSRF guard, so 3xx responses
    surface as :class:`SourceError` from :func:`guarded_get` instead.
    """
    if timeout is None:
        timeout = get_settings().job_source_timeout
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


def _is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when ``ip`` must never be contacted by the job-source layer.

    WS-12: this delegates to the one predicate in
    :mod:`src.security.allowlist` rather than keeping a second copy. The
    two copies had drifted — the allowlist's refused CGNAT
    (``100.64.0.0/10``) and multicast addresses, this one did not — and a
    blocklist with two versions of itself is only as strict as its weakest
    copy.
    """
    from src.security.allowlist import is_forbidden_ip

    return is_forbidden_ip(ip)


def assert_url_allowed(url: str) -> None:
    """Raise :class:`SSRFBlockedError` unless ``url`` is a public http(s) URL.

    Resolves the hostname with ``socket.getaddrinfo`` and checks every
    returned address, so a hostname that resolves to a public IP on one
    record but a private IP on another is still rejected.
    """
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise SSRFBlockedError(f"URL could not be parsed: {url!r}") from exc
    if parsed.scheme not in ("http", "https"):
        raise SSRFBlockedError(
            f"Scheme {parsed.scheme!r} is not allowed (only http/https): {url!r}"
        )
    host = parsed.hostname
    if not host:
        raise SSRFBlockedError(f"URL has no hostname: {url!r}")
    try:
        addr_infos = _getaddrinfo(host, None)
    except socket.gaierror as exc:
        # Fail closed: an unresolvable host cannot be proven public.
        raise SSRFBlockedError(f"Hostname {host!r} does not resolve: {url!r}") from exc
    for addr_info in addr_infos:
        ip = ipaddress.ip_address(addr_info[4][0])
        if _is_forbidden_ip(ip):
            raise SSRFBlockedError(f"Hostname {host!r} resolves to forbidden address {ip}: {url!r}")


class HostRateLimiter:
    """Spaces requests per host at least ``min_interval`` seconds apart.

    One asyncio lock per host serializes waiters; the wait happens inside the
    lock so concurrent callers queue instead of stampeding the host.
    """

    def __init__(self, min_interval: float) -> None:
        self.min_interval = max(0.0, min_interval)
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}

    async def acquire(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            last = self._last_request.get(host)
            if last is not None:
                remaining = self.min_interval - (now - last)
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last_request[host] = time.monotonic()


_default_limiter: HostRateLimiter | None = None


def get_default_limiter() -> HostRateLimiter:
    """Process-wide limiter built from ``settings.job_source_min_interval``."""
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = HostRateLimiter(get_settings().job_source_min_interval)
    return _default_limiter


def reset_default_limiter() -> None:
    """Drop the process-wide limiter (next use rebuilds it from settings)."""
    global _default_limiter
    _default_limiter = None


def _backoff_delay(attempt: int, base: float) -> float:
    """Exponential backoff with full jitter: base * 2^(attempt-1) + jitter."""
    return base * (2 ** (attempt - 1)) + random.uniform(0, base / 2)


def _assert_response_size(response: httpx.Response, url: str) -> None:
    """Refuse a response whose body is larger than the cap.

    WS-12: a job board is untrusted input, and ``client.get`` buffers the
    whole body in memory. A board that returns a 2 GB JSON body would
    exhaust the process before a single listing was parsed. The declared
    ``Content-Length`` is checked first (the cheap case); the body is
    counted as well, so a response that omits or lies about its length is
    still bounded.
    """
    from src.security.limits import get_limits

    cap = get_limits().max_response_bytes
    declared = response.headers.get("content-length")
    if declared is not None:
        try:
            declared_size = int(declared)
        except ValueError:
            declared_size = None
        if declared_size is not None and declared_size > cap:
            raise SourceError(f"GET {url} declared {declared_size} bytes, over the {cap} byte cap")
    actual = len(response.content or b"")
    if actual > cap:
        raise SourceError(f"GET {url} returned {actual} bytes, over the {cap} byte cap")


async def guarded_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    limiter: HostRateLimiter | None = None,
    max_retries: int = 2,
    backoff_base: float = 0.5,
) -> httpx.Response:
    """SSRF-checked, rate-limited, retrying GET. Returns a 2xx response.

    The response body is bounded by ``max_response_bytes``: a board that
    returns a huge body must not be able to exhaust the process's memory
    before a single listing is parsed.

    Raises:
        SSRFBlockedError: URL failed the SSRF guard (before any request).
        SourceError: non-retryable HTTP status, redirects, a response over
            the size cap, or retries exhausted for transport errors / 429 / 5xx.
    """
    assert_url_allowed(url)
    active_limiter = limiter or get_default_limiter()
    host = urlparse(url).hostname or ""
    attempt = 0
    while True:
        await active_limiter.acquire(host)
        try:
            response = await client.get(url)
        except httpx.TransportError as exc:
            if attempt >= max_retries:
                raise SourceError(f"GET {url} failed after {attempt + 1} attempts: {exc}") from exc
            attempt += 1
            delay = _backoff_delay(attempt, backoff_base)
            logger.warning(
                "Transport error on %s (attempt %d), retrying in %.2fs", url, attempt, delay
            )
            await asyncio.sleep(delay)
            continue
        if 200 <= response.status_code < 300:
            _assert_response_size(response, url)
            return response
        if response.status_code == 429 or response.status_code >= _RETRYABLE_STATUS_START:
            if attempt >= max_retries:
                raise SourceError(
                    f"GET {url} returned {response.status_code} after {attempt + 1} attempts"
                )
            attempt += 1
            delay = _backoff_delay(attempt, backoff_base)
            logger.warning(
                "HTTP %d on %s (attempt %d), retrying in %.2fs",
                response.status_code,
                url,
                attempt,
                delay,
            )
            await asyncio.sleep(delay)
            continue
        # Other 4xx, and 3xx (the client never follows redirects): fail now.
        raise SourceError(f"GET {url} returned non-retryable HTTP {response.status_code}")
