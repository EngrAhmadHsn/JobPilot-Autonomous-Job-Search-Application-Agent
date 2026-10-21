"""Tests for the LLM provider adapters (WS-10 · Phase C).

Both providers are driven without a network: the Gemini adapter through an
injected fake client that records the request it was handed, the
openai-compatible adapter through ``httpx.MockTransport`` — the same
fake-transport pattern the job-source adapters use.

The point of these tests is that they assert on **what reached the
provider**, not on what the code intended to send: the temperature, the
timeout, the privacy flag, the key's absence from every error message.
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.llm.errors import (
    LLMConfigError,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)
from src.llm.providers import (
    GeminiProvider,
    OpenAICompatibleProvider,
    ProviderRequest,
    build_provider,
)
from tests.fixtures.llm_fakes import FakeGeminiClient, FakeInteraction, FakeUsage

KEY = "sk-test-do-not-log-me"


def _request(**overrides) -> ProviderRequest:
    payload = {
        "prompt": "hello",
        "model": "gemini-3.8-flash",
        "temperature": 0.2,
        "timeout": 60.0,
    }
    payload.update(overrides)
    return ProviderRequest(**payload)


class TestGeminiProvider:
    def test_the_temperature_reaches_the_provider(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="ok")])
        provider = GeminiProvider(api_key=KEY, model="gemini-3.8-flash", client=fake)
        provider.complete(_request(temperature=0.7))
        assert fake.requests[0]["generation_config"]["temperature"] == 0.7

    def test_the_timeout_reaches_the_provider(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="ok")])
        provider = GeminiProvider(api_key=KEY, model="gemini-3.8-flash", client=fake)
        provider.complete(_request(timeout=12.5))
        assert fake.requests[0]["timeout"] == 12.5

    def test_the_privacy_flag_is_never_relaxed(self) -> None:
        """``store=False`` is a privacy control, not a tunable."""
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="ok")])
        provider = GeminiProvider(api_key=KEY, model="gemini-3.8-flash", client=fake)
        provider.complete(_request())
        assert fake.requests[0]["store"] is False

    def test_a_structured_call_carries_the_schema(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="{}")])
        provider = GeminiProvider(api_key=KEY, model="gemini-3.8-flash", client=fake)
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        provider.complete(_request(response_schema=schema))
        assert fake.requests[0]["response_format"]["schema"] == schema
        assert fake.requests[0]["response_format"]["mime_type"] == "application/json"

    def test_a_text_call_carries_no_response_format(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="ok")])
        provider = GeminiProvider(api_key=KEY, model="gemini-3.8-flash", client=fake)
        provider.complete(_request())
        assert "response_format" not in fake.requests[0]

    def test_the_usage_is_read_off_the_response(self) -> None:
        fake = FakeGeminiClient(
            outcomes=[
                FakeInteraction(
                    output_text="ok",
                    usage=FakeUsage(
                        total_tokens=120, total_input_tokens=100, total_output_tokens=20
                    ),
                )
            ]
        )
        provider = GeminiProvider(api_key=KEY, model="gemini-3.8-flash", client=fake)
        response = provider.complete(_request())
        assert response.total_tokens == 120
        assert response.input_tokens == 100
        assert response.output_tokens == 20
        assert response.text == "ok"

    def test_a_response_without_usage_is_not_an_error(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="ok")])
        provider = GeminiProvider(api_key=KEY, model="gemini-3.8-flash", client=fake)
        response = provider.complete(_request())
        assert response.total_tokens is None
        assert response.text == "ok"

    def test_a_provider_failure_becomes_a_taxonomy_error(self) -> None:
        fake = FakeGeminiClient(outcomes=[RuntimeError("429 Too Many Requests")])
        provider = GeminiProvider(api_key=KEY, model="gemini-3.8-flash", client=fake)
        with pytest.raises(LLMRateLimited):
            provider.complete(_request())

    def test_a_5xx_becomes_unavailable(self) -> None:
        fake = FakeGeminiClient(outcomes=[RuntimeError("503 Service Unavailable")])
        provider = GeminiProvider(api_key=KEY, model="gemini-3.8-flash", client=fake)
        with pytest.raises(LLMUnavailable):
            provider.complete(_request())

    def test_the_key_never_appears_in_an_error_message(self) -> None:
        """A provider that echoed the key must not put it in our message."""
        fake = FakeGeminiClient(outcomes=[RuntimeError(f"boom {KEY}")])
        provider = GeminiProvider(api_key=KEY, model="gemini-3.8-flash", client=fake)
        with pytest.raises(LLMError) as excinfo:
            provider.complete(_request())
        assert KEY not in str(excinfo.value)

    def test_a_missing_key_is_a_config_error(self) -> None:
        provider = GeminiProvider(api_key="", model="gemini-3.8-flash")
        with pytest.raises(LLMConfigError, match="LLM_API_KEY"):
            provider.complete(_request())

    def test_the_sdk_does_not_retry_behind_the_clients_back(self) -> None:
        """Both of the SDK's internal retry layers must be off.

        The google-genai SDK retries a 429/5xx twice over: the api client
        wraps requests in a tenacity loop (five attempts, waits up to a
        minute), and the Interactions resource has its own layer (four
        retries) which **honours a ``Retry-After`` header verbatim**. Left
        on, they sit in front of the client's retry policy: a throttled call
        hangs inside the SDK — a daily-quota 429 carries
        ``Retry-After: 50951``, fourteen hours — while the client's backoff
        never runs. The live verification found this the hard way: the
        throttled call hung instead of failing.
        """
        provider = GeminiProvider(api_key=KEY, model="gemini-3.8-flash")
        client = provider._ensure_client()  # constructing it makes no request

        # The api client's layer: one attempt, no retries.
        retry_options = client._api_client._http_options.retry_options
        assert retry_options is not None
        assert retry_options.attempts == 0

        # The Interactions resource's layer: no retries either.
        interactions_config = client.interactions.sdk_configuration.retry_config
        assert interactions_config is not None
        assert interactions_config.max_retries == 0


def _mock_http(
    handler,
) -> tuple[httpx.Client, list[httpx.Request]]:
    """An httpx client on a mock transport, plus the list of requests it saw."""
    seen: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(recording_handler)), seen


def _chat_response(text: str = '{"ok": true}', **usage) -> dict:
    payload = {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    payload["usage"].update(usage)
    return payload


class TestOpenAICompatibleProvider:
    def test_the_temperature_reaches_the_provider(self) -> None:
        http, seen = _mock_http(lambda _r: httpx.Response(200, json=_chat_response()))
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1", http_client=http
        )
        provider.complete(_request(temperature=0.7, model="gpt-4o-mini"))
        body = json.loads(seen[0].read())
        assert body["temperature"] == 0.7

    def test_the_key_travels_as_an_authorization_header_only(self) -> None:
        http, seen = _mock_http(lambda _r: httpx.Response(200, json=_chat_response()))
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1", http_client=http
        )
        provider.complete(_request(model="gpt-4o-mini"))
        assert seen[0].headers["authorization"] == f"Bearer {KEY}"
        assert KEY not in seen[0].read().decode()

    def test_a_structured_call_requests_json_mode_and_sends_the_schema(self) -> None:
        http, seen = _mock_http(lambda _r: httpx.Response(200, json=_chat_response()))
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1", http_client=http
        )
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        provider.complete(_request(model="gpt-4o-mini", response_schema=schema))
        body = json.loads(seen[0].read())
        assert body["response_format"] == {"type": "json_object"}
        prompt = body["messages"][0]["content"]
        assert "JSON" in prompt
        assert "ok" in prompt

    def test_the_url_is_the_chat_completions_endpoint(self) -> None:
        http, seen = _mock_http(lambda _r: httpx.Response(200, json=_chat_response()))
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1/", http_client=http
        )
        provider.complete(_request(model="gpt-4o-mini"))
        assert str(seen[0].url) == "https://example.test/v1/chat/completions"

    def test_the_usage_is_read_off_the_response(self) -> None:
        http, _ = _mock_http(lambda _r: httpx.Response(200, json=_chat_response()))
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1", http_client=http
        )
        response = provider.complete(_request(model="gpt-4o-mini"))
        assert response.total_tokens == 15
        assert response.input_tokens == 10
        assert response.output_tokens == 5

    def test_a_429_is_rate_limited(self) -> None:
        http, _ = _mock_http(lambda _r: httpx.Response(429, json={"error": "slow down"}))
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1", http_client=http
        )
        with pytest.raises(LLMRateLimited):
            provider.complete(_request(model="gpt-4o-mini"))

    def test_a_500_is_unavailable(self) -> None:
        http, _ = _mock_http(lambda _r: httpx.Response(500))
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1", http_client=http
        )
        with pytest.raises(LLMUnavailable):
            provider.complete(_request(model="gpt-4o-mini"))

    def test_a_rejected_key_is_a_config_error(self) -> None:
        http, _ = _mock_http(lambda _r: httpx.Response(401, json={"error": "bad key"}))
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1", http_client=http
        )
        with pytest.raises(LLMConfigError):
            provider.complete(_request(model="gpt-4o-mini"))

    def test_a_bad_request_is_not_retryable(self) -> None:
        http, _ = _mock_http(lambda _r: httpx.Response(400, json={"error": "bad request"}))
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1", http_client=http
        )
        with pytest.raises(LLMError) as excinfo:
            provider.complete(_request(model="gpt-4o-mini"))
        assert not isinstance(excinfo.value, (LLMRateLimited, LLMUnavailable))

    def test_a_transport_failure_is_unavailable(self) -> None:
        def boom(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        http, _ = _mock_http(boom)
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1", http_client=http
        )
        with pytest.raises(LLMUnavailable):
            provider.complete(_request(model="gpt-4o-mini"))

    def test_a_timeout_is_a_timeout(self) -> None:
        def boom(_request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow")

        http, _ = _mock_http(boom)
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1", http_client=http
        )
        with pytest.raises(LLMTimeout):
            provider.complete(_request(model="gpt-4o-mini"))

    def test_a_response_without_a_message_is_an_invalid_output(self) -> None:
        http, _ = _mock_http(lambda _r: httpx.Response(200, json={"choices": []}))
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1", http_client=http
        )
        with pytest.raises(LLMInvalidOutput):
            provider.complete(_request(model="gpt-4o-mini"))

    def test_the_key_never_appears_in_an_error_message(self) -> None:
        http, _ = _mock_http(
            lambda _r: httpx.Response(500, json={"error": {"message": f"boom {KEY}"}})
        )
        provider = OpenAICompatibleProvider(
            api_key=KEY, model="gpt-4o-mini", base_url="https://example.test/v1", http_client=http
        )
        with pytest.raises(LLMError) as excinfo:
            provider.complete(_request(model="gpt-4o-mini"))
        assert KEY not in str(excinfo.value)

    def test_a_missing_key_is_a_config_error(self) -> None:
        provider = OpenAICompatibleProvider(
            api_key="", model="gpt-4o-mini", base_url="https://example.test/v1"
        )
        with pytest.raises(LLMConfigError, match="LLM_API_KEY"):
            provider.complete(_request(model="gpt-4o-mini"))


class TestBuildProvider:
    def test_google_builds_the_gemini_adapter(self) -> None:
        provider = build_provider("google", api_key=KEY, model="gemini-3.8-flash")
        assert isinstance(provider, GeminiProvider)

    def test_the_openai_compatible_aliases_build_the_chat_adapter(self) -> None:
        provider = build_provider(
            "openai-compatible", api_key=KEY, model="m", base_url="https://example.test/v1"
        )
        assert isinstance(provider, OpenAICompatibleProvider)
        for name in ("openai", "zai"):
            assert isinstance(
                build_provider(name, api_key=KEY, model="m"), OpenAICompatibleProvider
            )

    def test_openai_compatible_needs_a_base_url(self) -> None:
        with pytest.raises(LLMConfigError, match="LLM_BASE_URL"):
            build_provider("openai-compatible", api_key=KEY, model="m")

    def test_the_aliases_carry_their_default_base_url(self) -> None:
        assert (
            build_provider("openai", api_key=KEY, model="m").base_url == "https://api.openai.com/v1"
        )
        assert (
            build_provider("zai", api_key=KEY, model="m").base_url == "https://api.z.ai/api/paas/v4"
        )

    def test_an_unknown_provider_is_refused(self) -> None:
        with pytest.raises(LLMConfigError, match="Unsupported LLM provider"):
            build_provider("anthropic", api_key=KEY, model="m")

    def test_an_empty_provider_is_refused(self) -> None:
        with pytest.raises(LLMConfigError, match="Unsupported LLM provider"):
            build_provider("", api_key=KEY, model="m")
