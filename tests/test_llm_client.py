"""Tests for the LLM client facade (WS-10).

The client is the agent's brain, so these tests are about the promises the
client makes: the temperature reaches the provider, a call cannot hang, a
transient failure is retried and a permanent one is not, the call is paced,
the spend is recorded — and the key and the prompt never leak.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from src.llm.client import (
    LLMClient,
    LLMConfigError,
    LLMDailyQuotaExhausted,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMUnavailable,
    classify_provider_error,
    repair_json_text,
    strict_json_schema,
)
from src.llm.providers import GeminiProvider
from tests.fixtures.llm_fakes import (
    FakeClock,
    FakeGeminiClient,
    FakeInteraction,
    FakeUsage,
)

KEY = "sk-test-do-not-log-me"
SECRET_PROMPT = "Ahmad Hassan, ahmad@example.com, +1 555 0101"


class _Sample(BaseModel):
    """A model with defaulted fields, like the WS-05 research contract."""

    summary: str = ""
    items: list[str] = Field(default_factory=list)
    nested: _Nested | None = None


class _Nested(BaseModel):
    label: str = ""


def _client(
    fake: FakeGeminiClient | None = None,
    *,
    clock: FakeClock | None = None,
    max_retries: int = 2,
    max_rpm: int = 10,
    provider: str = "google",
    api_key: str = KEY,
    temperature: float = 0.2,
) -> LLMClient:
    """A client wired to a fake Gemini client and a fake clock."""
    the_clock = clock or FakeClock()
    fake = fake if fake is not None else FakeGeminiClient()
    provider_instance = GeminiProvider(api_key=api_key, model="gemini-3.8-flash", client=fake)
    return LLMClient(
        provider=provider,
        api_key=api_key,
        model="gemini-3.8-flash",
        temperature=temperature,
        provider_instance=provider_instance,
        max_retries=max_retries,
        max_rpm=max_rpm,
        sleep=the_clock.sleep,
        clock=the_clock.time,
        jitter=lambda _lo, _hi: 0.0,
    )


class TestConfiguration:
    def test_missing_api_key_raises_clear_error(self) -> None:
        client = LLMClient(provider="google", api_key="", model="gemini-3.8-flash", temperature=0.2)
        with pytest.raises(LLMError, match="LLM_API_KEY"):
            client.generate_text("hello")

    def test_missing_api_key_is_a_config_error(self) -> None:
        client = LLMClient(provider="google", api_key="", model="gemini-3.8-flash", temperature=0.2)
        with pytest.raises(LLMConfigError):
            client.generate_text("hello")

    def test_unsupported_provider_raises(self) -> None:
        """Anthropic's native API is not chat-completions shaped — refused."""
        client = LLMClient(provider="anthropic", api_key="k", model="claude", temperature=0.2)
        with pytest.raises(LLMError, match="Unsupported LLM provider"):
            client.generate_text("hello")

    def test_taxonomy_subclasses(self) -> None:
        for exc_type in (LLMConfigError, LLMRateLimited, LLMUnavailable, LLMInvalidOutput):
            assert issubclass(exc_type, LLMError)

    def test_classify_rate_limit_errors(self) -> None:
        for message in (
            "429 Too Many Requests",
            "quota exceeded for project",
            "RESOURCE_EXHAUSTED",
        ):
            assert isinstance(classify_provider_error(RuntimeError(message)), LLMRateLimited)

    def test_classify_unavailable_errors(self) -> None:
        for message in ("500 Internal Server Error", "503 Service Unavailable", "connection reset"):
            assert isinstance(classify_provider_error(RuntimeError(message)), LLMUnavailable)

    def test_classify_unknown_error_stays_llm_error(self) -> None:
        assert type(classify_provider_error(RuntimeError("weird failure"))) is LLMError

    def test_rate_limit_errors_are_not_confused_with_unavailable(self) -> None:
        assert not isinstance(classify_provider_error(RuntimeError("429 too many")), LLMUnavailable)

    def test_a_timeout_is_its_own_retryable_class(self) -> None:
        from src.llm.errors import LLMTimeout

        error = classify_provider_error(RuntimeError("request timeout"))
        assert isinstance(error, LLMTimeout)
        assert isinstance(error, LLMUnavailable)  # still retryable


class TestParametersReachTheProvider:
    def test_the_temperature_reaches_a_text_call(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="ok")])
        _client(fake, temperature=0.7).generate_text("hello")
        assert fake.requests[0]["generation_config"]["temperature"] == 0.7

    def test_the_temperature_reaches_a_structured_call(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="{}")])
        _client(fake, temperature=0.7).generate_structured("hello", _Sample)
        assert fake.requests[0]["generation_config"]["temperature"] == 0.7

    def test_the_timeout_reaches_the_provider(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="ok")])
        client = LLMClient(
            provider="google",
            api_key=KEY,
            model="gemini-3.8-flash",
            temperature=0.2,
            provider_instance=GeminiProvider(api_key=KEY, model="m", client=fake),
            timeout=12.5,
        )
        client.generate_text("hello")
        assert fake.requests[0]["timeout"] == 12.5

    def test_the_privacy_flag_is_never_relaxed(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="ok")])
        _client(fake).generate_text("hello")
        assert fake.requests[0]["store"] is False


class TestRetry:
    def test_a_429_then_a_5xx_then_success_is_one_logical_call(self) -> None:
        """The acceptance case: three attempts, one answer, jittered backoff."""
        clock = FakeClock()
        fake = FakeGeminiClient(
            outcomes=[
                RuntimeError("429 Too Many Requests"),
                RuntimeError("503 Service Unavailable"),
                FakeInteraction(output_text="finally"),
            ]
        )
        client = _client(fake, clock=clock)
        assert client.generate_text("hello") == "finally"
        assert fake.call_count == 3
        # 1 s, then 4 s — and the suite never waited for them.
        assert clock.sleeps == [1.0, 4.0]

    def test_the_backoff_is_jittered(self) -> None:
        clock = FakeClock()
        fake = FakeGeminiClient(
            outcomes=[RuntimeError("500 boom"), FakeInteraction(output_text="ok")]
        )
        client = LLMClient(
            provider="google",
            api_key=KEY,
            model="gemini-3.8-flash",
            temperature=0.2,
            provider_instance=GeminiProvider(api_key=KEY, model="m", client=fake),
            sleep=clock.sleep,
            clock=clock.time,
            jitter=lambda _lo, hi: hi,  # the worst-case jitter
        )
        client.generate_text("hello")
        assert clock.sleeps == [1.5]

    def test_a_config_error_is_not_retried(self) -> None:
        fake = FakeGeminiClient(outcomes=[RuntimeError("400 bad request")])
        client = _client(fake)
        with pytest.raises(LLMError):
            client.generate_text("hello")
        assert fake.call_count == 1

    def test_a_daily_quota_error_is_not_retried(self) -> None:
        """The daily budget does not reset in seconds."""
        clock = FakeClock()
        fake = FakeGeminiClient(outcomes=[RuntimeError("GenerateRequestsPerDay quota exceeded")])
        client = _client(fake, clock=clock)
        with pytest.raises(LLMDailyQuotaExhausted):
            client.generate_text("hello")
        assert fake.call_count == 1
        assert clock.sleeps == []

    def test_a_per_minute_quota_error_is_retried(self) -> None:
        clock = FakeClock()
        fake = FakeGeminiClient(
            outcomes=[RuntimeError("429 Resource exhausted"), FakeInteraction(output_text="ok")]
        )
        client = _client(fake, clock=clock)
        assert client.generate_text("hello") == "ok"
        assert fake.call_count == 2

    def test_the_retries_are_bounded(self) -> None:
        clock = FakeClock()
        fake = FakeGeminiClient(outcomes=[RuntimeError("500 boom")])
        client = _client(fake, clock=clock, max_retries=2)
        with pytest.raises(LLMUnavailable):
            client.generate_text("hello")
        assert fake.call_count == 3
        assert len(clock.sleeps) == 2

    def test_no_retries_means_one_attempt(self) -> None:
        fake = FakeGeminiClient(outcomes=[RuntimeError("500 boom")])
        client = _client(fake, max_retries=0)
        with pytest.raises(LLMUnavailable):
            client.generate_text("hello")
        assert fake.call_count == 1

    def test_the_retry_is_counted_in_the_usage(self) -> None:
        clock = FakeClock()
        fake = FakeGeminiClient(
            outcomes=[RuntimeError("500 boom"), FakeInteraction(output_text="ok")]
        )
        client = _client(fake, clock=clock)
        client.generate_text("hello")
        assert client.last_usage is not None
        assert client.last_usage.attempts == 2


class TestPacing:
    def test_thirty_rapid_calls_are_paced_inside_the_budget(self) -> None:
        """The limiter's acceptance case, through the client.

        Thirty calls at ten per minute span two minutes of virtual time, and
        no 60-second window holds more than ten of them — so the provider
        never sees the burst that would earn a 429.
        """
        clock = FakeClock()
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="ok")])
        client = _client(fake, clock=clock, max_rpm=10)
        for _ in range(30):
            client.generate_text("hello")
        assert fake.call_count == 30
        assert clock.elapsed == pytest.approx(120.0, abs=1.0)

    def test_a_call_is_never_refused_by_the_limiter(self) -> None:
        """Pacing sleeps; it does not fail the call."""
        clock = FakeClock()
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="ok")])
        client = _client(fake, clock=clock, max_rpm=1)
        assert client.generate_text("one") == "ok"
        assert client.generate_text("two") == "ok"
        assert fake.call_count == 2


class TestUsage:
    def test_the_usage_of_the_last_call_is_readable(self) -> None:
        fake = FakeGeminiClient(
            outcomes=[
                FakeInteraction(
                    output_text="ok",
                    usage=FakeUsage(
                        total_tokens=150, total_input_tokens=120, total_output_tokens=30
                    ),
                )
            ]
        )
        client = _client(fake)
        client.generate_text("hello")
        usage = client.last_usage
        assert usage is not None
        assert usage.total_tokens == 150
        assert usage.input_tokens == 120
        assert usage.output_tokens == 30
        assert usage.provider == "google"
        assert usage.model == "gemini-3.8-flash"

    def test_there_is_no_usage_before_the_first_call(self) -> None:
        assert _client().last_usage is None

    def test_a_structured_call_records_its_usage(self) -> None:
        fake = FakeGeminiClient(
            outcomes=[FakeInteraction(output_text="{}", usage=FakeUsage(total_tokens=42))]
        )
        client = _client(fake)
        client.generate_structured("hello", _Sample)
        assert client.last_usage is not None
        assert client.last_usage.kind == "structured"
        assert client.last_usage.total_tokens == 42

    def test_a_failed_call_records_the_failure(self) -> None:
        fake = FakeGeminiClient(outcomes=[RuntimeError("500 boom")])
        client = _client(fake, max_retries=0)
        with pytest.raises(LLMUnavailable):
            client.generate_text("hello")
        assert client.last_usage is not None
        assert client.last_usage.error_type == "LLMUnavailable"

    def test_the_audit_row_holds_the_counts_and_no_content(self) -> None:
        from sqlalchemy import select

        from src.db.audit import AuditEventDB
        from src.db.session import SessionLocal
        from src.security.audit import ACTION_LLM_USAGE

        fake = FakeGeminiClient(
            outcomes=[FakeInteraction(output_text="ok", usage=FakeUsage(total_tokens=77))]
        )
        _client(fake).generate_text(SECRET_PROMPT)

        with SessionLocal() as session:
            rows = list(
                session.scalars(select(AuditEventDB).where(AuditEventDB.action == ACTION_LLM_USAGE))
            )
        assert rows
        rendered = str(rows[-1].extra_metadata)
        assert "77" in rendered
        assert "Ahmad" not in rendered
        assert "ahmad@example.com" not in rendered
        assert KEY not in rendered


class TestKeyHygiene:
    def test_the_key_never_appears_in_an_exception(self) -> None:
        fake = FakeGeminiClient(outcomes=[RuntimeError(f"boom {KEY}")])
        client = _client(fake)
        with pytest.raises(LLMError) as excinfo:
            client.generate_text("hello")
        assert KEY not in str(excinfo.value)

    def test_the_key_never_appears_in_a_usage_row(self) -> None:
        from sqlalchemy import select

        from src.db.audit import AuditEventDB
        from src.db.session import SessionLocal
        from src.security.audit import ACTION_LLM_USAGE

        fake = FakeGeminiClient(outcomes=[RuntimeError("500 boom")])
        with pytest.raises(LLMUnavailable):
            _client(fake, max_retries=0).generate_text("hello")

        with SessionLocal() as session:
            rows = list(
                session.scalars(select(AuditEventDB).where(AuditEventDB.action == ACTION_LLM_USAGE))
            )
        assert rows
        assert KEY not in str(rows[-1].extra_metadata)


class TestStructuredOutput:
    def test_a_valid_answer_is_parsed(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text='{"summary": "hi"}')])
        result = _client(fake).generate_structured("hello", _Sample)
        assert result.summary == "hi"

    def test_a_fenced_answer_is_repaired(self) -> None:
        """A model that wraps its JSON in a code fence is a formatting slip."""
        fake = FakeGeminiClient(
            outcomes=[FakeInteraction(output_text='```json\n{"summary": "hi"}\n```')]
        )
        result = _client(fake).generate_structured("hello", _Sample)
        assert result.summary == "hi"

    def test_an_answer_with_prose_around_it_is_repaired(self) -> None:
        fake = FakeGeminiClient(
            outcomes=[FakeInteraction(output_text='Here you go: {"summary": "hi"} — enjoy!')]
        )
        result = _client(fake).generate_structured("hello", _Sample)
        assert result.summary == "hi"

    def test_the_repair_does_not_spend_a_second_call(self) -> None:
        fake = FakeGeminiClient(
            outcomes=[FakeInteraction(output_text='```json\n{"summary": "hi"}\n```')]
        )
        _client(fake).generate_structured("hello", _Sample)
        assert fake.call_count == 1

    def test_an_unrepairable_answer_raises_invalid_output(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="not json at all")])
        with pytest.raises(LLMInvalidOutput):
            _client(fake).generate_structured("hello", _Sample)

    def test_a_schema_violation_raises_invalid_output(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text='{"summary": 42}')])
        with pytest.raises(LLMInvalidOutput):
            _client(fake).generate_structured("hello", _Sample)

    def test_the_invalid_output_message_never_quotes_the_answer(self) -> None:
        """The answer is the model's rendering of candidate data."""
        fake = FakeGeminiClient(
            outcomes=[FakeInteraction(output_text=f'{{"summary": {SECRET_PROMPT!r}}}')]
        )
        with pytest.raises(LLMInvalidOutput) as excinfo:
            _client(fake).generate_structured("hello", _Sample)
        assert SECRET_PROMPT not in str(excinfo.value)

    def test_an_invalid_output_is_not_retried(self) -> None:
        fake = FakeGeminiClient(outcomes=[FakeInteraction(output_text="not json")])
        with pytest.raises(LLMInvalidOutput):
            _client(fake).generate_structured("hello", _Sample)
        assert fake.call_count == 1


class TestRepairJsonText:
    def test_a_fenced_block_is_unwrapped(self) -> None:
        assert repair_json_text('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_a_bare_fence_is_unwrapped(self) -> None:
        assert repair_json_text('```\n{"a": 1}\n```') == '{"a": 1}'

    def test_prose_around_the_object_is_removed(self) -> None:
        assert repair_json_text('Sure! {"a": 1} Hope that helps!') == '{"a": 1}'

    def test_a_brace_inside_a_string_does_not_end_the_object(self) -> None:
        assert repair_json_text('x {"a": "b { c"} y') == '{"a": "b { c"}'

    def test_valid_json_is_unchanged(self) -> None:
        assert repair_json_text('{"a": 1}') == '{"a": 1}'

    def test_text_without_an_object_is_returned_as_is(self) -> None:
        assert repair_json_text("no json here") == "no json here"


class TestStrictJsonSchema:
    def test_strict_json_schema_requires_every_property(self) -> None:
        """Defaulted fields must still be required in the provider's schema.

        Pydantic marks defaulted fields as optional, and a provider may then omit
        them — the structured call comes back with the field silently missing.
        """
        schema = strict_json_schema(_Sample)
        assert set(schema["required"]) == {"summary", "items", "nested"}
        for prop in schema["properties"].values():
            assert "default" not in prop

    def test_strict_json_schema_requires_nested_properties_too(self) -> None:
        schema = strict_json_schema(_Sample)
        nested = schema["$defs"]["_Nested"]
        assert nested["required"] == ["label"]

    def test_strict_json_schema_keeps_the_model_defaults_usable_in_code(self) -> None:
        """The model itself still constructs with omitted fields."""
        sample = _Sample()
        assert sample.summary == ""
        assert sample.items == []
