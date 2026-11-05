"""WS-18 · circuit breakers and the unified retry schedule.

Two properties matter and are tested directly:

- **A breaker is per provider.** One board's repeated failures must not
  disable another board, and a permanent error must not open a circuit at
  all (a bad request is not an outage).
- **A breaker is shared when the deployment runs more than one worker.**
  The database-backed store is exercised against a real SQLite file, not a
  mock.

The retry schedule is tested in ``test_llm_resilience.py``; here the
``Retry-After`` parsing and the job-board client's use of it are covered.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.jobs import http_client
from src.jobs.http_client import CircuitOpenError, guarded_get
from src.llm.client import LLMCircuitOpen, LLMClient, LLMUnavailable
from src.llm.resilience import (
    CLOSED,
    HALF_OPEN,
    OPEN,
    CircuitBreaker,
    CircuitRecord,
    breaker_snapshot,
    get_breaker,
    reset_breakers,
    retry_after_seconds,
)
from src.runs.circuit import DatabaseCircuitStore


class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class MemoryStore:
    def __init__(self) -> None:
        self.records: dict[str, CircuitRecord] = {}

    def load(self, name: str) -> CircuitRecord | None:
        return self.records.get(name)

    def save(self, name: str, record: CircuitRecord) -> None:
        self.records[name] = record


def _breaker(clock: FakeClock, **overrides) -> CircuitBreaker:
    return CircuitBreaker(
        "test-provider",
        failure_threshold=overrides.pop("failure_threshold", 3),
        recovery_seconds=overrides.pop("recovery_seconds", 30.0),
        clock=clock,
        **overrides,
    )


# -- the state machine --------------------------------------------------------


def test_a_closed_breaker_opens_on_the_threshold() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    assert breaker.state == CLOSED
    for _ in range(2):
        breaker.record_failure()
    assert breaker.state == CLOSED
    assert breaker.allow_request() is True
    breaker.record_failure()
    assert breaker.state == OPEN


def test_an_open_breaker_fails_fast() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    assert breaker.allow_request() is False
    assert breaker.retry_after() == pytest.approx(30.0)
    clock.advance(10)
    assert breaker.allow_request() is False


def test_the_circuit_probes_once_after_the_cooldown() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.advance(31)
    assert breaker.allow_request() is True  # the single probe
    assert breaker.state == HALF_OPEN
    assert breaker.allow_request() is False  # no stampede
    breaker.record_success()
    assert breaker.state == CLOSED
    assert breaker.allow_request() is True


def test_a_failed_probe_reopens_the_circuit() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.advance(31)
    assert breaker.allow_request() is True
    breaker.record_failure()
    assert breaker.state == OPEN
    assert breaker.allow_request() is False


def test_a_permanent_failure_never_opens_the_circuit() -> None:
    """A 400 or a bad key is the caller's problem, not a provider outage."""
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(20):
        breaker.record_failure(retryable=False)
    assert breaker.state == CLOSED
    assert breaker.allow_request() is True


def test_breakers_are_independent_per_provider() -> None:
    clock = FakeClock()
    first = CircuitBreaker("board-a", failure_threshold=2, clock=clock)
    second = CircuitBreaker("board-b", failure_threshold=2, clock=clock)
    first.record_failure()
    first.record_failure()
    assert first.state == OPEN
    assert second.state == CLOSED
    assert second.allow_request() is True


def test_success_resets_the_failure_count() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CLOSED


# -- shared state -------------------------------------------------------------


def test_shared_state_makes_one_processes_outage_visible_to_another() -> None:
    clock = FakeClock()
    store = MemoryStore()
    first = CircuitBreaker(
        "gemini", failure_threshold=2, recovery_seconds=30, store=store, clock=clock
    )
    first.record_failure()
    first.record_failure()
    assert first.state == OPEN
    assert store.records["gemini"].state == OPEN

    second = CircuitBreaker(
        "gemini", failure_threshold=2, recovery_seconds=30, store=store, clock=clock
    )
    assert second.allow_request() is False
    assert second.state == OPEN


def test_the_database_store_round_trips(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'breakers.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    store = DatabaseCircuitStore(factory)

    assert store.load("gemini") is None
    store.save(
        "gemini", CircuitRecord(state=OPEN, failure_count=3, opened_at_epoch=1_700_000_000.0)
    )
    record = store.load("gemini")
    assert record is not None
    assert record.state == OPEN
    assert record.failure_count == 3
    assert record.opened_at_epoch == pytest.approx(1_700_000_000.0)

    store.save("gemini", CircuitRecord(state=CLOSED, failure_count=0))
    assert store.load("gemini").state == CLOSED
    engine.dispose()


def test_the_registry_returns_one_breaker_per_name() -> None:
    reset_breakers()
    try:
        first = get_breaker("provider-x", failure_threshold=2)
        second = get_breaker("provider-x", failure_threshold=99)
        assert first is second
        assert first.failure_threshold == 2
        snapshot = breaker_snapshot()
        assert any(entry["name"] == "provider-x" for entry in snapshot)
    finally:
        reset_breakers()


# -- Retry-After --------------------------------------------------------------


def test_retry_after_parses_seconds_and_dates() -> None:
    assert retry_after_seconds("12") == 12.0
    assert retry_after_seconds("0") == 0.0
    assert retry_after_seconds(None) is None
    assert retry_after_seconds("") is None
    assert retry_after_seconds("definitely not a date") is None


@pytest.mark.asyncio
async def test_the_job_board_client_honours_retry_after(monkeypatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(http_client.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        http_client, "_getaddrinfo", lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={})

    breaker = CircuitBreaker("board:example.com", failure_threshold=10)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await guarded_get(
            client,
            "https://example.com/jobs",
            backoff_base=0.01,
            max_retries=1,
            breaker=breaker,
        )

    assert response.status_code == 200
    assert sleeps and sleeps[0] >= 7.0


@pytest.mark.asyncio
async def test_an_open_board_circuit_is_a_source_error(monkeypatch) -> None:
    monkeypatch.setattr(
        http_client, "_getaddrinfo", lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )
    breaker = CircuitBreaker("board:example.com", failure_threshold=1)
    breaker.record_failure()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200))
    ) as client:
        with pytest.raises(CircuitOpenError):
            await guarded_get(client, "https://example.com/jobs", breaker=breaker)


# -- the LLM client -----------------------------------------------------------


class FailingProvider:
    name = "fake-llm"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        raise LLMUnavailable("provider down")


def test_the_llm_client_fails_fast_once_the_circuit_opens() -> None:
    reset_breakers()
    try:
        provider = FailingProvider()
        client = LLMClient(
            provider="fake-llm",
            api_key="",
            model="model",
            temperature=0.0,
            max_retries=0,
            provider_instance=provider,
        )
        for _ in range(5):
            with pytest.raises(LLMUnavailable):
                client.generate_text("hi")
        calls_before = provider.calls

        with pytest.raises(LLMCircuitOpen):
            client.generate_text("hi")
        # The provider was not called at all: that is the point.
        assert provider.calls == calls_before
    finally:
        reset_breakers()


def test_a_permanent_llm_error_does_not_open_the_circuit() -> None:
    from src.llm.errors import LLMConfigError

    reset_breakers()
    try:

        class ConfigFailing:
            name = "fake-llm-config"

            def complete(self, request):
                raise LLMConfigError("bad key")

        client = LLMClient(
            provider="fake-llm-config",
            api_key="",
            model="model",
            temperature=0.0,
            max_retries=0,
            provider_instance=ConfigFailing(),
        )
        for _ in range(10):
            with pytest.raises(LLMConfigError):
                client.generate_text("hi")
        breaker = get_breaker("llm:fake-llm-config")
        assert breaker.state == CLOSED
    finally:
        reset_breakers()


def test_no_sleep_is_made_when_the_circuit_is_open(monkeypatch) -> None:
    """The breaker's whole value: an open circuit costs no wall-clock time."""
    reset_breakers()
    sleeps: list[float] = []
    try:
        provider = FailingProvider()
        client = LLMClient(
            provider="fake-llm",
            api_key="",
            model="model",
            temperature=0.0,
            max_retries=0,
            provider_instance=provider,
            sleep=sleeps.append,
        )
        for _ in range(5):
            with pytest.raises(LLMUnavailable):
                client.generate_text("hi")
        with pytest.raises(LLMCircuitOpen):
            client.generate_text("hi")
        assert sleeps == []
    finally:
        reset_breakers()
