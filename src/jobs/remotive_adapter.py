"""Remotive public API adapter (WS-02 task 3).

Public, unauthenticated endpoint:
``GET https://remotive.com/api/remote-jobs?search={q}``

Remotive is remote-only, so ``remote_policy`` is always ``"remote"``. Unlike
Greenhouse/Lever, Remotive filters server-side via the ``search`` parameter —
no client-side filter here (an empty query returns the full board, which the
search planner avoids by always deriving at least one query). Tags are kept
verbatim as required skills (they are the board's own taxonomy), supplemented
by lexicon extraction from the HTML description.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from src.jobs.contracts import JobListing
from src.jobs.http_client import SourceError, create_client, guarded_get
from src.jobs.normalize import html_to_text, normalize_publication_date
from src.jobs.skills import extract_skills

logger = logging.getLogger(__name__)

REMOTIVE_API_HOST = "remotive.com"
REMOTIVE_BASE_URL = f"https://{REMOTIVE_API_HOST}/api/remote-jobs"


def _normalize_job_type(value: Any) -> str | None:
    """Normalize Remotive job_type to hyphenated form ("full_time" -> "full-time")."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().replace("_", "-")


class RemotiveJobAdapter:
    """JobSource implementation for the Remotive remote-jobs API."""

    name = "remotive"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def _search_url(self, query: str) -> str:
        if query.strip():
            return f"{REMOTIVE_BASE_URL}?search={quote(query.strip())}"
        return REMOTIVE_BASE_URL

    def _normalize(self, payload: dict[str, Any]) -> JobListing | None:
        job_id = payload.get("id")
        title = (payload.get("title") or "").strip()
        company = (payload.get("company_name") or "").strip()
        if job_id is None or not title or not company:
            # id/title/company are the acceptance-critical fields; a listing
            # missing any of them is skipped rather than fabricated.
            return None
        description = html_to_text(payload.get("description"))
        tags = [
            tag.strip()
            for tag in (payload.get("tags") or [])
            if isinstance(tag, str) and tag.strip()
        ]
        # Board tags first (verbatim taxonomy), then lexicon skills from the
        # description, deduplicated preserving order.
        required_skills = list(dict.fromkeys([*tags, *extract_skills(description)]))
        return JobListing(
            id=f"remotive:{job_id}",
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            company=company,
            description=description or None,
            location=(payload.get("candidate_required_location") or "").strip() or None,
            remote_policy="remote",
            employment_type=_normalize_job_type(payload.get("job_type")),
            salary=(payload.get("salary") or "").strip() or None,
            posted_at=normalize_publication_date(payload.get("publication_date")),
            application_url=(payload.get("url") or "").strip() or None,
            required_skills=required_skills,
        )

    async def search(self, query: str, location: str | None = None) -> list[JobListing]:
        """Query the Remotive search endpoint and normalize the results."""
        if self._client is not None:
            return await self._search_with(self._client, query)
        async with create_client() as client:
            return await self._search_with(client, query)

    async def _search_with(self, client: httpx.AsyncClient, query: str) -> list[JobListing]:
        try:
            response = await guarded_get(client, self._search_url(query))
            payload = response.json()
        except (SourceError, ValueError) as exc:
            raise SourceError(f"Remotive search failed for query {query!r}: {exc}") from exc
        jobs = payload.get("jobs") or []
        listings = []
        for job in jobs:
            listing = self._normalize(job)
            if listing is not None:
                listings.append(listing)
        return listings

    async def get_job(self, job_id: str) -> JobListing | None:
        """Fetch one job by canonical id ``remotive:{job_id}``.

        The public API has no single-job endpoint, so this fetches the full
        board once and finds the job — an explicit, documented trade-off for
        a rarely used detail path.
        """
        prefix = f"{self.name}:"
        if not job_id.startswith(prefix):
            return None
        source_job_id = job_id[len(prefix) :]
        if not source_job_id:
            return None
        if self._client is not None:
            return await self._find_by_id(self._client, source_job_id)
        async with create_client() as client:
            return await self._find_by_id(client, source_job_id)

    async def _find_by_id(self, client: httpx.AsyncClient, source_job_id: str) -> JobListing | None:
        try:
            response = await guarded_get(client, REMOTIVE_BASE_URL)
            payload = response.json()
        except (SourceError, ValueError) as exc:
            logger.warning("Remotive board fetch failed while finding %r: %s", source_job_id, exc)
            return None
        for job in payload.get("jobs") or []:
            if str(job.get("id")) == source_job_id:
                return self._normalize(job)
        return None
