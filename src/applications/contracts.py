from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ApplicationRequest(BaseModel):
    job_title: str
    company_name: str
    job_url: str
    candidate_name: str = "Candidate"
    email: str = "candidate@example.com"
    phone: str = "+1 555 000 0000"
    resume_path: str | None = None
    cover_letter: str | None = None
    custom_fields: dict[str, str] = Field(default_factory=dict)


class PreparedApplication(BaseModel):
    request: ApplicationRequest
    prepared_fields: dict[str, str] = Field(default_factory=dict)
    resume_path: str | None = None
    cover_letter: str | None = None
    prepared_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    requires_manual_review: bool = False
    # The workflow this payload belongs to (WS-06). The evidence artifacts
    # are named after it, and the approval record carries it.
    workflow_id: str | None = None


class SubmissionEvidence(BaseModel):
    url: str
    confirmation_text: str | None = None
    screenshot_path: str | None = None
    trace_path: str | None = None
    status: str = "unknown"


class ApplicationResult(BaseModel):
    success: bool
    status: str
    message: str
    evidence: SubmissionEvidence | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationAdapter(ABC):
    name: str = "application-adapter"

    @abstractmethod
    def supports_url(self, url: str) -> bool:
        """Return True when this adapter can handle the provided application URL."""

    @abstractmethod
    def prepare(self, request: ApplicationRequest) -> PreparedApplication:
        """Prepare a structured application payload prior to browser or API submission."""

    @abstractmethod
    def submit(self, prepared: PreparedApplication) -> ApplicationResult:
        """Submit the prepared application and return evidence of the outcome."""

    @abstractmethod
    def verify(self, result: ApplicationResult) -> ApplicationResult:
        """Verify that the submission truly succeeded and return the final status."""
