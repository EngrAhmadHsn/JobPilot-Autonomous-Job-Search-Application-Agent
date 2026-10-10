"""Minimal LLM client for the agent "brain" (currently Google Gemini).

Uses the google-genai Interactions API. All calls set store=False so candidate
data is never retained by the provider (free tier would retain it for 1 day).
The API key is never logged or included in error messages.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from src.config.settings import get_settings

logger = logging.getLogger(__name__)

_STORE = False  # privacy: never persist interactions on the provider side


class LLMError(RuntimeError):
    """Raised when the LLM provider is unconfigured or a call fails."""


class LLMClient:
    """Thin provider-backed client exposing text and structured generation."""

    def __init__(self, provider: str, api_key: str, model: str, temperature: float) -> None:
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self._api_key = api_key
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise LLMError("LLM_API_KEY is not set; configure it in .env (never commit it)")
        if self.provider != "google":
            raise LLMError(f"Unsupported LLM provider: {self.provider!r}")
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - environment issue
            raise LLMError("google-genai is not installed; add it to the environment") from exc
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _create(self, **kwargs: Any) -> Any:
        client = self._ensure_client()
        try:
            return client.interactions.create(**kwargs)
        except Exception as exc:  # provider SDK raises many types; convert to LLMError
            raise LLMError(f"LLM call failed: {type(exc).__name__}: {exc}") from exc

    def generate_text(self, prompt: str) -> str:
        interaction = self._create(model=self.model, input=prompt, store=_STORE)
        return interaction.output_text or ""

    def generate_structured[T: BaseModel](self, prompt: str, schema: type[T]) -> T:
        interaction = self._create(
            model=self.model,
            input=prompt,
            store=_STORE,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": schema.model_json_schema(),
            },
        )
        raw = interaction.output_text or ""
        try:
            return schema.model_validate_json(raw)
        except ValueError as exc:
            raise LLMError(f"LLM returned invalid JSON for {schema.__name__}: {exc}") from exc


_client: LLMClient | None = None


def get_client() -> LLMClient:
    """Return the process-wide LLM client configured from settings."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = LLMClient(
            provider=settings.llm_provider,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
        )
    return _client
