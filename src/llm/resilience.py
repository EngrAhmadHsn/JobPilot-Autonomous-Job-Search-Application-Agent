"""Resilience primitives for the LLM client (WS-10).

Two hand-rolled pieces, no third-party dependency — the workspace rule is "no
dependencies without clear justification", and both of these are a dozen
lines each:

- :class:`SlidingWindowLimiter` — a rate limiter that **paces** instead of
  refusing. The free tier throttles; a client that sleeps is a client that
  keeps working.
- :func:`backoff_delay` — the exponential backoff schedule for a retry.

Every timing dependency is an argument (clock, sleep, jitter) so the tests
drive the whole thing on virtual time and cost no wall-clock delay.
"""

from __future__ import annotations

import random
import time
from collections import deque
from collections.abc import Callable

__all__ = [
    "SlidingWindowLimiter",
    "backoff_delay",
    "get_limiter",
    "reset_limiters",
]


class SlidingWindowLimiter:
    """At most ``max_calls`` in any rolling ``window_seconds`` window.

    The limiter keeps the timestamps of the recent calls; a call that would
    make the window hold more than ``max_calls`` entries waits until the
    oldest one falls out of the window. The guarantee is therefore exactly
    "no more than ``max_calls`` calls in any window of ``window_seconds``",
    which is the shape a provider's per-minute limit has.

    A token bucket would **not** give that guarantee. A bucket of capacity
    ``R`` refilling at ``R / 60`` tokens per second admits up to
    ``R + R/60`` calls in a 60-second window — 19 calls at ``R = 10`` —
    which is enough to trip the very limit the limiter is there to respect.
    The sliding window admits 10.

    :meth:`acquire` never raises and never refuses a call — it sleeps until
    the window has room and reports how long it waited. A rate limit is a
    pacing problem, not an error: failing the call would defeat the purpose
    of a limiter.
    """

    def __init__(
        self,
        max_calls: int,
        window_seconds: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_calls < 1:
            raise ValueError("a rate limiter needs a limit of at least 1 call")
        if window_seconds <= 0:
            raise ValueError("a rate limiter needs a positive window")
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()

    @property
    def calls_in_window(self) -> int:
        """The calls currently inside the window."""
        self._prune(self._clock())
        return len(self._calls)

    def _prune(self, now: float) -> None:
        """Drop the calls that have fallen out of the window."""
        while self._calls and (now - self._calls[0]) >= self.window_seconds:
            self._calls.popleft()

    def acquire(self) -> float:
        """Take a slot in the window, sleeping if the window is full.

        Returns:
            The number of seconds waited (0.0 when the window had room).
        """
        now = self._clock()
        self._prune(now)
        waited = 0.0
        if len(self._calls) >= self.max_calls:
            waited = self.window_seconds - (now - self._calls[0])
            if waited > 0:
                self._sleep(waited)
                now = self._clock()
                self._prune(now)
        self._calls.append(now)
        return waited


def backoff_delay(
    attempt: int,
    base: float,
    jitter: Callable[[float, float], float] = random.uniform,
) -> float:
    """The delay before retry number ``attempt`` (1 is the first retry).

    The schedule is ``base * 4 ** (attempt - 1)`` plus a jitter of up to half
    the base — with ``base = 1.0`` the two retries of a three-attempt call
    wait 1.0–1.5 s and 4.0–4.5 s. The jitter keeps a fleet of workers from
    retrying in lockstep; the source is injectable so a test can pin the
    schedule to exact values.
    """
    if attempt < 1:
        raise ValueError("attempt numbering starts at 1")
    return base * (4 ** (attempt - 1)) + jitter(0.0, base / 2)


# The process-wide limiters. The LLM client and the Gemini embedding path
# meter DIFFERENT provider quotas (Gemini bills the embedding model and the
# generation model separately), so they never share a limiter — but they share
# this one registry, so a limiter is created once per process and every
# caller of a given name paces against the same budget.
_limiters: dict[str, SlidingWindowLimiter] = {}


def get_limiter(
    name: str,
    max_calls: int,
    window_seconds: float = 60.0,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> SlidingWindowLimiter:
    """The process-wide limiter called ``name``, created on first use.

    The first creation wins: a limiter keeps the clock and the sleep it was
    built with, so a process does not end up with two limiters of the same
    name metering the same budget differently. ``reset_limiters()`` drops
    them (the tests use it).
    """
    limiter = _limiters.get(name)
    if limiter is None:
        limiter = SlidingWindowLimiter(max_calls, window_seconds, clock=clock, sleep=sleep)
        _limiters[name] = limiter
    return limiter


def reset_limiters() -> None:
    """Drop every process-wide limiter (the next use rebuilds them)."""
    _limiters.clear()
