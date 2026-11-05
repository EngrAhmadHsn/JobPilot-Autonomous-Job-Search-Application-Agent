"""Resilience primitives shared by every provider call (WS-10 · WS-18).

Three hand-rolled pieces, no third-party dependency — the workspace rule is
"no dependencies without clear justification", and each of these is small:

- :class:`SlidingWindowLimiter` — a rate limiter that **paces** instead of
  refusing. The free tier throttles; a client that sleeps is a client that
  keeps working.
- :func:`backoff_delay` / :class:`RetryPolicy` — **one** exponential backoff
  schedule for every retry in the system. WS-18 unified the two that had
  drifted apart: the LLM client multiplied by four and the job-board client
  by two. The conventional 1×, 2×, 4× schedule now applies to both, the
  delay is capped, jitter is added, and a provider's ``Retry-After`` is
  honoured.
- :class:`CircuitBreaker` — CLOSED/OPEN/HALF_OPEN, with an optional durable
  store so several worker processes respect the same provider outage.

Every timing dependency is an argument (clock, sleep, jitter) so the tests
drive the whole thing on virtual time and cost no wall-clock delay.
"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Protocol

__all__ = [
    "CLOSED",
    "HALF_OPEN",
    "OPEN",
    "CircuitBreaker",
    "CircuitOpen",
    "CircuitRecord",
    "CircuitStore",
    "RetryPolicy",
    "SlidingWindowLimiter",
    "backoff_delay",
    "breaker_snapshot",
    "get_breaker",
    "get_limiter",
    "reset_breakers",
    "reset_limiters",
    "retry_after_seconds",
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
    *,
    max_delay: float | None = None,
    multiplier: float = 2.0,
) -> float:
    """The delay before retry number ``attempt`` (1 is the first retry).

    **One schedule for the whole system.** Before WS-18 the LLM client used
    ``base * 4 ** (attempt - 1)`` while the job-board client used
    ``base * 2 ** (attempt - 1)``; two copies of "exponential backoff" with
    different curves is two policies pretending to be one. The conventional
    schedule is 1×, 2×, 4× — with ``base = 1.0`` the two retries of a
    three-attempt call wait 1.0–1.5 s and 2.0–2.5 s.

    The jitter keeps a fleet of workers from retrying in lockstep; the source
    is injectable so a test can pin the schedule to exact values. ``max_delay``
    caps the result, including a provider's own ``Retry-After`` (which would
    otherwise park a worker for hours).
    """
    if attempt < 1:
        raise ValueError("attempt numbering starts at 1")
    delay = base * (multiplier ** (attempt - 1)) + jitter(0.0, base / 2)
    if max_delay is not None:
        delay = min(delay, max_delay)
    return delay


@dataclass(frozen=True)
class RetryPolicy:
    """The retry contract, in one place.

    ``max_attempts`` counts the **total** attempts (not the retries after the
    first), so the default of 3 means two retries. A provider's
    ``Retry-After`` is honoured but capped by ``max_delay``: a work item that
    needs to wait longer belongs in ``RETRY_WAIT``, not in a sleeping worker.
    """

    max_attempts: int = 3
    base: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0

    def delay(
        self,
        attempt: int,
        *,
        retry_after: float | None = None,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> float:
        """The delay before retry *attempt* (1-based)."""
        delay = backoff_delay(
            attempt,
            self.base,
            jitter,
            multiplier=self.multiplier,
            max_delay=self.max_delay,
        )
        if retry_after is not None:
            delay = min(max(delay, retry_after), self.max_delay)
        return delay


def retry_after_seconds(header: str | None) -> float | None:
    """Parse a ``Retry-After`` header (seconds or an HTTP date).

    Returns ``None`` when the header is absent or unparseable. A negative
    value is clamped to zero: a date in the past means "now".
    """
    if not header:
        return None
    raw = header.strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - time.time())


# -- circuit breakers ---------------------------------------------------------

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


class CircuitOpen(RuntimeError):
    """The provider is being skipped while its circuit is open."""

    def __init__(self, name: str, *, retry_after: float | None = None) -> None:
        super().__init__(f"The circuit for {name!r} is open; failing fast.")
        self.name = name
        self.retry_after = retry_after


@dataclass(frozen=True)
class CircuitRecord:
    """The durable part of a breaker's state.

    ``opened_at_epoch`` is a wall-clock epoch second, which is what makes the
    cooldown meaningful across processes. The in-memory path uses the
    injectable clock instead.
    """

    state: str
    failure_count: int
    opened_at_epoch: float | None = None


class CircuitStore(Protocol):
    """Where a breaker keeps its shared state (optional)."""

    def load(self, name: str) -> CircuitRecord | None: ...

    def save(self, name: str, record: CircuitRecord) -> None: ...


class CircuitBreaker:
    """A three-state breaker around one downstream provider.

    - **CLOSED** — calls pass. Consecutive *retryable* failures increment a
      counter; reaching ``failure_threshold`` opens the circuit.
    - **OPEN** — calls fail fast. After ``recovery_seconds`` the breaker
      moves to HALF_OPEN and allows exactly one probe.
    - **HALF_OPEN** — one probe is in flight. A success closes; a failure
      reopens.

    A **permanent** failure (a 400, an authorization failure, a model
    mismatch) never opens the circuit: retrying it cannot help, and opening
    the circuit would hide a configuration error behind a "provider down"
    message. Permanent errors are the caller's problem, not the provider's.
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        recovery_seconds: float = 60.0,
        store: CircuitStore | None = None,
        clock: Callable[[], float] = time.time,
        sync_interval: float = 2.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("a circuit breaker needs a failure threshold of at least 1")
        if recovery_seconds <= 0:
            raise ValueError("a circuit breaker needs a positive recovery window")
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._store = store
        self._clock = clock
        self._sync_interval = max(0.0, sync_interval)
        self._state = CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._last_sync = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            self._sync()
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    def _sync(self) -> None:
        """Read shared state, at most once per ``sync_interval``."""
        if self._store is None:
            return
        now = self._clock()
        if now - self._last_sync < self._sync_interval:
            return
        self._last_sync = now
        try:
            record = self._store.load(self.name)
        except Exception:  # noqa: BLE001 - shared state is best-effort
            return
        if record is None:
            return
        self._state = record.state if record.state in (CLOSED, OPEN, HALF_OPEN) else CLOSED
        self._failure_count = int(record.failure_count)
        self._opened_at = record.opened_at_epoch

    def _persist(self) -> None:
        if self._store is None:
            return
        try:
            self._store.save(
                self.name,
                CircuitRecord(
                    state=self._state,
                    failure_count=self._failure_count,
                    opened_at_epoch=self._opened_at,
                ),
            )
        except Exception:  # noqa: BLE001 - a breaker must not fail the call
            return

    def _open(self) -> None:
        self._state = OPEN
        self._opened_at = self._clock()
        self._probe_in_flight = False
        self._persist()

    def allow_request(self) -> bool:
        """May a call proceed now? Never raises."""
        with self._lock:
            self._sync()
            if self._state == CLOSED:
                return True
            if self._state == OPEN:
                now = self._clock()
                if self._opened_at is not None and now - self._opened_at >= self.recovery_seconds:
                    self._state = HALF_OPEN
                    self._probe_in_flight = True
                    self._persist()
                    return True
                return False
            # HALF_OPEN: exactly one probe at a time.
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True

    def retry_after(self) -> float | None:
        """Seconds until the open circuit admits a probe, if it is open."""
        with self._lock:
            if self._state != OPEN or self._opened_at is None:
                return None
            return max(0.0, self.recovery_seconds - (self._clock() - self._opened_at))

    def record_success(self) -> None:
        with self._lock:
            changed = self._state != CLOSED or self._failure_count
            self._state = CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._probe_in_flight = False
            if changed:
                self._persist()

    def record_failure(self, *, retryable: bool = True) -> None:
        """Count a failure. A permanent failure leaves the state untouched."""
        if not retryable:
            return
        with self._lock:
            if self._state == HALF_OPEN:
                self._failure_count += 1
                self._open()
                return
            if self._state == OPEN:
                return
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._open()
            else:
                self._persist()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state,
                "failure_count": self._failure_count,
                "retry_after_seconds": (
                    round(max(0.0, self.recovery_seconds - (self._clock() - self._opened_at)), 3)
                    if self._state == OPEN and self._opened_at is not None
                    else None
                ),
            }


# -- registries ---------------------------------------------------------------

_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def _shared_store() -> CircuitStore | None:
    """The database-backed store, when the deployment asks for sharing."""
    try:
        from src.config.settings import get_settings

        if not get_settings().circuit_shared_state:
            return None
        from src.runs.circuit import DatabaseCircuitStore

        return DatabaseCircuitStore()
    except Exception:  # noqa: BLE001 - in-memory is a valid degradation
        return None


def get_breaker(
    name: str,
    *,
    failure_threshold: int | None = None,
    recovery_seconds: float | None = None,
    store: CircuitStore | None = None,
    clock: Callable[[], float] = time.time,
) -> CircuitBreaker:
    """The process-wide breaker called ``name``, created on first use.

    The first creation wins, so a process does not end up with two breakers
    of the same name disagreeing about a provider. The settings supply the
    threshold and the recovery window; the database-backed store is used when
    ``CIRCUIT_SHARED_STATE`` is on.
    """
    breaker = _breakers.get(name)
    if breaker is not None:
        return breaker
    with _breakers_lock:
        breaker = _breakers.get(name)
        if breaker is not None:
            return breaker
        from src.config.settings import get_settings

        settings = get_settings()
        breaker = CircuitBreaker(
            name,
            failure_threshold=(
                settings.circuit_failure_threshold
                if failure_threshold is None
                else failure_threshold
            ),
            recovery_seconds=(
                settings.circuit_recovery_seconds if recovery_seconds is None else recovery_seconds
            ),
            store=store if store is not None else _shared_store(),
            clock=clock,
        )
        _breakers[name] = breaker
        return breaker


def reset_breakers() -> None:
    """Drop every process-wide breaker (the next use rebuilds them)."""
    with _breakers_lock:
        _breakers.clear()


def breaker_snapshot() -> list[dict]:
    """Every known breaker's state, for the health/metrics endpoints."""
    with _breakers_lock:
        breakers = list(_breakers.values())
    return [breaker.snapshot() for breaker in breakers]


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
