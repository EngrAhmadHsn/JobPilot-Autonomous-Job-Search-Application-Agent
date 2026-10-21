"""The application lifecycle: statuses, transitions, and the event log (WS-07).

This module is the domain layer of the tracking feature. It answers two
questions and nothing else:

1. **May this application move to that status?** — the transition matrix.
2. **Who caused the move?** — the actor rule.

The rules exist because the agent must never invent an outcome. The agent can
prepare, submit and verify an application; it can never decide that an
employer made an offer. A *human outcome* (``INTERVIEW``, ``OFFER``,
``REJECTED``, ``WITHDRAWN``) is therefore only settable by a human actor, and
the actor string says who acted in a form that cannot be faked by accident:
``agent``, ``system`` or ``human:<who>``.

Every state change appends exactly one row to the append-only
``application_events`` table, so an application's history is complete and
ordered, and cannot be rewritten.

The module has no HTTP knowledge and no LangGraph knowledge: it is a state
machine plus an event log, usable from the API, the graph, or a script.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.applications import ApplicationDB, ApplicationEventDB, build_application_row
from src.db.jobs import JobDB
from src.db.users import LEGACY_OWNER_ID
from src.security.audit import (
    ACTION_TRACKING_EVENT,
    ACTION_TRANSITION,
    OUTCOME_SUCCESS,
    record_audit,
)
from src.security.redaction import sanitize_metadata

logger = logging.getLogger(__name__)


class ApplicationStatus(str, Enum):
    """The lifecycle states of a tracked application."""

    DISCOVERED = "discovered"
    MATCHED = "matched"
    SHORTLISTED = "shortlisted"
    PREPARED = "prepared"
    AWAITING_APPROVAL = "awaiting_approval"
    SUBMITTED = "submitted"
    VERIFIED = "verified"
    REJECTED = "rejected"
    INTERVIEW = "interview"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"


#: The legal moves. This matrix is the single source of truth: the API, the
#: graph and the tests all read it, so the rules cannot drift apart.
#:
#: A self-transition is not a transition — ``X -> X`` is illegal everywhere.
ALLOWED_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.DISCOVERED: frozenset(
        {ApplicationStatus.MATCHED, ApplicationStatus.REJECTED}
    ),
    ApplicationStatus.MATCHED: frozenset(
        {ApplicationStatus.SHORTLISTED, ApplicationStatus.DISCOVERED}
    ),
    ApplicationStatus.SHORTLISTED: frozenset(
        {ApplicationStatus.PREPARED, ApplicationStatus.MATCHED}
    ),
    ApplicationStatus.PREPARED: frozenset(
        {ApplicationStatus.AWAITING_APPROVAL, ApplicationStatus.SHORTLISTED}
    ),
    ApplicationStatus.AWAITING_APPROVAL: frozenset(
        {ApplicationStatus.SUBMITTED, ApplicationStatus.REJECTED, ApplicationStatus.PREPARED}
    ),
    ApplicationStatus.SUBMITTED: frozenset(
        {ApplicationStatus.VERIFIED, ApplicationStatus.AWAITING_APPROVAL}
    ),
    ApplicationStatus.VERIFIED: frozenset(
        {
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.OFFER,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.INTERVIEW: frozenset(
        {ApplicationStatus.OFFER, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}
    ),
    ApplicationStatus.OFFER: frozenset({ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}),
    ApplicationStatus.REJECTED: frozenset(),
    ApplicationStatus.WITHDRAWN: frozenset(),
}

#: The statuses that record an *outcome* — something that happened to the
#: application, rather than something the agent did to it. Only a human may
#: set them.
HUMAN_OUTCOME_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    }
)

#: The statuses with no outgoing transitions.
TERMINAL_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}
)

# --- Actors ---------------------------------------------------------------

#: The actor identity of the agent itself.
AGENT_ACTOR = "agent"
#: The actor identity of the platform (schedulers, maintenance).
SYSTEM_ACTOR = "system"
#: The prefix that marks an identity as a named human.
HUMAN_ACTOR_PREFIX = "human:"

# --- Event types ----------------------------------------------------------

EVENT_APPLICATION_CREATED = "application_created"
EVENT_STATUS_TRANSITION = "status_transition"
EVENT_APPROVAL_GRANTED = "approval_granted"
EVENT_APPROVAL_REJECTED = "approval_rejected"
EVENT_EVIDENCE_RECORDED = "evidence_recorded"
EVENT_VERIFICATION_FAILED = "verification_failed"

#: The source used for a listing that has no stored row behind it.
MANUAL_JOB_SOURCE = "manual"


class TrackingError(Exception):
    """Base class for the tracking errors."""


class IllegalTransitionError(TrackingError):
    """The requested move is not in the transition matrix."""


class ActorNotPermittedError(TrackingError):
    """The actor may not set the requested status."""


def is_human_actor(actor: str) -> bool:
    """True when *actor* names a human.

    A human identity is the reserved ``human:`` prefix followed by a name.
    The prefix is what makes the distinction checkable: without it
    ``actor="agent"`` and ``actor="ada"`` would be indistinguishable, and the
    human-outcome rule would be unenforceable.
    """
    if not actor:
        return False
    return actor.startswith(HUMAN_ACTOR_PREFIX) and len(actor) > len(HUMAN_ACTOR_PREFIX)


def human_actor(name: str) -> str:
    """Normalize a free-form operator name into a human actor identity.

    Idempotent: an identity that is already in the ``human:<name>`` form is
    returned unchanged.
    """
    if is_human_actor(name):
        return name
    return f"{HUMAN_ACTOR_PREFIX}{name.strip()}"


def _status_value(status: ApplicationStatus | str | None) -> str | None:
    """The stored form of a status (``None`` stays ``None``)."""
    if status is None:
        return None
    if isinstance(status, ApplicationStatus):
        return status.value
    return str(status)


def _current_status(app: ApplicationDB) -> ApplicationStatus:
    """The application's current status.

    Raises:
        TrackingError: the stored status is not a known status.
    """
    try:
        return ApplicationStatus(app.status)
    except ValueError as exc:
        raise TrackingError(f"Application {app.id!r} has an unknown status {app.status!r}") from exc


def record_event(
    db: Session,
    application_id: str,
    event_type: str,
    *,
    owner_id: str = LEGACY_OWNER_ID,
    actor: str,
    from_status: ApplicationStatus | str | None = None,
    to_status: ApplicationStatus | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ApplicationEventDB:
    """Append one event to an application's history.

    This is the **only** way an event is written, and it only ever inserts.
    The event log is append-only: a history that can be rewritten is not a
    history.

    Args:
        db: The session to write through.
        application_id: The application the event belongs to.
        event_type: What happened (see the ``EVENT_*`` constants).
        actor: Who caused it.
        from_status: The status the application was in, when the event is a
            state change.
        to_status: The status the application moved to.
        metadata: Extra detail; sanitized before it is stored, so a secret
            key is dropped and personal data is masked.

    Returns:
        The stored event row.
    """
    event = ApplicationEventDB(
        owner_id=owner_id,
        application_id=application_id,
        event_type=event_type,
        actor=actor,
        from_status=_status_value(from_status),
        to_status=_status_value(to_status),
        extra_metadata=sanitize_metadata(metadata),
        recorded_at=datetime.now(UTC),
    )
    db.add(event)
    db.commit()

    record_audit(
        ACTION_TRACKING_EVENT,
        actor=actor,
        resource=application_id,
        outcome=OUTCOME_SUCCESS,
        metadata={
            "event_type": event_type,
            "from_status": _status_value(from_status),
            "to_status": _status_value(to_status),
            **(metadata or {}),
        },
        session=db,
    )
    return event


def transition(
    app: ApplicationDB,
    to: ApplicationStatus,
    *,
    actor: str,
    db: Session,
    metadata: dict[str, Any] | None = None,
    event_type: str = EVENT_STATUS_TRANSITION,
    application_url: str | None = None,
) -> ApplicationDB:
    """Move an application to a new status and record the move.

    The move is validated *before* anything is written: an illegal move
    leaves the row, the event log and the audit trail exactly as they were.

    Args:
        app: The application row to move.
        to: The status to move to.
        actor: Who caused the move — ``agent``, ``system`` or
            ``human:<who>``.
        db: The session to write through.
        metadata: Extra detail for the event; sanitized before it is stored.
        event_type: The event type to record. The default describes a plain
            state change; a specialization (for example
            ``verification_failed``) describes *what kind* of change it was.
        application_url: The URL the application landed on, recorded on the
            row when it is given.

    Returns:
        The moved application row.

    Raises:
        ActorNotPermittedError: a human outcome was requested by an actor
            that is not a human.
        IllegalTransitionError: the move is not in the transition matrix.
    """
    current = _current_status(app)

    if to in HUMAN_OUTCOME_STATUSES and not is_human_actor(actor):
        raise ActorNotPermittedError(
            f"Status {to.value!r} is a human outcome and may only be set by a human actor; "
            f"got {actor!r}."
        )

    allowed = ALLOWED_TRANSITIONS[current]
    if to not in allowed:
        raise IllegalTransitionError(
            f"Application {app.id!r} cannot move from {current.value!r} to {to.value!r}. "
            f"Allowed: {sorted(status.value for status in allowed) or 'none'}."
        )

    now = datetime.now(UTC)
    app.status = to.value
    app.updated_at = now
    if to is ApplicationStatus.SUBMITTED:
        # The latest submission: re-submitting after a failed verification
        # moves the timestamp forward.
        app.submitted_at = now
    if to is ApplicationStatus.VERIFIED:
        app.verified_at = now
    if application_url:
        app.application_url = application_url

    event = ApplicationEventDB(
        # The event belongs to the same owner as the application it
        # records, so it is read from the row rather than taken as a
        # parameter that could disagree with it.
        owner_id=app.owner_id,
        application_id=app.id,
        event_type=event_type,
        actor=actor,
        from_status=current.value,
        to_status=to.value,
        extra_metadata=sanitize_metadata(metadata),
        recorded_at=now,
    )
    db.add(event)
    # The row and its event are committed together: a crash can never leave
    # a status without the event that explains it.
    db.commit()

    record_audit(
        ACTION_TRANSITION,
        actor=actor,
        outcome=OUTCOME_SUCCESS,
        resource=app.id,
        metadata={
            "from_status": current.value,
            "to_status": to.value,
            "event_type": event_type,
            **(metadata or {}),
        },
        workflow_id=app.workflow_id,
        session=db,
    )
    return app


def manual_job_id(job_url: str) -> str:
    """The deterministic id of the stub listing for a job URL.

    Deriving the id from the URL means preparing the same posting twice
    resolves to the same listing instead of creating a second one.
    """
    digest = hashlib.sha256(job_url.encode("utf-8")).hexdigest()[:16]
    return f"{MANUAL_JOB_SOURCE}:{digest}"


def ensure_job_row(
    db: Session,
    job_url: str,
    job_title: str,
    company_name: str,
) -> str:
    """Resolve the listing id for a job URL, creating a stub row when needed.

    A tracked application always points at a real row of the ``jobs`` table.
    The prepare flow is called with a raw URL that may have no stored listing
    behind it, so a **stub** listing is created: it records the URL the agent
    acted on, and it is not a claim that the job exists on a board.

    Args:
        db: The session to write through.
        job_url: The posting URL.
        job_title: The job title (for the stub row).
        company_name: The company name (for the stub row).

    Returns:
        The id of the ``jobs`` row.
    """
    existing = db.scalars(select(JobDB).where(JobDB.application_url == job_url)).first()
    if existing is not None:
        return existing.id

    job_id = manual_job_id(job_url)
    if db.get(JobDB, job_id) is None:
        db.add(
            JobDB(
                id=job_id,
                source=MANUAL_JOB_SOURCE,
                title=job_title,
                company=company_name,
                application_url=job_url,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            # Another writer created the same stub concurrently.
            db.rollback()
    return job_id


def create_application(
    db: Session,
    *,
    owner_id: str = LEGACY_OWNER_ID,
    workflow_id: str,
    adapter_name: str,
    job_url: str,
    job_title: str,
    company_name: str,
    approval_id: str | None = None,
    profile_id: str | None = None,
    tailored_resume_id: str | None = None,
    status: ApplicationStatus = ApplicationStatus.PREPARED,
) -> ApplicationDB:
    """Create a tracked application and record its creation.

    The application is created **already prepared**: the system never matched
    or shortlisted anything in this flow, so those states are not written —
    a history is not a decoration, and inventing a step that never happened
    would be a fabricated fact.

    Args:
        db: The session to write through.
        workflow_id: The application workflow this belongs to.
        adapter_name: The adapter that prepared it.
        job_url: The posting URL.
        job_title: The job title.
        company_name: The company name.
        approval_id: The WS-06 approval request that gates it.
        profile_id: The candidate profile, when the caller knows it.
        tailored_resume_id: The WS-05 tailoring, when the caller knows it.
        status: The status to create it in.

    Returns:
        The created application row.
    """
    job_id = ensure_job_row(db, job_url, job_title, company_name)
    row = build_application_row(
        # The row belongs to the account that prepared it. Leaving this
        # to the default would put every tracked application on the
        # legacy owner — invisible to the account that created it, and
        # claimed by whoever registers next.
        owner_id=owner_id,
        workflow_id=workflow_id,
        job_id=job_id,
        adapter_name=adapter_name,
        job_url=job_url,
        job_title=job_title,
        company_name=company_name,
        status=status.value,
        approval_id=approval_id,
        profile_id=profile_id,
        tailored_resume_id=tailored_resume_id,
    )
    db.add(row)
    db.commit()

    record_event(
        db,
        row.id,
        EVENT_APPLICATION_CREATED,
        owner_id=owner_id,
        actor=AGENT_ACTOR,
        to_status=status,
        metadata={
            "workflow_id": workflow_id,
            "job_id": job_id,
            "adapter_name": adapter_name,
        },
    )
    return row


def find_application(
    db: Session,
    *,
    application_id: str | None = None,
    approval_id: str | None = None,
    workflow_id: str | None = None,
) -> ApplicationDB | None:
    """Find a tracked application by id, approval id or workflow id."""
    if application_id:
        return db.get(ApplicationDB, application_id)
    if approval_id:
        return db.scalars(
            select(ApplicationDB).where(ApplicationDB.approval_id == approval_id)
        ).first()
    if workflow_id:
        return db.scalars(
            select(ApplicationDB).where(ApplicationDB.workflow_id == workflow_id)
        ).first()
    return None


def application_events(db: Session, application_id: str) -> list[ApplicationEventDB]:
    """The full history of an application, in append order.

    The order is the event id — the autoincrement primary key — and never a
    timestamp, so two events written in the same millisecond keep their real
    order.
    """
    return list(
        db.scalars(
            select(ApplicationEventDB)
            .where(ApplicationEventDB.application_id == application_id)
            .order_by(ApplicationEventDB.id)
        )
    )
