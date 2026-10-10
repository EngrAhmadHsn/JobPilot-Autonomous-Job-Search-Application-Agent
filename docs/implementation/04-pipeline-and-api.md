# WS-04 · Pipeline Wiring + API Surface

Status: **Not started** · Milestone: **M1** · Depends on: [01](01-data-foundation.md), [02](02-job-discovery.md), [03](03-matching-engine.md) · Blocks: [05](05-tailoring-and-research.md), [09](09-evaluation.md)

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

- [ ] Over HTTP: upload a DOCX resume → `profile_id`; search → top-10 ranked matches with per-component explanations; job detail fetchable. This is the plan's First Milestone, demonstrated by the updated demo script.
- [ ] `src/graph/job_workflow.py` contains no placeholder nodes; grep for "Placeholder" in `src/graph/` matches only the application workflow comments.
- [ ] A failing job source degrades the report, not the request (HTTP 200 with `source_errors` populated).
- [ ] Profiles and matches survive a server restart (SQLite persistence).
- [ ] Oversized/wrong-type uploads rejected with 400 and a clear message.
- [ ] All prior tests remain green; new endpoints covered.

## Tests

- `tests/test_job_workflow.py` (rewrite `test_full_workflow.py`) — graph executes end-to-end with a fixture `JobSource` + `FakeEmbeddingFn`: ordering of nodes, dedup applied, top-N slice, source_errors tolerated.
- `tests/test_resumes_api.py` — upload happy path (docx fixture), rejection matrix (wrong ext, >5 MB, corrupt docx), profile persisted and fetchable.
- `tests/test_jobs_api.py` — search with dependency-overridden executor returning fixture matches; response schema; match rows persisted; `GET /api/jobs/{id}`.
- `tests/fixtures/fake_source.py` — deterministic in-memory `JobSource` used by both workflow and API tests.

## New dependencies

- `python-multipart` (FastAPI `UploadFile` requirement — explicitly declared, per the dependencies rule).
