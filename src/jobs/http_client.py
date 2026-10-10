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
    """True when ``ip`` must never be contacted by the job-source layer."""
    # An IPv4-mapped IPv6 address (::ffff:10.0.0.1) must be judged by its
    # embedded IPv4 address, or the private v4 ranges could be smuggled in.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_forbidden_ip(ip.ipv4_mapped)
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_reserved:
        return True
    if isinstance(ip, ipaddress.IPv4Address):
        return ip.is_private  # RFC 1918: 10/8, 172.16/12, 192.168/16
    return ip.is_private  # IPv6 unique-local fc00::/7 and friends


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


async def guarded_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    limiter: HostRateLimiter | None = None,
    max_retries: int = 2,
    backoff_base: float = 0.5,
) -> httpx.Response:
    """SSRF-checked, rate-limited, retrying GET. Returns a 2xx response.

    Raises:
        SSRFBlockedError: URL failed the SSRF guard (before any request).
        SourceError: non-retryable HTTP status, redirects, or retries
            exhausted for transport errors / 429 / 5xx.
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
