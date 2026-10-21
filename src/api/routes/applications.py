"""API routes for the two-phase job application flow (WS-06 · SEC-05 / SEC-06).

The flow has two phases, and the split is the security property:

1. ``POST /api/applications/prepare`` — the target domain is checked, the
   adapter is selected, the payload is built, and an **approval request** is
   persisted. Nothing is submitted.
2. ``POST /api/applications/{approval_id}/approve`` (or ``/reject``) — a human
   records a decision, and only an approved record may execute. The payload
   that is executed is the one that was persisted, so the approver reviews
   exactly what is submitted.

The former ``POST /api/applications/submit`` route — and with it the
``approval: bool`` request flag — is gone. A single-call submit route is
exactly the hole SEC-05 forbids: every submission now provably has an
``approved`` decision row behind it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
)
from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter
from src.applications.form import facts_from_profile
from src.applications.greenhouse_adapter import GreenhouseAdapter
from src.applications.lever_adapter import LeverAdapter
from src.applications.tracking import (
    AGENT_ACTOR,
    EVENT_APPROVAL_GRANTED,
    EVENT_APPROVAL_REJECTED,
    ApplicationStatus,
    create_application,
    find_application,
    human_actor,
    record_event,
    transition,
)
from src.db import access
from src.db.approval import (
    ApprovalRequestDB,
    ApprovalStatus,
    build_approval_row,
)
from src.db.profiles import profile_from_row
from src.db.session import get_db
from src.db.users import LEGACY_OWNER_ID
from src.graph.executor import (
    execute_approved,
    new_workflow_id,
    record_prepare_audit,
    select_adapter_for_url,
)
from src.graph.executor import prepare_application as build_prepared_application
from src.security.allowlist import DisallowedDomainError, assert_job_url_allowed
from src.security.audit import (
    ACTION_APPROVE,
    ACTION_REJECT,
    OUTCOME_BLOCKED,
    OUTCOME_DENIED,
    OUTCOME_SUCCESS,
    record_audit,
)
from src.security.paths import PathNotAllowedError, assert_within_allowed_roots
from src.security.policy import (
    AutoSubmitNotAllowed,
    PolicyError,
    SubmissionPolicy,
    assert_execution_allowed,
    get_submission_policy,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/applications", tags=["applications"])

# Adapters that may prepare an application. Only the fake ATS holds the
# submit capability (src/security/registry_setup.py).
AVAILABLE_ADAPTERS = [
    FakeAtsPlaywrightAdapter(),
    GreenhouseAdapter(),
    LeverAdapter(),
]


class ApplicationPrepareRequest(BaseModel):
    """Request body for preparing an application for review."""

    job_title: str = Field(..., description="Job title from the posting")
    company_name: str = Field(..., description="Company name")
    job_url: str = Field(..., description="URL of the job posting")

    candidate_name: str = Field(..., description="Full name of the candidate")
    email: str = Field(..., description="Email address")
    phone: str = Field(..., description="Phone number")

    resume_path: str | None = Field(None, description="File path to candidate resume")
    cover_letter: str | None = Field(None, description="Cover letter text or path")

    custom_fields: dict = Field(default_factory=dict, description="Additional form fields")

    # WS-07: the tracked application may be linked to the candidate profile
    # and the tailored resume it was built from. Both are optional: the
    # prepare flow works without them.
    profile_id: str | None = Field(
        None, description="Candidate profile this application belongs to"
    )
    tailored_resume_id: str | None = Field(
        None, description="Tailored resume used for this application"
    )


class PreparedSummary(BaseModel):
    """What a human is asked to review before approving.

    The prepared field *names* are listed, not their values: the values are
    the candidate's personal data and the reviewer does not need them echoed
    back to make a decision. The same holds for the profile facts (WS-08):
    their *names* say what the agent may answer a form question with.
    """

    job_title: str
    company_name: str
    job_url: str
    adapter_name: str
    field_names: list[str] = Field(default_factory=list)
    profile_fact_names: list[str] = Field(default_factory=list)
    resume_path: str | None = None
    requires_manual_review: bool = False


class ApplicationPrepareResponse(BaseModel):
    """Response body for a prepared application."""

    approval_id: str = Field(..., description="Id of the approval request")
    workflow_id: str = Field(..., description="Unique workflow execution ID")
    adapter_name: str = Field(..., description="Name of the adapter used")
    status: str = Field(..., description="awaiting_approval")
    prepared_summary: PreparedSummary
    application_id: str | None = Field(None, description="Id of the tracked application (WS-07)")


class ApprovalDecisionRequest(BaseModel):
    """A human decision on a prepared application."""

    approver: str = Field(..., min_length=1, description="Identity of the approving operator")
    reason: str | None = Field(None, description="Why the application was approved or rejected")


class ApprovalDecisionResponse(BaseModel):
    """Response body for an approval decision."""

    approval_id: str
    workflow_id: str
    adapter_name: str
    status: str
    success: bool
    message: str
    evidence: dict | None = None
    metadata: dict | None = None


class ApprovalStatusResponse(BaseModel):
    """The stored state of an approval request."""

    approval_id: str
    workflow_id: str
    adapter_name: str
    job_url: str
    job_title: str
    company_name: str
    status: str
    approver: str | None = None
    decision_reason: str | None = None
    created_at: datetime
    decided_at: datetime | None = None
    success: bool | None = None
    message: str | None = None


def _evidence_payload(result: ApplicationResult) -> dict | None:
    """The evidence of a result, as a small JSON-safe dict."""
    if result.evidence is None:
        return None
    return {
        "url": result.evidence.url,
        "confirmation_text": result.evidence.confirmation_text[:200]
        if result.evidence.confirmation_text
        else None,
        "status": result.evidence.status,
        "screenshot_path": result.evidence.screenshot_path,
        "trace_path": result.evidence.trace_path,
    }


def _load_approval(approval_id: str, db: Session, scope: UserScope) -> ApprovalRequestDB:
    """Load an approval record this scope may read, or raise a 404.

    A record that belongs to another owner is **not found**, not
    "forbidden": the two answers must be indistinguishable, or the API
    becomes an existence oracle.
    """
    row = access.get_approval(db, scope, approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Approval request {approval_id!r} not found")
    return row


@router.post("/prepare", response_model=ApplicationPrepareResponse)
def prepare_application(
    req: ApplicationPrepareRequest,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> ApplicationPrepareResponse:
    """Prepare an application and record it for human approval.

    Nothing is submitted by this call. The prepared payload is persisted as an
    approval request so that the approval decision and the submitted payload
    are the same thing.

    Args:
        req: The application details.
        db: The request-scoped database session.

    Returns:
        The approval id, the workflow id, and a summary of what will be
        submitted.

    Raises:
        HTTPException 400: The URL is not on the domain allowlist, or no
            adapter supports it.
        HTTPException 403: The configured policy forbids the operation.
    """
    policy = get_submission_policy()
    if policy is SubmissionPolicy.AUTO_SUBMIT:
        raise HTTPException(
            status_code=403,
            detail=(
                "AUTO_SUBMIT is defined but not enabled in this version. Use REQUIRE_APPROVAL."
            ),
        )

    # SEC-06: the target domain is checked before anything else.
    try:
        assert_job_url_allowed(req.job_url)
    except DisallowedDomainError as exc:
        logger.warning("Rejected application for a non-allowlisted URL: %s", exc)
        record_audit(
            "allowlist.violation",
            actor="api",
            resource=req.job_url,
            outcome=OUTCOME_DENIED,
            metadata={"reason": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        adapter = select_adapter_for_url(req.job_url, AVAILABLE_ADAPTERS)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"No adapter available for job URL: {req.job_url}",
        ) from exc

    workflow_id = new_workflow_id()

    # WS-12: the resume path is request-supplied and the browser layer
    # uploads that file to a third-party job site. An uncontained path is
    # therefore an exfiltration channel (point it at .env and the browser
    # sends the secrets to an employer). It is checked here, at the
    # boundary, so the browser layer can trust what it receives.
    resume_path: str | None = None
    if req.resume_path and req.resume_path.strip():
        try:
            resume_path = str(assert_within_allowed_roots(req.resume_path, what="resume path"))
        except PathNotAllowedError as exc:
            logger.warning("Rejected an application with an out-of-bounds resume path: %s", exc)
            record_audit(
                "allowlist.violation",
                actor="api",
                resource="resume_path",
                outcome=OUTCOME_DENIED,
                metadata={"reason": str(exc)},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # WS-12: the custom fields are an unbounded, unvalidated dict that is
    # merged straight into the payload the adapter submits. The count and
    # the value length are bounded here so a request cannot carry a
    # megabyte of form data into a submission.
    custom_fields = _validated_custom_fields(req.custom_fields)

    app_request = ApplicationRequest(
        job_title=req.job_title,
        company_name=req.company_name,
        job_url=req.job_url,
        candidate_name=req.candidate_name,
        email=req.email,
        phone=req.phone,
        resume_path=resume_path,
        cover_letter=req.cover_letter,
        custom_fields=custom_fields,
        # WS-08: the grounded facts come from the **stored profile**, never
        # from the request body. A question the candidate's document does not
        # answer stays unanswered.
        profile_facts=_profile_facts(db, req.profile_id, scope),
    )

    try:
        prepared = build_prepared_application(app_request, adapter, workflow_id=workflow_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    row = build_approval_row(
        owner_id=LEGACY_OWNER_ID,
        workflow_id=workflow_id,
        adapter_name=adapter.name,
        prepared=prepared,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_prepare_audit(prepared, adapter, workflow_id=workflow_id, approval_id=row.id)

    # WS-07: the tracked application. It is created already prepared (the
    # system never matched or shortlisted anything in this flow) and moves to
    # AWAITING_APPROVAL, because an approval request now exists.
    application_id = _track_prepare(
        db,
        workflow_id=workflow_id,
        adapter_name=adapter.name,
        approval_id=row.id,
        job_url=req.job_url,
        job_title=req.job_title,
        company_name=req.company_name,
        profile_id=req.profile_id,
        tailored_resume_id=req.tailored_resume_id,
    )

    logger.info(
        "[%s] Application prepared for approval (%s)",
        workflow_id,
        row.id,
        extra={"workflow_id": workflow_id},
    )

    return ApplicationPrepareResponse(
        approval_id=row.id,
        workflow_id=workflow_id,
        adapter_name=adapter.name,
        status="awaiting_approval",
        prepared_summary=PreparedSummary(
            job_title=prepared.request.job_title,
            company_name=prepared.request.company_name,
            job_url=prepared.request.job_url,
            adapter_name=adapter.name,
            field_names=sorted(prepared.prepared_fields),
            profile_fact_names=sorted(prepared.profile_facts),
            resume_path=prepared.resume_path,
            requires_manual_review=prepared.requires_manual_review,
        ),
        application_id=application_id,
    )


def _validated_custom_fields(custom_fields: dict) -> dict[str, str]:
    """Validate and bound the request-supplied custom form fields.

    WS-12: these fields are merged straight into the payload the adapter
    submits, so they were an unbounded, unvalidated dictionary — a request
    could carry a megabyte of form data, or a non-string value, into a
    submission. The count, the value length, and the value type are all
    bounded here.

    Raises:
        HTTPException 400: The fields exceed the limits or carry a value
            that is not a string.
    """
    from src.security.limits import get_limits

    limits = get_limits()
    if not custom_fields:
        return {}
    if len(custom_fields) > limits.max_custom_fields:
        raise HTTPException(
            status_code=400,
            detail=f"At most {limits.max_custom_fields} custom fields are allowed",
        )
    validated: dict[str, str] = {}
    for key, value in custom_fields.items():
        name = str(key)
        if not name.strip():
            raise HTTPException(status_code=400, detail="A custom field name may not be empty")
        if not isinstance(value, str):
            raise HTTPException(
                status_code=400,
                detail=f"The custom field {name!r} must be a string",
            )
        if len(value) > limits.max_custom_field_chars:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"The custom field {name!r} exceeds {limits.max_custom_field_chars} characters"
                ),
            )
        validated[name] = value
    return validated


def _profile_facts(db: Session, profile_id: str | None, scope: UserScope) -> dict[str, str]:
    """The grounded facts of a stored candidate profile (WS-08).

    The facts are derived from the profile the candidate uploaded — the
    document itself — and never from the request body. A profile that does
    not exist yields no facts, which means the questions it would have
    answered stay *unresolved* rather than being invented.
    """
    if not profile_id:
        return {}
    try:
        row = access.get_profile(db, scope, profile_id)
        if row is None:
            logger.info("No candidate profile %r; the application has no profile facts", profile_id)
            return {}
        return facts_from_profile(profile_from_row(row))
    except Exception as exc:  # noqa: BLE001 - a missing profile must not block the flow
        logger.warning("The profile facts could not be derived: %s", exc)
        return {}


def _track_prepare(
    db: Session,
    *,
    workflow_id: str,
    adapter_name: str,
    approval_id: str,
    job_url: str,
    job_title: str,
    company_name: str,
    profile_id: str | None = None,
    tailored_resume_id: str | None = None,
) -> str | None:
    """Create the tracked application and move it to AWAITING_APPROVAL.

    A tracking failure is logged and swallowed: the tracking tables are an
    observability feature, and a missing one must not stop an application
    from being prepared. The audit trail remains the fallback record.
    """
    try:
        application = create_application(
            db,
            owner_id=LEGACY_OWNER_ID,
            workflow_id=workflow_id,
            adapter_name=adapter_name,
            job_url=job_url,
            job_title=job_title,
            company_name=company_name,
            approval_id=approval_id,
            profile_id=profile_id,
            tailored_resume_id=tailored_resume_id,
        )
        transition(
            application,
            ApplicationStatus.AWAITING_APPROVAL,
            actor=AGENT_ACTOR,
            db=db,
        )
        return application.id
    except Exception as exc:  # noqa: BLE001 - tracking must never block the flow
        logger.error("Tracking the prepared application failed: %s", exc)
        try:
            db.rollback()
        except Exception as rollback_exc:  # noqa: BLE001 - the rollback must not mask the cause
            logger.error("Rollback after the tracking failure failed too: %s", rollback_exc)
        return None


def _record_tracking_event(
    db: Session,
    application_id: str,
    event_type: str,
    *,
    actor: str,
    metadata: dict | None = None,
) -> None:
    """Append an event to a tracked application's history (best effort)."""
    try:
        record_event(
            db,
            application_id,
            event_type,
            owner_id=LEGACY_OWNER_ID,
            actor=actor,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001 - tracking must never block the flow
        logger.error("Recording the tracking event failed: %s", exc)
        _rollback_tracking(db)


def _transition_tracked(
    db: Session,
    application,
    to: ApplicationStatus,
    *,
    actor: str,
    event_type: str,
    metadata: dict | None = None,
) -> None:
    """Move a tracked application (best effort).

    A failure here is logged, not raised: the human decision is already
    recorded on the approval request, and that record is the authority.
    """
    try:
        transition(
            application,
            to,
            actor=actor,
            db=db,
            event_type=event_type,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001 - tracking must never block the flow
        logger.error("The tracking transition failed: %s", exc)
        _rollback_tracking(db)


def _rollback_tracking(db: Session) -> None:
    """Discard a failed tracking write without letting the rollback raise."""
    try:
        db.rollback()
    except Exception as exc:  # noqa: BLE001 - the rollback must not mask the cause
        logger.error("Rollback after the tracking failure failed too: %s", exc)


@router.post("/{approval_id}/approve", response_model=ApprovalDecisionResponse)
def approve_application(
    approval_id: str,
    req: ApprovalDecisionRequest,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> ApprovalDecisionResponse:
    """Approve a prepared application and execute it.

    The decision is recorded with the approver's identity and the time. The
    payload that is executed is the persisted one.

    Args:
        approval_id: The approval request to approve.
        req: The decision (approver identity and optional reason).
        db: The request-scoped database session.

    Returns:
        The result of the execution, with its evidence.

    Raises:
        HTTPException 403: The policy forbids executing the application.
        HTTPException 404: The approval request is unknown.
        HTTPException 409: The request was already decided.
    """
    row = _load_approval(approval_id, db, scope)
    if row.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Approval request {approval_id!r} was already decided ({row.status})",
        )

    policy = get_submission_policy()
    try:
        assert_execution_allowed(policy)
    except (PolicyError, AutoSubmitNotAllowed) as exc:
        record_audit(
            ACTION_APPROVE,
            actor=req.approver,
            resource=approval_id,
            outcome=OUTCOME_BLOCKED,
            metadata={"reason": str(exc), "policy": policy.value},
            workflow_id=row.workflow_id,
        )
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    row.status = ApprovalStatus.APPROVED
    row.approver = req.approver
    row.decision_reason = req.reason
    row.decided_at = datetime.now(UTC)
    db.commit()

    prepared = PreparedApplication.model_validate(row.payload)
    adapter = _adapter_for(row.adapter_name)

    # WS-07: the decision is an event in the tracked application's history.
    # The application itself stays in AWAITING_APPROVAL until the agent
    # actually performs the submission.
    application = find_application(db, approval_id=approval_id)
    if application is not None:
        _record_tracking_event(
            db,
            application.id,
            EVENT_APPROVAL_GRANTED,
            actor=human_actor(req.approver),
            metadata={"reason": req.reason, "approval_id": approval_id},
        )

    result = execute_approved(
        prepared,
        adapter,
        workflow_id=row.workflow_id,
        approval_id=approval_id,
        approver=req.approver,
        decision_reason=req.reason or "",
        session=db,
        application_id=application.id if application is not None else None,
    )

    row.status = ApprovalStatus.EXECUTED if result.success else ApprovalStatus.FAILED
    row.result = result.model_dump(mode="json")
    db.commit()

    record_audit(
        ACTION_APPROVE,
        actor=req.approver,
        resource=approval_id,
        outcome=OUTCOME_SUCCESS if result.success else OUTCOME_BLOCKED,
        metadata={
            "workflow_id": row.workflow_id,
            "status": result.status,
            "reason": req.reason,
        },
        workflow_id=row.workflow_id,
    )

    return ApprovalDecisionResponse(
        approval_id=approval_id,
        workflow_id=row.workflow_id,
        adapter_name=row.adapter_name,
        status=result.status,
        success=result.success,
        message=result.message,
        evidence=_evidence_payload(result),
        metadata=result.metadata,
    )


@router.post("/{approval_id}/reject", response_model=ApprovalDecisionResponse)
def reject_application(
    approval_id: str,
    req: ApprovalDecisionRequest,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> ApprovalDecisionResponse:
    """Reject a prepared application. Nothing is submitted.

    Args:
        approval_id: The approval request to reject.
        req: The decision (approver identity and optional reason).
        db: The request-scoped database session.

    Returns:
        A response describing the rejection.

    Raises:
        HTTPException 404: The approval request is unknown.
        HTTPException 409: The request was already decided.
    """
    row = _load_approval(approval_id, db, scope)
    if row.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Approval request {approval_id!r} was already decided ({row.status})",
        )

    row.status = ApprovalStatus.REJECTED
    row.approver = req.approver
    row.decision_reason = req.reason
    row.decided_at = datetime.now(UTC)
    db.commit()

    # WS-07: a decline at the gate is a human outcome, so the tracked
    # application moves to REJECTED with a human actor.
    application = find_application(db, approval_id=approval_id)
    if application is not None:
        _transition_tracked(
            db,
            application,
            ApplicationStatus.REJECTED,
            actor=human_actor(req.approver),
            event_type=EVENT_APPROVAL_REJECTED,
            metadata={"reason": req.reason, "approval_id": approval_id},
        )

    record_audit(
        ACTION_REJECT,
        actor=req.approver,
        resource=approval_id,
        outcome=OUTCOME_SUCCESS,
        metadata={"workflow_id": row.workflow_id, "reason": req.reason},
        workflow_id=row.workflow_id,
    )

    logger.info(
        "[%s] Application rejected by %s",
        row.workflow_id,
        req.approver,
        extra={"workflow_id": row.workflow_id},
    )

    return ApprovalDecisionResponse(
        approval_id=approval_id,
        workflow_id=row.workflow_id,
        adapter_name=row.adapter_name,
        status=ApprovalStatus.REJECTED,
        success=False,
        message=req.reason or "Application rejected by the approver",
        metadata={"approver": req.approver},
    )


@router.get("/approvals/{approval_id}", response_model=ApprovalStatusResponse)
def get_approval(
    approval_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> ApprovalStatusResponse:
    """Return the stored state of an approval request.

    The path is ``/approvals/{id}`` because ``/api/applications/{id}`` is the
    *tracked application* (WS-07). Two different resources cannot share one
    path shape.
    """
    row = _load_approval(approval_id, db, scope)

    success: bool | None = None
    message: str | None = None
    if row.result:
        success = bool(row.result.get("success"))
        message = row.result.get("message")

    return ApprovalStatusResponse(
        approval_id=row.id,
        workflow_id=row.workflow_id,
        adapter_name=row.adapter_name,
        job_url=row.job_url,
        job_title=row.job_title,
        company_name=row.company_name,
        status=row.status,
        approver=row.approver,
        decision_reason=row.decision_reason,
        created_at=row.created_at,
        decided_at=row.decided_at,
        success=success,
        message=message,
    )


def _adapter_for(adapter_name: str) -> ApplicationAdapter:
    """The registered adapter instance with this name."""
    for adapter in AVAILABLE_ADAPTERS:
        if adapter.name == adapter_name:
            return adapter
    raise HTTPException(
        status_code=404,
        detail=f"Adapter {adapter_name!r} is not available",
    )
