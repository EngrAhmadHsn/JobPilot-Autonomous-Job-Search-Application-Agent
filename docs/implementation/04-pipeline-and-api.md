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
- `fastembed>=0.9.0` — **added, FU-7** (local embedding provider): thin in-process
  ONNX wrapper; onnxruntime + tokenizers already present via chromadb, so this adds
  only the wrapper plus model weights (~300 MiB int8, pattern-restricted download).

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

### FU-7 · Local embedding provider — fastembed + EmbeddingGemma-2 text-only int8 (ADOPT — user decision, researched 2026-10-11; spec written, implementation pending)

**Context.** The FU-4 live run confirmed the free-tier binding constraint:
RPD 20 × 100-text batches ≈ 2,000 embeddable texts/day — the 4,314-job corpus
is a multi-day backfill and the daily refresh spends the budget every run. A
local in-process embedder removes the quota entirely (embed happens when code
calls `embed_documents`, costs milliseconds of CPU, zero marginal cost, no
second process/service/container — same in-process pattern as the SQLite
cache). **User decisions (2026-10-11):** adopt the local provider as the
*default* once installed and validated (Gemini stays selectable for A/B and
fallback); target model **EmbeddingGemma-2 (text-only), int8 ONNX**; runtime
**fastembed 0.9.0 with custom registration**.

**Model choice — verified facts (researched 2026-10-11 against
ai.google.dev/gemma/docs/embeddinggemma/model_card_2, the HF API for
`onnx-community/embeddinggemma-2-ONNX`, and the fastembed v0.9.0 source):**

- `google/embeddinggemma-2`: 740M total, **270M text-only backbone**
  (vision 170M / audio 300M are separate, officially optional). MTEB(eng, v2)
  **mean 68.46** vs EmbeddingGemma-300M's 64.2. 768-dim native (MRL
  512/256/128). Ungated, Apache-2.0 tagged (base model carries Gemma terms).
- **int8 ONNX variant is `onnx/model_quantized.onnx`** (495 KB graph) +
  **`onnx/model_quantized.onnx_data` (~299 MiB)** — there is no
  `model_int8.onnx`. fp32 reference: `model.onnx` + `.onnx_data` (~1.01 GiB).
  fp16 variants exist but are **forbidden** by the model card (fp16 overflow
  → NaNs); never register them.
- The text graph outputs **both** `last_hidden_state` (token-level) and
  **`sentence_embedding`** — mean-pooled **and L2-normalized inside the
  graph** (per model card; verify at implementation, see open items). Dim 768.
- Prefix scheme is identical to the repo's existing constants (and fastembed
  does **not** apply prompts itself — verified in
  `builtin_sentence_embedding.py`): query
  `task: search result | query: {content}`, document
  `title: {title | 'none'} | text: {content}`. `MODEL_PREFIX_QUERY` /
  `MODEL_PREFIX_DOC` are reused verbatim.
- fastembed 0.9.0 does **not** ship embeddinggemma-2 (only the 300M builtin);
  custom registration is the sanctioned path (`TextEmbedding.add_custom_model`).
  The stale qdrant docs page omits even the 300M — trust the source registry.

**Rejected alternatives (recorded so this decision is auditable):**

- *fastembed built-in 300M* — zero custom code, but −4.26 MTEB mean, 2,048-
  token cap, and Gemma-licensed HF source. Remains the fallback if the gemma-2
  custom registration hits a blocker.
- *sentence-transformers / torch* — pulls ~2.5 GB of PyTorch for no quality
  gain over the ONNX graph.
- *electroglyph uint8-output build* — single-author graph surgery, zero third-
  party validation, benefit (smaller vectors) worthless at 4.3k-job cache scale.
- *LiteRT/TFLite* — transfers tokenization/pooling/normalization ownership to
  us; onnxruntime is already in the venv (chromadb), so LiteRT *adds* footprint.

**Spec 1 — dependency (`pyproject.toml`).** Add `"fastembed>=0.9.0"`
alphabetically between `chromadb` and `fastapi` (house `>=` floor style).
onnxruntime + tokenizers are already present via chromadb — fastembed adds the
wrapper plus weights only. Update the `## New dependencies` section below.

**Spec 2 — settings (`src/config/settings.py`, embedding block ~L61-69).**

- `EMBEDDING_PROVIDER` env, default **`"fastembed"`** (user decision);
  accepted values `fastembed | gemini`, anything else → `RuntimeError`
  (house fail-fast style).
- When provider is `fastembed`, `embedding_model` defaults to
  **`google/embeddinggemma-2@int8`** (the `@int8` suffix is *identity, not
  decoration*: it flows into every cache key and the Chroma collection
  metadata, so a future fp32/q4 switch is structurally forced into a clean
  re-embed instead of silently mixing spaces). When `gemini`, default stays
  `gemini-embedding-2`. Explicit `EMBEDDING_MODEL` still overrides.
- `EMBEDDING_DIMENSIONALITY` stays `768`. RPM/RPD limits remain Gemini-only.

**Spec 3 — registration + provider class (`src/llm/embeddings.py`).**

- Registration (runs once, inside the local class's lazy-init; fastembed
  downloads **only** the pattern-restricted files — the vision/audio encoders
  are never fetched because `download_model` allow-lists `model_file`,
  `additional_files`, and tokenizer/config files):

  ```python
  TextEmbedding.add_custom_model(
      model="onnx-community/embeddinggemma-2-ONNX:int8",
      pooling=PoolingType.DISABLED,      # graph mean-pools internally
      normalization=False,               # graph L2-normalizes internally
      sources=ModelSource(hf="onnx-community/embeddinggemma-2-ONNX"),
      dim=768,
      model_file="onnx/model_quantized.onnx",
      additional_files=["onnx/model_quantized.onnx_data"],
      output_name="sentence_embedding",  # explicit: validated at load time
  )
  ```

  `pooling=DISABLED` + `normalization=False` are correct **only because**
  `sentence_embedding` is pooled+normalized in-graph; if the open-item check
  below disproves that, flip to `pooling=MEAN, normalization=True,
  output_name="last_hidden_state"` instead (do not silently change one flag).
- New class `FastembedEmbedding` implementing `EmbeddingFn` (structural, like
  `GeminiEmbedding`): `TextEmbedding` built lazily in `_ensure_model`
  (mirrors `_ensure_client`), so construction without the model on disk is
  safe; **injected-double param `text_embedding=`** for offline tests
  (mirrors `client=`); model cache dir via `FASTEMBED_CACHE_PATH` env
  (documented in `.env.example`); CPU provider explicit
  (`providers=["CPUExecutionProvider"]`). `embed_documents` applies
  `MODEL_PREFIX_DOC` + `_truncate` (MAX_TEXT_CHARS stays 6,000 — ~1,500
  tokens fits even the 2,048-token truncation cap), then one fastembed
  `embed` call (it handles its own batching; no API batching semantics
  apply); `embed_query` applies `MODEL_PREFIX_QUERY`. Floats cast to `float`
  lists. **No** `remaining_daily_budget` / `estimate_api_requests` — the
  refresh's `getattr`-guarded hooks (job_executor.py:255, 265) already
  tolerate absence (planned/used stay 0, `quota_exhausted` False).
- Provider factory `build_embedding_fn(settings)` in the same module; both
  production construction sites call it instead of hardcoding
  `GeminiEmbedding()`: `src/rag/chroma_store.py:93` and
  `src/graph/job_executor.py:252-254`; `scripts/backfill_embeddings.py:64`
  switches to it too. FU-4 pacing/budget code in `GeminiEmbedding` is kept
  **dormant, not deleted** (Gemini path remains selectable and A/B-able).

**Spec 4 — drift-guard consistency (`src/rag/chroma_store.py:91-92`).**
The store currently reads `embedding_model`/`dimension` from settings only.
Change it to prefer the injected fn's identity:
`getattr(embedding_fn, "model", settings.embedding_model)` and likewise for
dimensionality — so the guard compares the collection against **the provider
actually constructed**, closing the silent-degradation trap where the env
selects fastembed but stale settings say gemini (the blanket
`except Exception` in `_get_store`, job_workflow.py:206-216, would turn that
into degraded search with no visible error). `FakeEmbeddingFn` lacks `.model`
→ falls back to settings, so all existing tests keep their semantics.

**Spec 5 — warm-up.** First real embed loads the model (a few seconds).
`FastembedEmbedding` uses fastembed's `lazy_load=False` (default) so the
refresh constructs it up front; the API app's startup path performs one
`embed_query("warmup")` so the first user search never pays load latency.

**Spec 6 — one-time migration runbook (performed once, deliberate).**

1. Validate int8 quality (gate below). 2. Install fastembed, set
`EMBEDDING_PROVIDER=fastembed` + `EMBEDDING_MODEL=google/embeddinggemma-2@int8`.
3. Delete `data/chroma/` (the `VectorStoreMismatch` guard will demand exactly
this — schedule it, don't discover it). 4. Re-embed via refresh or
`scripts/backfill_embeddings.py` — **~4,314 docs, ~300 MiB model, CPU,
budget 10–30 min** (not the API's 2–3 days). 5. Verify: search returns
`degraded=false`, corpus count matches, cache populates under the new
`@int8` key space (old Gemini keys remain on disk, unused).

**Spec 7 — int8 validation gate (mandatory before flipping the default).**
Quantized (q8/dynamic) ONNX costs a small, unmeasured amount of quality.
Before migration: register the fp32 variant the same way
(`model.onnx` + `model.onnx_data`) and embed ~200 stored documents + 20
sample queries under both variants; compare top-10 rankings. **Gate: ≥90%
of queries with ≥9/10 top-10 overlap**, else fall back to fp32 (identity
`google/embeddinggemma-2@fp32`) and record the numbers here.

**Spec 8 — tests (suite stays offline, per repo convention).**

- `tests/test_embeddings.py` additions: `FastembedEmbedding` with an injected
  fake `TextEmbedding` double — prefix application (doc/query strings passed
  to the double verbatim), truncation at `MAX_TEXT_CHARS`, float-list
  conversion, determinism, identity `model`/`dimensionality` exposure.
- Factory test: `build_embedding_fn` returns `FastembedEmbedding` /
  `GeminiEmbedding` per settings; unknown provider → `RuntimeError`.
- Drift-guard test: store built with a fn exposing `model="google/
  embeddinggemma-2@int8"` raises/accepts per collection metadata (extends the
  existing `VectorStoreMismatch` tests in `tests/test_chroma_store.py`).
- Refresh test: with a budget-less local double, report fields
  `embedding_requests_planned/used` are 0 and `quota_exhausted` is False.
- Live smoke (manual, **not** in the default suite): real ~300 MiB download,
  real embed of a sample doc, one real re-embed + store-only search.

**Acceptance:**

- [x] `fastembed>=0.9.0` in pyproject with a New-dependencies entry; suite
  green and offline (fastembed imported lazily, tests use injected doubles).
- [x] `EMBEDDING_PROVIDER` selects the provider at both construction sites;
  default `fastembed`; unknown value fails fast.
- [x] Chroma metadata and cache keys carry `google/embeddinggemma-2@int8`;
  drift guard reflects the constructed provider, not stale settings.
- [x] int8-vs-fp32 gate numbers recorded in this section before migration.
- [x] Live: corpus re-embedded locally (≥4,300 docs), store-only search
  `degraded=false`, zero embedding API requests logged for the run.

**Open items to verify at implementation time (do not assume):**

1. `sentence_embedding` is truly L2-normalized in-graph (embed the same text
   twice + check norm ≈ 1.0; if not, use the MEAN/last_hidden_state recipe).
2. The graph's optional multimodal inputs run with only `input_ids` +
   `attention_mask` (fastembed introspects input names; the card's text-only
   usage implies defaults exist — confirm with one real session).
3. fastembed tolerates the repo's missing `special_tokens_map.json`.
4. Truncation cap: official card says 8,192-token context, the ONNX card
   mentions 2,048-token truncation — 6,000 chars (~1,500 tokens) fits either;
   confirm empirically which applies (over-cap behavior = truncation, not
   error) before raising any constant.
5. Reproducibility: `add_custom_model` pins no HF revision (files come from
   latest). Mitigation: record the downloaded `files_metadata.json` blob ids
   here after first download; production uses `FASTEMBED_CACHE_PATH` +
   `HF_HUB_OFFLINE=1` after the first fetch. Cache integrity is verified by
   fastembed against stored file metadata (`CorruptedCacheError` on drift).

**Implementation notes (2026-10-12 — implemented, gate passed, migration run).**

Suite: **345 passing** (was 332), offline, ruff clean. All five open items
settled empirically (`scripts/validate_int8_gate.py`, kept for re-runs):

1. `sentence_embedding` **is** mean-pooled and L2-normalized in-graph:
   output norm 1.0000002, deterministic across calls. Spec 3's
   `pooling=DISABLED, normalization=False` recipe confirmed correct.
2. **Spec's assumption was false**: the fused multimodal graph *requires*
   `image_features`/`video_features`/`audio_features` (`[num_tokens, 512]`
   each); fastembed feeds only `input_ids` + `attention_mask`, so every
   text-only call is rejected. Fix: `_TextOnlySession` shim in
   `src/llm/embeddings.py` wraps the onnxruntime session and injects
   zero-filled `[0, 512]` tensors — verified live to yield norm-1.0 outputs,
   byte-identical for 0 and 1 filler rows.
3. fastembed tolerates the missing `special_tokens_map.json` (empty-map
   fallback) — but NOT the sentinel `model_max_length` (~1e30) the export
   shipped: first load raised `ValueError`. Fix: `ensure_tokenizer_context`
   patches the cached tokenizer config **byte-length-preservingly** (sentinel
   digits → `8192` + padding spaces; resizing the file makes fastembed's
   remote-size verification flag every later download "corrupted" — found
   live the hard way). The upstream repo has since shipped a corrected
   tokenizer config (8,192); the shim remains as a no-op defense. Model card
   context is 8,192 (the "2,048" in the research notes was the hidden dim).
4. Truncation: far over-cap input (56k chars) embeds cleanly — tokenizer
   truncation, not an error; cap confirmed 8,192.
5. Downloaded revision `daa72c51243991dfcaf9f9137d2c573d8f7790c0`; blob ids
   (from `files_metadata.json`): config `b267dcb2…`, preprocessor `97ebeb96…`,
   tokenizer.json `8562f6c9…`, tokenizer_config `a9afd12f…`,
   model.onnx `158f4f33…` + model.onnx_data `051a412d…`.

**Spec 7 gate (recorded before migration, as required):** 200 persisted
documents + 20 held-out title+company queries, cosine top-10 per variant —
**20/20 queries with ≥9/10 overlap (100%)**, gate ≥90% → **PASS**, int8
adopted (`google/embeddinggemma-2@int8`). fp32: 783 s / 200 docs; int8: 822 s
/ 200 docs on 12 CPUs (memory-bandwidth-bound; `threads` scaling flat).

**Deviations from the spec (each forced by a live finding):**

- *No prefix application inside the provider.* Spec 3 had
  `embed_documents` apply `MODEL_PREFIX_DOC`; but the store and query path
  already compose prefixed text (same contract as `GeminiEmbedding`), so
  re-applying would double-prefix. `FastembedEmbedding` mirrors
  `GeminiEmbedding` exactly: callers prefix, the provider truncates — the two
  providers see byte-identical inputs and A/B comparisons are exact.
- *`FASTEMBED_BATCH_SIZE = 8`.* fastembed's default (256) OOMs outright on
  ~2,000-token documents (~2.4 GB single buffer); 16 still OOMs the int8
  graph's `MatMulNBits` dequantization buffers (9 GiB free); 8 verified safe.
- *One shared ONNX session per variant* (module-level cache): two resident
  sessions exhaust RAM mid-batch (live-verified); the API warm-up, the store,
  and the executor all construct their own `FastembedEmbedding`.
- *Warm-up skips when the weights are not downloaded yet* (cache dir empty):
  a fresh install or the test suite must never trigger the ~300 MiB download
  from app startup. After the first download the warm-up runs at startup
  (lifespan hook in `src/main.py`).
- *Throughput reality*: ~4.3 s/doc (not the 10–30 min/corpus the spec
  budgeted) — the 5,290-listing corpus fill is a multi-hour one-time CPU run,
  still ~10× faster than the 2–3-day Gemini path. Resumable via the store's
  chunked upserts (re-embed, not re-download, on restart).

**Migration (Spec 6) performed 2026-10-12:** `.env` set to
`EMBEDDING_PROVIDER=fastembed` + `EMBEDDING_MODEL=google/embeddinggemma-2@int8`
+ `FASTEMBED_CACHE_PATH=./data/fastembed`; `data/chroma/` deleted (held only
184 KB — the Gemini backfill had been quota-stopped long before completion);
corpus re-embedded via `scripts/refresh_jobs.py`.

## Execution plan (added 2026-10-11 — implementation of FU-1..FU-6)

Live probes done before coding (2026-10-11), two corrections to the plan above:

- **FU-2 confirmed:** `https://api.ashbyhq.com/posting-api/job-board/{org}` returns
  `{jobs, apiVersion}` with per-job keys `id` (uuid), `title`, `department`, `team`,
  `employmentType` (`FullTime`/`Contract`/`Intern`), `location` (plain string),
  `secondaryLocations`, `publishedAt` (ISO), `isListed`, `isRemote`, `workplaceType`
  (`Hybrid`/`None`), `jobUrl`, `applyUrl`, `descriptionHtml`, **and `descriptionPlain`
  (populated on 132/132 Notion jobs)** — so the adapter prefers `descriptionPlain`
  verbatim and falls back to `html_to_text(descriptionHtml)`. Live counts: openai 815,
  notion 132.
- **FU-3 correction:** Greenhouse *does* have a light listing mode — omitting
  `content=true` returns the same job list without the `content` field
  (7,512 B → 666 B per job on the stripe board, ~11x reduction; `title`,
  `location`, `absolute_url`, `metadata`, `company_name` survive). **Lever has
  no light mode**: `mode=json` is the only accepted value (`all`/`raw` → HTTP
  406). Two-pass therefore applies to Greenhouse only; Lever stays single-pass.
- **FU-3 identity caveat (by construction):** the light list has no descriptions,
  so the pass-1 filter runs on titles only. A listing whose *description* matches a
  token but whose title does not is invisible in pass 1 and cannot be rescued in
  pass 2 — two-pass narrows recall exactly to title-visible matches, while pass 2
  re-applies the full title+description filter on fetched content. Single-pass
  semantics are unchanged for: empty-query runs (no tokens → fetch everything,
  full content), which is what the FU-1 refresh uses, and everything stored
  server-side. Search-after-FU-1 never fetches boards at all, so the corpus and
  store-only searches are unaffected by the recall difference.

Phases, in dependency order (each phase: implement → unit tests → full offline
suite → live verification where the phase claims one):

1. **Phase A — FU-2 (Ashby adapter).** `src/jobs/ashby_adapter.py` following the
   Lever pattern (org-slug validation, DI `client=`/`orgs=`, `ASHBY_ORGS` env +
   settings + `.env.example`, registry + planner registration). Field mapping as
   probed above; canonical id `ashby:{org}:{uuid}`; `get_job` scans the board once
   (Ashby's public API has no single-job endpoint — Remotive trade-off). Recorded
   trimmed fixture `tests/fixtures/sources/ashby.json` (2 real jobs, verbatim
   shapes) replayed via MockTransport. Live acceptance: adapter returns
   openai/notion listings over HTTP.
2. **Phase B — FU-3 (Greenhouse two-pass).** `GreenhouseJobAdapter.search`:
   empty token set (refresh path) → single-pass `content=true`; otherwise pass 1
   light list, title filter, pass 2 per-survivor `?content=true` fetches
   (sequential, existing 1 s/host limiter), full filter, per-survivor failure
   degrades that survivor only. Lever untouched (no light mode). Tests:
   MockTransport asserting request sequence (light list first, no `content=true`
   board fetch), fixture parity for title-visible matches, survivor-fetch failure
   tolerance.
3. **Phase C — FU-4 (quota budget in `GeminiEmbedding`).** `classify_provider_error`
   distinguishes daily exhaustion (`…PerDay…` quota ids in SDK exception text) →
   new `LLMDailyQuotaExhausted(LLMRateLimited)` (still retryable, next day). The
   embedding class gains: batch pacing at ≤ RPM limit (12 s default between API
   batch calls, `EMBEDDING_RPM_LIMIT`), bounded per-minute 429 retries then raise
   (interactive calls degrade instead of hanging), immediate clean raise on daily
   exhaustion, an `api_requests` table in the existing `embedding_cache.sqlite`
   (UTC-day counters, survives restarts) exposing `remaining_daily_budget()`, and
   `estimate_api_requests(texts)` = cache-miss count ÷ 100 for refresh planning.
   `EMBEDDING_RPD_LIMIT` default 20. The backfill script's outer retry loop keeps
   working unchanged (class raises, script retries across days).
4. **Phase D — FU-1 (decouple refresh from search).** New executor functions in
   `src/graph/job_executor.py`: `refresh_jobs()` (fan out empty-query plans →
   normalize filter → dedup → `save_jobs` upsert → Chroma upsert, which embeds
   **only new/changed texts via the content-hash cache**; daily-quota exhaustion
   mid-run returns a partial, resumable report) and `search_stored_jobs()`
   (load `JobDB` rows → hybrid match vs Chroma → rank → top-N; zero board
   fetches, 1 query-embedding request). `run_job_search` keeps its current shape
   for tests/demo. API: `POST /api/jobs/refresh` (dependency-seamed, sync def) +
   `scripts/refresh_jobs.py` cron/Task-Scheduler wrapper. Tests: store-only
   search proves zero source calls with a call-recording fake; refresh is
   idempotent (second run embeds nothing new); suite stays offline.
5. **Phase E — verification + docs.** Full suite green; live run: Ashby over
   HTTP, one real `refresh_jobs()` against the configured boards, one
   `search_stored_jobs()` from the persisted corpus; doc statuses updated here;
   FU-5/FU-6 remain deferred per their sections above (FU-5 waits for WS-09's
   nDCG harness; FU-6 waits for a UI consumer).

### Implementation status (2026-10-11 — all phases complete, live-verified)

Suite: **332 passing** (was 297), offline, two consecutive green runs.

- **FU-2 done.** `src/jobs/ashby_adapter.py` registered in SOURCES + planner;
  `ASHBY_ORGS` in settings/.env/.env.example; recorded fixture
  `tests/fixtures/sources/ashby.json`. Live: notion 73 + openai 696 listings
  matched for "engineer" over the real API with correct field mapping
  (`descriptionPlain` verbatim, CamelCase employmentType normalized,
  `isRemote`/`workplaceType` → remote_policy, department/team in metadata).
- **FU-3 done, with the documented Lever exception.** Greenhouse two-pass
  (`content`-less light list → title filter → per-survivor content fetches);
  empty-token runs stay single-pass (the refresh path). Live on stripe:
  728 jobs → 163 title survivors → 163 content fetches, no board-level
  content fetch. Live fixture data also proved the recall caveat is real:
  "python" on stripe matches only in descriptions (4 single-pass, 0 two-pass)
  — asserted as documented behavior in tests.
- **FU-4 done.** `LLMDailyQuotaExhausted` classification (per-day quota ids in
  SDK 429 text), batch pacing at `60/EMBEDDING_RPM_LIMIT`, bounded per-minute
  retries, persistent UTC-day request counter in `embedding_cache.sqlite`
  (`remaining_daily_budget()`), `estimate_api_requests()` for planning,
  backfill script stops cleanly on daily exhaustion. Live: the refresh's first
  batch 429'd on the per-day quota (the backfill had spent it) → immediate
  clean stop, no retry spam.
- **FU-1 done.** `refresh_jobs()` / `search_stored_jobs()` in the executor;
  `POST /api/jobs/refresh`; `POST /api/jobs/search` now defaults to the
  store-only executor bound to the request-scoped DB; `scripts/refresh_jobs.py`
  for cron. `run_job_search` unchanged for tests/demo. Live: one real refresh
  fetched **5,287 listings (zero source errors — the +973 are the rescued
  Ashby boards), planned 45 embedding requests, persisted all rows, stopped
  cleanly on the daily quota (quota_exhausted, exit 0, resumable)**;
  `search_stored_jobs` matched 5,290 stored listings with zero board fetches.
- **Resumability hardening found by the live run:** the store upsert is now
  chunked (embed 100 → upsert 100), so a quota stop keeps every completed
  chunk in Chroma (`embedded` counts partial progress; the next run pays only
  for the remainder). Without this, nothing reached the store until a day
  with enough quota for the whole corpus.
- FU-5/FU-6: still deferred as documented. The live degraded search again
  showed FU-5's neutral-inflation ties (OpenAI roles all at 85.0) — the
  mitigation remains filling the vector store, and the WS-09 nDCG harness
  remains the decision point.

Known flake (pre-existing, not FU-related): the SSRF guard in
`src/jobs/http_client.py` resolves adapter hostnames via real DNS even under
MockTransport, so a transient DNS hiccup can fail remotive/greenhouse/lever
fixture tests in a full-suite run; isolated reruns pass. Not changed —
SEC-11 behavior deserves an explicit decision.
