"""Bring-your-own-key API (WS-22).

Four routes, one resource — **the caller's own** credential:

- ``GET  /api/llm/credentials``        what is in use, and what is stored;
- ``PUT  /api/llm/credentials``        register or replace it;
- ``DELETE /api/llm/credentials``      remove it;
- ``POST /api/llm/credentials/test``   prove it works, with one small call.

**The key never travels back.** The read returns a mask (the last four
characters), the provider and the model. There is no route that returns the
key and no field it could hide in: the response model has no such field.

**The scope decides whose row.** Every route takes
:func:`src.api.scope.current_scope` and the store is keyed by the scope's own
id, so a request can only ever touch its own credential — there is no
identifier in the body to point at somebody else's.

**Nothing raises where a fact belongs.** A provider failure on the test
route is a 200 with ``ok: false`` and an error *type*: the operator asked
"does this key work", the answer is "no", and a 500 would say something
untrue about our own service.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.db.session import get_db
from src.llm.credentials import (
    BYOK_MODE_DISABLED,
    CredentialState,
    LlmCredentialInput,
    LlmCredentialStatus,
    credential_state,
    delete_credential,
    store_credential,
    test_credential,
)
from src.llm.errors import LLMConfigError
from src.security.secrets import SecretBoxUnavailable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm/credentials", tags=["llm"])


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


@router.get("", response_model=CredentialState)
def get_credentials(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> CredentialState:
    """The caller's credential state — masked, never the key."""
    return credential_state(db, scope.user_id)


@router.put("", response_model=LlmCredentialStatus)
def put_credentials(
    payload: LlmCredentialInput,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> LlmCredentialStatus:
    """Register or replace the caller's own provider credential.

    The key is encrypted before it is stored; the response carries the mask.
    Registering does **not** test the key — that spends the user's quota, so
    it is an explicit action (``POST .../test``).
    """
    _available_or_503()
    try:
        return store_credential(db, scope.user_id, payload)
    except SecretBoxUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        # The base URL failed the SSRF guard or the provider combination is
        # unusable — a 422 the caller can act on, not a 500.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("", response_model=CredentialDeleteAck)
def delete_credentials(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> CredentialDeleteAck:
    """Remove the caller's stored credential (idempotent)."""
    try:
        removed = delete_credential(db, scope.user_id)
    except SecretBoxUnavailable as exc:  # pragma: no cover - delete needs no key
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return CredentialDeleteAck(removed=removed)


@router.post("/test", response_model=CredentialTestResult)
def test_credentials(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> CredentialTestResult:
    """Make one small call with the stored credential and report the outcome."""
    try:
        result = test_credential(db, scope.user_id)
    except SecretBoxUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMConfigError as exc:
        # No stored credential to exercise — a conflict with the resource's
        # state, not a server fault.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CredentialTestResult(**result)
