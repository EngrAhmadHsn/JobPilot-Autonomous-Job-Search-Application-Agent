"""Fakes for the LLM client tests (WS-10).

Two things every LLM test needs and neither may take from the network or the
wall clock:

- a **fake clock** whose ``sleep`` advances virtual time, so the rate limiter
  and the backoff can be asserted on without the suite ever waiting;
- a **fake Gemini client** that records the request it was handed, so a test
  can prove what actually reached the provider (the temperature, the timeout,
  the response format) instead of trusting the code that built it.

The openai-compatible provider needs no fake of its own — it speaks HTTP, and
the tests drive it through ``httpx.MockTransport``, the same pattern the
job-source adapters use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class FakeClock:
    """A monotonic clock whose ``sleep`` advances virtual time.

    The elapsed time is the sum of the sleeps, so a test can assert "this call
    waited 6 seconds" without the suite spending 6 seconds.
    """

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    @property
    def elapsed(self) -> float:
        """The total virtual time spent sleeping."""
        return sum(self.sleeps)


@dataclass
class FakeUsage:
    """A stand-in for the SDK's ``Usage`` object."""

    total_tokens: int | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None


@dataclass
class FakeInteraction:
    """A stand-in for an ``interactions.Interaction`` response."""

    output_text: str = ""
    usage: FakeUsage | None = None


@dataclass
class FakeGeminiClient:
    """A fake ``genai.Client`` that records the requests it receives.

    ``outcomes`` is the script: each element is either a response object to
    return or an exception to raise. The last element is repeated once the
    script runs out, so a test only has to spell out the interesting part.
    """

    outcomes: list[Any] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.interactions = _FakeInteractions(self)

    @property
    def call_count(self) -> int:
        return len(self.requests)


class _FakeInteractions:
    """The ``client.interactions`` namespace of the fake client."""

    def __init__(self, client: FakeGeminiClient) -> None:
        self._client = client

    def create(self, **kwargs: Any) -> Any:
        self._client.requests.append(kwargs)
        index = len(self._client.requests) - 1
        outcomes = self._client.outcomes
        if not outcomes:
            return FakeInteraction(output_text="")
        outcome = outcomes[min(index, len(outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def no_jitter(_low: float, _high: float) -> float:
    """A jitter source that adds nothing — the backoff schedule, unpinned."""
    return 0.0
