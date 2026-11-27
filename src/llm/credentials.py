"""Bring-your-own-key: the credential store and per-user client resolution (WS-22).

**The feature.** A user may register *their own* LLM provider keys — one or
several at a time. Every model call their requests make runs on the
connection **in use**, their quota and their bill; the deployment's own key
is only a fallback, and only when ``BYOK_MODE`` allows it.

**Several connections, one in use.** Storing a connection is not the same as
using it: adding, editing or testing a provider never changes which key a job
spends. That is a separate, explicit action (``activate_credential``), and it
is why the console can hold a work key and a personal key side by side.
Removing the connection in use needs no promotion step — the next row in list
order already holds the highest activation rank.

**Where the resolution happens.** :func:`resolve_client` is what the two
generation call sites call instead of
:func:`src.llm.client.get_client`. The decision table:

===============  ======================  ===============================
tenant           stored credential       result
===============  ======================  ===============================
none             —                       the platform client (a script, a
                                         worker, a CLI has no user to
                                         charge and no key to spend)
present          none, mode ``optional``  the platform client
present          none, mode ``required``  ``LLMConfigError`` naming the fix
present          none, mode ``disabled``  the platform client
present          present                 a client built from the user's
                                         connection in use
===============  ======================  ===============================

**A user's key that fails never falls back to the platform key.** A fallback
would spend the deployment's quota on the user's misconfiguration and hide
the problem; the error names the fix instead. The circuit breaker and
rate-limit bucket are the **connection's** own (``llm:byok:<owner>:<id>``),
so one broken key cannot open the platform breaker, another user's, or even
another connection of the same user's.

**What a stored key can never do.** It cannot reach a route response, a log
line, an audit row or an exception message; it cannot be read by another
user, or by a superuser; and it cannot point the server at an internal
address — the base URL passes the same SSRF predicate the browser and the
job-source client use, with the loopback exception granted only in
development.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import socket
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from src.config.settings import get_settings
from src.llm.client import (
    SPEND_BYOK,
    LLMClient,
    get_client,
)
from src.llm.errors import LLMConfigError, LLMCredentialError, LLMError
from src.llm.providers import (
    PROVIDER_GOOGLE,
    PROVIDER_GROQ,
    PROVIDER_OPENAI_COMPATIBLE,
    PROVIDER_POLLINATIONS,
    PROVIDER_TOKENHARBOR,
    alias_base_url,
    build_provider,
)
from src.llm.resilience import get_limiter
from src.llm.tenant import current_tenant
from src.security.allowlist import (
    has_allowed_scheme,
    host_of,
    is_blocked_host,
    is_forbidden_ip,
    is_local_host,
)
from src.security.audit import (
    ACTION_LLM_CREDENTIAL_ACTIVATE,
    ACTION_LLM_CREDENTIAL_DELETE,
    ACTION_LLM_CREDENTIAL_SET,
    ACTION_LLM_CREDENTIAL_TEST,
    OUTCOME_SUCCESS,
    SYSTEM_ACTOR,
    record_audit,
)
from src.security.secrets import (
    SecretBoxUnavailable,
    decrypt_secret,
    encrypt_secret,
    key_material_source,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BYOK_MODE_DISABLED",
    "BYOK_MODE_OPTIONAL",
    "BYOK_MODE_REQUIRED",
    "CredentialKeyRequiredError",
    "CredentialState",
    "LlmCredentialInput",
    "LlmCredentialStatus",
    "LlmCredentialUpdate",
    "activate_credential",
    "add_credential",
    "credential_state",
    "delete_credential",
    "get_credential",
    "mark_used",
    "reset_client_cache",
    "resolve_client",
    "resolve_credential",
    "store_credential",
    "test_credential",
    "update_credential",
    "validate_base_url",
]

#: The three deployment modes. The default is ``optional``.
BYOK_MODE_DISABLED = "disabled"
BYOK_MODE_OPTIONAL = "optional"
BYOK_MODE_REQUIRED = "required"

#: The provider ids a user may register — the same set the platform
#: supports, aliases included. WS-30 adds the three fallback-chain aliases:
#: each carries its vendor's default endpoint, so a user stores a key and a
#: model and nothing else.
_USER_PROVIDERS = (
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI_COMPATIBLE,
    "openai",
    "zai",
    PROVIDER_GROQ,
    PROVIDER_TOKENHARBOR,
    PROVIDER_POLLINATIONS,
)

# The limiter window for a BYOK client's own pacing bucket.
_LIMIT_WINDOW_SECONDS = 60.0

# Bounds on what a user may store. Generous enough for any real provider,
# tight enough that the row cannot become a storage dump.
_MAX_MODEL_CHARS = 200
_MAX_BASE_URL_CHARS = 500
_MIN_KEY_CHARS = 8
_MAX_KEY_CHARS = 4096

# How many BYOK clients stay cached. One per (user, credential revision);
# a deployment with more concurrent users rebuilds a client, which costs
# nothing but the object.
_CLIENT_CACHE_SIZE = 32


class LlmCredentialInput(BaseModel):
    """A credential a user registers. The key is never echoed back."""

    provider: str = Field(..., description="google, openai-compatible, openai or zai")
    model: str = Field(..., min_length=1, max_length=_MAX_MODEL_CHARS)
    api_key: str = Field(..., min_length=_MIN_KEY_CHARS, max_length=_MAX_KEY_CHARS)
    base_url: str | None = Field(
        default=None,
        max_length=_MAX_BASE_URL_CHARS,
        description="Required for openai-compatible; validated against the SSRF rule",
    )

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        name = (value or "").strip().lower()
        if name not in _USER_PROVIDERS:
            raise ValueError(
                f"Unsupported provider {value!r}. Supported: {', '.join(_USER_PROVIDERS)}."
            )
        return name

    @field_validator("model", "api_key", mode="before")
    @classmethod
    def _stripped(cls, value: object) -> object:
        """Strip **before** the length checks run (WS-27).

        Pydantic validates ``min_length`` before an ``after`` validator, so
        eight spaces used to satisfy ``_MIN_KEY_CHARS`` and then be stored as
        the empty string. Every later ``if not key`` guard then passed it
        through to the provider, which answered 403 "unregistered callers".
        A stripped-empty key must fail here, where the user can see it.
        """
        return value.strip() if isinstance(value, str) else value

    @field_validator("api_key")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The API key cannot be blank.")
        return value.strip()


class LlmCredentialUpdate(BaseModel):
    """A partial edit of one stored connection (``PATCH``).

    Every field is optional and an omitted field keeps its stored value. The
    distinction that matters is between **omitting** ``api_key`` (keep the
    stored key — the common case, editing a model name) and **supplying** one
    (rotate it). ``model_fields_set`` answers that; a plain ``None`` default
    cannot, because "not sent" and "send null" would look the same.
    """

    provider: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=_MAX_MODEL_CHARS)
    api_key: str | None = Field(default=None, min_length=_MIN_KEY_CHARS, max_length=_MAX_KEY_CHARS)
    base_url: str | None = Field(default=None, max_length=_MAX_BASE_URL_CHARS)

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip().lower()
        if name not in _USER_PROVIDERS:
            raise ValueError(
                f"Unsupported provider {value!r}. Supported: {', '.join(_USER_PROVIDERS)}."
            )
        return name

    @field_validator("model", "api_key", mode="before")
    @classmethod
    def _stripped(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("api_key")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value:
            raise ValueError("The API key cannot be blank.")
        return value

    def supplied(self) -> set[str]:
        """The field names the caller actually sent."""
        return set(self.model_fields_set)


class LlmCredentialStatus(BaseModel):
    """One stored connection, described — never disclosed.

    ``hint`` is the last four characters of the key, enough for the owner to
    recognise which key is registered. ``id`` is what the per-connection
    routes take; it is the connection's own name, not the owner's.

    The timestamps are nullable because a row written before those columns
    existed has none — the API says "not recorded" rather than inventing a
    date.
    """

    id: str
    provider: str
    model: str
    base_url: str | None = None
    hint: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_used_at: datetime | None = None


class CredentialState(BaseModel):
    """Everything the console needs to render the credentials card.

    ``credential`` and ``credentials`` say different things and both are
    needed: ``credentials`` is every stored connection in the order the
    console shows (the one in use first, then whoever would take over), and
    ``credential`` is the top of that list.
    """

    mode: str
    #: Whether a credential can be stored at all on this deployment.
    available: bool
    #: Where the encryption key comes from (``explicit``, ``auth_secret``,
    #: ``local_file``, ``none``) — never the key itself.
    encryption: str
    #: Whether the deployment's own key is configured.
    platform_configured: bool
    #: ``user`` when a call would run on the caller's credential,
    #: ``platform`` when on the deployment's, ``none`` when neither.
    using: str
    #: The connection a call would use — the top of ``credentials``.
    credential: LlmCredentialStatus | None = None
    #: Every stored connection, the one in use first. Empty when there are none.
    credentials: list[LlmCredentialStatus] = Field(default_factory=list)


class CredentialKeyRequiredError(ValueError):
    """A change cannot be applied without supplying a new key.

    A ``ValueError`` because the routes already answer those with a 422 the
    caller can act on; a distinct type because the message has a distinct
    job — telling the user to paste the key again — and because a test can
    then assert the rule without matching on prose.
    """


@dataclass(frozen=True)
class ResolvedCredential:
    """A decrypted credential, held for the duration of one call."""

    provider: str
    model: str
    api_key: str
    base_url: str | None
    updated_at: datetime | None
    #: The connection this came from. Defaults to the empty string so a
    #: credential assembled by hand (a test, a script) still resolves; the
    #: value only ever reaches the per-connection breaker bucket.
    id: str = ""


def validate_base_url(url: str) -> str:
    """Validate a user-supplied chat-completions base URL.

    The value is a URL the **server** will POST to with the user's key, so it
    passes the same guard the browser and the job-source HTTP client use: an
    http(s) URL whose host is neither internal nor metadata. The loopback
    exception is granted only in development, where the fake provider the
    live verification points at lives.

    Raises:
        ValueError: the URL is unusable or points somewhere it must not.
    """
    value = (url or "").strip()
    if not value:
        raise ValueError("base_url must not be empty")
    if len(value) > _MAX_BASE_URL_CHARS:
        raise ValueError(f"base_url must be at most {_MAX_BASE_URL_CHARS} characters")
    if not has_allowed_scheme(value):
        raise ValueError("base_url must use http or https")
    host = host_of(value)
    if not host:
        raise ValueError("base_url has no hostname")
    if is_local_host(value):
        if get_settings().app_env == "development":
            return value
        raise ValueError("A loopback base_url is refused outside development")
    if is_blocked_host(value):
        raise ValueError(f"Host {host!r} is an internal or metadata address and is blocked")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"Host {host!r} does not resolve") from exc
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:  # pragma: no cover - getaddrinfo returns addresses
            continue
        if is_forbidden_ip(ip):
            raise ValueError(f"Host {host!r} resolves to an internal address ({address})")
    return value


def _resolved_base_url(provider: str, base_url: str | None) -> str | None:
    """The base URL the client will use, with the provider's default applied.

    Mirrors :func:`src.llm.providers.build_provider`: a bare
    ``openai-compatible`` needs an explicit URL, while the aliases carry the
    vendor default. The check happens at write time so a stored credential is
    never unusable.

    WS-30: the alias table is the **one** source of the vendor endpoints. The
    three fallback aliases added here (Groq, TokenHarbor, Pollinations) are
    read from it rather than spelled out a second time, so a URL can never
    drift between what the platform client builds and what a stored user
    credential resolves to.
    """
    name = (provider or "").strip().lower()
    if name == PROVIDER_GOOGLE:
        return base_url or None
    default = alias_base_url(name)
    if default is not None:
        return base_url or default
    if name != PROVIDER_OPENAI_COMPATIBLE:
        # Unknown to the alias table: fall through to the explicit-URL rule so
        # the caller gets the same message build_provider would have given.
        raise ValueError(f"Unsupported provider {name!r}")
    if not base_url:
        raise ValueError(
            "base_url is required for the openai-compatible provider "
            "(e.g. https://api.z.ai/api/paas/v4)"
        )
    return base_url


# -- storage ------------------------------------------------------------------


def _status_of(row) -> LlmCredentialStatus:
    """The masked view of a stored row (never the key)."""
    return LlmCredentialStatus(
        id=row.id,
        provider=row.provider,
        model=row.model,
        base_url=row.base_url,
        hint=row.hint,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_used_at=row.last_used_at,
    )


def _register(
    db: Session,
    owner_id: str,
    *,
    provider: str,
    model: str,
    base_url: str | None,
    api_key: str,
    create: bool,
) -> LlmCredentialStatus:
    """Write one connection and audit it — the shared tail of add and replace.

    The audit row carries the provider, the model, the hint and the
    connection id — never the key, and never a key-shaped metadata *name*
    (the redaction filter drops those, so a value smuggled under one would
    vanish from the trail silently).
    """
    from src.db import access
    from src.db.byok import hint_of

    resolved = _resolved_base_url(provider, base_url)
    if resolved is not None:
        resolved = validate_base_url(resolved)
    encrypted = encrypt_secret(api_key)
    scope = _self_scope(owner_id)
    if create:
        row = access.create_llm_credential(
            db,
            scope,
            provider=provider,
            model=model,
            base_url=resolved,
            encrypted_key=encrypted,
            hint=hint_of(api_key),
        )
    else:
        row = access.upsert_llm_credential(
            db,
            scope,
            provider=provider,
            model=model,
            base_url=resolved,
            encrypted_key=encrypted,
            hint=hint_of(api_key),
        )
    db.commit()
    record_audit(
        ACTION_LLM_CREDENTIAL_SET,
        actor=SYSTEM_ACTOR,
        resource=f"llm:{provider}:{model}",
        outcome=OUTCOME_SUCCESS,
        owner_id=owner_id,
        metadata={
            "provider": provider,
            "model": model,
            "hint": row.hint,
            "base_url": resolved or "",
            "credential_id": row.id,
            "created": create,
        },
    )
    return _status_of(row)


def add_credential(db: Session, owner_id: str, payload: LlmCredentialInput) -> LlmCredentialStatus:
    """Store **another** connection for *owner_id*.

    The new row never takes over: it is created at the same activation rank
    as the existing ones, and the older row wins the tie, so adding a
    provider cannot silently change which key a job runs on.

    Raises:
        ValueError: the provider/base-url combination is unusable.
        SecretBoxUnavailable: no encryption key material, so nothing is stored.
    """
    return _register(
        db,
        owner_id,
        provider=payload.provider,
        model=payload.model,
        base_url=payload.base_url,
        api_key=payload.api_key,
        create=True,
    )


def store_credential(
    db: Session, owner_id: str, payload: LlmCredentialInput
) -> LlmCredentialStatus:
    """Register or **replace the connection in use** for *owner_id*.

    The pre-multi-connection contract, kept for ``PUT``: a client that knows
    only this route keeps working, and on an account that holds several
    connections it edits the one in use rather than adding another.

    Raises:
        ValueError: the provider/base-url combination is unusable.
        SecretBoxUnavailable: this deployment has no encryption key material,
            so nothing may be stored.
    """
    return _register(
        db,
        owner_id,
        provider=payload.provider,
        model=payload.model,
        base_url=payload.base_url,
        api_key=payload.api_key,
        create=False,
    )


def get_credential(db: Session, owner_id: str, credential_id: str) -> LlmCredentialStatus | None:
    """One of the owner's connections, masked; ``None`` when it is not theirs."""
    from src.db import access

    row = access.get_llm_credential(db, _self_scope(owner_id), credential_id)
    return _status_of(row) if row is not None else None


def update_credential(
    db: Session, owner_id: str, credential_id: str, patch: LlmCredentialUpdate
) -> LlmCredentialStatus | None:
    """Apply a partial edit to one connection; ``None`` when there is no such row.

    **An omitted ``api_key`` keeps the stored key**, so renaming a model does
    not demand a secret the user may not have to hand. What it does not allow
    is a change that would leave the stored key paired with a *different*
    provider or endpoint: the key was issued for one of those, and sending it
    to another is how a working credential turns into a 401 nobody can
    explain. Changing either one therefore requires the key to be supplied
    again.

    Raises:
        CredentialKeyRequiredError: the provider or the endpoint changed and
            no key came with the request.
        ValueError: the resulting provider/base-url combination is unusable.
        SecretBoxUnavailable: the new key could not be encrypted.
    """
    from src.db import access
    from src.db.byok import hint_of

    row = access.get_llm_credential(db, _self_scope(owner_id), credential_id)
    if row is None:
        return None

    supplied = patch.supplied()
    provider = patch.provider if patch.provider else row.provider
    model = patch.model if patch.model else row.model
    # An explicit ``base_url`` (including one sent as null, to clear it) wins;
    # an omitted one keeps the stored value.
    base_url = patch.base_url if "base_url" in supplied else row.base_url

    resolved = _resolved_base_url(provider, base_url)
    if resolved is not None:
        resolved = validate_base_url(resolved)

    key = patch.api_key if "api_key" in supplied else None
    if key is None and (provider != row.provider or resolved != row.base_url):
        raise CredentialKeyRequiredError(
            "Changing the provider or the endpoint requires a new API key: the "
            "stored key was issued for the previous provider and endpoint. Paste "
            "the key again to save this change."
        )

    updated = access.update_llm_credential(
        db,
        _self_scope(owner_id),
        credential_id,
        provider=provider,
        model=model,
        base_url=resolved,
        encrypted_key=encrypt_secret(key) if key is not None else None,
        hint=hint_of(key) if key is not None else None,
    )
    if updated is None:  # pragma: no cover - the row was read a moment ago
        return None
    db.commit()
    record_audit(
        ACTION_LLM_CREDENTIAL_SET,
        actor=SYSTEM_ACTOR,
        resource=f"llm:{provider}:{model}",
        outcome=OUTCOME_SUCCESS,
        owner_id=owner_id,
        metadata={
            "provider": provider,
            "model": model,
            "hint": updated.hint,
            "base_url": resolved or "",
            "credential_id": updated.id,
            "created": False,
            "key_rotated": key is not None,
        },
    )
    return _status_of(updated)


def activate_credential(
    db: Session, owner_id: str, credential_id: str
) -> LlmCredentialStatus | None:
    """Put one of the owner's connections in use; ``None`` when it is not theirs.

    This is the only way the key a job spends changes, which is why it is its
    own route and never a side effect of saving or of testing.
    """
    from src.db import access

    row = access.activate_llm_credential(db, _self_scope(owner_id), credential_id)
    if row is None:
        return None
    db.commit()
    record_audit(
        ACTION_LLM_CREDENTIAL_ACTIVATE,
        actor=SYSTEM_ACTOR,
        resource=f"llm:{row.provider}:{row.model}",
        outcome=OUTCOME_SUCCESS,
        owner_id=owner_id,
        metadata={
            "provider": row.provider,
            "model": row.model,
            "hint": row.hint,
            "credential_id": row.id,
        },
    )
    return _status_of(row)


def delete_credential(db: Session, owner_id: str, credential_id: str | None = None) -> bool:
    """Remove one of *owner_id*'s connections; True when it was there.

    With no *credential_id*, the connection in use is the one removed — the
    pre-multi-connection meaning of the call. **Removing the one in use needs
    no promotion step**: the next row in list order already holds the highest
    remaining rank, so the fallback is decided by the same ordering the
    console displays.
    """
    from src.db import access

    row = access.get_llm_credential(db, _self_scope(owner_id), credential_id)
    if row is None:
        return False
    removed = access.delete_llm_credential(db, _self_scope(owner_id), credential_id)
    if removed:
        db.commit()
        record_audit(
            ACTION_LLM_CREDENTIAL_DELETE,
            actor=SYSTEM_ACTOR,
            resource=f"user:{owner_id}",
            outcome=OUTCOME_SUCCESS,
            owner_id=owner_id,
            metadata={"credential_id": row.id, "provider": row.provider, "model": row.model},
        )
    return removed


def credential_state(db: Session, owner_id: str) -> CredentialState:
    """What the console shows: mode, availability, and every masked connection."""
    from src.db import access

    settings = get_settings()
    credentials = [
        _status_of(row) for row in access.list_llm_credentials(db, _self_scope(owner_id))
    ]
    source = key_material_source()
    available = settings.byok_mode != BYOK_MODE_DISABLED and source != "none"
    platform_configured = bool(settings.llm_api_key)
    # A stored connection only counts as "in use" when the deployment would
    # actually spend it. Under ``disabled`` the row is still listed — the
    # owner can see and remove it — but nothing runs on it, and answering
    # "user" would be a claim the next call would disprove.
    stored_in_use = bool(credentials) and settings.byok_mode != BYOK_MODE_DISABLED
    if stored_in_use:
        using = "user"
    elif platform_configured and settings.byok_mode != BYOK_MODE_REQUIRED:
        using = "platform"
    else:
        using = "none"
    return CredentialState(
        mode=settings.byok_mode,
        available=available,
        encryption=source,
        platform_configured=platform_configured,
        using=using,
        credential=credentials[0] if credentials else None,
        credentials=credentials,
    )


def _self_scope(owner_id: str):
    """A scope that is exactly *owner_id* — never a superuser.

    A credential is self-owned by construction; the platform's cross-owner
    audit exception does not extend to it.
    """
    from src.db.access import UserScope

    return UserScope(user_id=owner_id, is_superuser=False)


# -- resolution ---------------------------------------------------------------


def resolve_credential(
    db: Session, owner_id: str, credential_id: str | None = None
) -> ResolvedCredential | None:
    """The decrypted credential for *owner_id*, or ``None``.

    Without *credential_id* this is the connection in use; with one it is
    exactly that connection, owner-scoped. The base URL is re-validated
    defensively: a value that was acceptable when it was stored must not
    become a passthrough if the rule later tightens. A row that no longer
    decrypts (rotated or lost key material) raises
    :class:`SecretBoxUnavailable` with an actionable message.
    """
    from src.db import access

    row = access.get_llm_credential(db, _self_scope(owner_id), credential_id)
    if row is None:
        return None
    if row.base_url:
        validate_base_url(row.base_url)
    return ResolvedCredential(
        id=row.id,
        provider=row.provider,
        model=row.model,
        api_key=decrypt_secret(row.encrypted_key),
        base_url=row.base_url,
        updated_at=row.updated_at,
    )


_clients: dict[tuple[str, str], LLMClient] = {}


def reset_client_cache() -> None:
    """Drop the cached BYOK clients (tests change credentials)."""
    _clients.clear()


def _build_byok_client(owner_id: str, credential: ResolvedCredential) -> LLMClient:
    """Build the client that spends *owner_id*'s key.

    The provider is built (and its config errors raised) here rather than on
    first use, so a credential the provider adapter cannot support is a
    configuration error at once — :func:`resolve_client` translates it into
    an actionable message. The provider's own SDK client is still created
    lazily inside the adapter, so building one costs nothing.
    """
    settings = get_settings()
    # The breaker and the pacer are per **connection**, not per user: two keys
    # for the same provider can be healthy and broken independently, and a
    # failure counted against one must not gate the other. The owner is still
    # in the name, so a bucket is diagnosable by account.
    bucket = f"llm:byok:{owner_id}:{credential.id}"
    provider = _CredentialProvider(
        build_provider(
            credential.provider,
            api_key=credential.api_key,
            model=credential.model,
            base_url=credential.base_url,
            timeout=settings.llm_timeout,
        )
    )
    return LLMClient(
        provider=credential.provider,
        api_key=credential.api_key,
        model=credential.model,
        temperature=settings.llm_temperature,
        base_url=credential.base_url,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
        max_rpm=settings.llm_max_rpm,
        limiter=get_limiter(bucket, settings.llm_max_rpm, _LIMIT_WINDOW_SECONDS),
        breaker_scope=bucket,
        spend_source=SPEND_BYOK,
        provider_instance=provider,
    )


class _CredentialProvider:
    """A provider that reports *why* a personal key failed, without the provider's words.

    The platform client's failure messages are allowed to carry the
    provider's own error text (scrubbed of the key) because the operator
    reading them is the one who configured that provider. A user's stored key
    is different: the useful answer is "your key was rejected, update it",
    and the provider's 401 body is not the user's business — nor ours to
    relay. Every non-transient configuration failure is therefore rewritten
    into :class:`LLMCredentialError` with our own message.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.name = getattr(inner, "name", "unknown")

    def complete(self, request):
        try:
            return self._inner.complete(request)
        except LLMCredentialError:
            raise
        except LLMConfigError as exc:
            raise LLMCredentialError(
                "Your stored model key was rejected by the provider or is "
                "unusable — update it under Account → Model credentials."
            ) from exc


def _cached_client(owner_id: str, credential: ResolvedCredential) -> LLMClient:
    """The client for this credential revision, built once.

    The cache key carries a digest of the credential **including the key
    itself**, so rotating the key takes effect on the very next call without
    a restart — a timestamp alone would miss a same-second rotation. The
    digest never leaves this process: it is a cache key, not a record. The
    cache is bounded; eviction costs a rebuild, never correctness.
    """
    digest = hashlib.sha256(
        f"{credential.provider}|{credential.model}|{credential.base_url}|{credential.api_key}".encode()
    ).hexdigest()[:24]
    key = (owner_id, digest)
    client = _clients.get(key)
    if client is None:
        if len(_clients) >= _CLIENT_CACHE_SIZE:
            _clients.pop(next(iter(_clients)))
        client = _build_byok_client(owner_id, credential)
        _clients[key] = client
    return client


def resolve_client() -> LLMClient:
    """The client the current context should use: the user's own, or the platform's.

    "The user's own" is the connection **in use** — the one the owner
    activated, or the one that predates activation. Merely storing a second
    connection never changes which client this returns.

    Raises:
        LLMCredentialError: the deployment requires a personal key and the
            caller has none, or the caller's stored credential could not be
            built. The message is ours and actionable (the console may show
            it verbatim).
    """
    settings = get_settings()
    owner_id = current_tenant()
    if not owner_id or settings.byok_mode == BYOK_MODE_DISABLED:
        return get_client()

    from src.db.session import SessionLocal

    try:
        with SessionLocal() as db:
            credential = resolve_credential(db, owner_id)
    except SecretBoxUnavailable as exc:
        raise LLMCredentialError(str(exc)) from exc

    if credential is None:
        if settings.byok_mode == BYOK_MODE_REQUIRED:
            raise LLMCredentialError(
                "This deployment requires your own model key: register one under "
                "Account → Model credentials before running a tailoring or research job."
            )
        return get_client()
    try:
        return _cached_client(owner_id, credential)
    except LLMConfigError as exc:
        # The provider adapter refused the stored configuration (an unknown
        # provider, a missing base URL). That is the user's credential to
        # fix, and the message says so.
        raise LLMCredentialError(
            "Your stored model credential is not usable "
            f"({type(exc).__name__}) — check the provider, model and base URL "
            "under Account → Model credentials."
        ) from exc


def mark_used(owner_id: str, credential_id: str | None = None) -> None:
    """Record that a connection was just exercised.

    Without an id it stamps the connection in use; with one it stamps exactly
    that connection. Never raises: bookkeeping must not break a call that
    otherwise succeeded.
    """
    from src.db.session import SessionLocal

    try:
        with SessionLocal() as db:
            from src.db import access

            access.touch_llm_credential(db, _self_scope(owner_id), credential_id)
            db.commit()
    except Exception as exc:  # noqa: BLE001 - bookkeeping must never break a call
        logger.debug("Could not record credential use: %s", exc)


def test_credential(db: Session, owner_id: str, credential_id: str | None = None) -> dict:
    """Make one small call with a stored credential, to prove it works.

    Without *credential_id* the connection in use is exercised; with one,
    exactly that connection — testing a spare provider must not disturb which
    one is in use. The call is deliberately tiny and bounded by the client's
    own timeout. It spends the *user's* quota — which is why storing a key
    does not test it silently.

    Returns:
        ``{"ok": True, "provider", "model", "latency_ms"}`` on success;
        ``{"ok": False, "provider", "model", "error_type"}`` on a provider
        failure. The error text is a type name, never a provider message:
        those can echo request material.

    Raises:
        LLMConfigError: there is no such stored connection to exercise.
    """
    credential = resolve_credential(db, owner_id, credential_id)
    if credential is None:
        raise LLMConfigError("No stored credential to test")
    client = _build_byok_client(owner_id, credential)

    started = datetime.now(UTC)
    try:
        client.generate_text("Reply with the single word: ok")
    except LLMError as exc:
        return {
            "ok": False,
            "provider": credential.provider,
            "model": credential.model,
            "error_type": type(exc).__name__,
        }
    latency_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    mark_used(owner_id, credential.id)
    record_audit(
        ACTION_LLM_CREDENTIAL_TEST,
        actor=SYSTEM_ACTOR,
        resource=f"llm:{credential.provider}:{credential.model}",
        outcome=OUTCOME_SUCCESS,
        owner_id=owner_id,
        metadata={
            "provider": credential.provider,
            "model": credential.model,
            "credential_id": credential.id,
        },
    )
    return {
        "ok": True,
        "provider": credential.provider,
        "model": credential.model,
        "latency_ms": latency_ms,
    }
