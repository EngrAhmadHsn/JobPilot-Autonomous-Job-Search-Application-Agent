"""WS-30 tests: the model provider fallback chain.

The chain's promises, each pinned here:

* the three aliases resolve to their vendor endpoints, and a stored
  bring-your-own-key credential resolves them without a base URL;
* a link is active exactly when its key is set, and `LLM_FALLBACK_ENABLED=false`
  leaves the primary alone;
* the chain advances on a retryable failure, a configuration failure and a
  plain error — and does **not** advance on success;
* a link whose breaker is open is skipped without a call;
* the link that answered is the one recorded in the usage row;
* when everything fails, the primary's error class is raised, every link is
  named, and no key appears in the message;
* a bring-your-own-key client is never chained (WS-22's ruling).

The endpoints are never contacted: the adapters are fakes and the "provider
factory" is the injection seam.
"""

from __future__ import annotations

import pytest

from src.config.settings import FallbackLinkConfig
from src.llm import client as client_module
from src.llm.client import LLMClient
from src.llm.errors import (
    LLMConfigError,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMUnavailable,
)
from src.llm.fallback import (
    FallbackLink,
    FallbackProvider,
    build_fallback_chain,
    build_fallback_links,
)
from src.llm.providers import (
    PROVIDER_GROQ,
    PROVIDER_POLLINATIONS,
    PROVIDER_TOKENHARBOR,
    ProviderRequest,
    ProviderResponse,
    alias_base_url,
)
from src.llm.resilience import reset_breakers

KEY = "sk-test-do-not-log-me"


# -- fakes --------------------------------------------------------------------


class FakeProvider:
    """An adapter that answers or fails, and counts its calls."""

    def __init__(
        self,
        name: str,
        *,
        model: str = "fake-model",
        error: Exception | None = None,
        text: str = "ok",
        **kwargs,
    ) -> None:
        # ``**kwargs`` absorbs what ``build_provider`` passes (api_key,
        # base_url, timeout) so the fake can stand in as the factory.
        self.name = name
        self.model = model
        self._error = error
        self._text = text
        self.calls: list[ProviderRequest] = []

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        return ProviderResponse(
            text=self._text,
            input_tokens=7,
            output_tokens=3,
            total_tokens=10,
        )


def _request(model: str = "primary-model") -> ProviderRequest:
    return ProviderRequest(prompt="hello", model=model, temperature=0.2, timeout=5.0)


def _link(alias: str, *, error: Exception | None = None, model: str | None = None) -> FallbackLink:
    return FallbackLink(
        alias=alias,
        provider=FakeProvider(alias, model=model or f"{alias}-model", error=error),
        model=model or f"{alias}-model",
    )


@pytest.fixture(autouse=True)
def _clean_breakers():
    """Each case starts with a closed registry.

    The WS-18 breakers are process-wide by design; a test that opens one must
    not leak it into the next case.
    """
    reset_breakers()
    yield
    reset_breakers()


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Rebuild the settings for every case that changes the environment.

    ``get_settings`` is ``lru_cache``d, so ``monkeypatch.setenv`` alone has no
    effect: the cached object still reports the old environment.
    """
    from src.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# -- the aliases --------------------------------------------------------------


class TestAliases:
    def test_each_fallback_alias_carries_its_vendor_endpoint(self) -> None:
        assert alias_base_url(PROVIDER_GROQ) == "https://api.groq.com/openai/v1"
        assert alias_base_url(PROVIDER_TOKENHARBOR) == "https://tokenharbor.ai/v1"
        assert alias_base_url(PROVIDER_POLLINATIONS) == "https://gen.pollinations.ai/v1"

    def test_the_bare_openai_compatible_provider_still_needs_a_url(self) -> None:
        """The alias table must not invent a default for the generic provider."""
        assert alias_base_url("openai-compatible") is None

    def test_a_build_accepts_the_alias_without_a_base_url(self) -> None:
        from src.llm.providers import build_provider

        provider = build_provider(PROVIDER_GROQ, api_key=KEY, model="m")
        assert provider.base_url == "https://api.groq.com/openai/v1"

    def test_a_user_may_store_a_fallback_alias_without_a_url(self) -> None:
        """The point of naming the aliases: a key and a model, nothing else."""
        from src.llm.credentials import _USER_PROVIDERS, _resolved_base_url

        for alias in (PROVIDER_GROQ, PROVIDER_TOKENHARBOR, PROVIDER_POLLINATIONS):
            assert alias in _USER_PROVIDERS
            assert _resolved_base_url(alias, None) == alias_base_url(alias)

    def test_a_stored_url_still_wins_over_the_vendor_default(self) -> None:
        from src.llm.credentials import _resolved_base_url

        assert (
            _resolved_base_url(PROVIDER_GROQ, "https://proxy.internal/v1")
            == "https://proxy.internal/v1"
        )

    def test_an_unknown_alias_has_no_default(self) -> None:
        assert alias_base_url("not-a-provider") is None


# -- building the links -------------------------------------------------------


class TestBuildLinks:
    def test_a_blank_key_skips_the_link(self) -> None:
        configs = [
            FallbackLinkConfig("groq", "", "qwen/qwen3.8-27b"),
            FallbackLinkConfig("tokenharbor", "thk_live_x", "deepseek-v4.1-flash"),
        ]
        links = build_fallback_links(configs, provider_factory=FakeProvider)
        assert [link.alias for link in links] == ["tokenharbor"]

    def test_the_order_is_the_configured_order(self) -> None:
        configs = [
            FallbackLinkConfig("groq", "k1", "m1"),
            FallbackLinkConfig("tokenharbor", "k2", "m2"),
            FallbackLinkConfig("pollinations", "k3", "m3"),
        ]
        links = build_fallback_links(configs, provider_factory=FakeProvider)
        assert [link.alias for link in links] == ["groq", "tokenharbor", "pollinations"]

    def test_a_link_is_built_with_its_own_model_and_key(self) -> None:
        seen: dict = {}

        def factory(provider, *, api_key, model, timeout):
            seen.update(provider=provider, api_key=api_key, model=model, timeout=timeout)
            return FakeProvider(provider, model=model)

        configs = [FallbackLinkConfig("groq", "gsk_x", "qwen/qwen3.8-27b")]
        build_fallback_links(configs, timeout=12.5, provider_factory=factory)
        assert seen == {
            "provider": "groq",
            "api_key": "gsk_x",
            "model": "qwen/qwen3.8-27b",
            "timeout": 12.5,
        }

    def test_the_settings_supply_the_links_and_their_defaults(self, monkeypatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
        monkeypatch.setenv("POLLINATIONS_API_KEY", "pk_x")
        links = build_fallback_links(provider_factory=FakeProvider)
        assert [link.alias for link in links] == ["groq", "pollinations"]
        assert links[0].model == "qwen/qwen3.8-27b"
        assert links[1].model == "community/morriszdweck/glm-5.3-flash-free"


# -- the chain walk -----------------------------------------------------------


class TestTheChainAdvances:
    def test_the_primary_answers_and_no_fallback_is_called(self) -> None:
        primary = _link("primary")
        fallback = _link("groq")
        chain = FallbackProvider([primary, fallback])
        response = chain.complete(_request())
        assert response.text == "ok"
        assert len(primary.provider.calls) == 1
        assert fallback.provider.calls == []

    @pytest.mark.parametrize(
        "error",
        [
            LLMRateLimited("429 slow down"),
            LLMUnavailable("503 down"),
            LLMConfigError("401 bad key"),
            LLMError("something else"),
        ],
    )
    def test_a_failure_advances_to_the_next_link(self, error: Exception) -> None:
        primary = _link("primary", error=error)
        fallback = _link("groq")
        chain = FallbackProvider([primary, fallback])
        response = chain.complete(_request())
        assert response.text == "ok"
        assert len(primary.provider.calls) == 1
        assert len(fallback.provider.calls) == 1

    def test_the_second_fallback_answers_when_the_first_also_fails(self) -> None:
        chain = FallbackProvider(
            [
                _link("primary", error=LLMUnavailable("503")),
                _link("groq", error=LLMRateLimited("429")),
                _link("tokenharbor"),
            ]
        )
        response = chain.complete(_request())
        assert response.provider == "tokenharbor"
        assert response.text == "ok"

    def test_each_link_is_called_with_its_own_model(self) -> None:
        primary = _link("primary", error=LLMUnavailable("503"), model="gemini-3.8-flash")
        fallback = _link("groq", model="qwen/qwen3.8-27b")
        chain = FallbackProvider([primary, fallback])
        chain.complete(_request(model="gemini-3.8-flash"))
        assert primary.provider.calls[0].model == "gemini-3.8-flash"
        assert fallback.provider.calls[0].model == "qwen/qwen3.8-27b"

    def test_the_answer_is_stamped_with_the_link_that_gave_it(self) -> None:
        chain = FallbackProvider([_link("primary", error=LLMUnavailable("503")), _link("groq")])
        response = chain.complete(_request())
        assert response.provider == "groq"
        assert response.model == "groq-model"
        # The counts survive the stamping.
        assert (response.input_tokens, response.output_tokens, response.total_tokens) == (7, 3, 10)


class TestTheChainPreservesTheRequest:
    def test_the_prompt_schema_and_temperature_travel_unchanged(self) -> None:
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        request = ProviderRequest(
            prompt="TAILOR THIS",
            model="m",
            temperature=0.7,
            timeout=9.0,
            response_schema=schema,
        )
        fallback = _link("groq")
        FallbackProvider([_link("primary", error=LLMUnavailable("503")), fallback]).complete(
            request
        )
        sent = fallback.provider.calls[0]
        assert sent.prompt == "TAILOR THIS"
        assert sent.response_schema == schema
        assert sent.temperature == 0.7
        assert sent.timeout == 9.0


class TestEverythingFailed:
    def test_the_primarys_error_class_and_message_are_kept(self) -> None:
        chain = FallbackProvider(
            [
                _link("primary", error=LLMUnavailable("503 primary is down")),
                _link("groq", error=LLMRateLimited("429 groq is throttled")),
            ]
        )
        with pytest.raises(LLMUnavailable) as excinfo:
            chain.complete(_request())
        # The class is the primary's: that is the provider an operator repairs.
        assert not isinstance(excinfo.value, LLMRateLimited)
        assert "503 primary is down" in str(excinfo.value)

    def test_every_link_is_named_in_the_summary(self) -> None:
        chain = FallbackProvider(
            [
                _link("primary", error=LLMUnavailable("503")),
                _link("groq", error=LLMRateLimited("429"), model="qwen/qwen3.8-27b"),
                _link("tokenharbor", error=LLMConfigError("401"), model="deepseek-v4.1-flash"),
            ]
        )
        with pytest.raises(LLMUnavailable) as excinfo:
            chain.complete(_request())
        message = str(excinfo.value)
        assert "Provider fallback chain exhausted" in message
        assert "primary (primary-model) → LLMUnavailable" in message
        assert "groq (qwen/qwen3.8-27b) → LLMRateLimited" in message
        assert "tokenharbor (deepseek-v4.1-flash) → LLMConfigError" in message

    def test_a_rejected_key_never_reaches_the_message(self) -> None:
        """The adapter scrubs the key; the chain must not put one back.

        The real adapter is driven here (through ``MockTransport``) rather than
        a fake that is handed a pre-scrubbed message, so this pins the actual
        path: the provider echoes the key in its 401 body, the adapter's
        ``_status_error`` scrubs it, and the chain's own summary — which the
        chain builds itself — adds no key of its own.
        """

        import httpx

        from src.llm.providers import OpenAICompatibleProvider

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": f"bad key {KEY}"}})

        adapter = OpenAICompatibleProvider(
            api_key=KEY,
            model="qwen/qwen3.8-27b",
            base_url="https://example.test/v1",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        chain = FallbackProvider([FallbackLink("groq", adapter, "qwen/qwen3.8-27b")])
        with pytest.raises(LLMError) as excinfo:
            chain.complete(_request())
        message = str(excinfo.value)
        assert KEY not in message
        assert "<redacted>" in message  # the scrub really ran
        assert "Provider fallback chain exhausted" in message

    def test_a_chain_needs_at_least_one_link(self) -> None:
        with pytest.raises(ValueError, match="at least one link"):
            FallbackProvider([])


class TestTheLinkBreakers:
    def test_an_open_link_is_skipped_without_a_call(self) -> None:
        """The breaker exists to skip a provider that is already failing."""
        from src.llm.resilience import get_breaker

        primary = _link("primary")
        groq = _link("groq", error=LLMUnavailable("503"))
        chain = FallbackProvider([primary, groq])

        # Drive Groq's own breaker open.
        breaker = get_breaker("llm:groq", failure_threshold=1)
        with pytest.raises(LLMUnavailable):
            FallbackProvider([groq]).complete(_request())
        assert breaker.state == "OPEN"

        # The chain now skips it and the primary answers.
        response = chain.complete(_request())
        assert response.provider == "primary"
        assert len(groq.provider.calls) == 1  # only the first, pre-breaker call

    def test_a_primary_failure_does_not_open_a_fallbacks_breaker(self) -> None:
        from src.llm.resilience import get_breaker

        primary = _link("primary", error=LLMUnavailable("503"))
        FallbackProvider([primary, _link("groq")]).complete(_request())
        assert get_breaker("llm:primary").state == "CLOSED"
        assert get_breaker("llm:groq").failure_count == 0

    def test_a_link_success_closes_its_own_breaker(self) -> None:
        """A probe after the cooldown closes the breaker, and the answer stands."""
        from src.llm.resilience import CircuitBreaker, get_breaker, reset_breakers

        # A breaker with a zero-length cooldown admits the probe immediately —
        # the same state machine, driven on virtual time.
        reset_breakers()
        breaker = get_breaker("llm:groq", failure_threshold=1, recovery_seconds=0.001)
        breaker.record_failure(retryable=True)
        assert breaker.state == "OPEN"

        groq = _link("groq")
        response = FallbackProvider([groq]).complete(_request())
        assert response.text == "ok"
        assert len(groq.provider.calls) == 1  # the probe really called the link
        assert breaker.state == "CLOSED"
        assert isinstance(breaker, CircuitBreaker)

    def test_a_config_error_does_not_open_the_breaker(self) -> None:
        """A bad key is not an outage (the WS-27 rule)."""
        from src.llm.resilience import get_breaker

        chain = FallbackProvider(
            [_link("primary", error=LLMConfigError("401 bad key")), _link("groq")]
        )
        chain.complete(_request())
        assert get_breaker("llm:primary").failure_count == 0


# -- the decorator ------------------------------------------------------------


class TestBuildFallbackChain:
    def test_nothing_configured_returns_the_primary_unchanged(self) -> None:
        primary = FakeProvider("google")
        assert build_fallback_chain(primary, link_configs=[]) is primary

    def test_the_switch_disables_the_chain(self, monkeypatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_ENABLED", "false")
        monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
        primary = FakeProvider("google")
        assert build_fallback_chain(primary, provider_factory=FakeProvider) is primary

    def test_a_configured_link_wraps_the_primary(self, monkeypatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
        primary = FakeProvider("google", model="gemini-3.8-flash")
        chain = build_fallback_chain(
            primary,
            primary_alias="google",
            primary_model="gemini-3.8-flash",
            provider_factory=FakeProvider,
        )
        assert isinstance(chain, FallbackProvider)
        assert [link.alias for link in chain.links] == ["google", "groq"]

    def test_the_primary_answers_through_the_chain(self, monkeypatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
        primary = FakeProvider("google", model="gemini-3.8-flash")
        chain = build_fallback_chain(
            primary,
            primary_alias="google",
            primary_model="gemini-3.8-flash",
            provider_factory=FakeProvider,
        )
        assert chain.complete(_request()).text == "ok"
        assert len(primary.calls) == 1


# -- the client integration ---------------------------------------------------


def _client_with(fake: FakeProvider, **kwargs) -> LLMClient:
    return LLMClient(
        provider="google",
        api_key=KEY,
        model="gemini-3.8-flash",
        temperature=0.2,
        provider_instance=fake,
        **kwargs,
    )


class TestTheClientUsesTheChain:
    def test_the_client_wraps_its_adapter_in_the_chain(self, monkeypatch, tmp_path) -> None:
        """``_ensure_provider`` builds the chain, not the bare adapter."""
        monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
        client = LLMClient(
            provider="google",
            api_key=KEY,
            model="gemini-3.8-flash",
            temperature=0.2,
            max_retries=0,
        )
        provider = client._ensure_provider()
        assert isinstance(provider, FallbackProvider)
        assert provider.links[0].alias == "google"

    def test_the_answering_links_identity_is_recorded_in_the_usage_row(self, monkeypatch) -> None:
        """Otherwise a Groq answer would be booked under the Gemini model."""
        monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
        recorded: list = []
        monkeypatch.setattr(
            client_module, "record_usage", lambda usage, **kw: recorded.append(usage)
        )

        client = LLMClient(
            provider="google",
            api_key=KEY,
            model="gemini-3.8-flash",
            temperature=0.2,
            max_retries=0,
        )
        # Replace the built chain's primary with a failing fake, and let the
        # real Groq link — a fake adapter — answer.
        client._provider = FallbackProvider(
            [
                FallbackLink(
                    alias="google",
                    provider=FakeProvider("google", error=LLMUnavailable("503")),
                    model="gemini-3.8-flash",
                ),
                _link("groq", model="qwen/qwen3.8-27b"),
            ]
        )
        assert client.generate_text("hello") == "ok"
        usage = recorded[-1]
        assert usage.provider == "groq"
        assert usage.model == "qwen/qwen3.8-27b"

    def test_a_single_provider_still_records_its_own_identity(self, monkeypatch) -> None:
        recorded: list = []
        monkeypatch.setattr(
            client_module, "record_usage", lambda usage, **kw: recorded.append(usage)
        )
        client = _client_with(FakeProvider("google", model="m"), max_retries=0)
        client.generate_text("hello")
        assert recorded[-1].provider == "google"
        assert recorded[-1].model == "gemini-3.8-flash"

    def test_the_bring_your_own_key_client_is_not_chained(self, monkeypatch) -> None:
        """WS-22's ruling stands: a user's key never spends the platform's.

        The chain is built inside ``LLMClient._ensure_provider``, which a BYOK
        client never reaches — it is constructed with a ``provider_instance``.
        """
        monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
        from datetime import UTC, datetime

        from src.llm.credentials import ResolvedCredential, _build_byok_client

        credential = ResolvedCredential(
            provider="google",
            model="gemini-3.8-flash",
            api_key="user-key",
            base_url=None,
            updated_at=datetime.now(UTC),
        )
        client = _build_byok_client("owner-1", credential)
        provider = client._ensure_provider()
        assert not isinstance(provider, FallbackProvider)
        assert getattr(provider, "name", None) == "google"

    def test_an_invalid_answer_does_not_advance_the_chain(self, monkeypatch) -> None:
        """The chain is below parsing by design; this pins that boundary."""
        monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
        groq = _link("groq")
        chain = FallbackProvider(
            [
                FallbackLink(
                    alias="google",
                    provider=FakeProvider("google", text="not json at all", model="m"),
                    model="m",
                ),
                groq,
            ]
        )
        client = LLMClient(
            provider="google",
            api_key=KEY,
            model="gemini-3.8-flash",
            temperature=0.2,
            max_retries=0,
            provider_instance=chain,
        )
        from pydantic import BaseModel

        class Sample(BaseModel):
            ok: bool = False

        with pytest.raises(LLMInvalidOutput):
            client.generate_structured("hello", Sample)
        # The fallback was not consulted: the answer parsed as far as the
        # chain is concerned (it is a string), and the chain never sees the
        # validation failure.
        assert groq.provider.calls == []
