"""The LLM client — the agent's "brain" (currently Google Gemini).

The client is a thin **facade** over a provider adapter
(:mod:`src.llm.providers`): it owns the policy — pacing, retrying, timeout,
usage accounting — and the provider owns the wire.

What this module guarantees:

- **The temperature is applied.** ``settings.llm_temperature`` used to be
  stored on the client and never sent; it now reaches the provider on every
  call.
- **A call cannot hang.** Every call carries a timeout
  (``settings.llm_timeout``).
- **A transient failure does not fail the workflow.** A 429 or a 5xx is
  retried with exponential backoff and jitter; a bad key, an unknown provider
  and an invalid answer are not.
- **The call is paced.** A sliding-window limiter keeps the client inside
  the provider's per-minute budget (``settings.llm_max_rpm``) by sleeping,
  never by refusing the call.
- **The spend is visible.** Every call writes a usage row to the audit trail
  — counts only, never a prompt.
- **The privacy stance is unchanged.** Gemini calls still carry
  ``store=False``; the API key is never logged, never in an exception
  message, never in the audit trail, and never in a request body.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

from pydantic import BaseModel

from src.config.settings import get_settings
from src.llm.errors import (
    LLMConfigError,
    LLMDailyQuotaExhausted,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
    classify_provider_error,
)
from src.llm.providers import (
    Provider,
    ProviderRequest,
    ProviderResponse,
    build_provider,
)
from src.llm.resilience import SlidingWindowLimiter, backoff_delay, get_limiter
from src.llm.usage import (
    KIND_STRUCTURED,
    KIND_TEXT,
    GenerationUsage,
    record_usage,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LLMClient",
    "LLMConfigError",
    "LLMDailyQuotaExhausted",
    "LLMError",
    "LLMInvalidOutput",
    "LLMRateLimited",
    "LLMTimeout",
    "LLMUnavailable",
    "classify_provider_error",
    "get_client",
    "repair_json_text",
    "strict_json_schema",
]

# The first retry waits this long, the second four times as long; the jitter
# is added on top (see src.llm.resilience.backoff_delay).
_BACKOFF_BASE = 1.0

# The limiter's window: the provider's budget is per minute.
_LIMIT_WINDOW_SECONDS = 60.0


class LLMClient:
    """A provider-backed client exposing text and structured generation.

    Args:
        provider: The provider id — ``google``, or ``openai-compatible``
            (aliases ``openai`` and ``zai``).
        api_key: The provider key. Never logged, never in an exception.
        model: The model id.
        temperature: The sampling temperature, applied on every call.
        base_url: The chat-completions endpoint, for the openai-compatible
            provider.
        timeout: Seconds one call may take. Defaults to
            ``settings.llm_timeout``.
        max_retries: Retries after the first attempt, for a retryable
            failure. Defaults to ``settings.llm_max_retries``.
        max_rpm: Calls per minute allowed against the provider. Defaults to
            ``settings.llm_max_rpm``.
        provider_instance: A ready-made provider adapter (the injection seam
            for the tests).
        limiter: A ready-made rate limiter.
        sleep, clock, jitter: The timing seams, so the tests drive the
            backoff and the pacing on virtual time.
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        temperature: float,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        max_rpm: int | None = None,
        provider_instance: Provider | None = None,
        limiter: SlidingWindowLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        settings = get_settings()
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = settings.llm_timeout if timeout is None else timeout
        self._max_retries = settings.llm_max_retries if max_retries is None else max_retries
        self._max_rpm = settings.llm_max_rpm if max_rpm is None else max_rpm
        self._sleep = sleep
        self._clock = clock
        self._jitter = jitter
        self._provider_instance = provider_instance
        self._provider: Provider | None = None
        self._limiter = limiter or SlidingWindowLimiter(
            self._max_rpm, _LIMIT_WINDOW_SECONDS, clock=clock, sleep=sleep
        )
        self._last_usage: GenerationUsage | None = None

    # -- public API ---------------------------------------------------------

    @property
    def last_usage(self) -> GenerationUsage | None:
        """The usage of the most recent call, or ``None`` before the first."""
        return self._last_usage

    def generate_text(self, prompt: str) -> str:
        """Generate free text.

        Raises:
            LLMConfigError: the provider is unconfigured or unsupported.
            LLMRateLimited / LLMUnavailable: the provider stayed unavailable
                after the configured retries.
            LLMInvalidOutput: the answer broke the caller's contract.
        """
        provider = self._ensure_provider()
        request = ProviderRequest(
            prompt=prompt,
            model=self.model,
            temperature=self.temperature,
            timeout=self._timeout,
        )
        started = self._clock()
        try:
            response, attempts = self._call(provider, request)
        except LLMError as exc:
            self._record_failure(exc, started, KIND_TEXT, attempts=0)
            raise
        return self._record_success(response, started, KIND_TEXT, attempts)

    def generate_structured[T: BaseModel](self, prompt: str, schema: type[T]) -> T:
        """Generate an object that satisfies ``schema``.

        The answer is validated against the schema. A malformed answer is
        repaired **once, locally** (a code fence is stripped, or the JSON
        object is extracted from surrounding prose) and validated again; a
        second failure raises ``LLMInvalidOutput``. The repair never spends
        another model call.

        Raises:
            LLMInvalidOutput: the answer could not be made to satisfy the
                schema.
        """
        provider = self._ensure_provider()
        request = ProviderRequest(
            prompt=prompt,
            model=self.model,
            temperature=self.temperature,
            timeout=self._timeout,
            response_schema=strict_json_schema(schema),
        )
        started = self._clock()
        try:
            response, attempts = self._call(provider, request)
        except LLMError as exc:
            self._record_failure(exc, started, KIND_STRUCTURED, attempts=0)
            raise
        self._record_success(response, started, KIND_STRUCTURED, attempts)
        return _parse_structured(response.text, schema)

    # -- internals ----------------------------------------------------------

    def _ensure_provider(self) -> Provider:
        """The provider adapter, built on first use."""
        if self._provider is not None:
            return self._provider
        if self._provider_instance is not None:
            self._provider = self._provider_instance
            return self._provider
        if not self._api_key:
            raise LLMConfigError("LLM_API_KEY is not set; configure it in .env (never commit it)")
        self._provider = build_provider(
            self.provider,
            api_key=self._api_key,
            model=self.model,
            base_url=self._base_url,
            timeout=self._timeout,
        )
        return self._provider

    def _provider_name(self) -> str:
        provider = self._provider or self._provider_instance
        return getattr(provider, "name", None) or self.provider or "unknown"

    @staticmethod
    def _is_retryable(exc: LLMError) -> bool:
        """Whether a failure is worth another attempt.

        The daily-quota error is a subclass of the rate-limit error, but a
        *daily* budget does not reset in seconds: retrying it would hammer
        the provider until the backoff gave up.
        """
        if isinstance(exc, LLMDailyQuotaExhausted):
            return False
        return isinstance(exc, (LLMRateLimited, LLMUnavailable))

    def _call(self, provider: Provider, request: ProviderRequest) -> tuple[ProviderResponse, int]:
        """One logical call, with the retry loop around the provider call."""
        attempt = 0
        while True:
            self._limiter.acquire()
            try:
                response = provider.complete(request)
            except LLMError as exc:
                if not self._is_retryable(exc) or attempt >= self._max_retries:
                    raise
                attempt += 1
                delay = backoff_delay(attempt, _BACKOFF_BASE, self._jitter)
                logger.warning(
                    "LLM call failed (%s); retrying in %.2fs (attempt %d/%d)",
                    type(exc).__name__,
                    delay,
                    attempt,
                    self._max_retries,
                )
                self._sleep(delay)
                continue
            return response, attempt + 1

    def _record_success(
        self, response: ProviderResponse, started: float, kind: str, attempts: int
    ) -> str:
        """Account for a successful call and return its text."""
        usage = GenerationUsage(
            provider=self._provider_name(),
            model=self.model,
            kind=kind,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            total_tokens=response.total_tokens,
            duration_ms=self._elapsed_ms(started),
            attempts=attempts,
        )
        self._last_usage = usage
        record_usage(usage)
        return response.text

    def _record_failure(self, exc: LLMError, started: float, kind: str, *, attempts: int) -> None:
        """Account for a failed call (counts only, never the message)."""
        usage = GenerationUsage(
            provider=self._provider_name(),
            model=self.model,
            kind=kind,
            duration_ms=self._elapsed_ms(started),
            attempts=attempts,
            error_type=type(exc).__name__,
        )
        self._last_usage = usage
        record_usage(usage, outcome="error")

    def _elapsed_ms(self, started: float) -> int:
        return max(0, int((self._clock() - started) * 1000))


def _parse_structured[T: BaseModel](raw: str, schema: type[T]) -> T:
    """Validate the answer against the schema, repairing it once if needed.

    The validation error is summarised by its **locations and types only**:
    a Pydantic error message quotes the offending input, and that input is
    the model's rendering of candidate data — it must not reach a log line
    or an exception message.
    """
    try:
        return schema.model_validate_json(raw)
    except ValueError as first_error:
        repaired = repair_json_text(raw)
        if repaired != raw:
            try:
                return schema.model_validate_json(repaired)
            except ValueError:
                pass
        raise LLMInvalidOutput(
            f"LLM returned invalid JSON for {schema.__name__}: "
            f"{_safe_validation_summary(first_error)}"
        ) from first_error


def _safe_validation_summary(exc: Exception) -> str:
    """A validation-error summary that quotes no input."""
    errors = exc.errors() if hasattr(exc, "errors") else []
    parts: list[str] = []
    for error in errors[:5]:
        location = ".".join(str(item) for item in error.get("loc", ()))
        parts.append(f"{location or '<root>'}: {error.get('type', 'invalid')}")
    return "; ".join(parts) or type(exc).__name__


def repair_json_text(raw: str) -> str:
    """Make a model's JSON answer parseable, without asking the model again.

    Two fixes, in order:

    1. a fenced block (``\\`\\`\\`json … \\`\\`\\```) is unwrapped;
    2. otherwise the outermost balanced ``{…}`` object is extracted, so an
       answer with a sentence of prose around it still parses.

    Braces inside strings are ignored, so a value like ``"a { b"`` does not
    end the object early.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # drop the opening fence (and its language tag)
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text


def strict_json_schema(schema: type[BaseModel]) -> dict:
    """The JSON schema of a model with every property required and no defaults.

    Pydantic marks fields that have a default (including ``default_factory``)
    as optional in the JSON schema, and a provider that honours the schema
    treats a non-required property as one it may simply leave out. The result
    is silent data loss: a structured call can come back with a field the
    caller asked for missing, and the Pydantic default quietly fills it in.

    Requiring every property closes that hole — the provider has to emit the
    whole object — while the model keeps its defaults for direct construction
    in code and tests.
    """
    raw = schema.model_json_schema()
    for definition in (raw, *raw.get("$defs", {}).values()):
        properties = definition.get("properties")
        if not properties:
            continue
        definition["required"] = list(properties)
        for prop in properties.values():
            prop.pop("default", None)
    return raw


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
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
            max_rpm=settings.llm_max_rpm,
            limiter=get_limiter("llm", settings.llm_max_rpm, _LIMIT_WINDOW_SECONDS),
        )
    return _client
