# WS-02 · Job Discovery (Greenhouse, Lever, Remotive)

Status: **Done** (2026-10-11) · Milestone: **M1** · Depends on: [01](01-data-foundation.md) (done) · Blocks: [03](03-matching-engine.md), [04](04-pipeline-and-api.md), [09](09-evaluation.md)

> Implemented as specced, with two evidence-based deviations: (1) real payloads
> carry Greenhouse `company_name` (flat string, no `company` object) and
> Remotive `publication_date` in naive ISO (UTC) — not RFC 2822 — so the
> normalizer handles both shapes (`src/jobs/normalize.py`); (2) canonical ids
> are `greenhouse:{token}:{id}` and `lever:{company}:{id}` because Lever
> posting ids are only unique per company. Fixtures in
> `tests/fixtures/sources/` were recorded from the live APIs on 2026-10-11
> via `scripts/record_source_fixtures.py`; all adapter tests replay them
> through `httpx.MockTransport` (no live network in the suite).

## Goal

Replace the placeholder job-source layer with three real, public-API adapters — **no scraping,
no auth walls, no ToS-gray areas** — plus a search planner, a shared guarded HTTP client, and
persistence of normalized listings into `JobDB`. This delivers plan §15 (adapter abstraction)
and the retrieval half of plan Phase 3–4.

## Current state

- `src/jobs/contracts.py` — `JobSource` protocol (`async search`, `async get_job`) and the canonical `JobListing` model: **keep both unchanged**.
- `src/jobs/linkedin_adapter.py` — placeholder returning `[]`. Stays in the tree but is **not registered** (AGENTS.md forbids modifying uncommitted modules without instruction; it is simply bypassed).
- `src/jobs/deduplicate.py` — real, tested; becomes the single dedup entry point for `search_all`.
- `src/db/jobs.py` — `JobDB` model exists; nothing writes to it in a live path. `id` is a free string — we standardize on `"{source}:{source_job_id}"` so re-searches upsert instead of duplicating.
- No HTTP client layer, no search planner, no source registry.

## Source APIs (all public, verified shapes)

| Source | Endpoint | Auth | Notes |
|---|---|---|---|
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true` | none | `jobs[]`: `id`, `title`, `content` (HTML), `location.name`, `absolute_url`, `updated_at`, `metadata[]` (key/value pairs, e.g. employment type). Detail: `.../jobs/{id}?questions=true` |
| Lever | `GET https://api.lever.co/v0/postings/{company}?mode=json` | none | `[]` of: `id`, `text` (title), `descriptionPlain`, `hostedUrl`, `applyUrl`, `categories.{location,team,commitment}`, `createdAt` (ms epoch), `lists[]` (structured sections) |
| Remotive | `GET https://remotive.com/api/remote-jobs?search={q}` | none | `jobs[]`: `id`, `title`, `company_name`, `candidate_required_location`, `job_type`, `salary`, `publication_date`, `description` (HTML), `tags`, `url` |

Boards/companies searched are configured, not discovered: `settings.greenhouse_boards` (board tokens) and `settings.lever_companies` (company slugs). The user curates which boards to watch — this is a personal agent, not a crawler.

## Concrete tasks

### 1. Explicit `httpx` dependency + guarded HTTP client — `src/jobs/http_client.py`

```python
def create_client() -> httpx.AsyncClient: ...
async def guarded_get(client, url) -> httpx.Response: ...
```

- **SSRF guard (SEC-11)** before every request: resolve hostname via `socket.getaddrinfo`; reject loopback, private (RFC 1918), link-local (169.254.0.0/16 incl. cloud metadata 169.254.169.254), and non-`http(s)` schemes. Unit-tested with a spoof matrix.
- Timeouts from `settings.job_source_timeout`; **2 retries** on `httpx.TransportError` / 429 / 5xx with exponential backoff + jitter (hand-rolled loop, no tenacity); 4xx → `SourceError` immediately.
- Polite `User-Agent` identifying the agent; per-host min interval `settings.job_source_min_interval` enforced with an `asyncio` lock map (rate limiting, plan §28).
- The adapter layer **never** fetches a URL that did not come from its own host allowlist constants (Greenhouse calls only ever hit `boards-api.greenhouse.io`, etc.).

### 2. Shared skill extraction — `src/jobs/skills.py`

- `SKILL_LEXICON`: curated set (~150 entries: languages, frameworks, clouds, DBs, practices — "Python", "FastAPI", "PostgreSQL", "Kubernetes", "RAG", "LangGraph", …), each with regex-safe aliases ("JS"→"JavaScript").
- `extract_skills(text) -> list[str]`: word-boundary, case-insensitive scan over the lexicon; returns lexicon-canonical names. Deterministic, no LLM. Used by all three adapters to populate `required_skills`/`preferred_skills` from description text (heuristic: first-mention-early / "requirements" section → required; "nice to have"/"preferred" section → preferred).

### 3. Adapters (job-source side; do not confuse with `src/applications/*` submission adapters)

Each implements `JobSource` and follows the same skeleton: fetch → normalize → return.

- `src/jobs/greenhouse_adapter.py` — `GreenhouseJobAdapter` (`name = "greenhouse"`)
  - `search(query, location)`: for each `settings.greenhouse_boards` token, fetch board JSON, build `JobListing`:
    `id=f"greenhouse:{token}:{job_id}"`, `source="greenhouse"`, `source_job_id=str(job_id)`, `description=html_to_text(content)` (regex-free tag stripper: `html.unescape` + `re.sub(r"<[^>]+>", " ")` + whitespace collapse), `location=location.name`, `application_url=absolute_url`, `posted_at=updated_at`, `employment_type` from metadata `employmentType` key when present, skills via `extract_skills`.
    Client-side filter by query tokens against title+description (the API has no query param).
  - `get_job(job_id)`: `GET .../jobs/{id}?content=true` by parsed `source_job_id`.
- `src/jobs/lever_adapter.py` — `LeverJobAdapter` (`name = "lever"`)
  - Map: `text→title`, `descriptionPlain→description`, `categories.location→location`, `categories.commitment→employment_type`, `applyUrl→application_url`, `hostedUrl→company_url`, `createdAt→posted_at` (ms→ISO 8601 UTC), skills via `extract_skills(descriptionPlain)`.
- `src/jobs/remotive_adapter.py` — `RemotiveJobAdapter` (`name = "remotive"`)
  - Map: `title→title`, `company_name→company`, `candidate_required_location→location`, `job_type→employment_type` (normalize "full_time"→"full-time"), `salary→salary`, `publication_date→posted_at`, `url→application_url`, `tags→required_skills` (verbatim) + `extract_skills(description)`.
  - `remote_policy="remote"` always (source property).

### 4. Search planner — `src/jobs/search_planner.py`

`plan_queries(profile: CandidateProfile) -> list[SourceQuery]`:
- Derive 1–3 queries per source: personal_information.title tokens + top skills (e.g. `"AI Engineer"`, `"python fastapi"`).
- Remotive benefits from a single free-text query; Greenhouse/Lever get board-wide fetches with client-side filtering. Keep it a pure function — a deterministic planner per plan §22.2 (no LLM in v1).

### 5. Registry + orchestration — `src/jobs/registry.py`

```python
SOURCES: dict[str, JobSource] = {"greenhouse": ..., "lever": ..., "remotive": ...}
async def search_all(queries, sources=None) -> list[JobListing]:
    # gather with asyncio.gather(return_exceptions=True); a failing source
    # logs a warning and is skipped (plan §35: "job source unavailable → try another")
    # → deduplicate() → save_jobs() → return unique listings
```

- `save_jobs(listings)` in `src/db/jobs.py`: upsert by `id` (`"{source}:{source_job_id}"`) using `merge()` semantics; returns count persisted.

### 6. Fixture recording helper — `scripts/record_source_fixtures.py` (dev-time only)

Fetches each source once and writes pretty JSON under `tests/fixtures/sources/{greenhouse,lever,remotive}.json` for the MockTransport tests. Never runs in CI.

## Acceptance criteria

- [ ] `search_all` returns normalized, deduplicated listings from all three configured sources; every listing passes `JobListing` validation with non-empty `id/source/title/company`.
- [ ] Re-running a search upserts (row count stable in `jobs` table, no duplicates).
- [ ] One source being down (simulated) degrades gracefully: warning logged, others' results returned.
- [ ] SSRF guard rejects `localhost`, `127.0.0.1`, `169.254.169.254`, `10.x`, `192.168.x`, and `file://` targets — unit tested.
- [ ] No test makes a live network call.

## Tests

- `tests/test_jobs.py` (extend) — per-adapter normalization tests driving `httpx.MockTransport` with the recorded fixtures: field mapping, HTML→text, epoch→ISO, skills extraction, empty/short payloads.
- `tests/test_http_client.py` — SSRF spoof matrix, retry-on-429/5xx then success, timeout → `SourceError`, per-host rate limit honors interval.
- `tests/test_skills.py` — lexicon extraction: canonicalization, aliases, word boundaries ("Java" must not match "JavaScript").
- `tests/test_search_all.py` — dedup across sources + persistence upsert + partial-failure degradation (one MockTransport raising).

## New dependencies

- `httpx` (explicit pin in `pyproject.toml` — already transitively present via Starlette).
