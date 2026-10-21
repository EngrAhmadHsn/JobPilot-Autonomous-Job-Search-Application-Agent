"""Per-client rate limiting for the API (WS-12).

The API has no authentication, so it has no way to tell one operator from a
flood. Rate limiting is the control that keeps the difference between "a
script hammered the refresh endpoint" and "the refresh endpoint melted the
process" in the *request* dimension; every other limit in
:mod:`src.security.limits` bounds what one accepted request may cost.

Two properties matter as much as the limit itself:

**The limiter's own memory is bounded.** A limiter that stores a bucket per
client IP is itself a denial-of-service target: an attacker with access to
many source addresses fills the bucket table until the process is out of
memory. The table is therefore capped, and the least-recently-used bucket is
evicted when the cap is reached. Eviction costs the attacker their limit
only for as long as it takes to re-flood, and it costs the process nothing.

**The key is not attacker-controlled.** The client address comes from the
transport, never from a header. ``X-Forwarded-For`` is trivially forged, so
trusting it here would let an attacker mint a fresh budget per request by
inventing a new address. When the deployment sits behind a reverse proxy,
the proxy is the client for every request — which is why the limit must be
set to a value the proxy can serve, and why the proxy's own limit is the
real first line of defence.

The limiter is deterministic and dependency-free: the clock is an argument so
the tests run on virtual time and cost no wall-clock delay.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable

__all__ = ["RateLimitDecision", "RateLimiter", "client_address"]


class RateLimitDecision:
    """The outcome of one rate-limit check."""

    __slots__ = ("allowed", "limit", "remaining", "retry_after")

    def __init__(self, *, allowed: bool, limit: int, remaining: int, retry_after: float) -> None:
        self.allowed = allowed
        self.limit = limit
        self.remaining = remaining
        self.retry_after = retry_after

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"RateLimitDecision(allowed={self.allowed}, limit={self.limit}, "
            f"remaining={self.remaining}, retry_after={self.retry_after:.2f})"
        )


def client_address(request) -> str:
    """The transport-level client address of *request*.

    Deliberately the socket peer and never a forwarded header: a forwarded
    header is attacker-supplied data, and a limit keyed on attacker-supplied
    data is no limit at all. Returns ``"unknown"`` when the transport does
    not expose a peer (a test double, for instance).
    """
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    if not host:
        return "unknown"
    return str(host)


class RateLimiter:
    """At most ``max_requests`` per client in any ``window_seconds`` window.

    The guarantee is exactly "no more than ``max_requests`` requests from one
    client in any rolling ``window_seconds`` window" — the shape an abuse
    limit has.

    The bucket table is capped at ``max_clients``. When it is full, the
    least-recently-used bucket is evicted to make room. That keeps the
    limiter's memory bounded no matter how many distinct addresses the
    traffic comes from.

    Args:
        max_requests: Requests allowed per client per window.
        window_seconds: The rolling window length.
        max_clients: Maximum number of tracked clients.
        clock: Monotonic time source (injectable for the tests).
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: float = 60.0,
        *,
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_requests < 1:
            raise ValueError("a rate limiter needs a limit of at least 1 request")
        if window_seconds <= 0:
            raise ValueError("a rate limiter needs a positive window")
        if max_clients < 1:
            raise ValueError("a rate limiter needs to track at least 1 client")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._clock = clock
        # An OrderedDict is the LRU: the most recently touched bucket is last,
        # so eviction takes the first key.
        self._buckets: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def _prune(self, bucket: list[float], now: float) -> None:
        """Drop the timestamps that have fallen out of the window."""
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.pop(0)

    def check(self, key: str) -> RateLimitDecision:
        """Record a request from *key* and report whether it is allowed.

        A rejected request does **not** consume budget: only accepted
        requests count, so a client that keeps hammering past the limit
        recovers the moment the window slides rather than being punished
        for longer than the limit states.
        """
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self.max_clients:
                    self._buckets.popitem(last=False)
                bucket = []
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)

            self._prune(bucket, now)
            if len(bucket) >= self.max_requests:
                # The oldest request in the window decides when one frees up.
                retry_after = max(0.0, bucket[0] + self.window_seconds - now)
                return RateLimitDecision(
                    allowed=False,
                    limit=self.max_requests,
                    remaining=0,
                    retry_after=retry_after,
                )
            bucket.append(now)
            return RateLimitDecision(
                allowed=True,
                limit=self.max_requests,
                remaining=self.max_requests - len(bucket),
                retry_after=0.0,
            )

    def tracked_clients(self) -> int:
        """How many clients are currently tracked (bounded by ``max_clients``)."""
        with self._lock:
            return len(self._buckets)

    def reset(self) -> None:
        """Forget every tracked client."""
        with self._lock:
            self._buckets.clear()
