"""Lever Postings API adapter (WS-02 task 3).

Public, unauthenticated endpoint:
``GET https://api.lever.co/v0/postings/{company}?mode=json``

Returns a list of postings (see the mapping in :meth:`LeverJobAdapter._normalize`).
Like Greenhouse there is no server-side query, so postings are fetched
company-wide and filtered client-side. Company slugs are configured via
``settings.lever_companies``; the adapter only ever constructs URLs from its
own host constant plus a strictly validated slug.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.config.settings import get_settings
from src.jobs.board_health import record_failure, record_success
from src.jobs.contracts import JobListing
from src.jobs.http_client import SourceError, create_client, guarded_get
from src.jobs.normalize import html_to_text, ms_epoch_to_iso
from src.jobs.salary import salary_from_lever_range
from src.jobs.seniority import classify_seniority
from src.jobs.skills import split_required_preferred


def _text_from_lists(lists: Any) -> str:
    """The plain text of Lever's ``lists[]`` requirements blocks.

    Each entry is ``{"text": NAME, "content": "<li>…</li><li>…</li>"}`` —
    a bare sequence of ``<li>`` elements with no wrapping ``<ul>``. The
    content is therefore wrapped in a ``<ul>`` before it is converted to
    text, so the bullets come out one per line instead of running
    together.
    """
    if not isinstance(lists, list):
        return ""
    chunks: list[str] = []
    for entry in lists:
        if not isinstance(entry, dict):
            continue
        label = entry.get("text")
        content = entry.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        heading = label.strip() if isinstance(label, str) and label.strip() else ""
        wrapped = content.strip()
        if "<li" in wrapped.lower() and "<ul" not in wrapped.lower():
            wrapped = f"<ul>{wrapped}</ul>"
        body = html_to_text(wrapped)
        if body:
            chunks.append(f"{heading}\n{body}" if heading else body)
    return "\n".join(chunks)


def _merge_skills(existing: list[str], extra: list[str]) -> list[str]:
    """Two skill lists, without duplicates, preserving order."""
    merged: list[str] = []
    seen: set[str] = set()
    for skill in [*existing, *extra]:
        key = skill.strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(skill.strip())
    return merged


logger = logging.getLogger(__name__)

LEVER_API_HOST = "api.lever.co"
LEVER_BASE_URL = f"https://{LEVER_API_HOST}/v0/postings"

# Company slugs are URL path segments; refuse anything else before a URL is
# built (same injection rationale as Greenhouse board tokens).
_COMPANY_SLUG_RE = re.compile(r"[A-Za-z0-9_-]+")


def _is_valid_company_slug(slug: str) -> bool:
    return bool(slug) and _COMPANY_SLUG_RE.fullmatch(slug) is not None


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


class LeverJobAdapter:
    """JobSource implementation for public Lever postings."""

    name = "lever"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        companies: list[str] | None = None,
    ) -> None:
        self._client = client
        self._companies = companies

    def _resolve_companies(self) -> list[str]:
        """The boards this adapter watches (WS-23, Phase 5).

        The registry is the source of truth; the environment list is the
        seed and the fallback for a database that is not ready.
        """
        if self._companies is not None:
            return self._companies
        from src.jobs.board_health import registry_slugs

        registered = registry_slugs("lever")
        if registered:
            return registered
        return get_settings().lever_companies

    def _postings_url(self, company: str) -> str:
        return f"{LEVER_BASE_URL}/{company}?mode=json"

    def _posting_url(self, company: str, job_id: str) -> str:
        return f"{LEVER_BASE_URL}/{company}/{job_id}?mode=json"

    def _normalize(self, payload: dict[str, Any], company: str) -> JobListing | None:
        job_id = payload.get("id")
        title = (payload.get("text") or "").strip()
        if not job_id or not title:
            # Skip listings without identity; never fabricate a stand-in.
            return None
        description = (payload.get("descriptionPlain") or "").strip()
        categories = payload.get("categories") or {}
        required_skills, preferred_skills = split_required_preferred(description)
        commitment = (categories.get("commitment") or "").strip()

        # WS-23: Lever's ``lists[]`` is where the requirements bullets
        # live — ``{"text": "Skill Set:", "content": "<li>3+ years of
        # …</li><li>…</li>"}``. The content is a bare sequence of ``<li>``
        # elements with no wrapping ``<ul>``, so it is wrapped before it is
        # parsed. This is the best structured requirements source of the
        # four providers, and it was being discarded entirely.
        list_text = _text_from_lists(payload.get("lists"))
        if list_text:
            list_required, list_preferred = split_required_preferred(list_text)
            required_skills = _merge_skills(required_skills, list_required)
            preferred_skills = _merge_skills(preferred_skills, list_preferred)

        # ``workplaceType`` is Lever's own work-mode statement: "hybrid",
        # "onsite", "remote" or "unspecified" (verified live). It is
        # authoritative, and it is what the location component needs —
        # the adapter previously left ``remote_policy`` unset for every
        # Lever listing, which put all 350 of them through the
        # location component's fallback branch.
        workplace_type = (payload.get("workplaceType") or "").strip().casefold()
        remote_policy = workplace_type if workplace_type in {"hybrid", "onsite", "remote"} else None

        salary, currency = salary_from_lever_range(
            payload.get("salaryRange"), payload.get("salaryDescription")
        )

        extra_metadata: dict[str, Any] = {}
        team = (categories.get("team") or "").strip()
        if team:
            extra_metadata["team"] = team
        department = (categories.get("department") or "").strip()
        if department:
            extra_metadata["department"] = department
        all_locations = categories.get("allLocations")
        if isinstance(all_locations, list) and all_locations:
            extra_metadata["all_locations"] = [
                str(loc).strip() for loc in all_locations if str(loc).strip()
            ]
        country = (payload.get("country") or "").strip()
        if country:
            extra_metadata["country"] = country.upper()

        return JobListing(
            # Canonical id embeds the company slug because Lever posting ids
            # are only unique per company; get_job parses it back.
            id=f"lever:{company}:{job_id}",
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            # Lever postings carry no company name field; the configured slug
            # is the company the user asked to watch.
            company=company.replace("-", " ").replace("_", " ").title(),
            description=description or None,
            location=(categories.get("location") or "").strip() or None,
            remote_policy=remote_policy,
            employment_type=commitment or None,
            salary=salary,
            currency=currency,
            seniority=classify_seniority(title),
            application_url=(payload.get("applyUrl") or "").strip() or None,
            company_url=(payload.get("hostedUrl") or "").strip() or None,
            posted_at=ms_epoch_to_iso(payload.get("createdAt")),
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            metadata=extra_metadata,
        )

    async def search(self, query: str, location: str | None = None) -> list[JobListing]:
        """Fetch all configured companies and client-side filter by query tokens."""
        tokens = _query_tokens(query)
        if self._client is not None:
            return await self._search_with(self._client, tokens)
        async with create_client() as client:
            return await self._search_with(client, tokens)

    async def _search_with(self, client: httpx.AsyncClient, tokens: list[str]) -> list[JobListing]:
        listings: list[JobListing] = []
        for company in self._resolve_companies():
            if not _is_valid_company_slug(company):
                logger.warning("Skipping invalid Lever company slug %r", company)
                continue
            try:
                response = await guarded_get(client, self._postings_url(company))
                payload = response.json()
            except (SourceError, ValueError) as exc:
                # One unavailable company must not sink the search.
                logger.warning("Lever postings for %r unavailable: %s", company, exc)
                record_failure("lever", company, exc)
                continue
            if not isinstance(payload, list):
                logger.warning("Lever postings for %r returned unexpected payload", company)
                record_failure("lever", company, "unexpected payload")
                continue
            record_success("lever", company, len(payload))
            for posting in payload:
                listing = self._normalize(posting, company)
                if listing is not None and _matches_query(listing, tokens):
                    listings.append(listing)
        return listings

    async def get_job(self, job_id: str) -> JobListing | None:
        """Fetch one posting by canonical id ``lever:{company}:{job_id}``.

        The canonical id embeds the company slug because Lever posting ids
        are only unique per company.
        """
        parts = job_id.split(":")
        if len(parts) != 3 or parts[0] != self.name:
            return None
        company, source_job_id = parts[1], parts[2]
        if not _is_valid_company_slug(company) or not source_job_id:
            return None
        if self._client is not None:
            return await self._get_job_with(self._client, company, source_job_id)
        async with create_client() as client:
            return await self._get_job_with(client, company, source_job_id)

    async def _get_job_with(
        self, client: httpx.AsyncClient, company: str, source_job_id: str
    ) -> JobListing | None:
        try:
            response = await guarded_get(client, self._posting_url(company, source_job_id))
            payload = response.json()
        except (SourceError, ValueError) as exc:
            logger.warning(
                "Lever job fetch failed for lever:%s:%s: %s", company, source_job_id, exc
            )
            return None
        return self._normalize(payload, company)
