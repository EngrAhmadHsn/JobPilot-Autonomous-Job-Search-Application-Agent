"""Provider adapters for the LLM client (WS-10).

The client facade owns the *policy* — pacing, retrying, recording usage — and
the provider owns the *wire*. A provider never retries, never sleeps and
never decides what a failure means beyond mapping it onto the shared taxonomy
in :mod:`src.llm.errors`.

Two adapters ship:

- :class:`GeminiProvider` — the default. The ``google-genai`` **Interactions**
  API, with ``store=False`` on every call so candidate data is never
  retained on the provider side (the free tier would retain it for a day).
- :class:`OpenAICompatibleProvider` — **experimental**. Any chat-completions
  endpoint (OpenAI, Z.ai, a self-hosted gateway). The key is only ever an
  ``Authorization`` header; the API is called with the same taxonomy, the
  same retries and the same usage mapping as Gemini.

The Gemini request is built exactly like this (verified against the installed
SDK, and on the wire in the live verification):

.. code-block:: python

    client.interactions.create(
        model=..., input=..., store=False,
        generation_config={"temperature": 0.2},
        timeout=60.0,
        response_format={"type": "text", "mime_type": "application/json", "schema": ...},
    )
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from src.llm.errors import (
    LLMConfigError,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
    classify_provider_error,
    scrub_secret,
)

logger = logging.getLogger(__name__)

_STORE = False  # privacy: never persist interactions on the provider side

# The provider ids the client understands. "openai" and "zai" are aliases of
# "openai-compatible": both speak the chat-completions dialect and both are
# already documented in .env.example with an LLM_BASE_URL. "anthropic" is NOT
# supported — its native API is not chat-completions shaped, and half of it
# would be worse than a clear refusal.
PROVIDER_GOOGLE = "google"
PROVIDER_OPENAI_COMPATIBLE = "openai-compatible"
SUPPORTED_PROVIDERS = (PROVIDER_GOOGLE, PROVIDER_OPENAI_COMPATIBLE)
_OPENAI_COMPATIBLE_ALIASES: dict[str, str | None] = {
    PROVIDER_OPENAI_COMPATIBLE: None,  # LLM_BASE_URL is required
    "openai": "https://api.openai.com/v1",
    "zai": "https://api.z.ai/api/paas/v4",
}

# The longest provider error detail kept in an exception message.
_MAX_ERROR_DETAIL = 200


@dataclass(frozen=True)
class ProviderRequest:
    """One generation request, independent of the provider that carries it."""

    prompt: str
    model: str
    temperature: float
    timeout: float
    response_schema: dict | None = None  # a strict JSON schema, None for plain text


@dataclass(frozen=True)
class ProviderResponse:
    """One generation response, with the token counts when the provider gives them."""

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@runtime_checkable
class Provider(Protocol):
    """What the client needs from a provider."""

    name: str

    def complete(self, request: ProviderRequest) -> ProviderResponse: ...


def _usage_value(usage: Any, *names: str) -> int | None:
    """Read a token count off a usage object (an SDK model or a mapping)."""
    if usage is None:
        return None
    for name in names:
        value = getattr(usage, name, None)
        if value is None and isinstance(usage, Mapping):
            value = usage.get(name)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _build_genai_client(genai: Any, types: Any, api_key: str, base_url: str | None = None) -> Any:
    """A ``genai`` client whose internal retry layers are switched off.

    The SDK retries behind the caller's back **twice**, and the two layers
    disagree about what an attempt is:

    - the api client wraps every request in a tenacity loop — five attempts,
      exponential waits up to a minute, on 408/429/5xx;
    - the Interactions resource has its own layer — up to four retries on
      408/409/429/5xx, and it **honours a ``Retry-After`` header verbatim**.

    That second one is the dangerous one. A daily-quota 429 from Gemini
    carries ``Retry-After: 50951`` — fourteen hours — so the SDK would sleep
    for fourteen hours inside a call whose timeout was sixty seconds. The
    live verification found exactly this: a throttled call hung instead of
    failing.

    The client's own policy has to be the only one in effect, so both layers
    are reduced to a single attempt. ``attempts=0`` is read as "no retries"
    by the Interactions layer; the api client rewrites it to 1 for its own
    loop, so it is put back to 0 before the Interactions resource is built
    (it reads the same options object, lazily, on first use).

    Args:
        base_url: An alternative endpoint (a regional endpoint, a proxy, or
            the local capture server the live verification points at).
    """
    options = types.HttpOptions(
        base_url=base_url,
        retry_options=types.HttpRetryOptions(attempts=0),
    )
    client = genai.Client(api_key=api_key, http_options=options)
    # The api client rewrote attempts to 1 for its own layer; the
    # Interactions layer, built later from the same object, reads it as a
    # retry count. Put the 0 back before anything touches client.interactions.
    options.retry_options.attempts = 0
    return client


class GeminiProvider:
    """The default provider: the Gemini Interactions API.

    The real ``genai`` client is created lazily, so constructing the provider
    without a key is safe — only an actual call without a key raises
    ``LLMConfigError``. The client can be injected for tests.
    """

    name = PROVIDER_GOOGLE

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: Any = None,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._client = client
        self._base_url = base_url

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise LLMConfigError("LLM_API_KEY is not set; configure it in .env (never commit it)")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - environment issue
            raise LLMConfigError(
                "google-genai is not installed; add it to the environment"
            ) from exc
        self._client = _build_genai_client(genai, types, self._api_key, self._base_url)
        return self._client

    def build_request(self, request: ProviderRequest) -> dict[str, Any]:
        """The keyword arguments handed to ``interactions.create``.

        Split out so a test can assert on the exact payload without going
        through a provider call.
        """
        kwargs: dict[str, Any] = {
            "model": request.model,
            "input": request.prompt,
            "store": _STORE,
            "generation_config": {"temperature": request.temperature},
            "timeout": request.timeout,
        }
        if request.response_schema is not None:
            kwargs["response_format"] = {
                "type": "text",
                "mime_type": "application/json",
                "schema": request.response_schema,
            }
        return kwargs

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        client = self._ensure_client()
        try:
            interaction = client.interactions.create(**self.build_request(request))
        except LLMError:
            raise
        except Exception as exc:  # the SDK raises many types
            raise classify_provider_error(exc, secret=self._api_key) from exc
        usage = getattr(interaction, "usage", None)
        return ProviderResponse(
            text=getattr(interaction, "output_text", None) or "",
            input_tokens=_usage_value(usage, "total_input_tokens", "input_tokens"),
            output_tokens=_usage_value(usage, "total_output_tokens", "output_tokens"),
            total_tokens=_usage_value(usage, "total_tokens"),
        )


class OpenAICompatibleProvider:
    """An experimental chat-completions provider (OpenAI, Z.ai, a gateway).

    ``generate_structured`` is served by the endpoint's JSON mode
    (``response_format={"type": "json_object"}``) plus the schema in the
    prompt — the chat-completions API has no schema field. The prompt always
    contains the word "JSON", which is what JSON mode requires to be
    present.

    The ``httpx`` client is injectable, so the tests drive it through
    ``httpx.MockTransport`` — the same fake-transport pattern the job-source
    adapters use.
    """

    name = PROVIDER_OPENAI_COMPATIBLE

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float = 60.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._http = http_client

    def _ensure_http(self) -> httpx.Client:
        if self._http is not None:
            return self._http
        if not self._api_key:
            raise LLMConfigError("LLM_API_KEY is not set; configure it in .env (never commit it)")
        self._http = httpx.Client(timeout=self._timeout)
        return self._http

    def build_request(self, request: ProviderRequest) -> tuple[dict[str, Any], str]:
        """The JSON body and the URL of one chat-completions call."""
        prompt = request.prompt
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": request.temperature,
        }
        if request.response_schema is not None:
            body["response_format"] = {"type": "json_object"}
            body["messages"] = [
                {"role": "user", "content": _schema_instruction(request.response_schema)}
            ]
        url = f"{self.base_url}/chat/completions"
        return body, url

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        http = self._ensure_http()
        body, url = self.build_request(request)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = http.post(url, json=body, headers=headers, timeout=request.timeout)
        except httpx.TimeoutException as exc:
            raise LLMTimeout(
                scrub_secret(
                    f"LLM request timed out after {request.timeout}s: {type(exc).__name__}: {exc}",
                    self._api_key,
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(
                scrub_secret(f"LLM transport error: {type(exc).__name__}: {exc}", self._api_key)
            ) from exc
        if response.status_code != 200:
            raise self._status_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMInvalidOutput(
                f"LLM returned a non-JSON response body: {type(exc).__name__}"
            ) from exc
        return _parse_chat_completion(payload, self._api_key)

    def _status_error(self, response: httpx.Response) -> LLMError:
        """Map an HTTP status onto the taxonomy."""
        status = response.status_code
        detail = scrub_secret(_error_detail(response), self._api_key)
        suffix = f": {detail}" if detail else ""
        if status == 429:
            return LLMRateLimited(f"LLM rate limited (HTTP {status}){suffix}")
        if status >= 500:
            return LLMUnavailable(f"LLM unavailable (HTTP {status}){suffix}")
        if status in (401, 403):
            return LLMConfigError(f"LLM rejected the API key (HTTP {status}){suffix}")
        return LLMError(f"LLM call failed (HTTP {status}){suffix}")


def _schema_instruction(schema: dict) -> str:
    """The prompt prefix that carries the schema for a JSON-mode call."""
    return (
        "Respond with a single JSON object and nothing else. "
        "The JSON object must conform to this JSON schema:\n"
        f"{json.dumps(schema, indent=2)}\n\n"
    )


def _error_detail(response: httpx.Response) -> str:
    """The provider's own error message, if it sent one, truncated."""
    try:
        payload = response.json()
    except ValueError:
        return ""
    detail = ""
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            detail = str(error.get("message", ""))
        elif isinstance(error, str):
            detail = error
        if not detail:
            detail = str(payload.get("message", ""))
    return detail[:_MAX_ERROR_DETAIL]


def _parse_chat_completion(payload: Any, secret: str | None) -> ProviderResponse:
    """Read the answer and the usage out of a chat-completions response."""
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMInvalidOutput("LLM response did not contain a chat completion message") from exc
    usage = payload.get("usage") if isinstance(payload, Mapping) else None
    return ProviderResponse(
        text=text or "",
        input_tokens=_usage_value(usage, "prompt_tokens", "input_tokens"),
        output_tokens=_usage_value(usage, "completion_tokens", "output_tokens"),
        total_tokens=_usage_value(usage, "total_tokens"),
    )


def build_provider(
    provider: str,
    *,
    api_key: str,
    model: str,
    base_url: str | None = None,
    timeout: float = 60.0,
    client: Any = None,
    http_client: httpx.Client | None = None,
) -> Provider:
    """Build the adapter for ``provider``.

    Raises:
        LLMConfigError: the provider is unknown, or the openai-compatible
            provider was selected without a base URL.
    """
    name = (provider or "").strip().lower()
    if name == PROVIDER_GOOGLE:
        return GeminiProvider(api_key=api_key, model=model, client=client)
    if name in _OPENAI_COMPATIBLE_ALIASES:
        default_base_url = _OPENAI_COMPATIBLE_ALIASES[name]
        resolved = base_url or default_base_url
        if not resolved:
            raise LLMConfigError(
                "LLM_BASE_URL is required for the openai-compatible provider; "
                "set it to the chat-completions endpoint "
                "(e.g. https://api.z.ai/api/paas/v4)"
            )
        return OpenAICompatibleProvider(
            api_key=api_key,
            model=model,
            base_url=resolved,
            timeout=timeout,
            http_client=http_client,
        )
    raise LLMConfigError(
        f"Unsupported LLM provider: {provider!r}. "
        f"Supported: {', '.join(SUPPORTED_PROVIDERS)} "
        "(aliases: openai, zai)."
    )
