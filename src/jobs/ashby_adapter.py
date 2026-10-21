"""Ashby posting API adapter (WS-02/FU-2).

Public, unauthenticated endpoint:
``GET https://api.ashbyhq.com/posting-api/job-board/{org}``

Like Greenhouse/Lever there is no server-side query parameter, so every
configured org board is fetched board-wide and filtered client-side by query
tokens. Org slugs are configured via ``settings.ashby_orgs`` (the user
curates which boards to watch — this is a personal agent, not a crawler).
The adapter only ever constructs URLs from its own host constant plus a
strictly validated org slug; it never fetches a URL that a response suggested.

Field mapping (verified against the live API 2026-10-11; see
docs/implementation/04-pipeline-and-api.md FU-2): ``descriptionPlain`` is
populated in practice, so it is preferred verbatim with
``html_to_text(descriptionHtml)`` as the fallback. There is no company-name
field — the configured org slug stands in for the company, exactly like
Lever. Ashby's public API has no single-job endpoint, so ``get_job`` fetches
the board once and scans it (the documented Remotive trade-off for a rarely
used detail path).
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.config.settings import get_settings
from src.jobs.contracts import JobListing
from src.jobs.http_client import SourceError, create_client, guarded_get
from src.jobs.normalize import html_to_text, job_records
from src.jobs.skills import extract_skills

logger = logging.getLogger(__name__)

ASHBY_API_HOST = "api.ashbyhq.com"
ASHBY_BASE_URL = f"https://{ASHBY_API_HOST}/posting-api/job-board"

# Org slugs are URL path segments; anything outside this set is either a
# typo or an injection attempt and is refused before a URL is built.
_ORG_SLUG_RE = re.compile(r"[A-Za-z0-9_-]+")

# CamelCase employmentType values ("FullTime") normalize to hyphenated
# lowercase, matching Remotive's "full_time" -> "full-time" convention.
_EMPLOYMENT_TYPE_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _is_valid_org_slug(slug: str) -> bool:
    return bool(slug) and _ORG_SLUG_RE.fullmatch(slug) is not None


def _normalize_employment_type(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _EMPLOYMENT_TYPE_RE.sub("-", value.strip()).lower()


def _normalize_remote_policy(payload: dict[str, Any]) -> str | None:
    """Remote policy from ``isRemote``/``workplaceType`` — nothing invented."""
    if payload.get("isRemote") is True:
        return "remote"
    workplace = payload.get("workplaceType")
    if isinstance(workplace, str) and workplace.strip() and workplace.strip().lower() != "none":
        return workplace.strip().lower()
    return None


def _query_tokens(query: str) -> list[str]:
    tokens = []
    for raw in query.lower().split():
        token = re.sub(r"[^a-z0-9+#.]", "", raw)
        if len(token) >= 2 and token not in tokens:
            tokens.append(token)
    return tokens


def _matches_query(listing: JobListing, tokens: list[str]) -> bool:
    if not tokens:
        return True
    haystack = f"{listing.title} {listing.description or ''}".lower()
    return any(token in haystack for token in tokens)


class AshbyJobAdapter:
    """JobSource implementation for public Ashby job boards."""

    name = "ashby"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        orgs: list[str] | None = None,
    ) -> None:
        self._client = client
        self._orgs = orgs

    def _resolve_orgs(self) -> list[str]:
        if self._orgs is not None:
            return self._orgs
        return get_settings().ashby_orgs

    def _board_url(self, org: str) -> str:
        return f"{ASHBY_BASE_URL}/{org}"

    def _normalize(self, payload: dict[str, Any], org: str) -> JobListing | None:
        job_id = payload.get("id")
        title = (payload.get("title") or "").strip()
        if not job_id or not title:
            # Without an id the listing cannot be deduplicated or persisted;
            # without a title it is not a usable listing. Skip, never fabricate.
            return None
        description = (payload.get("descriptionPlain") or "").strip()
        if not description:
            description = html_to_text(payload.get("descriptionHtml"))
        required_skills = extract_skills(description)
        return JobListing(
            # Canonical id embeds the org slug because Ashby job ids are
            # only unique per board; get_job parses it back.
            id=f"ashby:{org}:{job_id}",
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            # Ashby postings carry no company name field; the configured org
            # slug is the company the user asked to watch (Lever convention).
            company=org.replace("-", " ").replace("_", " ").title(),
            description=description or None,
            location=(payload.get("location") or "").strip() or None,
            remote_policy=_normalize_remote_policy(payload),
            employment_type=_normalize_employment_type(payload.get("employmentType")),
            application_url=(payload.get("applyUrl") or "").strip() or None,
            company_url=(payload.get("jobUrl") or "").strip() or None,
            posted_at=(payload.get("publishedAt") or "").strip() or None,
            required_skills=required_skills,
            metadata={
                key: value
                for key, value in (
                    ("department", (payload.get("department") or "").strip() or None),
                    ("team", (payload.get("team") or "").strip() or None),
                )
                if value
            },
        )

    async def search(self, query: str, location: str | None = None) -> list[JobListing]:
        """Fetch all configured org boards and client-side filter by query tokens."""
        tokens = _query_tokens(query)
        if self._client is not None:
            return await self._search_with(self._client, tokens)
        async with create_client() as client:
            return await self._search_with(client, tokens)

    async def _search_with(self, client: httpx.AsyncClient, tokens: list[str]) -> list[JobListing]:
        listings: list[JobListing] = []
        for org in self._resolve_orgs():
            if not _is_valid_org_slug(org):
                logger.warning("Skipping invalid Ashby org slug %r", org)
                continue
            try:
                response = await guarded_get(client, self._board_url(org))
                payload = response.json()
            except (SourceError, ValueError) as exc:
                # One unavailable board must not sink the search; the registry
                # also degrades per source, this degrades per board.
                logger.warning("Ashby board %r unavailable: %s", org, exc)
                continue
            for job in job_records(payload):
                listing = self._normalize(job, org)
                if listing is not None and _matches_query(listing, tokens):
                    listings.append(listing)
        return listings

    async def get_job(self, job_id: str) -> JobListing | None:
        """Fetch one job by canonical id ``ashby:{org}:{job_id}``.

        The public posting API has no single-job endpoint, so this fetches
        the full board once and finds the job — an explicit, documented
        trade-off for a rarely used detail path.
        """
        parts = job_id.split(":")
        if len(parts) != 3 or parts[0] != self.name:
            return None
        org, source_job_id = parts[1], parts[2]
        if not _is_valid_org_slug(org) or not source_job_id:
            return None
        if self._client is not None:
            return await self._find_by_id(self._client, org, source_job_id)
        async with create_client() as client:
            return await self._find_by_id(client, org, source_job_id)

    async def _find_by_id(
        self, client: httpx.AsyncClient, org: str, source_job_id: str
    ) -> JobListing | None:
        try:
            response = await guarded_get(client, self._board_url(org))
            payload = response.json()
        except (SourceError, ValueError) as exc:
            logger.warning("Ashby board fetch failed while finding %r: %s", source_job_id, exc)
            return None
        for job in job_records(payload):
            if str(job.get("id")) == source_job_id:
                return self._normalize(job, org)
        return None
