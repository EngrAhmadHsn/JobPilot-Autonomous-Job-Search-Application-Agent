"""LinkedIn adapter for job source abstraction."""

from __future__ import annotations

import logging

from src.jobs.contracts import JobListing, JobSource

logger = logging.getLogger(__name__)


class LinkedInAdapter(JobSource):
    """Placeholder adapter for LinkedIn job source."""

    name = "linkedin"

    async def search(self, query: str, location: str | None = None) -> list[JobListing]:
        logger.info("LinkedIn search placeholder: %s (%s)", query, location)
        return []

    async def get_job(self, job_id: str) -> JobListing | None:
        logger.info("LinkedIn get_job placeholder: %s", job_id)
        return None
