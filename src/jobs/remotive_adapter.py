"""Remotive public API adapter (WS-02 task 3, WS-23).

Public, unauthenticated endpoint:
``GET https://remotive.com/api/remote-jobs``

Remotive is remote-only, so ``remote_policy`` is always ``"remote"``.

WS-23: the adapter's docstring used to say that Remotive filters
server-side via the ``search`` parameter, unlike Greenhouse/Lever. **That
is no longer true.** The endpoint is served as a static JSON file by
Cloudflare and every query parameter is ignored — measured live on
2026-11-09, ``?search=engineer``, ``?search=zzzznonexistentterm``,
``?limit=1``, ``?category=software-dev`` and ``?company_name=…`` all
returned byte-identical bodies (204,646 B, 12 jobs). A query for "react"
was therefore returning the whole board.

The filter is now **client-side**, matching the other three adapters. The
live catalog is also much smaller than it once was — 12 listings, down
from the thousands the board historically held — so Remotive is a
remote-first supplement, not a scale source. Its terms ask for no more
than about four fetches a day and require credit and a link back.

Tags are kept verbatim as required skills (they are the board's own
taxonomy), supplemented by lexicon extraction from the HTML description.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from src.jobs.contracts import JobListing
from src.jobs.http_client import SourceError, create_client, guarded_get
from src.jobs.normalize import html_to_text, job_records, normalize_publication_date
from src.jobs.salary import parse_salary_range
from src.jobs.seniority import classify_seniority
from src.jobs.skills import extract_skills

logger = logging.getLogger(__name__)

REMOTIVE_API_HOST = "remotive.com"
REMOTIVE_BASE_URL = f"https://{REMOTIVE_API_HOST}/api/remote-jobs"


def _query_tokens(query: str) -> list[str]:
    """Lowercased word tokens of a query, punctuation-stripped, length >= 2."""
    tokens: list[str] = []
    for raw in query.lower().split():
        token = re.sub(r"[^a-z0-9+#.]", "", raw)
        if len(token) >= 2 and token not in tokens:
            tokens.append(token)
    return tokens


def _matches_query(listing: JobListing, query: str) -> bool:
    """Client-side filter: ANY query token found in title or description.

    This is the same rule the Greenhouse, Lever and Ashby adapters use, so
    a query means the same thing across the four sources.
    """
    tokens = _query_tokens(query)
    if not tokens:
        return True
    haystack = f"{listing.title} {listing.description or ''}".lower()
    return any(token in haystack for token in tokens)


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
        """The board URL.

        WS-23: the ``search`` parameter is **inert**. The endpoint is
        served as a static JSON file by Cloudflare and every query
        parameter is ignored — measured live on 2026-11-09:
        ``?search=engineer``, ``?search=zzzznonexistentterm``,
        ``?limit=1``, ``?limit=100``, ``?category=software-dev`` and
        ``?company_name=…`` all returned **byte-identical** bodies
        (204,646 B, 12 jobs). The adapter used to rely on server-side
        filtering and its docstring said so; the filtering is now
        client-side, matching the other three adapters.

        The parameter is still sent — it is harmless, and a future
        endpoint that honours it would narrow the result set further.
        """
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
        # WS-23: the salary is a free-text string ("$25k - $35k",
        # "$50-$75 /hour", "$35,3k- $52k" with a European decimal comma).
        # It is parsed tolerantly into a range and a currency, and the raw
        # text is kept so the console can show what the board actually
        # said.
        raw_salary = (payload.get("salary") or "").strip() or None
        salary, currency = parse_salary_range(raw_salary)
        extra_metadata: dict[str, Any] = {}
        if raw_salary:
            extra_metadata["salary_text"] = raw_salary
        category = (payload.get("category") or "").strip()
        if category:
            extra_metadata["category"] = category
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
            salary=salary,
            currency=currency,
            seniority=classify_seniority(title),
            posted_at=normalize_publication_date(payload.get("publication_date")),
            application_url=(payload.get("url") or "").strip() or None,
            required_skills=required_skills,
            metadata=extra_metadata,
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
        jobs = job_records(payload)
        listings = []
        for job in jobs:
            listing = self._normalize(job)
            if listing is not None and _matches_query(listing, query):
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
        for job in job_records(payload):
            if str(job.get("id")) == source_job_id:
                return self._normalize(job)
        return None
