"""Tests for Phase 3 job source abstraction."""

import pytest

from src.jobs.contracts import JobListing
from src.jobs.linkedin_adapter import LinkedInAdapter


@pytest.mark.asyncio
async def test_linkedin_adapter_search():
    adapter = LinkedInAdapter()
    results = await adapter.search("engineer", "remote")
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_linkedin_adapter_get_job():
    adapter = LinkedInAdapter()
    result = await adapter.get_job("123")
    assert result is None


def test_job_listing_model():
    job = JobListing(
        id="1",
        source="linkedin",
        title="Engineer",
        company="Tech",
    )
    assert job.id == "1"
    assert job.source == "linkedin"
