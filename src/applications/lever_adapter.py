"""Lever API adapter for job application submission."""

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


class LeverAdapter(ApplicationAdapter):
    """Adapter for Lever-hosted job applications."""

    name = "lever"

    def supports_url(self, url: str) -> bool:
        # Exact host matching (WS-06 · SEC-06): a substring test would let
        # "notlever.co.attacker.com" select this adapter.
        return host_matches_domain(url, "lever.co")

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
        logger.info("Lever submit called (placeholder)")
        return ApplicationResult(
            success=True,
            status="submitted",
            message="Lever submission placeholder",
            evidence=SubmissionEvidence(
                url=prepared.request.job_url,
                status="submitted",
            ),
        )

    def verify(self, result: ApplicationResult) -> ApplicationResult:
        return ApplicationResult(
            success=result.success,
            status="verified" if result.success else result.status,
            message=result.message,
            evidence=result.evidence,
        )
