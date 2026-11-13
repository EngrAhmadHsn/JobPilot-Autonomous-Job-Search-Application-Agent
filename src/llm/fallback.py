"""The model provider fallback chain (WS-30).

**The problem.** The client knows one provider. When that provider rate-limits,
times out or is down, the call fails — after the client's bounded retries
against *the same* provider, which cannot help. A deployment holding keys for
several providers used one of them.

**The design.** The chain lives at the **provider seam**, not above the client.
:class:`FallbackProvider` implements the same two-method :class:`~src.llm.providers.Provider`
protocol as :class:`~src.llm.providers.GeminiProvider` and wraps an ordered list
of already-built adapters. Everything the client owns — the timeout, the sliding
window, the retry loop, the circuit breaker, the usage row — is unchanged and
applies **once per logical call**, exactly as WS-10 specified it. The chain walks
*inside* that one call::

    LLMClient.generate_structured
      └─ limiter → retries → FallbackProvider.complete
           ├─ link 1 (the configured primary)  → ok?  return
           ├─ link 2 (Groq)                    → 429 / 5xx / 401 / open breaker → next
           └─ link 3 (…)                       → ok?  return

Putting the chain above the client instead — one :class:`LLMClient` per link —
would multiply the pacing, the retries and the breakers by the number of links
and turn "one logical call" into "three logical calls" the moment a provider was
slow. The decorator keeps that contract exactly;
:class:`~src.llm.credentials._CredentialProvider` is the precedent for it.

**What advances the chain.** A retryable failure (429, 5xx, timeout), a
configuration failure (a rejected key, an unknown model, a bad request), a
plain error, or an *open breaker* on that link — the last one without a call,
which is the point of having a breaker there. Every link failure is logged at
WARNING naming the link, so "Groq answered" or "Groq was skipped, its key was
rejected" is in the log even when the caller never sees an error.

**Whose breaker.** Each link keeps its own, under ``llm:<alias>`` in the WS-18
registry (shared across worker processes when ``CIRCUIT_SHARED_STATE`` is on).
An open link is skipped; a link success closes it; a link failure counts against
it; a **permanent** failure does not open it — a bad key is not an outage, which
is WS-27's rule. ``breaker_snapshot()`` already surfaces all of them through
``/api/health``, so which link is down is observable without new machinery.

**What the chain deliberately does not do.** It does not chain a
bring-your-own-key client: WS-22's ruling stands, a user's failing key never
spends the platform's quota, and these are the platform's keys. It does not give
each link its own rate limit: the client's window meters the deployment's own
call rate, and a link that throttles is handled by its 429 → breaker → skip path.
And it does not retry a link's *answer*: schema validation and the local JSON
repair stay in the client, above the chain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.config.settings import FallbackLinkConfig, get_settings
from src.llm.errors import (
    LLMCircuitOpen,
    LLMDailyQuotaExhausted,
    LLMError,
    LLMRateLimited,
    LLMUnavailable,
)
from src.llm.providers import (
    Provider,
    ProviderRequest,
    ProviderResponse,
    build_provider,
)
from src.llm.resilience import get_breaker

logger = logging.getLogger(__name__)

__all__ = [
    "FallbackLink",
    "FallbackProvider",
    "build_fallback_chain",
    "build_fallback_links",
]


@dataclass(frozen=True)
class FallbackLink:
    """One provider in the chain: its alias, its adapter and the model it speaks."""

    alias: str
    provider: Provider
    model: str

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        """Call this link with its own model substituted for the client's.

        The client's ``model`` names the **primary** provider's model — sending
        it to Groq would be a 400. The link therefore carries its own, which is
        the one thing about the request the chain changes.
        """
        if self.model and request.model != self.model:
            request = ProviderRequest(
                prompt=request.prompt,
                model=self.model,
                temperature=request.temperature,
                timeout=request.timeout,
                response_schema=request.response_schema,
            )
        return self.provider.complete(request)


def build_fallback_links(
    link_configs: list[FallbackLinkConfig] | None = None,
    *,
    timeout: float | None = None,
    provider_factory: Any = None,
) -> list[FallbackLink]:
    """Build a link for every **active** configured fallback (WS-30).

    A link with a blank key is skipped, not an error: that is how a deployment
    runs with one, two or three links, and how it turns one off. The order is
    the settings' order — Groq, TokenHarbor, Pollinations — and the endpoint
    comes from the alias table, so only a key and a model were configured.

    Args:
        link_configs: The configured links; defaults to the settings'.
        timeout: The per-call timeout the adapter enforces; defaults to
            ``settings.llm_timeout``.
        provider_factory: The adapter builder (the injection seam for tests).
            Defaults to :func:`~src.llm.providers.build_provider`.
    """
    settings = get_settings()
    configs = settings.llm_fallback_links if link_configs is None else link_configs
    effective_timeout = settings.llm_timeout if timeout is None else timeout
    factory = build_provider if provider_factory is None else provider_factory

    links: list[FallbackLink] = []
    for config in configs:
        if not config.active:
            logger.debug("Fallback link %r is not configured; skipping it", config.alias)
            continue
        links.append(
            FallbackLink(
                alias=config.alias,
                provider=factory(
                    config.alias,  # an alias resolves to its vendor base URL
                    api_key=config.api_key,
                    model=config.model,
                    timeout=effective_timeout,
                ),
                model=config.model,
            )
        )
    return links


class FallbackProvider:
    """The primary provider and its fallbacks, behind one ``Provider`` (WS-30).

    ``links`` is ordered: the primary first, then the configured fallbacks.
    :meth:`complete` tries each in turn and returns the first answer. When every
    link fails it raises the **first attempted link's** error — the primary's,
    when one is configured — with a one-line summary of each link appended.

    The first link's error class is preserved on purpose. The deployment
    declared that provider as its path; its failure is the one an operator
    repairs (a wrong key, an exhausted quota). Raising the *last* link's class
    would name the least important provider in the chain, which is exactly the
    confusion WS-27 removed for a single provider.

    The chain does not catch ``LLMInvalidOutput`` from rebuilding the request
    (it never parses) and it does not swallow anything the caller must see;
    only :class:`~src.llm.errors.LLMError` subclasses advance a link, and the
    last one is re-raised rather than masked.
    """

    #: The provider name the client records when no link answers. It reads as
    #: "the deployment's configured chain", which is what the client called.
    name = "fallback-chain"

    def __init__(self, links: list[FallbackLink]) -> None:
        if not links:
            raise ValueError("a fallback chain needs at least one link")
        self._links = list(links)
        self._primary_alias = self._links[0].alias

    @property
    def links(self) -> list[FallbackLink]:
        """The chain, in the order it is tried (primary first)."""
        return list(self._links)

    def primary_model(self) -> str:
        """The primary link's model, for the client's own identity."""
        return self._links[0].model

    def _breaker_for(self, link: FallbackLink):
        """The breaker bucket for a link.

        Its own bucket per alias, so one link's failures cannot open another's —
        the same isolation WS-22 gave a bring-your-own-key client.
        """
        return get_breaker(f"llm:{link.alias}")

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        """Send *request* to the first link that answers.

        Raises:
            LLMError: the first attempted link's error, with every link's
                outcome summarised. The message carries no key: each link's own
                error was already scrubbed by the adapter that raised it.
        """
        failures: list[tuple[str, LLMError]] = []
        for link in self._links:
            breaker = self._breaker_for(link)
            if not breaker.allow_request():
                # The link is already known to be failing. Calling it would
                # spend the timeout to learn what the breaker already knows.
                error = LLMCircuitOpen(
                    f"The {link.alias} circuit is open after repeated failures; not calling it."
                )
                logger.warning("Fallback link %s skipped: its circuit is open", link.alias)
                failures.append((link.alias, error))
                continue
            try:
                response = link.complete(request)
            except LLMError as exc:
                breaker.record_failure(retryable=_is_transient(exc))
                logger.warning(
                    "Fallback link %s (%s) failed with %s; trying the next provider",
                    link.alias,
                    link.model,
                    type(exc).__name__,
                )
                failures.append((link.alias, exc))
                continue
            breaker.record_success()
            if link is not self._links[0]:
                logger.info("Fallback link %s answered the call", link.alias)
            return _stamped(response, link)

        _first_alias, first_error = failures[0]
        summary = "; ".join(
            f"{alias} ({link_model(self._links, alias)}) → {type(exc).__name__}"
            for alias, exc in failures
        )
        raise _chain_error(first_error, summary=summary)


def link_model(links: list[FallbackLink], alias: str) -> str:
    """The model a named link speaks (for the failure summary)."""
    for link in links:
        if link.alias == alias:
            return link.model
    return "unknown"  # pragma: no cover - the alias came from the chain itself


def _is_transient(exc: LLMError) -> bool:
    """Whether a link failure is an outage rather than a misconfiguration.

    Only an outage may open the link's breaker — a rejected key or an unknown
    model is a configuration error, and retrying it cannot help (WS-27). This
    mirrors :meth:`src.llm.client.LLMClient._is_retryable` deliberately: the
    chain must not disagree with the client about what "transient" means.
    """
    if isinstance(exc, (LLMCircuitOpen, LLMDailyQuotaExhausted)):
        return False
    return isinstance(exc, (LLMRateLimited, LLMUnavailable))


def _stamped(response: ProviderResponse, link: FallbackLink) -> ProviderResponse:
    """The answer, stamped with the link that gave it.

    The client's usage row reads these to name the provider and model that
    actually answered — without them a call Groq answered would be recorded
    under the primary's model, and "the spend is visible" (WS-10) would be
    false in exactly the case the chain exists for.
    """
    if response.provider == link.alias and response.model == link.model:
        return response
    return ProviderResponse(
        text=response.text,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        total_tokens=response.total_tokens,
        provider=link.alias,
        model=link.model,
    )


def _chain_error(first_error: LLMError, *, summary: str) -> LLMError:
    """The primary's error class, carrying every link's outcome.

    The class and message of the first attempted link are kept (an operator
    repairs the declared path), and the chain's own accounting is appended so a
    caller can see that every link was tried. The message goes through no
    request data — each link's detail was scrubbed by its adapter before it
    reached here.
    """
    message = f"{first_error}\nProvider fallback chain exhausted: {summary}"
    try:
        rebuilt = type(first_error)(message)
    except Exception:  # noqa: BLE001 - an exotic signature must not mask the error
        return LLMError(message)
    # Preserve the attributes an error class may carry (e.g.
    # EmbeddingResourceExhausted.batch_size) without guessing at its signature.
    for attribute in ("batch_size",):
        if hasattr(first_error, attribute):
            try:
                setattr(rebuilt, attribute, getattr(first_error, attribute))
            except Exception:  # noqa: BLE001, S110 - best effort, never fatal
                pass
    return rebuilt


def build_fallback_chain(
    primary: Provider,
    *,
    primary_alias: str | None = None,
    primary_model: str | None = None,
    link_configs: list[FallbackLinkConfig] | None = None,
    provider_factory: Any = None,
) -> Provider:
    """The primary plus every active fallback, as one provider (WS-30).

    Returns the primary **unchanged** when there is nothing to chain: no
    fallback is enabled or configured. A single-provider deployment therefore
    keeps exactly the object graph it had before this module existed — the
    chain is a decoration, not a rewrite.

    Args:
        primary: The already-built primary adapter.
        primary_alias: The primary's provider id. ``None`` reads the protocol's
            own ``name`` attribute, which every adapter has.
        primary_model: The primary's model. ``None`` reads the adapter's
            ``model`` attribute; an adapter that exposes neither is chained
            under the summary's ``unknown``.
        link_configs, provider_factory: Forwarded to
            :func:`build_fallback_links`.
    """
    settings = get_settings()
    if not settings.llm_fallback_enabled:
        logger.debug("The provider fallback chain is disabled (LLM_FALLBACK_ENABLED)")
        return primary

    links = build_fallback_links(link_configs, provider_factory=provider_factory)
    if not links:
        return primary

    alias = primary_alias or getattr(primary, "name", None) or "primary"
    model = primary_model or getattr(primary, "model", None) or ""
    chain = FallbackProvider([FallbackLink(alias=alias, provider=primary, model=model), *links])
    logger.info(
        "Provider fallback chain active: %s",
        " → ".join(f"{link.alias} ({link.model})" for link in chain.links),
    )
    return chain
