# WS-04 · Pipeline Wiring + API Surface

Status: **Done (2026-10-11)** · Milestone: **M1** · Depends on: [01](01-data-foundation.md), [02](02-job-discovery.md), [03](03-matching-engine.md) · Blocks: [05](05-tailoring-and-research.md), [09](09-evaluation.md)

> **Completion notes (2026-10-11).** All tasks delivered; 297 tests green (from 262),
> ruff clean, **First Milestone verified live over HTTP**: real DOCX upload →
> `profile_id` → search hit Remotive live (54 found / 18 deduped / 18 persisted /
> top-10 with real `gemini-embedding-2` semantics, `degraded=false`) → job detail →
> match history; profile + match rows survived a server restart (SQLite, migrated
> via Alembic `b8e2c94d1f57`). Deviations worth knowing:
>
> 1. **`plan_queries(profile, sources=...)`** gained a `sources` parameter: the
>    original hardcoded `PLANNED_SOURCES` meant injected/fixture adapters never got
>    queries planned for them — tests and the demo inject their own sources.
> 2. **`registry.search_all_detailed()`** added next to `search_all` (behavior
>    unchanged): the pipeline needs *which* source failed in the report, and
>    `search_all` only logged it. Detailed mode also skips dedup/persist — the
>    pipeline owns those as explicit nodes.
> 3. **Match-node semantics**: the literal spec reading ("query the store with the
>    job's own text") returns the job's *self*-similarity. Implemented as: upsert the
>    run's jobs into Chroma, then one `query_similar(candidate_query_text(profile))`
>    maps every job id to its candidate-vs-listing similarity; any store failure
>    (construction/embedding/query) degrades the whole run per WS-03.
> 4. **Sync endpoints, `asyncio.run` in the search node**: the adapters are async;
>    the pipeline nodes are sync and bridge with `asyncio.run`, which requires a
>    thread without a running event loop — so `POST /api/jobs/search` is a sync
>    endpoint (FastAPI threadpool), consistent with the applications executor.
> 5. `python-multipart` added to dependencies (FastAPI `UploadFile` requirement).
> 6. Match rows carry no foreign keys by design (history may outlive profile/job
>    rows); `candidate_profiles` keeps personal-info columns + full profile JSON so
>    the schema survives `CandidateProfile` evolution without migrations.

## Goal

Wire the placeholder Phase-6 LangGraph job pipeline to the real modules and expose the
pipeline over REST. This achieves the plan's **First Milestone** (§42): *Resume →
CandidateProfile → Search Jobs → Normalize → Deduplicate → Hybrid Match → Top 10 →
Explanation*, end-to-end over HTTP.

## Current state

- `src/graph/job_workflow.py` — builds a `StateGraph` with search/normalize/deduplicate/match/rank nodes, but **every node is a log-and-return placeholder** (`src/graph/job_workflow.py:57-88`); it also reuses `ApplicationWorkflowState`, which has no fields for jobs/matches.
- `tests/fixtures/milestone_1_demo.py` — demonstrates the milestone with **three hardcoded mock jobs**.
- API surface: only `/`, `/health` (`src/api/routes/health.py`) and `POST /api/applications/submit` (`src/api/routes/applications.py`). No resume upload, no job search, no match endpoints.
- `src/resume/parser.py` / `profile.py` — real but reachable only from Python; not exposed via API; profiles are not persisted.

## Concrete tasks

### 1. Dedicated job-search state — `src/graph/job_state.py` (new)

```python
class JobSearchState(BaseModel):
    profile: CandidateProfile
    queries: list[SourceQuery] = []
    raw_jobs: list[JobListing] = []
    jobs: list[JobListing] = []
    matches: list[Pair] = []            # (JobListing, JobMatchResult) pairs
    top: list[Pair] = []
    source_errors: dict[str, str] = {}  # source -> error, tolerated per plan §35
```

LangGraph 1.x works with Pydantic state; do **not** reuse `ApplicationWorkflowState` (that state belongs to the submission workflow).

### 2. Rewrite `src/graph/job_workflow.py` — real nodes

- `search` → `plan_queries(profile)` + `registry.search_all(...)`; a source failure records into `source_errors` and continues.
- `normalize` → drop listings failing minimal completeness (`title`, `company`, `id`), count dropped.
- `deduplicate` → existing `src/jobs/deduplicate.py:deduplicate`.
- `persist` (new node) → `save_jobs(jobs)` upsert to `JobDB`.
- `match` → for each job: `sim = chroma.query_similar(job_text, 1)` + `calculate_match(job, profile, semantic_score=sim)`.
- `rank` → sort by `overall_score` desc, slice top-N (default 10).
- Compile with `MemorySaver()` (persistence upgrade is out of scope here; durable checkpointer noted in [11](11-docs-and-ops.md) as future work). Add explicit `END` edge after `rank` (current graph relies on implicit termination).

### 3. Executor — `src/graph/job_executor.py` (new)

```python
def run_job_search(profile: CandidateProfile, query: str | None,
                   location: str | None = None, top_n: int = 10) -> JobSearchReport
```

- Builds/invokes the graph (sync `.invoke()` — consistent with the existing application executor).
- Returns a `JobSearchReport` pydantic model: `{results: [{job, match}], source_errors, stats {found, deduped, persisted}}`.
- Embedding unavailability → degraded matching mode (WS-03) with `degraded` flag on the report, never a crash.

### 4. Profile persistence + upload API — `src/api/routes/resumes.py` (new)

- `POST /api/resumes` — multipart `UploadFile`:
  - validation (shared util lands fully in WS-06; minimal version here): extension whitelist `.docx/.txt/.md`, size cap 5 MB, `python-docx` open check for docx;
  - saves to `settings.resume_upload_dir` under a generated id, `parse_resume()` → `CandidateProfile`, `validate_candidate_profile()` → warnings;
  - persists `CandidateProfileDB` (new model + Alembic revision per WS-01 policy): id, personal info columns, full profile JSON, file path, `created_at`;
  - returns `{profile_id, warnings, profile}`.
- `GET /api/resumes/{id}` — stored profile JSON.
- **`python-multipart` added to dependencies** (FastAPI requirement for `UploadFile`).

### 5. Search + match API — `src/api/routes/jobs.py` (new)

- `POST /api/jobs/search` `{profile_id, query?, location?, top_n?}` → loads profile from DB, runs `run_job_search`, persists a `JobMatchDB` row per result (new model: `profile_id`, `job_id`, scores JSON, explanation, `created_at`), returns ranked results with explanations.
- `GET /api/jobs/{id}` → `JobListing` from DB.
- `GET /api/profiles/{id}/matches` → persisted matches (history).
- Router registration in `src/main.py`.

### 6. Milestone demo — update `tests/fixtures/milestone_1_demo.py`

Replace the hardcoded mock jobs with the real path: parse the fixture resume → `run_job_search` against a **fixture `JobSource`** (offline) so the demo stays deterministic; print the ranked table with explanations. A live variant (`--live`) uses the real registry.

### 7. Audit hooks (minimal, full system in WS-06)

Log-with-context (no PII beyond parsed counts) on upload, search start/complete — keeps SEC-13 moving without preempting 06.

## Acceptance criteria

- [x] Over HTTP: upload a DOCX resume → `profile_id`; search → top-10 ranked matches with per-component explanations; job detail fetchable. This is the plan's First Milestone, demonstrated by the updated demo script. **Verified live (2026-10-11): uvicorn + curl against real Remotive + real embeddings.**
- [x] `src/graph/job_workflow.py` contains no placeholder nodes; grep for "Placeholder" in `src/graph/` returns zero matches.
- [x] A failing job source degrades the report, not the request (HTTP 200 with `source_errors` populated) — `test_failing_source_recorded_not_fatal`, `test_search_source_errors_pass_through`.
- [x] Profiles and matches survive a server restart (SQLite persistence) — verified in the live smoke (restart → profile + 10 match rows fetchable).
- [x] Oversized/wrong-type uploads rejected with 400 and a clear message — rejection matrix in `tests/test_resumes_api.py`.
- [x] All prior tests remain green; new endpoints covered (297 passing; workflow, resumes API, jobs API, migrations, registry).

## Tests

- `tests/test_job_workflow.py` (rewrite `test_full_workflow.py`) — graph executes end-to-end with a fixture `JobSource` + `FakeEmbeddingFn`: ordering of nodes, dedup applied, top-N slice, source_errors tolerated.
- `tests/test_resumes_api.py` — upload happy path (docx fixture), rejection matrix (wrong ext, >5 MB, corrupt docx), profile persisted and fetchable.
- `tests/test_jobs_api.py` — search with dependency-overridden executor returning fixture matches; response schema; match rows persisted; `GET /api/jobs/{id}`.
- `tests/fixtures/fake_source.py` — deterministic in-memory `JobSource` used by both workflow and API tests.

## New dependencies

- `python-multipart` (FastAPI `UploadFile` requirement — explicitly declared, per the dependencies rule).

---

## Post-M1 follow-up plan (added 2026-10-11 — quota-driven pipeline strategy)

Context: the first full-scale live run over the user's configured boards (11 Greenhouse
tokens + `palantir` on Lever + Remotive) fetched **5,885 listings → 4,314 unique →
4,314 persisted, zero source errors**. It exposed (a) the embedding batch cap of 100
requests (fixed in `5d7f2bd`), and (b) the real free-tier embedding quota, confirmed
from the AI Studio dashboard: **RPM 5, TPM ~250K, RPD 20**. At ~1.5K tokens per job
document TPM is never binding; **RPD 20 × 100-text batches ≈ 2,000 embeddable texts
per day** is the binding constraint. Embedding a 4,314-job corpus is therefore a
multi-day background operation, not an interactive one — which drives the strategy
below. Observed side-effect worth fixing: in degraded mode (no semantics) listings
that state no skills score the neutral 70 and can outrank real partial matches
(live top-10 was all Stripe sales roles at an identical 81.2).

### FU-1 · Daily refresh decoupled from search (ADOPT — user proposal, refined)

User proposal: search for jobs once a day, embed and store them, and serve the rest
of the day's searches from stored data. **Accepted** — it is the only model that fits
RPD 20 — with one refinement: don't just batch the daily run, **fully decouple
refresh from search** so a search never waits on board fetching at all.

- `POST /api/jobs/refresh` (+ `scripts/refresh_jobs.py` CLI wrapper for Task
  Scheduler/cron — no in-process scheduler, no new dependencies): runs
  plan → search → normalize → deduplicate → persist, then embeds **only new or
  changed** listings (the content-hash cache makes this the daily delta, normally
  ≪ 2,000 texts) and upserts them into Chroma. Returns a summary report.
- `POST /api/jobs/search` becomes **store-only**: load listings from `JobDB`, match
  against Chroma, never fetch a board. Latency drops to seconds; embedding cost per
  search = 1 query request (the candidate text). `run_job_search` keeps its current
  shape for tests/demo via injected sources; the production executor path splits into
  `refresh_jobs()` and `search_stored_jobs()`.
- Initial corpus fill (in flight, `scripts/backfill_embeddings.py`): ~44 requests ≈
  2–3 days of quota. Refinement when re-running from scratch: order by deterministic
  pre-score (skill-overlap > 0 first) so day-1's 2,000 embedded texts are the
  plausible matches and ranking is useful immediately; the long tail follows.
- Acceptance: search performs zero board fetches and ≤1 embedding request; refresh
  is resumable across days (cache + upserts make every run idempotent); suite stays
  offline.

### FU-2 · Ashby adapter — rescue OpenAI + Notion (small, high value)

Both companies left Greenhouse; Ashby's key-less public posting API has them
(probed live: `openai` 815 jobs, `notion` 132; `doordash`/`shopify` are on neither
Greenhouse, Lever, nor Ashby — own career systems, out of reach without scraping,
which AGENTS.md forbids).

- `src/jobs/ashby_adapter.py` following the greenhouse pattern:
  `GET https://api.ashbyhq.com/posting-api/job-board/{org}`, `orgs=`/`client=` DI,
  token validation, normalize → `JobListing` (map Ashby's `title/location/
  descriptionHtml/department` — verify field mapping against a recorded payload),
  `ASHBY_ORGS` env + settings + `.env.example`, registry + planner registration.
- Tests replay recorded-JSON fixtures via MockTransport (offline suite unchanged).
- Acceptance: live run returns openai/notion listings; suite offline; recorded
  fixture committed.

### FU-3 · Two-pass board fetch ("filter early" bandwidth cut)

Greenhouse/Lever board endpoints have no server-side keyword filter, but they do
offer light listing modes. Two-pass: fetch the no-content list (titles/ids), apply
the client-side title-token filter, fetch `content=true` only for survivors, then
extract skills. Turns 11 full-content fetches per query into 11 light fetches + a
handful of content fetches.

- Trade-off: 2 requests per board instead of 1 — net bandwidth win whenever the
  title filter is selective (typical); keep single-pass for tiny boards.
- Politeness is unchanged: strictly sequential, 1 s/host spacing, retries.
- Acceptance: identical listing sets vs single-pass on recorded fixtures; payload
  log shows the reduction; no rate-limit regressions.

### FU-4 · Embedding quota budget in the embedding layer (overlaps WS-10)

- Promote the backfill's 429-and-wait loop into `GeminiEmbedding`: parse the
  `RetryInfo`/quota id, distinguish per-minute from per-day exhaustion, pace
  batches at ≤5 RPM, and on daily exhaustion stop cleanly (resume next day)
  instead of retry-spamming.
- Expose remaining-budget in logs; refresh (FU-1) plans the day's embedding spend.
- Hand-rolled (token bucket + counters) — no new dependencies, per repo rules.

### FU-5 · Ranking quality: degraded-mode neutral inflation (observed live)

In degraded mode, a listing with no stated skills scores the neutral 70 on the
skill component and, with the semantic weight redistributed, can outrank listings
with real (imperfect) skill matches. Candidates: cap the neutral contribution,
weight components by evidence availability, or require skill evidence for the top
slice. **Decide with data, not ad-hoc:** implement in WS-09's evaluation harness
(nDCG@k over a golden set) rather than hand-tuning now. Until then, semantics
(FU-1 backfill) is the mitigation.

### FU-6 · Streaming/incremental results per board (DEFERRED — user suggestion, critiqued)

Proposal: present each board's results to the user as soon as that board completes,
streaming further boards in as they arrive. **Not accepted now.** Reasons:
(1) the pipeline's promise is cross-source normalize→dedup→match→rank — per-board
partials are unranked, un-deduplicated, and (during quota-constrained periods)
degraded, i.e. a worse product for the same data; (2) plan §30 / AGENTS.md forbid
a frontend this iteration, so there is no consumer for streamed partials;
(3) FU-1 removes the motivation — once searches are store-only they return in
seconds, and the slow part (daily refresh) is a background job where progress
logging already gives visibility. **Revisit** when a UI/CLI consumer exists: the
natural shape is an SSE endpoint over the refresh run's per-board completion
events, not streaming search results.

### Note · 6,000-char description truncation is intentional (no action)

`Embedding input truncated from 6087 to 6000 chars` is the documented WS-03 guard:
the API silently truncates at 8,192 *tokens*, so text is pre-truncated to 6,000
*characters* (~1,500–2,000 tokens with headroom). The observed loss was 87 chars of
one description's tail. Raising the constant would change every cache key and force
a full re-embed (~2–3 days of free-tier quota) for negligible gain — accepted
behavior, do not change.
