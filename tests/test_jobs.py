"""Tests for Phase 3 job source abstraction.

The placeholder LinkedIn tests predate WS-02 and stay. Everything below the
marker exercises the three real WS-02 adapters (Greenhouse, Lever, Remotive)
against ``httpx.MockTransport`` replaying the recorded live-API fixtures in
``tests/fixtures/sources/`` — real response shapes, zero live network.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from src.jobs.ashby_adapter import AshbyJobAdapter
from src.jobs.contracts import JobListing
from src.jobs.greenhouse_adapter import GreenhouseJobAdapter
from src.jobs.http_client import SourceError
from src.jobs.lever_adapter import LeverJobAdapter
from src.jobs.linkedin_adapter import LinkedInAdapter
from src.jobs.remotive_adapter import RemotiveJobAdapter

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sources"


def _load_fixture(name: str) -> dict | list:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _mock_client(
    greenhouse: dict | None = None,
    lever: list | None = None,
    remotive: dict | None = None,
    greenhouse_single: dict | None = None,
    lever_single: dict | None = None,
    status_by_host: dict[str, int] | None = None,
    greenhouse_survivor_status: int | None = None,
) -> httpx.AsyncClient:
    """Build a MockTransport client serving the given provider payloads.

    ``status_by_host`` maps a hostname fragment to an HTTP status to simulate
    a source being down (e.g. {"boards-api.greenhouse.io": 500}).

    Greenhouse endpoints are simulated realistically for FU-3: a board
    listing request *with* ``content=true`` serves the recorded full payload,
    one *without* it serves the light variant (same jobs minus ``content``),
    and a per-job fetch serves that job's full payload from the fixture.
    ``greenhouse_survivor_status`` fails every per-job content fetch.
    """
    status_by_host = status_by_host or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        path = url.split("?")[0].rstrip("/")
        for fragment, status in status_by_host.items():
            if fragment in url:
                return httpx.Response(status)
        if path.endswith("/jobs"):  # greenhouse board listing
            payload = greenhouse or {"jobs": []}
            if "content=true" not in url:
                payload = {
                    "jobs": [
                        {k: v for k, v in job.items() if k != "content"}
                        for job in payload.get("jobs", [])
                    ]
                }
            return httpx.Response(200, json=payload)
        if "/v1/boards/" in path:  # greenhouse single job (content fetch)
            if greenhouse_survivor_status is not None:
                return httpx.Response(greenhouse_survivor_status)
            source_job_id = path.rsplit("/", 1)[-1]
            for job in (greenhouse or {}).get("jobs", []):
                if str(job.get("id")) == source_job_id:
                    return httpx.Response(200, json=job)
            return httpx.Response(200, json=greenhouse_single or {})
        if path.count("/") == 5 and "/v0/postings/" in path:  # lever company list
            return httpx.Response(200, json=lever or [])
        if "/v0/postings/" in path:  # lever single posting
            return httpx.Response(200, json=lever_single or {})
        if "remotive.com" in path:
            return httpx.Response(200, json=remotive or {"jobs": []})
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


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


# ------------------------------------------------------------------ WS-02 --
# ---------------------------------------------------------------- greenhouse


@pytest.fixture()
def greenhouse_payload() -> dict:
    return _load_fixture("greenhouse.json")


@pytest.mark.asyncio
async def test_greenhouse_normalizes_real_fixture(greenhouse_payload):
    async with _mock_client(greenhouse=greenhouse_payload) as client:
        adapter = GreenhouseJobAdapter(client=client, boards=["stripe"])
        listings = await adapter.search("")

    assert listings, "fixture must yield listings"
    for listing in listings:
        # Acceptance: every listing passes validation with id/source/title/company.
        assert listing.id.startswith("greenhouse:")
        assert listing.source == "greenhouse"
        assert listing.source_job_id
        assert listing.title.strip()
        assert listing.company.strip()


@pytest.mark.asyncio
async def test_greenhouse_field_mapping(greenhouse_payload):
    raw = greenhouse_payload["jobs"][0]
    async with _mock_client(greenhouse=greenhouse_payload) as client:
        adapter = GreenhouseJobAdapter(client=client, boards=["stripe"])
        listings = await adapter.search("")

    listing = listings[0]
    assert listing.id == f"greenhouse:stripe:{raw['id']}"
    assert listing.source_job_id == str(raw["id"])
    assert listing.title == raw["title"]
    assert listing.company == raw["company_name"]
    assert listing.location == raw["location"]["name"]
    assert listing.application_url == raw["absolute_url"]
    assert listing.posted_at == raw["updated_at"]
    # HTML content became plain text: no tags survive.
    assert "<" not in (listing.description or "")
    assert "&amp;" not in (listing.description or "")


@pytest.mark.asyncio
async def test_greenhouse_employment_type_from_metadata():
    payload = {
        "jobs": [
            {
                "id": 77,
                "title": "Backend Engineer",
                "content": "<p>Python and Docker.</p>",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/77",
                "location": {"name": "Berlin"},
                "updated_at": "2026-10-01T10:00:00-04:00",
                "metadata": [{"name": "Employment Type", "value": "Full-Time"}],
            }
        ]
    }
    async with _mock_client(greenhouse=payload) as client:
        listings = await GreenhouseJobAdapter(client=client, boards=["acme"]).search("")

    assert listings[0].employment_type == "Full-Time"


@pytest.mark.asyncio
async def test_greenhouse_skills_extracted_from_content():
    payload = {
        "jobs": [
            {
                "id": 5,
                "title": "Platform Engineer",
                "content": "<p>Requirements: Python, Kubernetes, Terraform.</p>",
                "location": {"name": "Remote"},
                "updated_at": "2026-10-01T10:00:00-04:00",
                "metadata": None,
            }
        ]
    }
    async with _mock_client(greenhouse=payload) as client:
        listings = await GreenhouseJobAdapter(client=client, boards=["acme"]).search("")

    listing = listings[0]
    assert listing.required_skills == ["Python", "Kubernetes", "Terraform"]
    assert listing.employment_type is None  # metadata null -> nothing invented


@pytest.mark.asyncio
async def test_greenhouse_client_side_query_filter(greenhouse_payload):
    async with _mock_client(greenhouse=greenhouse_payload) as client:
        adapter = GreenhouseJobAdapter(client=client, boards=["stripe"])
        all_listings = await adapter.search("")
        # "engineer" matches a title in the recorded stripe board, so the
        # two-pass path returns its survivors (see FU-3 tests below).
        filtered = await adapter.search("engineer")

    assert len(all_listings) > 0
    assert 0 < len(filtered) <= len(all_listings)
    # EVERY returned listing must contain at least one query token.
    for listing in filtered:
        haystack = f"{listing.title} {listing.description or ''}".lower()
        assert "engineer" in haystack


@pytest.mark.asyncio
async def test_greenhouse_two_pass_recall_narrowing_is_documented_behavior(
    greenhouse_payload,
):
    """On the recorded stripe board, 'python' appears only in descriptions
    (4 single-pass matches, 0 title matches). Two-pass cannot see those —
    the documented recall narrowing — while single-pass does."""
    async with _mock_client(greenhouse=greenhouse_payload) as client:
        adapter = GreenhouseJobAdapter(client=client, boards=["stripe"])
        two_pass = await adapter.search("python")
    async with _mock_client(greenhouse=greenhouse_payload) as client:
        adapter = GreenhouseJobAdapter(client=client, boards=["stripe"])
        single_pass = await adapter.search("")  # full fetch + full filter

    description_only = [
        listing
        for listing in single_pass
        if "python" not in listing.title.lower() and "python" in (listing.description or "").lower()
    ]
    assert description_only, "fixture must contain description-only matches"
    assert two_pass == []


@pytest.mark.asyncio
async def test_greenhouse_skips_malformed_jobs():
    payload = {
        "jobs": [
            {"title": "no id here"},
            {"id": 2, "title": ""},  # empty title
            {"id": 3, "title": "Valid Role", "content": "<p>Go is fine</p>"},
        ]
    }
    async with _mock_client(greenhouse=payload) as client:
        listings = await GreenhouseJobAdapter(client=client, boards=["acme"]).search("")

    assert [listing.source_job_id for listing in listings] == ["3"]


@pytest.mark.asyncio
async def test_greenhouse_empty_board_returns_empty_list():
    async with _mock_client(greenhouse={"jobs": []}) as client:
        listings = await GreenhouseJobAdapter(client=client, boards=["acme"]).search("python")
    assert listings == []


# ------------------------------------------------ FU-3 two-pass board fetch


@pytest.mark.asyncio
async def test_greenhouse_two_pass_fetches_light_list_then_survivor_content(
    greenhouse_payload,
):
    """Empty query -> single full-content fetch; token query -> light list
    first, per-survivor content fetches, never a board-level content fetch."""
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        path = url.split("?")[0].rstrip("/")
        requests.append(url)
        if path.endswith("/jobs"):  # board listing (light when no content=true)
            payload = greenhouse_payload
            if "content=true" not in url:
                payload = {
                    "jobs": [
                        {k: v for k, v in job.items() if k != "content"}
                        for job in payload.get("jobs", [])
                    ]
                }
            return httpx.Response(200, json=payload)
        if "/v1/boards/" in path:  # per-job content fetch
            source_job_id = path.rsplit("/", 1)[-1]
            for job in greenhouse_payload.get("jobs", []):
                if str(job.get("id")) == source_job_id:
                    return httpx.Response(200, json=job)
            return httpx.Response(404)
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    ) as client:
        adapter = GreenhouseJobAdapter(client=client, boards=["stripe"])

        await adapter.search("")  # single-pass path
        single_pass_requests = list(requests)
        requests.clear()

        two_pass_listings = await adapter.search("engineer")  # two-pass path
    two_pass_requests = requests

    # Single-pass: exactly one board request, with content=true.
    assert len(single_pass_requests) == 1
    assert "content=true" in single_pass_requests[0]

    # Two-pass: pass 1 used the light list (no board-level content=true)...
    board_requests = [u for u in two_pass_requests if u.rstrip("/").endswith("/jobs")]
    assert len(board_requests) == 1
    assert "content=true" not in board_requests[0]
    # ...and every content=true request was a per-job survivor fetch
    # (.../boards/{token}/jobs/{id}), not a board listing re-fetch.
    content_calls = [u for u in two_pass_requests if "content=true" in u]
    assert content_calls, "survivors must be re-fetched with content"
    assert all("/jobs/" in u for u in content_calls)
    # Every returned listing passed the full title+description filter.
    for listing in two_pass_listings:
        haystack = f"{listing.title} {listing.description or ''}".lower()
        assert "engineer" in haystack


@pytest.mark.asyncio
async def test_greenhouse_two_pass_parity_with_single_pass_on_title_matches(
    greenhouse_payload,
):
    """FU-3 acceptance: identical listing sets for title-visible matches.

    The light list has no descriptions, so exact parity holds for every
    single-pass listing whose title matches a token (documented recall
    caveat: description-only matches are invisible in pass 1).
    """
    token = "engineer"
    async with _mock_client(greenhouse=greenhouse_payload) as client:
        adapter = GreenhouseJobAdapter(client=client, boards=["stripe"])
        two_pass = await adapter.search(token)
    async with _mock_client(greenhouse=greenhouse_payload) as client:
        adapter = GreenhouseJobAdapter(client=client, boards=["stripe"])
        all_single = await adapter.search("")  # single-pass full fetch

    title_visible = {listing.id for listing in all_single if token in listing.title.lower()}
    assert title_visible, "fixture must contain title-matching jobs"
    assert {listing.id for listing in two_pass} == title_visible


@pytest.mark.asyncio
async def test_greenhouse_two_pass_survivor_failure_degrades_that_job_only(
    greenhouse_payload,
):
    async with _mock_client(
        greenhouse=greenhouse_payload, greenhouse_survivor_status=500
    ) as client:
        listings = await GreenhouseJobAdapter(client=client, boards=["stripe"]).search("engineer")

    assert listings == []  # every survivor failed, but no exception raised


@pytest.mark.asyncio
async def test_greenhouse_two_pass_skips_light_jobs_without_id(greenhouse_payload):
    payload = {
        "jobs": [
            {"title": "Python Engineer"},  # no id in the light list
            {"id": 9, "title": "Python Engineer", "content": "<p>Python</p>"},
        ]
    }
    async with _mock_client(greenhouse=payload) as client:
        listings = await GreenhouseJobAdapter(client=client, boards=["acme"]).search("python")

    assert [listing.source_job_id for listing in listings] == ["9"]


@pytest.mark.asyncio
async def test_greenhouse_invalid_board_token_skipped_not_fetched():
    async with _mock_client(greenhouse={"jobs": [{"id": 1, "title": "X"}]}) as client:
        # Slash in the token would be a path traversal attempt.
        listings = await GreenhouseJobAdapter(client=client, boards=["../evil"]).search("")
    assert listings == []


@pytest.mark.asyncio
async def test_greenhouse_get_job_roundtrip(greenhouse_payload):
    raw = greenhouse_payload["jobs"][0]
    async with _mock_client(greenhouse=greenhouse_payload, greenhouse_single=raw) as client:
        adapter = GreenhouseJobAdapter(client=client, boards=["stripe"])
        listings = await adapter.search("")
        fetched = await adapter.get_job(listings[0].id)

    assert fetched is not None
    assert fetched.id == listings[0].id
    assert fetched.title == raw["title"]


@pytest.mark.asyncio
async def test_greenhouse_get_job_rejects_foreign_id_format():
    async with _mock_client(greenhouse={"jobs": []}) as client:
        adapter = GreenhouseJobAdapter(client=client, boards=["stripe"])
        assert await adapter.get_job("not-a-greenhouse-id") is None
        assert await adapter.get_job("remotive:123") is None


@pytest.mark.asyncio
async def test_greenhouse_board_down_degrades_to_empty(greenhouse_payload):
    """A 500 from one board is logged and skipped, not raised."""
    async with _mock_client(
        greenhouse=greenhouse_payload, status_by_host={"boards-api.greenhouse.io": 500}
    ) as client:
        listings = await GreenhouseJobAdapter(client=client, boards=["stripe"]).search("")
    assert listings == []


# --------------------------------------------------------------------- lever


@pytest.fixture()
def lever_payload() -> list:
    return _load_fixture("lever.json")


@pytest.mark.asyncio
async def test_lever_normalizes_real_fixture(lever_payload):
    async with _mock_client(lever=lever_payload) as client:
        listings = await LeverJobAdapter(client=client, companies=["leverdemo"]).search("")

    assert listings
    for listing in listings:
        assert listing.id.startswith("lever:leverdemo:")
        assert listing.source == "lever"
        assert listing.title.strip()
        assert listing.company == "Leverdemo"


@pytest.mark.asyncio
async def test_lever_field_mapping(lever_payload):
    raw = lever_payload[0]
    async with _mock_client(lever=lever_payload) as client:
        listings = await LeverJobAdapter(client=client, companies=["leverdemo"]).search("")

    listing = listings[0]
    assert listing.source_job_id == raw["id"]
    assert listing.title == raw["text"]
    assert listing.description == raw["descriptionPlain"].strip()
    assert listing.location == raw["categories"]["location"]
    assert listing.employment_type == raw["categories"]["commitment"]
    assert listing.application_url == raw["applyUrl"]
    assert listing.company_url == raw["hostedUrl"]
    # Millisecond epoch became an ISO 8601 UTC stamp.
    assert listing.posted_at is not None
    assert listing.posted_at.endswith("+00:00")
    assert listing.posted_at.startswith("2026-") or listing.posted_at.startswith("2025-")


@pytest.mark.asyncio
async def test_lever_ms_epoch_to_iso():
    payload = [
        {
            "id": "abc",
            "text": "Engineer",
            "descriptionPlain": "Python and Kubernetes.",
            "categories": {"location": "Remote", "commitment": "Full-time"},
            "createdAt": 1727940000000,
            "applyUrl": "https://jobs.lever.co/acme/abc/apply",
            "hostedUrl": "https://jobs.lever.co/acme/abc",
        }
    ]
    async with _mock_client(lever=payload) as client:
        listings = await LeverJobAdapter(client=client, companies=["acme"]).search("")

    listing = listings[0]
    assert listing.posted_at == "2024-10-03T07:20:00+00:00"
    assert listing.employment_type == "Full-time"
    assert "Python" in listing.required_skills


@pytest.mark.asyncio
async def test_lever_query_filter(lever_payload):
    async with _mock_client(lever=lever_payload) as client:
        adapter = LeverJobAdapter(client=client, companies=["leverdemo"])
        all_listings = await adapter.search("")
        filtered = await adapter.search("sales")

    assert 0 < len(filtered) <= len(all_listings)
    for listing in filtered:
        haystack = f"{listing.title} {listing.description or ''}".lower()
        assert "sales" in haystack


@pytest.mark.asyncio
async def test_lever_invalid_slug_skipped():
    async with _mock_client(lever=[{"id": "1", "text": "X"}]) as client:
        listings = await LeverJobAdapter(client=client, companies=["bad/slug"]).search("")
    assert listings == []


@pytest.mark.asyncio
async def test_lever_get_job_roundtrip(lever_payload):
    raw = lever_payload[0]
    async with _mock_client(lever=lever_payload, lever_single=raw) as client:
        adapter = LeverJobAdapter(client=client, companies=["leverdemo"])
        listings = await adapter.search("")
        fetched = await adapter.get_job(listings[0].id)

    assert fetched is not None
    assert fetched.source_job_id == raw["id"]
    assert fetched.title == raw["text"]


@pytest.mark.asyncio
async def test_lever_get_job_rejects_plain_id():
    async with _mock_client(lever=[]) as client:
        adapter = LeverJobAdapter(client=client, companies=["leverdemo"])
        assert await adapter.get_job("ad208490") is None  # missing company segment


# ------------------------------------------------------------------ remotive


@pytest.fixture()
def remotive_payload() -> dict:
    return _load_fixture("remotive.json")


@pytest.mark.asyncio
async def test_remotive_normalizes_real_fixture(remotive_payload):
    async with _mock_client(remotive=remotive_payload) as client:
        listings = await RemotiveJobAdapter(client=client).search("python")

    assert listings
    for listing in listings:
        assert listing.id.startswith("remotive:")
        assert listing.source == "remotive"
        assert listing.title.strip()
        assert listing.company.strip()
        assert listing.remote_policy == "remote"


@pytest.mark.asyncio
async def test_remotive_field_mapping(remotive_payload):
    raw = remotive_payload["jobs"][0]
    async with _mock_client(remotive=remotive_payload) as client:
        listings = await RemotiveJobAdapter(client=client).search("python")

    listing = listings[0]
    assert listing.source_job_id == str(raw["id"])
    assert listing.title == raw["title"]
    assert listing.company == raw["company_name"]
    assert listing.location == raw["candidate_required_location"]
    assert listing.salary == raw["salary"]
    assert listing.application_url == raw["url"]
    # Board tags kept verbatim, in order, at the front of required_skills.
    tags = [tag.strip() for tag in raw["tags"]]
    assert listing.required_skills[: len(tags)] == tags


@pytest.mark.asyncio
async def test_remotive_job_type_normalized():
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "Backend Engineer",
                "company_name": "RemoteCo",
                "candidate_required_location": "Worldwide",
                "job_type": "full_time",
                "salary": "USD 100k",
                "publication_date": "2026-10-08T21:47:32",
                "description": "<p>Python, LLMs, RAG</p>",
                "tags": ["python"],
                "url": "https://remotive.com/remote-jobs/1",
            }
        ]
    }
    async with _mock_client(remotive=payload) as client:
        listings = await RemotiveJobAdapter(client=client).search("backend")

    listing = listings[0]
    assert listing.employment_type == "full-time"  # underscore -> hyphen
    # Naive ISO publication date (Remotive publishes UTC) gains +00:00.
    assert listing.posted_at == "2026-10-08T21:47:32+00:00"
    # Tags verbatim first, then lexicon skills from the description.
    assert listing.required_skills[0] == "python"
    assert "LLM" in listing.required_skills
    assert "RAG" in listing.required_skills


@pytest.mark.asyncio
async def test_remotive_rfc2822_publication_date():
    payload = {
        "jobs": [
            {
                "id": 2,
                "title": "DevOps",
                "company_name": "RemoteCo",
                "job_type": "part_time",
                "publication_date": "Fri, 03 Oct 2026 09:15:22 GMT",
                "description": "<p>Terraform</p>",
                "tags": [],
            }
        ]
    }
    async with _mock_client(remotive=payload) as client:
        listings = await RemotiveJobAdapter(client=client).search("devops")
    assert listings[0].posted_at == "2026-10-03T09:15:22+00:00"


@pytest.mark.asyncio
async def test_remotive_skips_jobs_missing_company():
    payload = {
        "jobs": [
            {"id": 1, "title": "No Company", "company_name": ""},
            {"id": 2, "title": "Good", "company_name": "RemoteCo", "tags": []},
        ]
    }
    async with _mock_client(remotive=payload) as client:
        listings = await RemotiveJobAdapter(client=client).search("")
    assert [listing.source_job_id for listing in listings] == ["2"]


@pytest.mark.asyncio
async def test_remotive_source_failure_raises_source_error():
    async with _mock_client(status_by_host={"remotive.com": 500}) as client:
        with pytest.raises(SourceError):
            await RemotiveJobAdapter(client=client).search("python")


@pytest.mark.asyncio
async def test_remotive_get_job_found_in_board_scan():
    payload = {
        "jobs": [
            {"id": 2086540, "title": "Inside Sales", "company_name": "Credit Wellness", "tags": []},
            {"id": 2091045, "title": "Service Desk", "company_name": "Unio", "tags": []},
        ]
    }
    async with _mock_client(remotive=payload) as client:
        fetched = await RemotiveJobAdapter(client=client).get_job("remotive:2091045")

    assert fetched is not None
    assert fetched.title == "Service Desk"


@pytest.mark.asyncio
async def test_remotive_get_job_not_found_or_foreign():
    async with _mock_client(remotive={"jobs": []}) as client:
        adapter = RemotiveJobAdapter(client=client)
        assert await adapter.get_job("remotive:999999") is None
        assert await adapter.get_job("greenhouse:x:1") is None


# --------------------------------------------------------------------- ashby
# FU-2: recorded live fixture (api.ashbyhq.com/posting-api/job-board/notion).


@pytest.fixture()
def ashby_payload() -> dict:
    return _load_fixture("ashby.json")


def _ashby_mock_client(payload: dict, status: int | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/posting-api/job-board/" in str(request.url):
            return httpx.Response(status or 200, json=payload)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


@pytest.mark.asyncio
async def test_ashby_normalizes_real_fixture(ashby_payload):
    async with _ashby_mock_client(ashby_payload) as client:
        listings = await AshbyJobAdapter(client=client, orgs=["notion"]).search("")

    assert len(listings) == len(ashby_payload["jobs"])
    for listing in listings:
        assert listing.id.startswith("ashby:notion:")
        assert listing.source == "ashby"
        assert listing.company == "Notion"  # org slug title-cased
        assert listing.description  # descriptionPlain is populated live
        assert listing.employment_type in ("full-time", "contract", "intern")


@pytest.mark.asyncio
async def test_ashby_field_mapping(ashby_payload):
    raw = ashby_payload["jobs"][0]
    async with _ashby_mock_client(ashby_payload) as client:
        listings = await AshbyJobAdapter(client=client, orgs=["notion"]).search("engineer")

    listing = listings[0]
    assert listing.id == f"ashby:notion:{raw['id']}"
    assert listing.source_job_id == raw["id"]
    assert listing.title == raw["title"]
    assert listing.description == raw["descriptionPlain"].strip()  # verbatim content
    assert listing.location == raw["location"]
    assert listing.remote_policy == "remote"  # isRemote true
    assert listing.employment_type == "full-time"  # CamelCase normalized
    assert listing.posted_at == raw["publishedAt"]
    assert listing.application_url == raw["applyUrl"]
    assert listing.company_url == raw["jobUrl"]
    assert listing.metadata["department"] == raw["department"]


@pytest.mark.asyncio
async def test_ashby_workplace_type_fallback_when_not_remote():
    payload = {
        "jobs": [
            {
                "id": "abc",
                "title": "On-site Role",
                "isRemote": False,
                "workplaceType": "Hybrid",
                "employmentType": "Contract",
                "descriptionPlain": "Plan and review systems.",
            }
        ]
    }
    async with _ashby_mock_client(payload) as client:
        listing = (await AshbyJobAdapter(client=client, orgs=["x"]).search("role"))[0]

    assert listing.remote_policy == "hybrid"
    assert listing.employment_type == "contract"


@pytest.mark.asyncio
async def test_ashby_html_fallback_when_plain_missing():
    payload = {
        "jobs": [
            {
                "id": "abc",
                "title": "Backend",
                "descriptionPlain": "",
                "descriptionHtml": "<p>Python, LLMs, RAG</p>",
            }
        ]
    }
    async with _ashby_mock_client(payload) as client:
        listing = (await AshbyJobAdapter(client=client, orgs=["x"]).search("backend"))[0]

    assert listing.description == "Python, LLMs, RAG"
    assert "Python" in listing.required_skills


@pytest.mark.asyncio
async def test_ashby_skips_invalid_org_and_bad_board(ashby_payload):
    async with _ashby_mock_client(ashby_payload, status=500) as client:
        listings = await AshbyJobAdapter(client=client, orgs=["openai", "bad slug!"]).search("")
    assert listings == []  # both boards unavailable/invalid, no exception


@pytest.mark.asyncio
async def test_ashby_get_job_found_in_board_scan(ashby_payload):
    raw = ashby_payload["jobs"][1]
    async with _ashby_mock_client(ashby_payload) as client:
        fetched = await AshbyJobAdapter(client=client, orgs=["notion"]).get_job(
            f"ashby:notion:{raw['id']}"
        )

    assert fetched is not None
    assert fetched.title == raw["title"]


@pytest.mark.asyncio
async def test_ashby_get_job_not_found_or_foreign(ashby_payload):
    raw = ashby_payload["jobs"][0]
    async with _ashby_mock_client(ashby_payload) as client:
        adapter = AshbyJobAdapter(client=client, orgs=["notion"])
        assert await adapter.get_job(f"ashby:notion:does-not-exist") is None
        assert await adapter.get_job(f"remotive:{raw['id']}") is None
