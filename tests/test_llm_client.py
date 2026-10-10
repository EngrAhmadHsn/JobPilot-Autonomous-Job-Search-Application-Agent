"""Tests for LLM client configuration guardrails (no network calls)."""

import pytest

from src.llm.client import LLMClient, LLMError


def test_missing_api_key_raises_clear_error() -> None:
    client = LLMClient(provider="google", api_key="", model="gemini-3.8-flash", temperature=0.2)
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        client.generate_text("hello")


def test_unsupported_provider_raises() -> None:
    client = LLMClient(provider="openai", api_key="k", model="gpt-4o-mini", temperature=0.2)
    with pytest.raises(LLMError, match="Unsupported LLM provider"):
        client.generate_text("hello")
