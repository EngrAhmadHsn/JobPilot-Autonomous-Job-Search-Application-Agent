"""Job source contracts and normalization models."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class JobListing(BaseModel):
    """Normalized job listing from any source."""

    id: str
    source: str
    source_job_id: str | None = None
    title: str
    company: str
    description: str | None = None
    location: str | None = None
    remote_policy: str | None = None
    employment_type: str | None = None
    salary: str | None = None
    currency: str | None = None
    seniority: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    experience_requirements: str | None = None
    education_requirements: str | None = None
    application_url: str | None = None
    company_url: str | None = None
    posted_at: str | None = None
    metadata: dict = Field(default_factory=dict)


class JobSource(Protocol):
    """Abstract interface for job retrieval sources."""

    async def search(self, query: str, location: str | None = None) -> list[JobListing]: ...

    async def get_job(self, job_id: str) -> JobListing | None: ...
