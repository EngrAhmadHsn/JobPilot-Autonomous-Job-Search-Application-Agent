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

from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
)
from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter
from src.applications.greenhouse_adapter import GreenhouseAdapter
from src.applications.lever_adapter import LeverAdapter
from src.db.approval import (
    ApprovalRequestDB,
    ApprovalStatus,
    build_approval_row,
)
from src.db.session import get_db
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


class PreparedSummary(BaseModel):
    """What a human is asked to review before approving.

    The prepared field *names* are listed, not their values: the values are
    the candidate's personal data and the reviewer does not need them echoed
    back to make a decision.
    """

    job_title: str
    company_name: str
    job_url: str
    adapter_name: str
    field_names: list[str] = Field(default_factory=list)
    resume_path: str | None = None
    requires_manual_review: bool = False


class ApplicationPrepareResponse(BaseModel):
    """Response body for a prepared application."""

    approval_id: str = Field(..., description="Id of the approval request")
    workflow_id: str = Field(..., description="Unique workflow execution ID")
    adapter_name: str = Field(..., description="Name of the adapter used")
    status: str = Field(..., description="awaiting_approval")
    prepared_summary: PreparedSummary


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


def _load_approval(approval_id: str, db: Session) -> ApprovalRequestDB:
    """Load an approval record or raise a 404."""
    row = db.get(ApprovalRequestDB, approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Approval request {approval_id!r} not found")
    return row


@router.post("/prepare", response_model=ApplicationPrepareResponse)
def prepare_application(
    req: ApplicationPrepareRequest,
    db: Annotated[Session, Depends(get_db)],
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
    app_request = ApplicationRequest(
        job_title=req.job_title,
        company_name=req.company_name,
        job_url=req.job_url,
        candidate_name=req.candidate_name,
        email=req.email,
        phone=req.phone,
        resume_path=req.resume_path,
        cover_letter=req.cover_letter,
        custom_fields=req.custom_fields,
    )

    try:
        prepared = build_prepared_application(app_request, adapter, workflow_id=workflow_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    row = build_approval_row(
        workflow_id=workflow_id,
        adapter_name=adapter.name,
        prepared=prepared,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_prepare_audit(prepared, adapter, workflow_id=workflow_id, approval_id=row.id)

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
            resume_path=prepared.resume_path,
            requires_manual_review=prepared.requires_manual_review,
        ),
    )


@router.post("/{approval_id}/approve", response_model=ApprovalDecisionResponse)
def approve_application(
    approval_id: str,
    req: ApprovalDecisionRequest,
    db: Annotated[Session, Depends(get_db)],
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
    row = _load_approval(approval_id, db)
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

    result = execute_approved(
        prepared,
        adapter,
        workflow_id=row.workflow_id,
        approval_id=approval_id,
        approver=req.approver,
        decision_reason=req.reason or "",
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
    row = _load_approval(approval_id, db)
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


@router.get("/{approval_id}", response_model=ApprovalStatusResponse)
def get_approval(
    approval_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalStatusResponse:
    """Return the stored state of an approval request."""
    row = _load_approval(approval_id, db)

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
