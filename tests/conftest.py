"""Shared test-suite fixtures.

The autouse ``fast_rate_limiter`` fixture replaces the process-wide job-source
rate limiter with a zero-interval one: politeness spacing (1 s/host by
default) is a live-network concern, and no test talks to a live network. Tests
that exercise the limiter itself inject their own explicit limiter.
"""

from __future__ import annotations

import pytest

from src.jobs.http_client import HostRateLimiter, get_default_limiter, reset_default_limiter


@pytest.fixture(autouse=True)
def fast_rate_limiter(monkeypatch):
    monkeypatch.setattr(
        "src.jobs.http_client.get_default_limiter", lambda: HostRateLimiter(min_interval=0.0)
    )
    yield
    reset_default_limiter()
    assert get_default_limiter() is not None  # rebuildable after reset
