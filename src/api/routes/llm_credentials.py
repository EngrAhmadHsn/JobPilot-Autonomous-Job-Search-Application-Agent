"""Bring-your-own-key API (WS-22).

The caller's own model connections. The resource is a **collection** now: an
account may hold several provider keys, so the routes are

- ``GET    /api/llm/credentials``                every connection, masked, in use first;
- ``POST   /api/llm/credentials``                add one (201);
- ``PUT    /api/llm/credentials``                register or replace the one in use (legacy);
- ``PATCH  /api/llm/credentials/{id}``           edit one, keeping its key unless told otherwise;
- ``DELETE /api/llm/credentials/{id}``           remove one;
- ``POST   /api/llm/credentials/{id}/activate``  make one the connection in use;
- ``POST   /api/llm/credentials/{id}/test``      prove one works, with one small call;
- ``PUT/DELETE/POST .../credentials[/test]``     the single-credential contract, kept working.

**The key never travels back.** The read returns a mask (the last four
characters), the provider and the model. There is no route that returns the
key and no field it could hide in: the response model has no such field.

**The scope decides whose rows.** Every route takes
:func:`src.api.scope.current_scope` and the store is keyed by the scope's own
id, so a request can only ever touch its own connections. An identifier in
the path names a row *within* that scope: a row that belongs to somebody else
is a 404, exactly as if it did not exist.

**Adding is not switching.** ``POST`` stores a connection; the key a job
spends changes only on ``activate``. A user who pastes a second provider key
to try it out has not silently redirected every later call.

**Nothing raises where a fact belongs.** A provider failure on a test route
is a 200 with ``ok: false`` and an error *type*: the operator asked "does
this key work", the answer is "no", and a 500 would say something untrue
about our own service.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.db.session import get_db
from src.llm.credentials import (
    BYOK_MODE_DISABLED,
    CredentialKeyRequiredError,
    CredentialState,
    LlmCredentialInput,
    LlmCredentialStatus,
    LlmCredentialUpdate,
    activate_credential,
    add_credential,
    credential_state,
    delete_credential,
    get_credential,
    store_credential,
    test_credential,
    update_credential,
)
from src.llm.errors import LLMConfigError
from src.security.secrets import SecretBoxUnavailable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm/credentials", tags=["llm"])

#: The response when a connection id in the path is not the caller's. The same
#: answer for "no such row" and "somebody else's row": the API must not become
#: an oracle for which ids exist.
_NO_SUCH_CONNECTION = "No such saved model connection"


class CredentialDeleteAck(BaseModel):
    """The result of removing a stored credential."""

    removed: bool


class CredentialTestResult(BaseModel):
    """What happened when the stored credential was exercised.

    ``error_type`` is the exception *class name* — never a provider message,
    which can echo request material back.
    """

    ok: bool
    provider: str
    model: str
    latency_ms: int | None = None
    error_type: str | None = Field(default=None, description="Exception type on failure")


def _available_or_503() -> None:
    """Refuse a write when this deployment cannot hold a credential.

    Two ways that happens: BYOK is disabled by configuration, or the
    deployment has no encryption key material. Both are answers about the
    deployment, and both are better said plainly (403/503) than discovered as
    a half-stored row.
    """
    from src.config.settings import get_settings
    from src.security.secrets import key_material_source

    if get_settings().byok_mode == BYOK_MODE_DISABLED:
        raise HTTPException(
            status_code=403,
            detail="This deployment has disabled personal model keys (BYOK_MODE=disabled).",
        )
    if key_material_source() == "none":
        raise HTTPException(
            status_code=503,
            detail=(
                "This deployment cannot store credentials: no encryption key material "
                "is configured (set BYOK_ENCRYPTION_KEY or AUTH_SECRET)."
            ),
        )


def _write_failure(exc: Exception) -> HTTPException:
    """Translate a write failure into the status the caller can act on.

    A 422 for anything the request itself made unusable (an unsupported
    provider, a base URL that fails the SSRF rule, an endpoint change without
    a key) and a 503 when this deployment has nowhere to put a secret. Never
    a 500: nothing here is our own fault, and a 500 would say otherwise.
    """
    if isinstance(exc, SecretBoxUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, CredentialKeyRequiredError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("", response_model=CredentialState)
def get_credentials(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> CredentialState:
    """The caller's connections — masked, never a key."""
    return credential_state(db, scope.user_id)


@router.post("", response_model=LlmCredentialStatus, status_code=status.HTTP_201_CREATED)
def create_credential(
    payload: LlmCredentialInput,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> LlmCredentialStatus:
    """Add a connection for the caller.

    The connection is stored but **not** put in use: a job keeps running on
    whichever connection already was. Registering does not test the key
    either — the test call is billed to the user's own account, so it stays
    an explicit action.
    """
    _available_or_503()
    try:
        return add_credential(db, scope.user_id, payload)
    except (SecretBoxUnavailable, ValueError) as exc:
        raise _write_failure(exc) from exc


@router.put("", response_model=LlmCredentialStatus)
def put_credentials(
    payload: LlmCredentialInput,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> LlmCredentialStatus:
    """Register or **replace the connection in use** (the single-credential contract).

    Kept for clients that predate multiple connections, and still the right
    call for "this account should have exactly this one key". On an account
    holding several connections it edits the one in use; it never adds a
    second.
    """
    _available_or_503()
    try:
        return store_credential(db, scope.user_id, payload)
    except (SecretBoxUnavailable, ValueError) as exc:
        raise _write_failure(exc) from exc


@router.patch("/{credential_id}", response_model=LlmCredentialStatus)
def patch_credential(
    credential_id: str,
    payload: LlmCredentialUpdate,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> LlmCredentialStatus:
    """Edit one of the caller's connections.

    An omitted ``api_key`` keeps the stored key, so editing a model name does
    not ask for a secret the user may not have to hand. Changing the provider
    or the endpoint **does** require one — see
    :func:`src.llm.credentials.update_credential`.
    """
    _available_or_503()
    try:
        updated = update_credential(db, scope.user_id, credential_id, payload)
    except (SecretBoxUnavailable, ValueError) as exc:
        raise _write_failure(exc) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=_NO_SUCH_CONNECTION)
    return updated


@router.post("/{credential_id}/activate", response_model=LlmCredentialStatus)
def activate_saved_credential(
    credential_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> LlmCredentialStatus:
    """Make one of the caller's connections the one their calls spend."""
    _available_or_503()
    activated = activate_credential(db, scope.user_id, credential_id)
    if activated is None:
        raise HTTPException(status_code=404, detail=_NO_SUCH_CONNECTION)
    return activated


@router.delete("/{credential_id}", response_model=CredentialDeleteAck)
def delete_saved_credential(
    credential_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> CredentialDeleteAck:
    """Remove one of the caller's connections.

    Removing the connection in use promotes the next one in display order, so
    this route needs no follow-up call. Allowed even when the deployment has
    refused new writes: a user must always be able to take their key back.
    """
    if not delete_credential(db, scope.user_id, credential_id):
        raise HTTPException(status_code=404, detail=_NO_SUCH_CONNECTION)
    return CredentialDeleteAck(removed=True)


@router.delete("", response_model=CredentialDeleteAck)
def delete_credentials(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> CredentialDeleteAck:
    """Remove the connection in use (the single-credential contract, idempotent)."""
    return CredentialDeleteAck(removed=delete_credential(db, scope.user_id))


@router.post("/{credential_id}/test", response_model=CredentialTestResult)
def test_saved_credential(
    credential_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> CredentialTestResult:
    """Exercise **one named** connection and report the outcome.

    Testing a spare provider answers a question about it and nothing else: it
    does not make it the connection in use, and it spends the user's quota on
    the key they asked about.
    """
    _available_or_503()
    if get_credential(db, scope.user_id, credential_id) is None:
        raise HTTPException(status_code=404, detail=_NO_SUCH_CONNECTION)
    return _exercise(db, scope.user_id, credential_id)


@router.post("/test", response_model=CredentialTestResult)
def test_credentials(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> CredentialTestResult:
    """Make one small call with the connection in use (the single-credential contract)."""
    _available_or_503()
    return _exercise(db, scope.user_id, None)


def _exercise(db: Session, owner_id: str, credential_id: str | None) -> CredentialTestResult:
    """Run the small provider call and map its failure modes onto statuses."""
    try:
        result = test_credential(db, owner_id, credential_id)
    except SecretBoxUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMConfigError as exc:
        # No stored connection to exercise — a conflict with the resource's
        # state, not a server fault.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CredentialTestResult(**result)
