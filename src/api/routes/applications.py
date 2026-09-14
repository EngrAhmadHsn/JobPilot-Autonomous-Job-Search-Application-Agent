"""API routes for job application submission and workflow management."""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.applications.contracts import (
    ApplicationRequest,
    ApplicationResult,
)
from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter
from src.graph.executor import execute_application_workflow, select_adapter_for_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/applications", tags=["applications"])

# Available adapters (will be expanded in Phase 2 #2b with Greenhouse, Lever, etc.)
AVAILABLE_ADAPTERS = [
    FakeAtsPlaywrightAdapter(),
]


class ApplicationSubmitRequest(BaseModel):
    """Request body for submitting a job application."""

    job_title: str = Field(..., description="Job title from the posting")
    company_name: str = Field(..., description="Company name")
    job_url: str = Field(..., description="URL of the job posting")

    candidate_name: str = Field(..., description="Full name of the candidate")
    email: str = Field(..., description="Email address")
    phone: str = Field(..., description="Phone number")

    resume_path: Optional[str] = Field(None, description="File path to candidate resume")
    cover_letter: Optional[str] = Field(None, description="Cover letter text or path")

    custom_fields: dict = Field(default_factory=dict, description="Additional form fields")

    approval: bool = Field(
        default=False,
        description="Set to True to auto-approve; False to require external approval",
    )


class ApplicationSubmitResponse(BaseModel):
    """Response body for application submission."""

    workflow_id: str = Field(..., description="Unique workflow execution ID")
    adapter_name: str = Field(..., description="Name of the adapter used")

    success: bool = Field(..., description="Whether the application was successfully submitted")
    status: str = Field(..., description="Status: submitted, verified, rejected, etc.")
    message: str = Field(..., description="Human-readable status message")

    evidence: Optional[dict] = Field(
        None, description="Submission evidence (URL, confirmation text, etc.)"
    )
    metadata: Optional[dict] = Field(None, description="Additional metadata")


@router.post("/submit", response_model=ApplicationSubmitResponse)
def submit_application(req: ApplicationSubmitRequest) -> ApplicationSubmitResponse:
    """Submit a job application via the automated workflow.

    This endpoint accepts an ApplicationSubmitRequest, selects the appropriate
    adapter based on the job_url, and executes the full application workflow:

    1. Prepare: validate and structure the request
    2. Approval: check approval gate (via request.approval flag for now)
    3. Submit: call adapter.submit() to fill forms and submit (if approved)
    4. Verify: check confirmation page (if submitted)

    The workflow returns an ApplicationResult with evidence and status.

    **Security note**: This endpoint currently uses the `approval` flag for
    testing. In production, approval will come from a separate authorization
    service or human review queue.

    Args:
        req: ApplicationSubmitRequest with job and candidate details

    Returns:
        ApplicationSubmitResponse with workflow_id, status, and result

    Raises:
        HTTPException 400: If no adapter supports the job_url
        HTTPException 500: If workflow execution fails
    """
    workflow_id = str(uuid.uuid4())[:8]

    try:
        logger.info(
            f"[{workflow_id}] Application submit endpoint called",
            extra={
                "workflow_id": workflow_id,
                "company": req.company_name,
                "job_url": req.job_url,
                "approval": req.approval,
            },
        )

        # Select adapter based on job_url
        try:
            adapter = select_adapter_for_url(req.job_url, AVAILABLE_ADAPTERS)
        except RuntimeError as e:
            logger.warning(
                f"[{workflow_id}] No adapter found for URL: {req.job_url}",
                extra={"workflow_id": workflow_id, "url": req.job_url, "error": str(e)},
            )
            raise HTTPException(
                status_code=400,
                detail=f"No adapter available for job URL: {req.job_url}",
            )

        # Build ApplicationRequest from submit request
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

        # Execute workflow (approval flag is pre-set in request)
        result: ApplicationResult = execute_application_workflow(
            request=app_request,
            adapter=adapter,
            approval=req.approval,
        )

        # Build response
        evidence_dict = None
        if result.evidence:
            evidence_dict = {
                "url": result.evidence.url,
                "confirmation_text": result.evidence.confirmation_text[:200]
                if result.evidence.confirmation_text
                else None,
                "status": result.evidence.status,
            }

        response = ApplicationSubmitResponse(
            workflow_id=workflow_id,
            adapter_name=adapter.name,
            success=result.success,
            status=result.status,
            message=result.message,
            evidence=evidence_dict,
            metadata=result.metadata,
        )

        logger.info(
            f"[{workflow_id}] Application submit completed: {result.status}",
            extra={
                "workflow_id": workflow_id,
                "success": result.success,
                "status": result.status,
            },
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[{workflow_id}] Unexpected error during application submit: {str(e)}",
            extra={"workflow_id": workflow_id, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Application submission failed: {str(e)}",
        )
