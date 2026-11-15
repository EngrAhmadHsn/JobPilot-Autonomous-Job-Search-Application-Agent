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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.applications.contracts import (
    ApplicationRequest,
    PreparedApplication,
)
from src.applications.form import facts_from_profile
from src.applications.tracking import (
    AGENT_ACTOR,
    EVENT_APPROVAL_GRANTED,
    EVENT_APPROVAL_REJECTED,
    ApplicationStatus,
    create_application,
    human_actor,
    record_event,
    transition,
)
from src.db import access
from src.db.approval import (
    ApprovalRequestDB,
    ApprovalStatus,
    build_approval_row,
    profile_version_for,
)
from src.db.profiles import profile_from_row
from src.db.session import get_db
from src.graph.executor import (
    new_workflow_id,
    record_prepare_audit,
    select_adapter_for_url,
)
from src.graph.executor import prepare_application as build_prepared_application
from src.runs import queue as run_queue
from src.runs import service as run_service
from src.security.allowlist import DisallowedDomainError, assert_job_url_allowed
from src.security.audit import (
    ACTION_APPROVE,
    ACTION_REJECT,
    OUTCOME_BLOCKED,
    OUTCOME_DENIED,
    OUTCOME_ERROR,
    OUTCOME_SUCCESS,
    Actor,
    record_audit,
)
from src.security.policy import (
    AutoSubmitNotAllowed,
    PolicyError,
    SubmissionPolicy,
    assert_execution_allowed,
    get_submission_policy,
)
from src.storage.paths import UserPathNotAllowedError, assert_within_user_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/applications", tags=["applications"])

# The adapter registry lives in ``src.graph.executor`` (WS-32), not here, and
# this module does not keep a second copy of it. The worker resolves the adapter
# an approval recorded from that same list, so a list here would be a second
# truth: the route could approve a payload for an adapter the worker cannot
# find, and the failure would surface on the worker thread after the operator
# had been told the work was accepted. ``select_adapter_for_url`` and
# ``select_adapter_by_name`` both read it at call time, so replacing the one
# list changes what both callers resolve. Only the fake ATS holds the submit
# capability (``src.security.registry_setup``).


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


class BoardQuestion(BaseModel):
    """One question of the board's own published form (WS-25b).

    This was ``list[dict]``, which made the response's most interesting field
    unreadable by a typed client: the generated TypeScript said
    ``{ [key: string]: unknown }[]`` and the console would have had to cast
    to render it. Naming the shape is what lets the operator read the form
    they are about to have filled.
    """

    label: str = Field(..., description="The board's own wording for the question")
    required: bool = Field(False, description="Whether the board marks it required")
    block: str = Field("questions", description="The form section it appears in")
    verdict: str = Field(
        "",
        description="answerable | needs_human | autofillable | skipped",
    )
    category: str | None = Field(None, description="The taxonomy category, when classified")
    answer_from: str | None = Field(None, description="The profile fact it is answered from")
    fields: list[str] = Field(
        default_factory=list, description="The form fields the answer is written to"
    )


class ApplicationPrepareResponse(BaseModel):
    """Response body for a prepared application."""

    approval_id: str = Field(..., description="Id of the approval request")
    workflow_id: str = Field(..., description="Unique workflow execution ID")
    adapter_name: str = Field(..., description="Name of the adapter used")
    status: str = Field(..., description="awaiting_approval or blocked_human_review")
    prepared_summary: PreparedSummary
    application_id: str | None = Field(None, description="Id of the tracked application (WS-07)")
    #: WS-25b: the board's **own** application form, question by question,
    #: in the order the board publishes it, with what the agent may do with
    #: each. Empty when the board publishes no schema or could not be reached.
    form_questions: list[BoardQuestion] = Field(
        default_factory=list,
        description="The board's form, with the agent's verdict per question",
    )
    #: WS-25b: the required questions the agent cannot answer. When this
    #: is non-empty the status is ``blocked_human_review``.
    blocking_questions: list[str] = Field(
        default_factory=list,
        description="Required questions the profile does not answer",
    )


class ApprovalDecisionRequest(BaseModel):
    """A human decision on a prepared application.

    **The approver is the authenticated principal, not this field**
    (WS-14 · A2, threat T2). The field is still accepted so that an older
    client keeps working, but its value is **ignored**: a caller cannot
    approve an application *as somebody else* by naming them. When a
    body carries an approver that is not the caller, the fact is audited.

    The field is optional because it is no longer the source of truth.
    """

    approver: str | None = Field(
        None,
        description="Ignored. The approver is the authenticated principal.",
    )
    reason: str | None = Field(None, description="Why the application was approved or rejected")


class ApprovalDecisionResponse(BaseModel):
    """Response body for an approval decision.

    WS-32: an approval no longer carries a submission result, because the
    submission no longer happens during the request. ``result``/``evidence``/
    ``metadata`` are therefore optional — the *reject* path still fills
    ``metadata``, and the approve path has nothing to report yet beyond the
    accepted run. ``status`` is the **run's** vocabulary (``QUEUED``), not the
    application's (``submitted``/``verified``): a response that said
    "submitted" would claim the employer had been reached when all that
    happened is that durable work was created.
    """

    approval_id: str
    workflow_id: str
    adapter_name: str
    status: str
    success: bool
    message: str
    evidence: dict | None = None
    metadata: dict | None = None
    #: WS-32: the durable run the worker will execute. ``None`` on the reject
    #: path, which queues nothing.
    run_id: str | None = None


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


def _load_approval(approval_id: str, db: Session, scope: UserScope) -> ApprovalRequestDB:
    """Load an approval record this scope may read, or raise a 404.

    A record that belongs to another owner is **not found**, not
    "forbidden": the two answers must be indistinguishable, or the API
    becomes an existence oracle.
    """
    row = access.get_approval(db, scope, approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return row


def _build_form_plans(adapter, job_url: str, facts: dict[str, str]) -> list:
    """Read the board's form and decide what the agent may answer.

    WS-25b. Returns an empty list when the adapter publishes no schema
    (Lever, Ashby, Remotive), when the board is unreachable, or when the
    schema is malformed. **Every** failure path here degrades to the
    previous behaviour — the prepare still succeeds — because a form
    schema is an enhancement, and a board being slow must not stop an
    operator from preparing an application.

    The fetch is bounded by the same timeout the rest of the outbound
    HTTP uses (``JOB_SOURCE_TIMEOUT``), so a hanging board cannot hang
    the route.
    """
    fetch = getattr(adapter, "fetch_form_schema", None)
    if fetch is None:
        return []
    try:
        import asyncio

        schema = asyncio.run(fetch(job_url))
    except Exception:
        # A schema we cannot read is not a reason to fail a prepare.
        logger.warning("Could not read the application form for %s", job_url, exc_info=True)
        return []
    if schema is None:
        return []
    try:
        from src.applications.form_plan import build_question_plan

        return build_question_plan(schema, facts)
    except Exception:
        logger.warning("Could not build the question plan for %s", job_url, exc_info=True)
        return []


def _job_liveness(row: ApprovalRequestDB) -> tuple[bool, str]:
    """Whether the job this approval names is **gone**, and why.

    WS-25b §9.2. Returns ``(True, reason)`` only when the board answers
    that the job is not open — a 404, or a deadline that has passed. It
    returns ``(False, reason)`` when the job is live **and** when the
    board could not be reached.

    That last case is the whole design. A transport failure is not
    evidence that a job closed, and treating it as one would turn a
    flaky board into a way to block every approval. The operator sees
    "could not verify" in the audit trail and decides.

    A provider that publishes no liveness endpoint (Lever, Ashby,
    Remotive — the check is Greenhouse-only for now) also returns
    ``(False, …)``: the absence of a check is not a reason to block.
    """
    adapter = _adapter_for_url(row.job_url)
    check = getattr(adapter, "check_job_is_live", None) if adapter is not None else None
    if check is None:
        return False, "the provider publishes no liveness check"

    try:
        import asyncio

        is_live, reason = asyncio.run(check(row.job_url))
    except Exception as exc:  # noqa: BLE001 - an unreachable board is not a closed job
        logger.warning("Could not check the liveness of %s: %s", row.job_url, exc)
        return False, f"could not verify: {type(exc).__name__}"

    if is_live:
        return False, reason
    # Only a *definitive* answer blocks: the 404 and the passed deadline.
    # "Could not be checked" comes back as ``False, "the job could not be
    # checked: …"`` from the adapter, and must not block.
    if "could not be checked" in reason or "not a Greenhouse" in reason:
        return False, reason
    return True, reason


def _adapter_for_url(job_url: str):
    """The application adapter that claims a URL, or ``None``.

    WS-32 fixed a one-argument call to a two-argument function here. The call
    raised ``TypeError`` on every invocation, the ``except`` swallowed it, and
    the liveness check the WS-25b approve path uses therefore **never ran**:
    ``_job_liveness`` saw ``None`` and answered "the provider publishes no
    liveness check" for every URL. The defect was invisible because its
    documented outcome ("do not block") is the same as its failure outcome
    ("could not verify"), which is exactly the shape the fail-soft design
    hides.
    """
    try:
        return select_adapter_for_url(job_url)
    except Exception:  # noqa: BLE001 - no adapter is a valid answer here
        return None


def _expire_if_stale(row: ApprovalRequestDB, db: Session) -> bool:
    """Mark an approval **expired** when its window has closed.

    WS-25. An approval had no clock: ``ApprovalStatus`` had no
    ``EXPIRED`` state and there was no expiry timestamp, so an approval
    granted on Monday would still authorize a submission on Friday —
    against a résumé tailored with Monday's profile, for a job that may
    have closed in between.

    The state is written, not merely reported, so the operator's view
    shows what happened. The expiry is measured from **creation**, so a
    request that sat pending for a week does not get a fresh week when
    it is approved.

    An approval with no expiry is never expired: the column is nullable
    because a row created before WS-25 has none, and refusing to
    execute it on that basis would strand the existing approvals.

    Returns:
        True when the approval was expired by this call.
    """
    if row.expires_at is None:
        return False
    expiry = row.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if expiry > datetime.now(UTC):
        return False
    row.status = ApprovalStatus.EXPIRED
    row.decided_at = datetime.now(UTC)
    row.decision_reason = f"the approval window closed at {expiry.isoformat()}; it was not executed"
    db.commit()
    return True


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
        adapter = select_adapter_for_url(req.job_url)
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
            # WS-14 · Phase B: the path must be inside the **caller's
            # own** directory. A check against the shared roots would
            # accept another user's resume — and this path is handed to
            # the browser, which uploads it to a third-party job site.
            resume_path = str(
                assert_within_user_root(req.resume_path, scope.user_id, what="resume path")
            )
        except UserPathNotAllowedError as exc:
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
        # WS-25c: the posting's URL is passed so the work-authorization fact is
        # answered for **this** job's country, not in the abstract.
        profile_facts=_profile_facts(db, req.profile_id, scope, job_url=req.job_url),
    )

    try:
        prepared = build_prepared_application(
            app_request, adapter, workflow_id=workflow_id, owner_id=scope.user_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    # WS-25b §9.1: read the board's **own** application form, and decide
    # what the agent may do with every question on it.
    #
    # The fetch is bounded and fail-soft on purpose. The prepare route
    # made no network call before this, and adding one changes its
    # failure modes: a board that is slow or down must degrade to the
    # fixed field map, not fail a prepare. A required question the agent
    # cannot answer stops the flow with a named reason instead of being
    # discovered at submission time.
    form_plans = _build_form_plans(adapter, req.job_url, app_request.profile_facts)
    from src.applications.form_plan import blocking_questions, plan_as_dicts

    blockers = blocking_questions(form_plans)

    row = build_approval_row(
        owner_id=scope.user_id,
        workflow_id=workflow_id,
        adapter_name=adapter.name,
        prepared=prepared,
        # WS-25: the approval is bound to the profile it was built from.
        # If the candidate edits their profile afterwards, the payload
        # the human reviewed is no longer the payload that would be
        # submitted.
        profile_version=profile_version_for(prepared.profile_facts),
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
        owner_id=scope.user_id,
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
        # WS-25b: a required question the agent cannot answer stops the
        # flow with a named reason, instead of the gap being discovered
        # at submission time. The approval row still exists — the
        # operator can read the form, answer the profile, and prepare
        # again — but its state says a human must look.
        status="blocked_human_review" if blockers else "awaiting_approval",
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
        form_questions=plan_as_dicts(form_plans),
        blocking_questions=[plan.label for plan in blockers],
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


def _profile_facts(
    db: Session,
    profile_id: str | None,
    scope: UserScope,
    *,
    job_url: str | None = None,
) -> dict[str, str]:
    """The grounded facts of a stored candidate profile (WS-08).

    The facts are derived from the profile the candidate uploaded — the
    document itself — and never from the request body. A profile that does
    not exist yields no facts, which means the questions it would have
    answered stay *unresolved* rather than being invented.

    ``job_url`` (WS-25c) makes the work-authorization fact **country-qualified**.
    The boards ask "are you authorized to work in the country for which you
    apply?", so the answer depends on the posting: the location is read from
    the corpus by the listing's application URL, resolved to a country, and
    handed to the fact map. When it cannot be resolved the fact is withheld
    and the question goes to a human — never answered from a blanket
    statement the posting's own field does not support.
    """
    if not profile_id:
        return {}
    try:
        row = access.get_profile(db, scope, profile_id)
        if row is None:
            logger.info("No candidate profile %r; the application has no profile facts", profile_id)
            return {}
        job_country = _job_country_for(db, job_url)
        return facts_from_profile(profile_from_row(row), job_country=job_country)
    except Exception as exc:  # noqa: BLE001 - a missing profile must not block the flow
        logger.warning("The profile facts could not be derived: %s", exc)
        return {}


def _job_country_for(db: Session, job_url: str | None) -> str | None:
    """The country of the posting at *job_url*, or ``None`` when unknown.

    A read-only lookup against the corpus the refresh already populated. It is
    confined to *country resolution* and changes no answer by itself: when it
    returns ``None`` the authorization fact is withheld, which is the same
    outcome as a profile that states nothing.
    """
    if not job_url:
        return None
    from src.applications.form import resolve_job_country
    from src.db.jobs import location_for_application_url

    try:
        location = location_for_application_url(job_url, session_factory=db.get_bind())
    except Exception:
        # An unknown country is safe here — it withholds the authorization
        # answer — so a lookup failure must not fail the prepare.
        logger.debug("Could not resolve the posting's location", exc_info=True)
        return None
    return resolve_job_country(location)


def _track_prepare(
    db: Session,
    *,
    owner_id: str,
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
            owner_id=owner_id,
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
    owner_id: str,
    actor: str,
    metadata: dict | None = None,
) -> None:
    """Append an event to a tracked application's history (best effort)."""
    try:
        record_event(
            db,
            application_id,
            event_type,
            owner_id=owner_id,
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


@router.post(
    "/{approval_id}/approve",
    response_model=ApprovalDecisionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def approve_application(
    approval_id: str,
    req: ApprovalDecisionRequest,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> ApprovalDecisionResponse:
    """Approve a prepared application and queue its submission (WS-32).

    Two things happen here and only two: the human's decision is recorded
    durably, and the submission is **accepted** as background work. The
    submission itself is performed by the worker, because a browser walk
    against a real board takes tens of seconds and outlives the HTTP request
    that asked for it — running it inline is how a proxy timeout or an API
    restart loses a run and leaves the approval row mid-flight.

    The payload that is executed is still the persisted one: the worker
    restores it from this row, so *the approved payload is the submitted
    payload*.

    Args:
        approval_id: The approval request to approve.
        req: The decision (optional reason; the approver is the principal).
        db: The request-scoped database session.

    Returns:
        ``202 Accepted`` with the run id the caller polls. The status is the
        run's (``QUEUED``), never "submitted" — the employer has not been
        reached yet, and the response must not say otherwise.

    Raises:
        HTTPException 403: The policy forbids executing the application.
        HTTPException 404: The approval request is unknown.
        HTTPException 409: The request was already decided, the job is no
            longer open, or its stored payload cannot be restored.
        HTTPException 503: The background queue is at capacity. Nothing was
            written and the approval is still pending, so the caller may retry.
    """
    row = _load_approval(approval_id, db, scope)
    if row.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Approval request {approval_id!r} was already decided ({row.status})",
        )

    # WS-25: an expired approval is not executable. The state is written
    # so the operator sees why, and the audit records the refusal.
    if _expire_if_stale(row, db):
        record_audit(
            ACTION_APPROVE,
            actor=Actor.user(scope.user_id),
            resource=approval_id,
            outcome=OUTCOME_DENIED,
            owner_id=scope.user_id,
            metadata={
                "reason": "the approval had expired",
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            },
            workflow_id=row.workflow_id,
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Approval request {approval_id!r} has expired. "
                "Prepare the application again to get a fresh review."
            ),
        )

    # WS-25b §9.2: is the job still open? The corpus has no expiry signal
    # (WS-23 §11.2), so a posting that closed months ago is still ranked
    # and still has a valid URL — this is the check that stops the
    # application.
    #
    # The distinction that matters: a job that is **gone** blocks (409),
    # while a board that **cannot be reached** does not. A transport
    # failure must not become a way to block every approval during an
    # outage; it degrades to "cannot verify", which the audit records.
    gone, reason = _job_liveness(row)
    if gone:
        record_audit(
            ACTION_APPROVE,
            actor=Actor.user(scope.user_id),
            resource=approval_id,
            outcome=OUTCOME_DENIED,
            owner_id=scope.user_id,
            metadata={"reason": "the job is no longer open", "detail": reason},
            workflow_id=row.workflow_id,
        )
        raise HTTPException(
            status_code=409,
            detail=f"The job is no longer open ({reason}). Nothing was submitted.",
        )

    # WS-14 · A2 (T2): the approver is the **authenticated principal**.
    # A body-supplied approver is ignored, and the attempt to name
    # somebody else is recorded.
    approver = scope.user_id
    if req.approver and req.approver != approver:
        record_audit(
            ACTION_APPROVE,
            actor=Actor.user(approver),
            resource=approval_id,
            outcome=OUTCOME_DENIED,
            owner_id=approver,
            metadata={
                "reason": "the request named a different approver; it was ignored",
                "named_approver": req.approver,
            },
            workflow_id=row.workflow_id,
        )

    policy = get_submission_policy()
    try:
        assert_execution_allowed(policy)
    except (PolicyError, AutoSubmitNotAllowed) as exc:
        record_audit(
            ACTION_APPROVE,
            actor=Actor.user(approver),
            resource=approval_id,
            outcome=OUTCOME_BLOCKED,
            owner_id=approver,
            metadata={"reason": str(exc), "policy": policy.value},
            workflow_id=row.workflow_id,
        )
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    # The decision is written but **not committed yet**: it is committed
    # together with the queued run below, so the two are one outcome.
    row.status = ApprovalStatus.APPROVED
    row.approver = approver
    row.decision_reason = req.reason
    row.decided_at = datetime.now(UTC)

    # WS-32: the decision and the queued run are **one transaction**. The
    # APPROVED write above is only flushed by this commit, and the enqueue
    # writes the run in the same session, so a QueueFull rolls the decision
    # back with it: the operator is told to retry instead of being left with an
    # approval that authorizes nothing and that no retry can reach, because the
    # row would no longer read PENDING.
    try:
        accepted = run_service.enqueue_submission(
            db,
            approval_id=approval_id,
            workflow_id=row.workflow_id,
            owner_id=row.owner_id,
            approver=approver,
        )
    except run_queue.QueueFull as exc:
        db.rollback()
        record_audit(
            ACTION_APPROVE,
            actor=Actor.user(approver),
            resource=approval_id,
            outcome=OUTCOME_BLOCKED,
            owner_id=approver,
            metadata={"reason": "the background queue is at capacity"},
            workflow_id=row.workflow_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    # The approved payload must still be valid — a row written by an older
    # version, or one whose payload a migration could not carry, would
    # otherwise fail on the worker thread where nobody is watching the request.
    # This checks only; it submits nothing. An invalid payload rolls the
    # decision back with the run, exactly as a full queue does.
    try:
        PreparedApplication.model_validate(row.payload)
    except ValidationError as exc:
        db.rollback()
        record_audit(
            ACTION_APPROVE,
            actor=Actor.user(approver),
            resource=approval_id,
            outcome=OUTCOME_ERROR,
            owner_id=approver,
            metadata={"reason": "the stored payload failed validation"},
            workflow_id=row.workflow_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Approval request {approval_id!r} stores a payload that no longer "
                "validates, so it cannot be submitted. Prepare the application again."
            ),
        ) from exc

    # WS-32: the acceptance is committed **before** the tracking write. The
    # tracking tables are observability, and ``_record_tracking_event`` is
    # best-effort — it swallows its exception and calls ``db.rollback()``. When
    # it ran before this commit, that rollback discarded the APPROVED write and
    # the run and item rows the enqueue had flushed, and the handler still
    # answered 202 with a run id no worker could ever claim, because the run had
    # been rolled back out of existence. Ordering the commit first is what makes
    # a tracking failure harmless: it can lose an event, never the acceptance.
    db.commit()
    db.refresh(row)

    # WS-07: the decision is an event in the tracked application's history.
    # The application itself stays in AWAITING_APPROVAL until the agent
    # actually performs the submission — which is now the worker's job, so the
    # transition to SUBMITTED happens there, with the evidence.
    application = access.get_application_by_approval(db, scope, approval_id)
    if application is not None:
        _record_tracking_event(
            db,
            application.id,
            EVENT_APPROVAL_GRANTED,
            owner_id=approver,
            actor=human_actor(approver),
            metadata={"reason": req.reason, "approval_id": approval_id},
        )

    record_audit(
        ACTION_APPROVE,
        actor=Actor.user(approver),
        resource=approval_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=approver,
        metadata={
            "workflow_id": row.workflow_id,
            "reason": req.reason,
            "run_id": accepted.run_id,
            "queued": True,
        },
        workflow_id=row.workflow_id,
    )

    logger.info(
        "[%s] Application approved by %s; submission queued as run %s",
        row.workflow_id,
        approver,
        accepted.run_id,
        extra={"workflow_id": row.workflow_id, "run_id": accepted.run_id},
    )

    # The answer is **accepted**, not submitted. The wording is the invariant:
    # a 200 with a success-shaped body would tell the operator the application
    # reached the employer when all that happened is that durable work was
    # created. ``status`` mirrors the run's own vocabulary (the same
    # ``QUEUED`` the refresh flow returns), so the console can render it.
    return ApprovalDecisionResponse(
        approval_id=approval_id,
        workflow_id=row.workflow_id,
        adapter_name=row.adapter_name,
        status=accepted.status,
        success=False,
        message=(
            "Approval recorded. The submission is queued and a background worker "
            "will perform it; track it with the run id."
        ),
        run_id=accepted.run_id,
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

    # WS-14 · A2 (T2): the approver is the authenticated principal, and a
    # body-supplied one is ignored.
    approver = scope.user_id
    if req.approver and req.approver != approver:
        record_audit(
            ACTION_REJECT,
            actor=Actor.user(approver),
            resource=approval_id,
            outcome=OUTCOME_DENIED,
            owner_id=approver,
            metadata={
                "reason": "the request named a different approver; it was ignored",
                "named_approver": req.approver,
            },
            workflow_id=row.workflow_id,
        )

    row.status = ApprovalStatus.REJECTED
    row.approver = approver
    row.decision_reason = req.reason
    row.decided_at = datetime.now(UTC)
    db.commit()

    # WS-07: a decline at the gate is a human outcome, so the tracked
    # application moves to REJECTED with a human actor.
    application = access.get_application_by_approval(db, scope, approval_id)
    if application is not None:
        _transition_tracked(
            db,
            application,
            ApplicationStatus.REJECTED,
            actor=human_actor(approver),
            event_type=EVENT_APPROVAL_REJECTED,
            metadata={"reason": req.reason, "approval_id": approval_id},
        )

    record_audit(
        ACTION_REJECT,
        actor=Actor.user(approver),
        resource=approval_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=approver,
        metadata={"workflow_id": row.workflow_id, "reason": req.reason},
        workflow_id=row.workflow_id,
    )

    logger.info(
        "[%s] Application rejected by %s",
        row.workflow_id,
        approver,
        extra={"workflow_id": row.workflow_id},
    )

    return ApprovalDecisionResponse(
        approval_id=approval_id,
        workflow_id=row.workflow_id,
        adapter_name=row.adapter_name,
        status=ApprovalStatus.REJECTED,
        success=False,
        message=req.reason or "Application rejected by the approver",
        metadata={"approver": approver},
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
