"""Append-only audit trail (WS-06 · SEC-13).

Every external action writes one audit event: a resume upload, a job search,
a match, an application prepare/approve/reject/submit/verify, and every
security guard that tripped. The event carries *what* happened, *who* caused
it, and the outcome — never a secret, never raw personal data (the metadata
is sanitized by :mod:`src.security.redaction`).

The store is append-only by construction: this module can insert events, and
nothing here can update or delete one. A database outage is logged as an
error and never raised, because a failing audit store must not crash a
request in flight; the log line remains as the fallback trail.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.db.audit import AuditEventDB
from src.db.users import LEGACY_OWNER_ID
from src.security.redaction import sanitize_metadata

logger = logging.getLogger(__name__)

# The canonical action names, so the trail can be queried by action.
ACTION_RESUME_UPLOAD = "resume.upload"
ACTION_JOB_SEARCH = "job.search"
ACTION_MATCH_COMPUTE = "match.compute"
ACTION_PREPARE = "application.prepare"
ACTION_APPROVE = "application.approve"
ACTION_REJECT = "application.reject"
ACTION_SUBMIT = "application.submit"
ACTION_VERIFY = "application.verify"
ACTION_PERMISSION_DENIED = "application.permission_denied"
ACTION_UNSAFE_NAVIGATION = "application.unsafe_navigation"
ACTION_BLOCKED_CHALLENGE = "application.blocked_challenge"
ACTION_ALLOWLIST_VIOLATION = "allowlist.violation"
# WS-07: the application lifecycle. A transition is a state change of a
# tracked application; a tracking event is an entry in its history that is
# not a state change (a granted approval, a recorded evidence row).
ACTION_TRANSITION = "application.transition"
ACTION_TRACKING_EVENT = "application.event"
# WS-10: the token spend of the LLM client. One row per generation call,
# holding counts only — never a prompt, never an answer, never a key.
ACTION_LLM_USAGE = "llm.usage"
# WS-14 · A1: the identity lifecycle. One row per registration, login,
# logout, password change, session revocation and account deletion.
# The action is always ``auth``; the *event* is in the metadata, so the
# trail can be queried by kind without a combinatorial action vocabulary.
ACTION_AUTH = "auth"

# Outcomes.
OUTCOME_SUCCESS = "success"
OUTCOME_BLOCKED = "blocked"
OUTCOME_DENIED = "denied"
OUTCOME_ERROR = "error"

# The actor used when a step is performed by the system itself.
SYSTEM_ACTOR = "system"


class AuditEvent(BaseModel):
    """One recorded action."""

    id: int | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    #: The principal the row belongs to (WS-13 · A0). An audit row is
    #: user data like any other: it is readable only by its owner (and by
    #: the platform's audit view).
    owner_id: str = LEGACY_OWNER_ID
    actor: str
    action: str
    resource: str
    outcome: str
    workflow_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _write_row(event: AuditEvent, session: Session | None) -> int | None:
    """Insert the event; return the row id (or ``None`` when the write failed)."""
    owns_session = session is None
    if session is None:
        from src.db.session import SessionLocal

        session = SessionLocal()
    try:
        row = AuditEventDB(
            owner_id=event.owner_id,
            actor=event.actor,
            action=event.action,
            resource=event.resource,
            outcome=event.outcome,
            workflow_id=event.workflow_id,
            extra_metadata=event.metadata,
        )
        session.add(row)
        session.commit()
        return row.id
    finally:
        if owns_session:
            session.close()


def record_audit(
    action: str,
    *,
    actor: str,
    resource: str,
    outcome: str,
    owner_id: str = LEGACY_OWNER_ID,
    metadata: dict[str, Any] | None = None,
    workflow_id: str | None = None,
    session: Session | None = None,
) -> AuditEvent:
    """Record one action in the audit trail.

    Args:
        action: What happened (see the ``ACTION_*`` constants).
        actor: Who caused it — an operator identity, an adapter name, or
            ``"system"``.
        resource: The object acted on (an approval id, a profile id, ...).
        outcome: The result (see the ``OUTCOME_*`` constants).
        metadata: Extra detail; sanitized before it is stored, so a secret
            key is dropped and personal data is masked.
        workflow_id: Correlation id of the application workflow, when there is
            one.
        session: An existing database session to use. When omitted, a short
            lived session is opened.

    Returns:
        The recorded event, with sanitized metadata. The function never
        raises: a failing audit store is logged as an error and the event is
        still returned (and still logged).
    """
    event = AuditEvent(
        owner_id=owner_id,
        actor=actor,
        action=action,
        resource=resource,
        outcome=outcome,
        workflow_id=workflow_id,
        metadata=sanitize_metadata(metadata),
    )

    try:
        event.id = _write_row(event, session)
    except Exception as exc:  # noqa: BLE001 - the audit store must never break a request
        logger.error(
            "Audit store write failed for action %s: %s", action, exc, extra={"action": action}
        )

    logger.info(
        "audit action=%s actor=%s resource=%s outcome=%s workflow_id=%s",
        event.action,
        event.actor,
        event.resource,
        event.outcome,
        event.workflow_id,
    )
    return event
