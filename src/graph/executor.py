"""Executor for the application workflow: glues adapter + graph + result handling.

The executor has two entry points, and the split is the point (WS-06 · SEC-05):

- :func:`prepare_application` — builds the payload a human is asked to
  review. It never submits.
- :func:`execute_approved` — executes a **previously approved** payload. The
  payload is the one that was persisted with the approval record, so *the
  approved payload is the submitted payload*.

There is deliberately no "submit with a boolean flag" entry point any more:
a submission always follows a recorded human decision.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from src.graph.application_workflow import build_application_workflow
from src.graph.state import ApplicationWorkflowState
from src.security.audit import (
    ACTION_PREPARE,
    ACTION_SUBMIT,
    ACTION_VERIFY,
    OUTCOME_ERROR,
    OUTCOME_SUCCESS,
    SYSTEM_ACTOR,
    record_audit,
)
from src.security.registry_setup import get_registry

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.applications.contracts import (
        ApplicationAdapter,
        ApplicationRequest,
        ApplicationResult,
        PreparedApplication,
    )

logger = logging.getLogger(__name__)


def _build_available_adapters() -> list[ApplicationAdapter]:
    """The adapters that may prepare or execute an application.

    WS-32 moved this list here from the API route module. Two callers need it —
    the route, which resolves the adapter for a URL it was handed, and the
    worker, which resolves the adapter an approval row recorded — and only one
    list may exist, or the two can drift. The runner-up was the worker
    importing ``src.api.routes.applications``, which would make a request
    handler a registry and invert the layering: nothing in ``src.runs`` should
    depend on ``src.api``.

    The adapter imports are inside the function so that the *builder* is
    self-contained; :data:`AVAILABLE_ADAPTERS` still calls it once at import
    time, exactly as the route module built its list. The cost is the
    Playwright import (the fake ATS adapter needs it), which every consumer of
    this module now pays once per process — the previous shape paid it in the
    route module instead, so the total is unchanged.

    Only the fake ATS holds the submit capability (``src.security
    .registry_setup``); the other two are here so a prepare can build and
    describe their payload, and the registry refuses their submissions.
    """

    from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter
    from src.applications.greenhouse_adapter import GreenhouseAdapter
    from src.applications.lever_adapter import LeverAdapter

    return [FakeAtsPlaywrightAdapter(), GreenhouseAdapter(), LeverAdapter()]


#: The adapter registry: one list, built once at import, read at call time by
#: both resolvers below. Replacing it (a test, a deployment) changes what both
#: the route and the worker resolve.
AVAILABLE_ADAPTERS: list[ApplicationAdapter] = _build_available_adapters()


def new_workflow_id() -> str:
    """A short, human-quotable id for one application workflow."""
    return str(uuid.uuid4())[:8]


def prepare_application(
    request: ApplicationRequest,
    adapter: ApplicationAdapter,
    *,
    workflow_id: str | None = None,
    owner_id: str | None = None,
) -> PreparedApplication:
    """Prepare an application for review — nothing is submitted here.

    Args:
        request: The application request with the job and candidate details.
        adapter: The adapter that builds the payload.
        workflow_id: Optional workflow id; a new one is generated when absent.
        owner_id: The account the run belongs to (WS-14 · Phase B). The
            evidence artifacts are written into that account's directory.

    Returns:
        The prepared application, stamped with the workflow id.

    Raises:
        PermissionError: The adapter holds no prepare capability.
    """
    if not get_registry().can_prepare(adapter.name):
        raise PermissionError(f"Adapter {adapter.name!r} is not permitted to prepare applications")

    active_workflow_id = workflow_id or new_workflow_id()
    logger.info(
        f"[{active_workflow_id}] Preparing application for {request.company_name}",
        extra={
            "workflow_id": active_workflow_id,
            "company": request.company_name,
            "job_url": request.job_url,
            "adapter": adapter.name,
        },
    )
    prepared = adapter.prepare(request)
    prepared.workflow_id = active_workflow_id
    prepared.owner_id = owner_id
    return prepared


def execute_approved(
    prepared: PreparedApplication,
    adapter: ApplicationAdapter,
    *,
    workflow_id: str,
    approval_id: str,
    approver: str,
    decision_reason: str = "",
    session: Session | None = None,
    application_id: str | None = None,
) -> ApplicationResult:
    """Execute an application that a human has already approved.

    The graph runs prepare → approval → submit → verify. The prepared payload
    is restored from the approval record, so the prepare node reuses it
    instead of rebuilding it, and the approval node sees the recorded
    decision.

    Args:
        prepared: The payload that was approved.
        adapter: The adapter to execute with.
        workflow_id: The workflow id of this execution.
        approval_id: The approval record this execution belongs to.
        approver: Who approved it.
        decision_reason: Why they approved it (recorded in the audit trail).
        session: An optional session for the WS-07 tracking writes. The API
            hands over its request-scoped session, so the tracking rows are
            written in the same transaction as the rest of the request.
        application_id: The tracked application this execution belongs to,
            when it is known.

    Returns:
        The final application result. A failure is a result, never an
        exception: an unexpected error becomes ``status="workflow_error"``.
    """
    from src.applications.contracts import ApplicationResult

    logger.info(
        f"[{workflow_id}] Executing approved application (approval {approval_id})",
        extra={
            "workflow_id": workflow_id,
            "approval_id": approval_id,
            "adapter": adapter.name,
            "approver": approver,
        },
    )

    try:
        graph = build_application_workflow(adapter, session=session)

        state = ApplicationWorkflowState(
            request=prepared.request,
            prepared_application=prepared,
            approval_status=True,
            approval_metadata={
                "approval_id": approval_id,
                "approver": approver,
                "reason": decision_reason,
            },
            workflow_id=workflow_id,
            adapter_name=adapter.name,
            approval_id=approval_id,
            approver=approver,
            application_id=application_id,
        )

        raw_result = graph.invoke(state, config={"configurable": {"thread_id": workflow_id}})
        final_state: ApplicationWorkflowState = (
            raw_result
            if isinstance(raw_result, ApplicationWorkflowState)
            else ApplicationWorkflowState(**raw_result)
        )

        if final_state.final_result is None:
            logger.error(
                f"[{workflow_id}] Workflow completed but no final_result was set",
                extra={"workflow_id": workflow_id},
            )
            return ApplicationResult(
                success=False,
                status="workflow_error",
                message="Workflow completed without producing a result",
                metadata={"workflow_id": workflow_id, "adapter": adapter.name},
            )

        result = final_state.final_result
        record_audit(
            ACTION_SUBMIT,
            actor=approver,
            resource=approval_id,
            outcome=OUTCOME_SUCCESS if result.success else "blocked",
            metadata={
                "workflow_id": workflow_id,
                "adapter": adapter.name,
                "status": result.status,
                "job_url": prepared.request.job_url,
            },
            workflow_id=workflow_id,
        )
        record_audit(
            ACTION_VERIFY,
            actor=approver,
            resource=approval_id,
            outcome=OUTCOME_SUCCESS if result.success else OUTCOME_ERROR,
            metadata={
                "workflow_id": workflow_id,
                "adapter": adapter.name,
                "status": result.status,
            },
            workflow_id=workflow_id,
        )
        return result

    except Exception as e:
        logger.exception(
            "[workflow] Approved workflow execution failed",
            extra={"workflow_id": workflow_id, "approval_id": approval_id},
        )
        record_audit(
            ACTION_SUBMIT,
            actor=approver,
            resource=approval_id,
            outcome=OUTCOME_ERROR,
            metadata={"workflow_id": workflow_id, "adapter": adapter.name, "error": str(e)},
            workflow_id=workflow_id,
        )
        return ApplicationResult(
            success=False,
            status="workflow_error",
            message=f"Workflow execution failed: {e!s}",
            metadata={"workflow_id": workflow_id, "adapter": adapter.name, "error": str(e)},
        )


def record_prepare_audit(
    prepared: PreparedApplication,
    adapter: ApplicationAdapter,
    *,
    workflow_id: str,
    approval_id: str,
    actor: str = SYSTEM_ACTOR,
) -> None:
    """Record the prepare step in the audit trail."""
    record_audit(
        ACTION_PREPARE,
        actor=actor,
        resource=approval_id,
        outcome=OUTCOME_SUCCESS,
        metadata={
            "workflow_id": workflow_id,
            "adapter": adapter.name,
            "job_url": prepared.request.job_url,
            "company": prepared.request.company_name,
        },
        workflow_id=workflow_id,
    )


def select_adapter_for_url(
    job_url: str, adapters: list[ApplicationAdapter] | None = None
) -> ApplicationAdapter:
    """Select the appropriate adapter for a given job URL.

    Iterates through available adapters and returns the first one that
    supports the URL via adapter.supports_url(job_url).

    Args:
        job_url: The job URL to match
        adapters: List of ApplicationAdapter instances to check. The module's
            :data:`AVAILABLE_ADAPTERS` when omitted — read at call time, not
            captured as a default value, so there is exactly one list in the
            process and a caller cannot hold a stale copy of it.

    Returns:
        The first adapter that supports the URL

    Raises:
        RuntimeError: If no adapter supports the URL
    """
    candidates = AVAILABLE_ADAPTERS if adapters is None else adapters
    for adapter in candidates:
        if adapter.supports_url(job_url):
            logger.info(
                f"Selected adapter '{adapter.name}' for URL {job_url}",
                extra={"url": job_url, "adapter": adapter.name},
            )
            return adapter

    supported = ", ".join(a.name for a in candidates)
    raise RuntimeError(f"No adapter supports URL {job_url}. Available: {supported}")


def select_adapter_by_name(
    adapter_name: str, adapters: list[ApplicationAdapter] | None = None
) -> ApplicationAdapter:
    """The registered adapter with this name — the resolution the worker needs.

    WS-32. The approve route selects by URL, because a request names a URL. The
    worker does not: it has an approval row that recorded *which* adapter the
    human reviewed, so it resolves by name, and it must resolve through the
    **same** list the route selected from. A second list would be a second
    truth, and the drift would be silent: the route could approve a payload for
    an adapter the worker cannot find, and the submission would fail with a
    configuration error at exactly the wrong moment.

    Args:
        adapter_name: The adapter name recorded on the approval row.
        adapters: The candidate list; the module's :data:`AVAILABLE_ADAPTERS`
            when omitted. The default is read at call time, not captured, so
            the list can be replaced (a test's, or a deployment's).

    Returns:
        The adapter with that name.

    Raises:
        LookupError: No adapter in the list carries that name. The caller
            decides the HTTP status (404) or the work outcome (a refusal);
            this layer does not know about either.
    """
    candidates = AVAILABLE_ADAPTERS if adapters is None else adapters
    for adapter in candidates:
        if adapter.name == adapter_name:
            return adapter

    supported = ", ".join(adapter.name for adapter in candidates) or "none"
    raise LookupError(f"Adapter {adapter_name!r} is not available. Available: {supported}")
