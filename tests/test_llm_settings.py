"""Tests for the LLM resilience settings (WS-10 · Phase A).

The three knobs added by WS-10 decide how long a provider call may hang, how
many calls per minute are allowed, and how many times a retryable failure is
retried. A typo in any of them must fail at startup — not silently at the
first call, in production, in the middle of a job search.
"""

from __future__ import annotations

import pytest

from src.config.settings import Settings


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """Build a Settings instance with the given LLM environment overrides."""
    for key in ("LLM_TIMEOUT", "LLM_MAX_RPM", "LLM_MAX_RETRIES"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings()


def test_defaults_are_sane(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)
    assert settings.llm_timeout == 60.0
    assert settings.llm_max_rpm == 10
    assert settings.llm_max_retries == 2


def test_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, LLM_TIMEOUT="12.5", LLM_MAX_RPM="3", LLM_MAX_RETRIES="0")
    assert settings.llm_timeout == 12.5
    assert settings.llm_max_rpm == 3
    assert settings.llm_max_retries == 0


@pytest.mark.parametrize("value", ["0", "-1"])
def test_a_non_positive_timeout_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    with pytest.raises(RuntimeError, match="LLM_TIMEOUT"):
        _settings(monkeypatch, LLM_TIMEOUT=value)


def test_a_zero_rpm_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """An RPM of zero would mean "never call the provider" — a typo, not a plan."""
    with pytest.raises(RuntimeError, match="LLM_MAX_RPM"):
        _settings(monkeypatch, LLM_MAX_RPM="0")


def test_a_negative_retry_count_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RuntimeError, match="LLM_MAX_RETRIES"):
        _settings(monkeypatch, LLM_MAX_RETRIES="-1")
