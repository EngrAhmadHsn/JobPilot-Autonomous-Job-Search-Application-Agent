"""LLM client module: the agent "brain" (Google Gemini via google-genai)."""

from src.llm.client import (
    LLMClient,
    LLMConfigError,
    LLMDailyQuotaExhausted,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
    classify_provider_error,
    get_client,
)
from src.llm.providers import (
    GeminiProvider,
    OpenAICompatibleProvider,
    Provider,
    ProviderRequest,
    ProviderResponse,
    build_provider,
)
from src.llm.usage import GenerationUsage

__all__ = [
    "GeminiProvider",
    "GenerationUsage",
    "LLMClient",
    "LLMConfigError",
    "LLMDailyQuotaExhausted",
    "LLMError",
    "LLMInvalidOutput",
    "LLMRateLimited",
    "LLMTimeout",
    "LLMUnavailable",
    "OpenAICompatibleProvider",
    "Provider",
    "ProviderRequest",
    "ProviderResponse",
    "build_provider",
    "classify_provider_error",
    "get_client",
]
