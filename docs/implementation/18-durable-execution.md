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