"""Greenhouse Board API adapter (WS-02 task 3).

Public, unauthenticated endpoint:
``GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true``

The API has no query parameter, so every configured board is fetched
board-wide and filtered client-side by query tokens against title and
description. Board tokens are configured via ``settings.greenhouse_boards``
(the user curates which boards to watch — this is a personal agent, not a
crawler). The adapter only ever constructs URLs from its own host constant
plus a strictly validated token; it never fetches a URL that a response
suggested.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.config.settings import get_settings
from src.jobs.board_health import record_failure, record_success
from src.jobs.board_metadata import (
    _EMPLOYMENT_ALIASES,
    GREENHOUSE_BOARD_METADATA,
    BoardMetadataMap,
    metadata_value,
    remote_policy_from_metadata,
)
from src.jobs.contracts import JobListing
from src.jobs.http_client import SourceError, create_client, guarded_get
from src.jobs.normalize import html_to_text, job_records
from src.jobs.salary import salary_from_greenhouse_pay_ranges
from src.jobs.seniority import classify_seniority
from src.jobs.skills import split_required_preferred

logger = logging.getLogger(__name__)

GREENHOUSE_API_HOST = "boards-api.greenhouse.io"
GREENHOUSE_BASE_URL = f"https://{GREENHOUSE_API_HOST}/v1/boards"

# Board tokens are URL path segments; anything outside this set is either a
# typo or an injection attempt and is refused before a URL is built.
_BOARD_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]+")

# WS-15: job ids are URL path segments too, and they are board-supplied.
# A Greenhouse id is a number, but the shape that matters is "a path
# segment and nothing else" — no ``/``, no ``?``, no ``#``, no ``..``.
_JOB_ID_RE = re.compile(r"[A-Za-z0-9_-]+")


def _is_valid_board_token(token: str) -> bool:
    return bool(token) and _BOARD_TOKEN_RE.fullmatch(token) is not None


def _is_valid_job_id(job_id: str) -> bool:
    """True when *job_id* is safe to interpolate into a URL path."""
    return bool(job_id) and _JOB_ID_RE.fullmatch(job_id) is not None


def _query_tokens(query: str) -> list[str]:
    """Lowercased word tokens of a query, punctuation-stripped, length >= 2."""
    tokens = []
    for raw in query.lower().split():
        token = re.sub(r"[^a-z0-9+#.]", "", raw)
        if len(token) >= 2 and token not in tokens:
            tokens.append(token)
    return tokens


def _matches_query(listing: JobListing, tokens: list[str]) -> bool:
    """Client-side filter: ANY query token found in title or description."""
    if not tokens:
        return True
    haystack = f"{listing.title} {listing.description or ''}".lower()
    return any(token in haystack for token in tokens)


def _employment_type_from_metadata(metadata: Any, board: str | None = None) -> str | None:
    """Extract employment type from Greenhouse ``metadata[]`` key/value pairs.

    Greenhouse metadata entries appear as ``{"name"|"key": ..., "value": ...}``,
    and **the key naming is not standardized across boards**. The adapter
    used to look for a key called ``"employmentType"`` — which appears
    **zero** times across the 11 boards and 4,406 jobs in the registry
    (measured live, 2026-11-09). The board that publishes it calls it
    ``"Employee Type"`` (block), and the others publish nothing.

    WS-23: the lookup is now per-board, with a small alias fallback. The
    board's own key wins; the aliases are only tried when the board has
    no explicit entry. Nothing is invented when no key is present — an
    employment type that is not stated stays unknown, because the
    preference component treats an unknown as unknown rather than as a
    match.
    """
    board_map = GREENHOUSE_BOARD_METADATA.get(board or "", BoardMetadataMap())
    keys: list[str] = []
    if board_map.employment_type_key:
        keys.append(board_map.employment_type_key)
    keys.extend(board_map.employment_type_aliases)
    if not keys:
        keys.extend(_EMPLOYMENT_ALIASES)
    return metadata_value(metadata, tuple(dict.fromkeys(keys)))


class GreenhouseJobAdapter:
    """JobSource implementation for public Greenhouse boards."""

    name = "greenhouse"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        boards: list[str] | None = None,
    ) -> None:
        self._client = client
        self._boards = boards

    def _resolve_boards(self) -> list[str]:
        """The boards this adapter watches.

        WS-23, Phase 5: the **registry** is the source of truth, and the
        environment list is the seed. The registry is what carries the
        per-board health, so an adapter that only read the env list
        could not know which boards were failing — and a board the
        operator disabled would keep being fetched.

        The env list is still the fallback for a database that is not
        ready, so a fresh checkout with no registry still works.
        """
        if self._boards is not None:
            return self._boards
        from src.jobs.board_health import registry_slugs

        registered = registry_slugs("greenhouse")
        if registered:
            return registered
        return get_settings().greenhouse_boards

    def _board_url(self, token: str, *, content: bool = True) -> str:
        """Board listing URL.

        ``content=False`` gives the ~11x lighter listing payload (verified
        live 2026-10-11: 7,512 B -> 666 B per job on stripe): same jobs,
        ``title``/``location``/``absolute_url``/``metadata`` survive, only
        the ``content`` HTML body is omitted.

        ``pay_transparency=true`` adds ``pay_input_ranges[]`` — the only
        structured pay the board publishes (measured live: dropbox
        publishes ranges; stripe, lyft and block return an empty list).
        The parameter is **not** a filter: it does not change which jobs
        are returned, only what each one carries.

        The parameter is added only to the **content** fetch. The light
        list is the delta refresh's payload (WS-23, Phase 4) and it is
        fetched for every board on every refresh, so it stays as small as
        possible; the pay structure is read from the per-job content
        fetch that a changed listing triggers anyway.

        The light list carries ``updated_at`` for every job, which is what
        makes a refresh cost O(changed jobs) instead of O(all jobs).
        """
        if content:
            return f"{GREENHOUSE_BASE_URL}/{token}/jobs?content=true&pay_transparency=true"
        return f"{GREENHOUSE_BASE_URL}/{token}/jobs"

    def _job_url(self, token: str, job_id: str) -> str:
        # WS-15: the job id is board-supplied, and it is interpolated into
        # a URL path. A board that returned ``id = "../../v1/boards/other"``
        # would send the request to a different path on the same host, and
        # an id carrying a ``?`` would inject a query. The id is therefore
        # checked against the same shape as the board token before a URL is
        # built: a path segment and nothing else.
        if not _is_valid_job_id(job_id):
            raise ValueError(f"Refusing a Greenhouse URL for a malformed job id: {job_id!r}")
        # WS-23: the pay structure is only published when the parameter is
        # asked for, and the per-job detail fetch is where it is read.
        return f"{GREENHOUSE_BASE_URL}/{token}/jobs/{job_id}?content=true&pay_transparency=true"

    def _normalize(self, payload: dict[str, Any], token: str) -> JobListing | None:
        job_id = payload.get("id")
        title = (payload.get("title") or "").strip()
        if job_id is None or not title:
            # Without an id the listing cannot be deduplicated or persisted;
            # without a title it is not a usable listing. Skip, never fabricate.
            return None
        description = html_to_text(payload.get("content"))
        location = payload.get("location")
        required_skills, preferred_skills = split_required_preferred(description)
        # Real payloads carry a flat ``company_name`` string; some older
        # board shapes expose a ``company`` object instead. Accept both,
        # falling back to the board token as a last resort.
        company_name = (payload.get("company_name") or "").strip()
        if not company_name:
            company = payload.get("company")
            if isinstance(company, dict):
                company_name = (company.get("name") or "").strip()
        if not company_name:
            company_name = token.replace("-", " ").replace("_", " ").title()

        metadata = payload.get("metadata")
        salary, currency = salary_from_greenhouse_pay_ranges(payload.get("pay_input_ranges"))
        board_map = GREENHOUSE_BOARD_METADATA.get(token, BoardMetadataMap())
        department = metadata_value(
            metadata, (board_map.department_key,) if board_map.department_key else ()
        )

        extra_metadata: dict[str, Any] = {}
        if department:
            extra_metadata["department"] = department
        # The board's own ``updated_at`` is stored so the delta refresh can
        # tell a changed listing from an unchanged one (WS-23, Phase 4).
        updated_at = (payload.get("updated_at") or "").strip()
        if updated_at:
            extra_metadata["updated_at"] = updated_at
        first_published = (payload.get("first_published") or "").strip()
        if first_published:
            extra_metadata["first_published"] = first_published

        return JobListing(
            id=f"greenhouse:{token}:{job_id}",
            source=self.name,
            source_job_id=str(job_id),
            title=title,
            company=company_name,
            description=description or None,
            location=(location.get("name") or "").strip() if isinstance(location, dict) else None,
            application_url=(payload.get("absolute_url") or "").strip() or None,
            posted_at=updated_at or None,
            # WS-23: the fields that were 0% populated across the corpus.
            remote_policy=remote_policy_from_metadata(metadata, token),
            employment_type=_employment_type_from_metadata(metadata, token),
            salary=salary,
            currency=currency,
            seniority=classify_seniority(title),
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            metadata=extra_metadata,
        )

    async def search(self, query: str, location: str | None = None) -> list[JobListing]:
        """Fetch all configured boards and client-side filter by query tokens."""
        tokens = _query_tokens(query)
        if self._client is not None:
            return await self._search_with(self._client, tokens)
        async with create_client() as client:
            return await self._search_with(client, tokens)

    async def _search_with(self, client: httpx.AsyncClient, tokens: list[str]) -> list[JobListing]:
        if not tokens:
            # No filter to apply: a light list would still force fetching
            # content for every job, so go single-pass (the refresh path).
            return await self._search_single_pass(client, tokens)
        return await self._search_two_pass(client, tokens)

    async def fetch_changed(
        self,
        known_updates: dict[str, str],
        *,
        client: httpx.AsyncClient | None = None,
    ) -> list[JobListing]:
        """The listings whose content changed since the last refresh.

        WS-23, Phase 4. This is the **delta refresh**, and it is what
        removes the oversized-board cliff.

        The problem it solves: the refresh fetched every board with
        ``?content=true`` in one request. A board whose response exceeded
        the size cap raised ``SourceError`` and the **whole board**
        disappeared — three live boards (9.83, 9.58 and 13.58 MiB) were
        silently dropped by the 8 MiB cap, taking 1,696 listings with
        them.

        The fix is that the **light** list carries ``updated_at`` for every
        job and is an order of magnitude smaller (measured live: 91 KB to
        792 KB for every board in the registry). So the refresh:

        1. fetches the light list for each board;
        2. compares each job's ``updated_at`` against the value stored
           for it last time;
        3. fetches the per-job content **only** for the jobs whose
           ``updated_at`` changed.

        The refresh therefore costs O(changed jobs) requests, not
        O(all jobs) — which is what actually dissolves the one-second
        pacing problem, more effectively than any title filter — and the
        light list is never anywhere near the response cap.

        It is also more **correct** than filtering the light list by
        title: a title filter can drop a listing whose description changed
        but whose title did not, and on the refresh path (an empty query)
        it has nothing to filter on at all.

        Args:
            known_updates: The ``updated_at`` value stored for each job
                id, keyed by the canonical ``"greenhouse:{token}:{id}"``.
                A job absent from the map is treated as new and fetched.
            client: An optional client (the tests supply a mock).

        Returns:
            The listings whose content changed, plus the listings that are
            new. A board that fails yields no listings and no exception —
            one board must not sink the refresh.
        """
        if client is not None:
            return await self._fetch_changed_with(client, known_updates)
        async with create_client() as owned:
            return await self._fetch_changed_with(owned, known_updates)

    async def _fetch_changed_with(
        self, client: httpx.AsyncClient, known_updates: dict[str, str]
    ) -> list[JobListing]:
        changed: list[JobListing] = []
        for token in self._resolve_boards():
            if not _is_valid_board_token(token):
                logger.warning("Skipping invalid Greenhouse board token %r", token)
                continue
            try:
                response = await guarded_get(client, self._board_url(token, content=False))
                payload = response.json()
            except (SourceError, ValueError) as exc:
                # One bad board must not sink the refresh. Its listings are
                # simply not updated this pass — and the WS-23 eviction
                # excludes a failing source, so its coverage survives.
                logger.warning("Greenhouse board %r unavailable: %s", token, exc)
                record_failure("greenhouse", token, exc)
                continue

            jobs = job_records(payload)
            stale: list[dict[str, Any]] = []
            for job in jobs:
                job_id = job.get("id")
                if job_id is None:
                    continue
                canonical = f"greenhouse:{token}:{job_id}"
                board_updated = (job.get("updated_at") or "").strip()
                previous = known_updates.get(canonical)
                if previous is None or board_updated != previous:
                    stale.append(job)

            logger.info(
                "Greenhouse board %r: %d jobs -> %d changed -> content fetch",
                token,
                len(jobs),
                len(stale),
            )
            record_success("greenhouse", token, len(jobs))
            for job in stale:
                job_id = job.get("id")
                if job_id is None:
                    continue
                source_job_id = str(job_id)
                try:
                    detail = await guarded_get(client, self._job_url(token, source_job_id))
                    listing = self._normalize(detail.json(), token)
                except (SourceError, ValueError) as exc:
                    # A survivor whose content fetch fails degrades alone.
                    logger.warning(
                        "Greenhouse content fetch failed for %s:%s: %s", token, source_job_id, exc
                    )
                    continue
                if listing is not None:
                    changed.append(listing)
        return changed

    async def _search_single_pass(
        self, client: httpx.AsyncClient, tokens: list[str]
    ) -> list[JobListing]:
        """One full-content fetch per board, then the title+description filter."""
        listings: list[JobListing] = []
        for token in self._resolve_boards():
            if not _is_valid_board_token(token):
                logger.warning("Skipping invalid Greenhouse board token %r", token)
                continue
            try:
                response = await guarded_get(client, self._board_url(token))
                payload = response.json()
            except (SourceError, ValueError) as exc:
                # One bad board must not sink the search; registry also
                # degrades per source, this degrades per board.
                logger.warning("Greenhouse board %r unavailable: %s", token, exc)
                continue
            for job in job_records(payload):
                listing = self._normalize(job, token)
                if listing is not None and _matches_query(listing, tokens):
                    listings.append(listing)
        return listings

    async def _search_two_pass(
        self, client: httpx.AsyncClient, tokens: list[str]
    ) -> list[JobListing]:
        """Light list first, full content only for title-filter survivors (FU-3).

        Pass 1 fetches the no-content listing per board (~11x lighter) and
        keeps jobs whose *title* matches any query token. Pass 2 fetches
        ``?content=true`` for the survivors only and re-applies the full
        title+description filter. Trade-off, documented in 04 doc FU-3: the
        light list carries no descriptions, so a job whose description matches
        but whose title does not is never fetched (narrowed recall vs
        single-pass); empty-token runs bypass this path entirely.
        """
        listings: list[JobListing] = []
        for token in self._resolve_boards():
            if not _is_valid_board_token(token):
                logger.warning("Skipping invalid Greenhouse board token %r", token)
                continue
            try:
                response = await guarded_get(client, self._board_url(token, content=False))
                payload = response.json()
            except (SourceError, ValueError) as exc:
                logger.warning("Greenhouse board %r unavailable: %s", token, exc)
                continue
            jobs = job_records(payload)
            survivors = [
                job
                for job in jobs
                if any(tok in (job.get("title") or "").lower() for tok in tokens)
            ]
            logger.info(
                "Greenhouse board %r: %d jobs -> %d title survivors -> content fetch",
                token,
                len(jobs),
                len(survivors),
            )
            for job in survivors:
                source_job_id = str(job.get("id") or "")
                if not source_job_id:
                    continue
                try:
                    detail = await guarded_get(client, self._job_url(token, source_job_id))
                    listing = self._normalize(detail.json(), token)
                except (SourceError, ValueError) as exc:
                    # A survivor whose content fetch fails degrades alone.
                    logger.warning(
                        "Greenhouse content fetch failed for %s:%s: %s", token, source_job_id, exc
                    )
                    continue
                if listing is not None and _matches_query(listing, tokens):
                    listings.append(listing)
        return listings

    async def get_job(self, job_id: str) -> JobListing | None:
        """Fetch one job by canonical id ``greenhouse:{token}:{job_id}``."""
        parts = job_id.split(":")
        if len(parts) != 3 or parts[0] != self.name:
            return None
        token, source_job_id = parts[1], parts[2]
        if not _is_valid_board_token(token) or not source_job_id:
            return None
        if self._client is not None:
            return await self._get_job_with(self._client, token, source_job_id)
        async with create_client() as client:
            return await self._get_job_with(client, token, source_job_id)

    async def _get_job_with(
        self, client: httpx.AsyncClient, token: str, source_job_id: str
    ) -> JobListing | None:
        try:
            response = await guarded_get(client, self._job_url(token, source_job_id))
        except SourceError as exc:
            logger.warning(
                "Greenhouse job fetch failed for greenhouse:%s:%s: %s", token, source_job_id, exc
            )
            return None
        payload = response.json()
        return self._normalize(payload, token)
