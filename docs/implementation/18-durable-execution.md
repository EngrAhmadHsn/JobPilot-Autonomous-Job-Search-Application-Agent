# WS-18 · Production Resilience, Durable Execution & Failure Recovery

Status: **Done (2026-11-05)** · Milestone: **M5** · Depends on: WS-02 (boards), WS-03 (embeddings), WS-04 (pipeline), WS-10 (LLM resilience), WS-12/WS-15 (runtime limits), WS-14 (identity), WS-17 (console) · Live-verified: offline + worker restart + failure injection

> The system already survives a crash in the sense that **re-running the
> refresh replays correctly**: jobs are merged by canonical id, embeddings are
> content-hash cached, Chroma ids are stable. That is *replayability*. It is
> not *durable execution*: nothing records which work item was being processed,
> who claimed it, why the process stopped, or who may resume it.
>
> This workstream closes that gap without introducing Redis, Celery, Kafka or
> a second service. SQL is the source of truth, Chroma is a rebuildable
> projection, and a single supervised worker drains a database-backed queue.

---

## 1. Phase 0 — Reliability audit

The matrix distinguishes a **full** safeguard from a **partial** one and from
**missing** functionality. Evidence is the file and function that carries the
control today.

| Capability | Existing implementation | Gap | Change |
|---|---|---|---|
| Persistent execution record | `refresh_jobs()` logs a random `workflow_id` (`src/graph/job_executor.py:389`); the id is never stored | **Missing.** No run row, no status, no history | `job_runs`, `job_work_items`, `job_run_events` tables; the correlation id becomes the durable run id |
| Accepted work survives an API restart | `POST /api/jobs/refresh` executes inline; a restart loses the accepted work | **Missing.** The HTTP request *is* the job | The route enqueues a durable run and returns `202`; a separate worker executes it |
| Atomic claim | None. One process, one refresh at a time by convention | **Missing.** Two workers would process the same listing | PostgreSQL `FOR UPDATE SKIP LOCKED`; SQLite conditional `UPDATE ... WHERE status='QUEUED'` with `rowcount` as the lock |
| Leases and recovery | None | **Missing** | `lease_owner`, `lease_token`, `lease_expires_at`; a reaper requeues expired items and marks the run `RECOVERABLE` |
| Per-item checkpoint | `ChromaVectorStore.upsert_jobs()` commits per 100-listing chunk (`src/rag/chroma_store.py:183`) | **Partial.** The chunk survives, but the *work item* has no state, so the system cannot say which listing is outstanding | One `job_work_item` per `(job_id, content_hash, model, dimension)`; completion is a conditional update guarded by the lease token |
| Idempotent retries | Stable Chroma ids + content-hash cache + `save_jobs` merge | **Partial.** A retry after "Chroma wrote, SQL update failed" is safe only because re-upsert is id-stable by luck of the design, not because a verifier proves it | Upsert → **verify** the vector and document → then mark the item complete; a failed final update retries the same item |
| Transactional outbox | `save_jobs()` and the embedding call are separate operations in one function; a crash between them leaves persisted rows with no record that they need a vector | **Missing.** The gap is exactly `Scenario C` in the brief | `save_jobs_and_enqueue()` writes job rows **and** work items in one transaction |
| Bounded queue | The API concurrency gate bounds *simultaneous heavy requests* (`src/api/middleware.py:255`) | **Partial.** It does not bound *accepted but not yet executed* work | `MAX_PENDING_RUNS`, `MAX_PENDING_WORK_ITEMS`; `QueueFull` → `503` + `Retry-After` |
| Duplicate refresh prevention | None | **Missing.** Two clicks enqueue two full refreshes | An active `refresh` run is returned instead of enqueued again |
| Priority | None | **Missing** | `priority`: recovery 10, embedding 20, refresh 30, reconciliation 40 |
| Retry policy | Two implementations: `src/llm/resilience.backoff_delay` (×4) and `src/jobs/http_client._backoff_delay` (×2) | **Partial / diverged.** Two schedules, no `Retry-After`, no maximum delay | One `RetryPolicy` + `backoff_delay` (×2, capped, jittered) + `retry_after_seconds()`; both call sites use it |
| Circuit breakers | None | **Missing** | `CircuitBreaker` (CLOSED/OPEN/HALF_OPEN), per job-board host and per LLM/embedding provider, optional durable shared state |
| Per-provider isolation | `search_all_detailed` already drops a failing source and continues (`src/jobs/registry.py:57`) | **Partial.** A board that is down is retried on every refresh; it cannot be *skipped* | A breaker per board host; one open board does not affect the others |
| Bulkheads | API concurrency gate; the worker is a separate process | **Partial.** The embedding loop still runs inside the API process today | Worker process; API stays responsive because it no longer embeds |
| Health checks | `GET /api/health` returns a static `ok` (`src/api/routes/health.py:11`) | **Partial.** It cannot tell a live process from a ready one, and says nothing about the worker | `/api/health/live`, `/api/health/ready`, `GET /api/admin/health/workers` |
| Admin recovery | None | **Missing** | `GET /api/admin/embedding-runs`, `GET .../{run_id}`, `POST .../{run_id}/resume`, `POST .../{run_id}/cancel`, `POST /api/admin/embeddings/reconcile` |
| User-visible execution history | None | **Missing** | `GET /api/runs`, `GET /api/runs/{run_id}` (owner-scoped) |
| Reconciliation | None | **Missing.** SQL and Chroma can disagree after any of the four crash windows | `reconcile_embeddings()` detects missing vectors, orphan vectors, stale content versions, interrupted items and inconsistent completion flags |
| Observability | Structured logs with an ad-hoc `workflow_id` | **Partial.** `run_id`, `worker_id`, `work_item_id` do not exist as durable fields | Every log line and event carries `run_id` + `correlation_id` + `worker_id`; `GET /api/admin/jobs/metrics` reports queued/running/retry/stale/reclaimed counts, the oldest pending item, cache hits and misses per batch, the embedding budget, breaker states, and per-worker heartbeat age, restarts and work-per-minute |
| Error taxonomy | `src/llm/errors.py` already separates retryable from permanent | **Full** for the LLM; boards classify by status only | Reuse the taxonomy; add failure categories (`retryable`, `permanent`, `quota`) to work items |
| Quota handling | `LLMDailyQuotaExhausted` stops the refresh cleanly (`src/graph/job_executor.py:518`) | **Partial.** The stop is reported, but the outstanding work is not recorded | Quota → run `PAUSED`, items left `QUEUED`, resume respects the same budget |
| Single-writer Chroma | Implicit: only the API process writes | **Partial.** Not enforced anywhere | The worker is the only writer; the API only reads. Documented and asserted by the worker entry point |
| Frontend truthfulness | The Operations screen waits on the HTTP request | **Partial.** A page reload loses the run | Runs table, progress polled from persistent state, explicit Resume with confirmation |

### What is deliberately **not** changed

- No Redis/Celery/Kafka. The queue is a table.
- No distributed transaction between SQL and Chroma. At-least-once with
  idempotent effects and a verifier.
- No custom WAL. SQLite/PostgreSQL durability is configured, not reinvented.
- No event sourcing. Current state in `job_runs`; history in `job_run_events`.
- No process-local lock presented as coordination. The atomic claim is a
  database operation on both engines.

---

## 2. Architecture

```text
                 POST /api/jobs/refresh                  GET /api/runs
                          │                                     │
                          ▼                                     │
                   ┌──────────────┐                             │
                   │  FastAPI     │  enqueue (202 Accepted)     │
                   │  (no long    │──────────────┐              │
                   │   work)      │              ▼              │
                   └──────────────┘      ┌───────────────┐      │
                          │              │  SQL (truth)  │◄─────┘
                          │ reads        │  job_runs     │
                          ▼              │  job_work_items│
                   ┌──────────────┐      │  job_run_events│
                   │   Chroma     │      └───────┬───────┘
                   │ (projection) │              │ atomic claim
                   └──────────────┘              ▼
                          ▲              ┌───────────────┐
                          │ verify       │    worker     │
                          └──────────────│  (supervised) │
                                         └───────────────┘
```

- **SQL is authoritative.** A listing exists because `jobs` says so. A
  vector exists because a work item completed and the store verified it.
- **Chroma is reproducible.** Deleting `data/chroma` and running the
  reconciler rebuilds it from `jobs`.
- **The worker is the single writer.** The API never embeds or upserts.
- **The run is the unit of accountability.** Every accepted job has a durable
  id before execution starts.

### Execution model

| Type | Run | Work items | Handler |
|---|---|---|---|
| `refresh` | one per accepted refresh | one `refresh` item | fetch → normalize → screen → admit → `save_jobs_and_enqueue()` |
| `embedding` | child of the refresh, created in the same transaction | one `embed` item per outstanding listing | cache → embed → upsert → **verify** → complete |
| `reconcile` | one per request | one `reconcile` item | detect and repair SQL/Chroma divergence |

### Run states and legal transitions

```text
QUEUED ──► RUNNING ──► COMPLETED
   │          │  ├────► PARTIAL
   │          │  ├────► FAILED
   │          │  ├────► PAUSED ──► QUEUED (administrator resume)
   │          │  └────► RETRY_WAIT ──► QUEUED (scheduler/resume)
   ├────────► RECOVERABLE ──► QUEUED (administrator resume)
   └────────► CANCELLED
```

`COMPLETED`, `PARTIAL`, `FAILED` and `CANCELLED` are terminal **for the
worker**. Only an explicit, attributable recovery request may move
`PAUSED`/`RECOVERABLE`/`RETRY_WAIT`/`FAILED`/`PARTIAL` back to `QUEUED`, and
the worker — never an arbitrary status write — decides whether a run is
`COMPLETED`. `assert_transition()` enforces the matrix in the backend.

Work item states: `QUEUED`, `RUNNING`, `RETRY_WAIT`, `COMPLETED`, `FAILED`,
`CANCELLED` (superseded content version).

### The four crash windows of `Scenario C`

| Window | Database after restart | Recovery |
|---|---|---|
| Embedding generated, not cached | item `RUNNING`, lease expires | Re-embed; the cache miss is paid once more |
| Cached, not in Chroma | item `RUNNING`; cache has the vector | Re-embed is a cache hit; upsert runs |
| Chroma upserted, SQL not completed | item `RUNNING`; vector exists | Re-upsert (id-stable), verify, complete |
| SQL update failed after Chroma | same as above | Same path; verification proves the vector matches the document |

The verifier reads back `ids`, `documents` and the `content_hash` metadata
before an item is marked complete. A vector that does not match is treated as
absent, so the retry is safe.

### Claiming

- **PostgreSQL:** `SELECT ... FOR UPDATE SKIP LOCKED` inside one transaction,
  then a conditional `UPDATE`.
- **SQLite:** `SELECT` candidate ids, then
  `UPDATE ... SET status='RUNNING', lease_token=?, ... WHERE id=? AND
  status IN ('QUEUED','RETRY_WAIT')`; `rowcount == 1` is the lock. A lost
  race costs one skipped id, never a double claim.
- A stale worker's `complete`/`fail` is conditioned on its `lease_token`;
  `rowcount == 0` raises `LeaseLost` and writes nothing.

---

## 3. Implementation phases

### Phase 1 — Durable job infrastructure

- `src/db/runs.py`: `JobRunDB`, `JobWorkItemDB`, `JobRunEventDB`,
  `WorkerHeartbeatDB`, `CircuitBreakerDB`.
- Migration `a7b8c9d0e1f2_ws18_durable_runs.py` (reversible; SQLite + PostgreSQL).
- `src/runs/state.py`: states, transitions, `utcnow`, `LeaseLost`, `IllegalTransition`.
- `src/runs/queue.py`: enqueue, atomic claim, heartbeat, complete, fail,
  lease reaper, checkpoint/finalize, queue stats, worker registry.

### Phase 2 — Worker isolation

- `src/runs/worker.py` + `scripts/run_worker.py`: supervised loop, signal
  handling, heartbeat, bounded batch, graceful stop.
- `POST /api/jobs/refresh` returns `202` + durable run id.
- `scripts/refresh_jobs.py --foreground` keeps the synchronous operator path.

### Phase 3 — Embedding recovery

- `src/runs/embedding.py`: content hashing, outbox, checkpointed batch
  processing, post-upsert verification, reconciliation.
- `refresh_jobs()` reuses the same queue/outbox/handler so the offline tests
  exercise the production path.
- Admin resume validates the model and dimension before requeueing anything.

### Phase 4 — System-wide resilience

- One retry policy (`RetryPolicy`, `backoff_delay` ×2, capped, jittered,
  `Retry-After` honoured).
- Circuit breakers per board host and per LLM/embedding provider, with
  optional shared state in `circuit_breakers`.
- `/api/health/live`, `/api/health/ready`, worker health, queue metrics.
- Admission: bounded queue, duplicate-refresh suppression, priority.

### Phase 5 — Admin dashboard

- Operations screen: enqueue, live run progress from persisted state, run
  history.
- Administration screen: background-run table, checkpoint detail, Resume with
  confirmation, reconcile action.

### Phase 6 — Validation

- Failure-injection suite covering every scenario in §5 of the brief.
- Full offline suite, lint, migration chain, worker restart on a real SQLite
  file, Postgres DDL rendering.
- Docs: ARCHITECTURE, SECURITY, RUNBOOK, README, `.env.example`.

---

## 4. Definition of done (mapped)

| # | Property | Proof |
|---|---|---|
| 1 | Work survives browser disconnection | Run exists before the reply; the console polls it |
| 2 | Accepted work survives API/worker restarts | `test_worker_recovery.py` reopens the database in a fresh session factory |
| 3 | An interrupted embedding operation is recoverable | Crash windows A–D |
| 4 | Administrators have a protected recovery action | `require_superuser` + 401/403 tests |
| 5 | Recovery resumes only unfinished work | completed items are never requeued |
| 6 | Repeated processing makes no duplicate vectors | unique identity + stable ids + store count assertion |
| 7 | Daily quotas and security limits still hold | quota → `PAUSED`; resume respects the budget |
| 8 | One failing provider does not bring the rest down | per-board breaker; one open board, other boards answer |
| 9 | No concurrent ownership of a live item | two workers claim disjoint sets |
| 10 | A stale worker cannot commit | `LeaseLost` after re-claim |
| 11 | Every execution has a durable id and history | `job_run_events`, logs, metrics |
| 12 | The API stays responsive under heavy work | worker is a separate process; API never embeds |
| 13 | Failure states are visible and distinct | status + `last_error_kind` + `last_error` |
| 14 | Inconsistencies are detectable and reconcilable | `POST /api/admin/embeddings/reconcile` |
| 15 | Deployment and recovery are documented | RUNBOOK §4.4/§5.5–5.7 |

---

## 5. Acceptance tests

| Area | Test file |
|---|---|
| Queue, leases, state machine | `tests/test_durable_queue.py` |
| Worker crash/recovery/failure injection | `tests/test_worker_recovery.py` |
| Admin + owner run API authorization | `tests/test_runs_api.py` |
| Circuit breakers and unified retry | `tests/test_circuit_breakers.py`, `tests/test_llm_resilience.py` |
| Health and worker liveness | `tests/test_health_workers.py` |
| Existing refresh behaviour preserved | `tests/test_refresh_and_stored_search.py` |
| Migration chain | `tests/test_migrations.py` |
| Docs/env agreement | `tests/test_env_docs.py`, `tests/test_docs_accuracy.py` |

## 6. Result (2026-11-05)

- 1,376 Python tests collected (1 skipped). Across three full runs the only failures were
  the six known Remotive DNS flakes (`SSRFBlockedError` from a transient `gaierror` under
  load; `tests/test_jobs.py` passes in isolation) and, in the first run, a `SecurityLimits`
  dataclass that gained two queue fields — fixed.
- 125 frontend tests passed; `tsc -b --force` and the production build pass.
- `ruff check src tests scripts` is clean.
- The migration chain applies and reverses on SQLite and renders on PostgreSQL
  (`tests/test_migrations.py`, `scripts/verify_migrations.py`).
- The live documentation/operations acceptance run (`scripts/verify_ws11.py`) passes 31/31
  on a throwaway database and a real fake-ATS browser, including a real registration, login,
  upload, search, prepare, approve, submit and verify.
- The live recovery surface was exercised on the developer database: `202` enqueue with a
  durable id, duplicate-click suppression (`existing: true`), the owner-scoped run detail,
  anonymous `401`, administrator `200`s on the metrics/worker views, and a worker `--once`
  start/stop with a registered heartbeat.

The scope was deliberately kept to the brief: one database-backed queue, one supervised
worker, one recovery path. No Redis, no Celery, no distributed transaction, no event
sourcing.

---

## 7. Follow-up (2026-11-08) — the local embedder's memory ceiling, and the lease under a slow batch

A day of live running produced the failure the unit suite could not: the queue never
emptied. Three runs of 2,000 embedding items sat at 0–20% for 29 hours, every batch
settling `0 completed, 100 retrying`, and the console showed only "Worker stopped
heartbeating; the run is recoverable".

### What the evidence said

| Observation | Evidence |
|---|---|
| Every batch failed *whole*, with a memory error | 3,700 item errors reading `Fail: [ONNXRuntimeError] … BFCArena::AllocateRawInternal Failed to allocate memory for requested buffer of size 584712192`, and `RuntimeException … bad allocation` |
| The failures were retried identically, forever | 54 batch failures in one worker log, each "100 item(s) to retry"; **no item ever reached the attempt cap** (0 `FAILED` rows), because the admin's own resume resets `attempt_count`, and a crash mid-batch leaves it to the lease reaper |
| The machine, not the model, was the limit | One worker process held **4.76 GB and was still growing** (5.65 GB forty minutes later); a `pytest` run and a `vitest` run on the same host both died with allocation failures of 84 KB |
| A long batch lost its lease | `job_work_items.lease_expires_at` (900 s from claim) passed mid-batch: 121 items requeued as "Worker lease expired; work requeued" and a `lost the lease while failing an item` traceback — the batch's work was discarded |
| The console showed "no worker" while a worker was working | the worker row is written only at the *start and end* of `run_once`; a 9–17 minute batch left it stale past `WORKER_STALE_SECONDS=60` (and `WORKER_HEARTBEAT_SECONDS` was read by nothing) |
| The cause was on no screen | the batch's failure was recorded per item (only `FAILED` items are sampled for display) and the run's `last_error` was overwritten by the reaper's heartbeat message |

### Root causes

1. **ONNX Runtime's CPU arena grows and never shrinks.** A long-lived process accumulates
   arena slabs across thousands of inferences until the next allocation cannot be
   satisfied. The embedder also does not degrade — the *whole* inference call raises — so a
   batch one document too large for the free memory failed entirely, and the queue retried
   the same oversized batch.
2. **fastembed's `embed()` is a generator.** The inference — and therefore the allocation
   failure — happens when the result is *consumed*, not when it is called. The first
   version of the adaptive-batching fix kept its `try` around the call and the exception
   escaped anyway; only materialising the generator inside the `try` catches it.
3. **A batch's lease was never renewed.** `WORKER_LEASE_SECONDS=900` was sized for a 100-item
   batch at 4 s/document, and nothing extended it when a batch ran longer.

### What changed

| Change | Where |
|---|---|
| The CPU arena is off (`enable_cpu_mem_arena=False`): the runtime allocates and frees per node, so memory is given back | `src/llm/embeddings.py` (model load) |
| The local embedder **halves its inference batch** on an allocation failure, down to one document, and remembers the smaller size for the process; a single document that still cannot be allocated raises the typed `EmbeddingResourceExhausted` | `src/llm/embeddings.py::_embed_chunk`, `src/llm/errors.py` |
| Vectors are cached **per sub-batch**, so a failure late in a large call keeps the minutes of CPU already spent (incremented daily work counter included) | `src/llm/embeddings.py::_embed_misses` |
| A new provider hook (`on_progress`) is called as sub-batches finish, threaded through the store to the worker, which **renews the batch's lease and its own heartbeat** from inside the batch | `src/llm/embeddings.py`, `src/rag/chroma_store.py`, `src/runs/embedding.py`, `src/runs/queue.py::renew_lease`, `src/runs/worker.py` |
| A batch that settled nothing now names its cause in the `batch.completed` event (and its metadata) | `src/runs/embedding.py::_settle` |
| `EMBEDDING_BATCH_SIZE` (default 8) is the ceiling the embedder starts from — a documented knob instead of a class constant | `src/config/settings.py`, `.env.example`, README |
| The admin runs table clamps the unbounded `last_error` to one line of a capped block and pins the action column, so a long error can no longer push the Resume/Progress buttons out of view | `frontend/src/screens/admin-screen.tsx` |

### The corpus, measured (2026-11-08, developer database)

| Quantity | Value |
|---|---|
| Listings in the corpus | 6,696 |
| Vectors in the store (`job_listings`) | 6,089 |
| …attributed to `google/embeddinggemma-2@int8` (their document is in the content-hash cache) | 5,438 |
| …still from the retired `gemini-embedding-2` space (should be re-embedded) | 34 |
| …unattributed (no cache record: written through a different cache or before it existed) | 617 |
| Cached vectors by model | gemma 5,730 · gemini 817 |
| Outstanding queue items / distinct listings behind them | 5,700 / 3,346 |
| …of those, already cached (the model must not run again) | 308 |

Two honesty notes the numbers force: **Chroma records the embedding model at collection
level, not per vector**, so per-vector attribution is an inference from the cache key, not
a stored fact — the 617 unattributed vectors are exactly the ones that assumption cannot
reach. And a run in the retired Gemini space cannot simply be resumed: the resume guard
refuses a model mismatch, so those vectors want a re-embed, not a retry.

### Verified live

A worker started with the fixed code (`--worker-id DESKTOP-090OH77-fix2`) against the stuck
run: batches complete (`400` items done, up from `100`), the run's `lease_expires_at` tracks
15 minutes ahead of a heartbeat refreshed every few documents (`heartbeat_at` 11 s old while
the batch was still embedding), and the process settles around 2.4 GB instead of climbing
past 5 GB. New tests: `tests/test_embeddings.py` (halving, per-sub-batch cache, typed
resource error, the progress hook — with a **generator** double so the lazy-exception trap
stays caught) and `tests/test_worker_recovery.py` (renewal survives the original expiry,
a reclaimed batch raises `LeaseLost`, the worker renews what it claims, a settled-nothing
batch names its cause).

Left open, deliberately: the API process (which embeds search queries) needs a restart to
pick up the same arena and batching changes, and the SQLite database has no WAL or
`busy_timeout` configured — with the worker now writing an extra lease renewal per few
documents, a "database is locked" is possible under API write load. It is logged and
retried at the next sub-batch rather than fatal, but the pragma is the real fix.

---

## 8. Follow-up (2026-11-09) — a dead worker reported "running", and the runs table

### The worker status was wrong, and the reason was structural

The console's worker list printed `worker.status` straight from the heartbeat row, and that
row said **running** for workers that had been dead for hours. The row is written `running`
at registration and flipped to `stopped` only by the worker's own `shutdown()` — and a
process that is killed (a crash, `taskkill /F`, a lost machine) never reaches `shutdown()`.
Nothing else ever wrote the row, so the lie was permanent.

The fix is at the read, not the display:

| Piece | Change |
|---|---|
| Effective status | `queue.worker_health` derives `crashed` for a row that still says `running`/`stopping` but whose heartbeat is older than `WORKER_STALE_SECONDS`, and reports the raw value beside it as `reported_status` (with `stale`) |
| Persisted verdict | `reap_expired_leases` now also writes those rows to `crashed` (with `stopped_at`), so every other consumer of the table sees the truth, not just this endpoint. Its window is `WORKER_STALE_SECONDS`, deliberately **not** `run_stale_seconds`: a run waits 30 minutes (it must outlast a long batch), a worker is gone after one |
| Presentation | a new `src/lib/worker-status.ts` gives each status a label, a tone and a next step; the console renders "Stopped responding" and never the raw string, and the Worker card separates live rows from a dashed "Not running" section |

Tests: `tests/test_health_workers.py` (a stale row reports `crashed` with
`reported_status: "running"`, a fresh row still reports `running`, a clean stop is never
reclassified), `tests/test_durable_queue.py` (the reaper persists the crash, leaves a fresh
worker alone, never touches a cleanly stopped one), and the admin screen test that a
`running`-in-the-row worker is not printed as running.

### The runs table, rebuilt

- **Active / Inactive groups.** The single flat list mixed "what the machine is doing" with
  "what it did", so a 30-row queue read as noise. Runs are split on `isRunTerminal`;
  `RECOVERABLE` is deliberately in **Active** (it is unfinished work, and its Resume button
  belongs with the work), and each group carries its own count and description.
- **Five rows per group, paged independently.** A `RunGroup` slices `RUNS_PER_PAGE = 5` and
  owns a `Pagination`; paging history never moves the active rows. The slice is clamped, so
  a poll that shrinks the list under the operator's page cannot render an empty table.
- **Polish and a real defect.** The status column's `runStatusCopy().tone` used
  `text-terracotta` — the pale **fill** intended to sit *behind* text, which painted an
  unreadable peach on the ivory surface (every other use in the repo pairs it with
  `terracotta-foreground`). Now `text-terracotta-foreground`, bounded with `max-w-52
  truncate` so a long label clips instead of overpainting the next column. Re-measured in a
  real browser: the table's `scrollWidth` equals its `clientWidth` (0 overflow) against a
  pathological 300-character error, with the full text on hover.

Verified in a browser (built bundle, `vite preview`, stubbed API): 3 active rows and 5
inactive rows, the inactive pager moving 5→2 without disturbing the 3 active rows, and a
worker whose row says `running` with an hour-old heartbeat rendering as
"Stopped responding" under "Not running".