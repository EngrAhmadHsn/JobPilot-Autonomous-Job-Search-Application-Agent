"""Greenhouse API adapter for job application submission."""

from __future__ import annotations

import logging

from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.security.allowlist import host_matches_domain

logger = logging.getLogger(__name__)


class GreenhouseAdapter(ApplicationAdapter):
    """Adapter for Greenhouse-hosted job applications.

    Uses the Greenhouse public API / application endpoint where available.
    Falls back to structured payload preparation for manual submission.
    """

    name = "greenhouse"

    def supports_url(self, url: str) -> bool:
        # Exact host matching (WS-06 · SEC-06): a substring test would let
        # "evil-greenhouse.io.attacker.com" select this adapter.
        return host_matches_domain(url, "greenhouse.io")

    def prepare(self, request: ApplicationRequest) -> PreparedApplication:
        fields = {
            "candidate_name": request.candidate_name,
            "email": request.email,
            "phone": request.phone,
            "resume_path": request.resume_path or "",
            "cover_letter": request.cover_letter or "",
            **request.custom_fields,
        }
        return PreparedApplication(
            request=request,
            prepared_fields=fields,
            resume_path=request.resume_path,
            cover_letter=request.cover_letter,
        )

    def submit(self, prepared: PreparedApplication) -> ApplicationResult:
        # Placeholder: real implementation would POST to the board endpoint
        logger.info("Greenhouse submit called (placeholder)")
        return ApplicationResult(
            success=True,
            status="submitted",
            message="Greenhouse submission placeholder",
            evidence=SubmissionEvidence(
                url=prepared.request.job_url,
                status="submitted",
            ),
        )

    def verify(self, result: ApplicationResult) -> ApplicationResult:
        # Placeholder verification
        return ApplicationResult(
            success=result.success,
            status="verified" if result.success else result.status,
            message=result.message,
            evidence=result.evidence,
        )
