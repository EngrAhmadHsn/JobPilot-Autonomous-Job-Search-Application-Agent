"""Tests for the LLM resilience primitives (WS-10 · Phase B).

The limiter and the backoff are the two places where the LLM client spends
wall-clock time, so both are driven on a **fake clock** here: the suite
asserts on virtual time and never waits.
"""

from __future__ import annotations

import pytest

from src.llm.resilience import (
    SlidingWindowLimiter,
    backoff_delay,
    get_limiter,
    reset_limiters,
)
from tests.fixtures.llm_fakes import FakeClock


class TestSlidingWindowLimiter:
    def test_an_empty_window_lets_a_call_through_without_waiting(self) -> None:
        clock = FakeClock()
        limiter = SlidingWindowLimiter(10, 60.0, clock=clock.time, sleep=clock.sleep)
        assert limiter.acquire() == 0.0
        assert clock.sleeps == []

    def test_the_burst_is_allowed_up_to_the_limit(self) -> None:
        """Ten calls at RPM 10 fit in the window — a burst is not a failure."""
        clock = FakeClock()
        limiter = SlidingWindowLimiter(10, 60.0, clock=clock.time, sleep=clock.sleep)
        for _ in range(10):
            assert limiter.acquire() == 0.0
        assert clock.sleeps == []

    def test_the_call_past_the_limit_waits_for_the_window(self) -> None:
        clock = FakeClock()
        limiter = SlidingWindowLimiter(2, 60.0, clock=clock.time, sleep=clock.sleep)
        limiter.acquire()
        limiter.acquire()
        waited = limiter.acquire()
        assert waited == pytest.approx(60.0)
        assert clock.sleeps == [pytest.approx(60.0)]

    def test_thirty_calls_at_ten_per_minute_are_paced_to_the_budget(self) -> None:
        """The limiter's acceptance case: 30 calls, no provider 429.

        Thirty calls at ten per minute span two minutes of virtual time, and
        no 60-second window ever holds more than ten of them.
        """
        clock = FakeClock()
        limiter = SlidingWindowLimiter(10, 60.0, clock=clock.time, sleep=clock.sleep)

        for _ in range(30):
            limiter.acquire()

        assert clock.elapsed == pytest.approx(120.0, abs=1.0)
        # The window never holds more than the configured limit.
        assert limiter.calls_in_window <= 10

    def test_no_60_second_window_holds_more_than_the_limit(self) -> None:
        """The guarantee the limiter exists for.

        A token bucket would admit 19 calls in the first minute at a limit of
        10 — enough to trip the provider's own limit. The sliding window
        admits exactly 10.
        """
        clock = FakeClock()
        limiter = SlidingWindowLimiter(10, 60.0, clock=clock.time, sleep=clock.sleep)

        call_times: list[float] = []
        for _ in range(30):
            limiter.acquire()
            call_times.append(clock.now)

        for start in call_times:
            in_window = [t for t in call_times if start <= t < start + 60.0]
            assert len(in_window) <= 10

    def test_an_idle_window_is_reused(self) -> None:
        """After a minute of silence the budget is full again."""
        clock = FakeClock()
        limiter = SlidingWindowLimiter(2, 60.0, clock=clock.time, sleep=clock.sleep)
        limiter.acquire()
        limiter.acquire()
        clock.sleep(60.0)
        assert limiter.acquire() == 0.0
        assert clock.sleeps == [60.0]  # only the explicit idle jump

    def test_an_invalid_limiter_is_refused(self) -> None:
        with pytest.raises(ValueError):
            SlidingWindowLimiter(0, 60.0)
        with pytest.raises(ValueError):
            SlidingWindowLimiter(1, 0.0)


class TestBackoff:
    def test_the_schedule_is_one_then_four_seconds(self) -> None:
        """The documented schedule: 1 s, then 4 s, plus jitter."""
        assert backoff_delay(1, 1.0, jitter=lambda _lo, _hi: 0.0) == pytest.approx(1.0)
        assert backoff_delay(2, 1.0, jitter=lambda _lo, _hi: 0.0) == pytest.approx(4.0)

    def test_the_jitter_adds_at_most_half_the_base(self) -> None:
        delay = backoff_delay(1, 2.0, jitter=lambda lo, hi: hi)
        assert delay == pytest.approx(2.0 + 1.0)

    def test_the_third_retry_is_sixteen_seconds(self) -> None:
        assert backoff_delay(3, 1.0, jitter=lambda _lo, _hi: 0.0) == pytest.approx(16.0)

    def test_attempt_numbering_starts_at_one(self) -> None:
        with pytest.raises(ValueError):
            backoff_delay(0, 1.0)


class TestLimiterRegistry:
    def teardown_method(self) -> None:
        reset_limiters()

    def test_a_named_limiter_is_created_once_and_reused(self) -> None:
        first = get_limiter("llm-test", 10)
        second = get_limiter("llm-test", 10)
        assert first is second

    def test_different_names_are_different_limiters(self) -> None:
        assert get_limiter("a", 10) is not get_limiter("b", 10)

    def test_reset_drops_them(self) -> None:
        first = get_limiter("llm-test", 10)
        reset_limiters()
        assert get_limiter("llm-test", 10) is not first
