"""Tests for LLM client configuration guardrails and error taxonomy (no network)."""

import pytest
from pydantic import BaseModel, Field

from src.llm.client import (
    LLMClient,
    LLMConfigError,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMUnavailable,
    classify_provider_error,
    strict_json_schema,
)


def test_missing_api_key_raises_clear_error() -> None:
    client = LLMClient(provider="google", api_key="", model="gemini-3.8-flash", temperature=0.2)
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        client.generate_text("hello")


def test_missing_api_key_is_a_config_error() -> None:
    client = LLMClient(provider="google", api_key="", model="gemini-3.8-flash", temperature=0.2)
    with pytest.raises(LLMConfigError):
        client.generate_text("hello")


def test_unsupported_provider_raises() -> None:
    client = LLMClient(provider="openai", api_key="k", model="gpt-4o-mini", temperature=0.2)
    with pytest.raises(LLMError, match="Unsupported LLM provider"):
        client.generate_text("hello")


def test_taxonomy_subclasses() -> None:
    for exc_type in (LLMConfigError, LLMRateLimited, LLMUnavailable, LLMInvalidOutput):
        assert issubclass(exc_type, LLMError)


def test_classify_rate_limit_errors() -> None:
    for message in ("429 Too Many Requests", "quota exceeded for project", "RESOURCE_EXHAUSTED"):
        assert isinstance(classify_provider_error(RuntimeError(message)), LLMRateLimited)


def test_classify_unavailable_errors() -> None:
    for message in ("500 Internal Server Error", "503 Service Unavailable", "connection reset"):
        assert isinstance(classify_provider_error(RuntimeError(message)), LLMUnavailable)


def test_classify_unknown_error_stays_llm_error() -> None:
    assert type(classify_provider_error(RuntimeError("weird failure"))) is LLMError


def test_rate_limit_errors_are_not_confused_with_unavailable() -> None:
    assert not isinstance(classify_provider_error(RuntimeError("429 too many")), LLMUnavailable)


class _Sample(BaseModel):
    """A model with defaulted fields, like the WS-05 research contract."""

    summary: str = ""
    items: list[str] = Field(default_factory=list)
    nested: "_Nested | None" = None


class _Nested(BaseModel):
    label: str = ""


def test_strict_json_schema_requires_every_property() -> None:
    """Defaulted fields must still be required in the provider's schema.

    Pydantic marks defaulted fields as optional, and a provider may then omit
    them — the structured call comes back with the field silently missing.
    """
    schema = strict_json_schema(_Sample)
    assert set(schema["required"]) == {"summary", "items", "nested"}
    for prop in schema["properties"].values():
        assert "default" not in prop


def test_strict_json_schema_requires_nested_properties_too() -> None:
    schema = strict_json_schema(_Sample)
    nested = schema["$defs"]["_Nested"]
    assert nested["required"] == ["label"]


def test_strict_json_schema_keeps_the_model_defaults_usable_in_code() -> None:
    """The model itself still constructs with omitted fields."""
    sample = _Sample()
    assert sample.summary == ""
    assert sample.items == []
