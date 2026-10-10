"""LLM client module: the agent "brain" (Google Gemini via google-genai)."""

from src.llm.client import LLMClient, LLMError, get_client

__all__ = ["LLMClient", "LLMError", "get_client"]
