# Autonomous AI Job Application Agent - Architecture Document

Status: **reconciled 2026-11-16 (through WS-32)** · Supersedes the status sections written on
2026-10-21 (WS-11) and 2026-09-13

> This document describes the system that exists. The file-level plan that produced it is
> [`docs/implementation/00-OVERVIEW.md`](implementation/00-OVERVIEW.md); the intent it was built
> from is [`docs/PROJECT_PLAN.md`](PROJECT_PLAN.md); the security model is
> [`docs/SECURITY.md`](SECURITY.md).
>
> The sections at the end (§14–§19) are **historical records** — the Phase footprints written
> as the work landed. They are kept because they are the only record of the plan-vs-actual
> sequence, but their "Status" lines are dated and are superseded by §13.
>
> **What the 2026-11-16 pass changed.** §2.1, §3.1, §6, §7, §10, §12 and §13 were reconciled
> against the code as of WS-32: the route count (17 → 67), the table count (14 → 21), the
> scorer count (six → eight, after WS-20's `lexical` and WS-21's `role`), the new runtime
> components (identity, storage layout, retention, the assist adapter, the provider fallback
> chain), and the two routes the flows above §3.2 had not been told about (`POST
> /api/jobs/refresh`'s durable 202, and `POST /api/applications/{id}/approve`'s move onto the
> same queue in WS-32).

## 1. System Overview

The Autonomous AI Job Application Agent is a production-oriented system that:

- Accepts candidate resumes and parses them into a validated `CandidateProfile`
- Searches and normalizes job listings from multiple public job-board APIs
- Matches jobs against the candidate profile using hybrid scoring
- Ranks jobs and explains each match score component by component
- Tailors resumes without inventing facts, and validates every claim deterministically
- Fills application forms on real job sites through browser automation, and stops there: the
  submit is the human's (the real-board adapter holds no `submit` capability)
- Submits applications **against the local fake ATS** with human approval, and verifies the
  outcome with stored evidence; a real-board submission has never been sent

## 2. System Architecture

The system is a **modular monolith** (plan §47): one Python package, one database, and two
processes with different lifetimes — the **API** (request serving) and the **worker**
(durable background execution, WS-18).
The separation that matters is not between services but between **development-time components**
(Cursor, ZCode, MCP servers, hooks, skills) and **runtime components** (the application that
actually runs).

### 2.1 Component status

| Component | State | Where it lives | Verified by |
|---|---|---|---|
| FastAPI service | **Implemented** | `src/main.py`, `src/api/routes/` | `tests/test_health.py`, `tests/test_resumes_api.py` |
| REST API (the full route table) | **Implemented** — 67 routes | `src/api/routes/` (13 route modules plus the identity API) | `tests/test_docs_accuracy.py` (the README's table is checked against the app's own OpenAPI schema) |
| Identity and sessions | **Implemented** | `src/auth/` (`manager.py`, `routes.py`, `backends.py`, `tokens.py`, `sessions.py`, `csrf.py`, `delivery.py`) | `tests/test_auth.py` (registration, both transports, CSRF, the session and account lifecycles — 41 tests) |
| Per-user storage layout | **Implemented** | `src/storage/paths.py` — every artifact under `data/users/{user_id}/…`, containment checked against the caller's own directory | `tests/test_user_storage.py` |
| Retention, the deletion cascade and the purge | **Implemented** | `src/retention.py`, `scripts/purge_expired.py` (operator-scheduled; not an in-process timer) | `tests/test_retention.py` |
| API middleware: rate limit, body cap, concurrency gate, in-flight cap, CSRF, response headers | **Implemented** | `src/api/middleware.py`, `src/security/limits.py` | `tests/test_ws12_hardening.py`, `tests/test_ws15_hardening.py` |
| Database schema and migrations | **Implemented** | `src/db/`, `migrations/versions/` (17 revisions, 20 tables) | `tests/test_migrations.py` |
| LangGraph job workflow | **Implemented** | `src/graph/job_workflow.py` | `tests/test_job_workflow.py` |
| LangGraph application workflow | **Implemented** | `src/graph/application_workflow.py` | `tests/test_application_workflow.py` |
| Job source adapters (Greenhouse, Lever, Ashby, Remotive) | **Implemented** | `src/jobs/*_adapter.py` | `tests/test_jobs.py` |
| Normalization and deduplication | **Implemented** — per-source identity and the cross-source merge key | `src/jobs/normalize.py`, `src/jobs/deduplicate.py` | `tests/test_deduplicate.py` |
| Matching engine (eight scorers) | **Implemented** | `src/matching/engine.py`, `src/matching/weights.py`, `src/matching/roles.py` | `tests/test_matching.py` |
| Vector store and embeddings | **Implemented** | `src/rag/chroma_store.py`, `src/llm/embeddings.py` | `tests/test_chroma_store.py`, `tests/test_embeddings.py` |
| Resume parsing (DOCX, TXT, MD, **PDF**) and profile validation | **Implemented** | `src/resume/parser.py`, `src/resume/profile.py` | `tests/test_resume_parser.py`, `tests/test_ws32_pdf_resume.py` |
| Resume tailoring and factuality validation | **Implemented** | `src/resume/tailor.py` | `tests/test_tailor.py` |
| In-place résumé editing, with the rewrite as fallback | **Implemented** | `src/resume/edit.py` (WS-31) | `tests/test_ws31_in_place_edit.py` |
| ATS analysis and DOCX rendering | **Implemented** | `src/resume/ats.py`, `src/resume/render.py` | `tests/test_ats.py`, `tests/test_render.py` |
| Grounded research engine | **Implemented** | `src/research/engine.py` | `tests/test_research.py` |
| LLM client with timeout, retries, pacing and usage accounting | **Implemented** | `src/llm/client.py`, `src/llm/resilience.py` | `tests/test_llm_client.py`, `tests/test_llm_resilience.py` |
| Provider fallback chain (Groq / TokenHarbor / Pollinations behind the primary) | **Implemented** — inactive until keys are added | `src/llm/fallback.py` (WS-30); the chain sits at the provider seam, so pacing, breakers and the usage row are unchanged | `tests/test_ws30_llm_fallback.py` |
| Bring-your-own model key (per-user, encrypted at rest) | **Implemented** | `src/api/routes/llm_credentials.py`, `src/db/byok.py`, `src/security/secrets.py` | `tests/test_ws22_byok.py`, `tests/test_ws22_byok_api.py` |
| Durable background execution: queue, leases, worker, recovery | **Implemented** | `src/runs/`, `src/db/runs.py`, `scripts/run_worker.py` | `tests/test_durable_queue.py`, `tests/test_worker_recovery.py`, `tests/test_runs_api.py` |
| Circuit breakers and one retry policy | **Implemented** | `src/llm/resilience.py`, `src/runs/circuit.py`, `src/jobs/http_client.py` | `tests/test_circuit_breakers.py`, `tests/test_llm_resilience.py` |
| Browser automation runtime (Playwright Python client) | **Implemented** | `src/applications/fake_ats_adapter.py`, `src/applications/form.py`, `src/applications/form_plan.py` | `tests/test_browser_variants.py`, `tests/test_isolation.py` |
| Assist-mode pilot: fill a real form, hand the submit to a human | **Implemented (WS-32), live-verified fill-only 2026-11-15** | `src/applications/assist_adapter.py` (`AssistAdapter`, PREPARE only — it never clicks submit) | `tests/test_ws32_assist_mode.py`, `scripts/probe_board.py`, the pilot evidence in `docs/evaluations/ws32-pilot-2026-11-15/` |
| Submission payload validation against the ATS contract | **Implemented** | `src/applications/greenhouse_contract.py`, `src/applications/greenhouse_forms.py` — fail-closed, because Greenhouse does **not** validate required fields itself | `tests/test_ws32_payload_contract.py` |
| Security layer: allowlist, policy, permissions, audit, injection, limits, paths | **Implemented** | `src/security/` | `tests/test_allowlist.py`, `tests/test_policy.py`, `tests/test_permissions.py`, `tests/test_audit.py`, `tests/test_injection.py`, `tests/test_page_guards.py`, `tests/test_ws12_hardening.py` |
| Application tracking and lifecycle | **Implemented** | `src/applications/tracking.py`, `src/db/applications.py` | `tests/test_tracking.py`, `tests/test_tracking_api.py` |
| Board registry, liveness and the measured form questions | **Implemented** (WS-25/25b/25c) | `src/db/boards.py`, `src/db/form_questions.py`, `src/applications/questions.py`, `src/applications/countries.py` | `tests/test_ws23b_boards.py`, `tests/test_ws25b_questions.py`, `tests/test_question_taxonomy.py` |
| Visa-sponsorship registers | **Implemented** | `src/db/sponsors.py`, `scripts/import_visa_sponsors.py` | `tests/test_ws22_sponsors.py` |
| Evaluation harness and measured baseline | **Implemented** | `src/evaluation/`, `scripts/run_eval.py` | `tests/test_eval_runner.py`, `tests/test_eval_metrics.py` |
| **Real-ATS submission (the submit half)** | **Planned** — the pilot fills the form and stops; nothing has ever been sent on a live board | the M5 pilot | — |
| **Web/company research by URL fetch** | **Planned** | behind the SSRF controls | — |
| LinkedIn retrieval | **Out of scope** | no public API; the placeholder adapter stays unregistered | — |

### 2.2 Development-time components

These help build the product. They are not part of the runtime architecture.

- **Cursor MCP configuration** (`.cursor/mcp.json`) — Playwright MCP for browser inspection
- **Cursor skills, hooks and rules** (`.cursor/`) — development-time procedures and guardrails
- **ZCode skills** (`.zcode/skills/`) — the same idea for this toolchain
- **Audit logging hooks** (`.cursor/hooks/`) — MCP-call auditing and Python formatting

## 3. Runtime Architecture

### 3.1 The three request flows

**Flow 1 — resume upload**

```text
POST /api/resumes
  → src/api/routes/resumes.py         route, multipart handling
  → src/api/validation.py              type, size, real-file check, zip-bomb guard
  → src/resume/parser.py               DOCX / TXT / MD extraction
  → src/resume/profile.py              validated CandidateProfile
  → src/db/profiles.py                 persisted row, id returned
  → src/security/audit.py              an audit event
```

**Flow 2 — job search (store only)**

```text
POST /api/jobs/search
  → src/api/routes/jobs.py             loads the stored profile
  → src/graph/job_executor.py          search_stored_jobs
  → src/matching/engine.py             eight deterministic scorers
  → src/rag/chroma_store.py            the semantic channel
  → src/db/matches.py                  one job_matches row per result
  → src/security/audit.py              an audit event
```

The daily refresh is the same pipeline with the board adapters in front of it
(`src/graph/job_workflow.py`: search → normalize → deduplicate → persist → match → rank). A
search never fetches a board.

**Flow 2b — the durable refresh (WS-18)**

```text
POST /api/jobs/refresh
  → src/api/routes/jobs.py           202: a durable run id, no long work
  → src/runs/service.py              enqueue (deduplicated against an active run)
  → src/runs/queue.py                job_runs + job_work_items, one transaction
        ... the request ends here; the browser may close ...
scripts/run_worker.py (a separate, supervised process)
  → src/runs/queue.py                atomic claim (FOR UPDATE SKIP LOCKED / conditional UPDATE)
  → src/graph/job_executor.py        fetch → normalize → screen → admit
  → src/runs/embedding.py            persist + enqueue the embedding work (transactional outbox)
  → src/rag/chroma_store.py          upsert, then verify the vector against the content hash
  → src/runs/queue.py                complete the item under its lease token; checkpoint the run
```

A crash at any point leaves a row that says exactly which work remains. The
lease reaper marks an interrupted run `RECOVERABLE`; an administrator resumes
the unfinished work through `POST /api/admin/embedding-runs/{id}/resume`.
SQL is the source of truth, and the Chroma index is rebuildable from it.

**Flow 3 — application (prepare → approve → submit → verify)**

```text
POST /api/applications/prepare
  → src/security/allowlist.py          the target host is checked
  → src/security/permissions.py        the adapter is selected from the registry
  → src/applications/<adapter>.py      the payload is assembled and validated
                                       against the ATS contract (fail-closed, WS-32)
  → src/db/approval.py                 an approval_requests row is written
  ── a human decides, in a separate call ──
POST /api/applications/{id}/approve
  → src/db/approval.py                 the decision, with an identity and a reason
  → src/security/policy.py             only an approved record may execute
  → src/runs/service.py                202: enqueue the submission (WS-32); the
                                       attempt row is the durable at-most-once marker
        ... the request ends here; the browser may close ...
scripts/run_worker.py (a separate, supervised process)
  → src/graph/application_workflow.py  prepare → approval → submit → verify
  → src/applications/fake_ats_adapter.py  the browser fills the form
  → src/applications/evidence.py       screenshot, action trace, Playwright trace
  → src/db/applications.py             the tracked application and its events
```

The **assist-mode pilot** (`src/applications/assist_adapter.py`) is the same flow with the
submit node replaced by a hand-over: it fills a real form through the same form walker, then
stops and returns `awaiting_human` — the human clicks Submit in a browser the run leaves open.
It writes no submission and claims none. Its first live run (2026-11-15, fill-only) is recorded
in `docs/implementation/32-submission-readiness.md` §5.5.

A submission whose outcome cannot be established — the process died after the board may have
accepted the form — is escalated as `submission.uncertain` to a human rather than guessed at,
which is why the durable attempt marker exists at all.

### 3.2 Runtime components

- **FastAPI application** (`src/main.py`) — the REST surface, the middleware stack, the lifespan
- **Identity** (`src/auth/`) — registration, login in two transports (a browser session cookie
  and a bearer token for scripts), server-side sessions, CSRF, the account lifecycle and the
  token mailbox that stands in for an SMTP provider
- **LangGraph runtime** (`src/graph/`) — two workflows with explicit state, branching and gates
- **Job adapters** (`src/jobs/`) — Greenhouse, Lever, Ashby, Remotive behind a guarded HTTP client
- **Matching engine** (`src/matching/`) — eight deterministic scorers over stored data
- **Vector store** (`src/rag/chroma_store.py`) — Chroma, with the model identity persisted
- **Embedding providers** (`src/llm/embeddings.py`) — local EmbeddingGemma-2 (default) or Gemini
- **LLM client** (`src/llm/`) — Gemini (supported), an `openai-compatible` path (experimental),
  and the WS-30 fallback chain (`fallback.py`) behind the primary provider
- **Browser automation** (`src/applications/`) — the Playwright Python client, the form walker,
  the form plan, the fake ATS, the real-board adapters and the assist-mode pilot
- **Security layer** (`src/security/`) — allowlist, policy, permissions, audit, limits, guards,
  the credential store's encryption and the HTML neutralizer
- **Storage layout** (`src/storage/paths.py`) — every artifact under `data/users/{user_id}/…`
- **Retention** (`src/retention.py`) — the windows, the deletion cascade and the purge
- **Database** (`src/db/`) — SQLAlchemy models, Alembic migrations, SQLite (dev) or PostgreSQL
- **Durable queue and worker** (`src/runs/`) — the run/work-item tables, the lease-protected
  claim, the checkpointed embedding handler, the reconciliation and the supervised loop. The
  worker is the **only writer** to Chroma; the API reads it. Submissions (WS-32) ride the same
  queue, so an approval is durable and executes at most once.
- **Circuit breakers** (`src/llm/resilience.py`) — per job-board host and per LLM/embedding
  provider, with optional shared state in `circuit_breakers`

## 4. Agent Architecture

The agent follows deterministic Python code with structured outputs, using LangGraph for
stateful workflows:

- **State Representation**: Pydantic models representing `CandidateProfile`, `JobListing`, and
  the two workflow states (`JobSearchState`, `ApplicationWorkflowState`)
- **Workflow States**: defined as LangGraph nodes with clear entry and exit conditions
- **Tool Integration**: narrow contracts with structured outputs for each tool
- **Retry Logic**: explicit retry mechanisms with timeout handling
- **Human Approval**: a persisted decision, with an identity and a reason, gates the irreversible
  action (the submission)
- **Observability**: an append-only audit trail for every external action, with secrets and PII
  redacted

## 5. LangGraph Workflows

**The job workflow** (`src/graph/job_workflow.py`) — a straight line, because every stage is
deterministic:

```text
search → normalize → deduplicate → persist → match → rank → END
```

**The application workflow** (`src/graph/application_workflow.py`) — branching, because a human
and a browser can both go wrong:

```text
prepare → approval ─┬─ (approved)  → submit ─┬─ (submitted) → verify → END
                    │                          └─ (failed)    → reject → END
                    └─ (rejected) → reject → END
```

The approval node **fails closed**: with no recorded decision, the run does not submit.

## 6. Browser Automation Architecture

- **Runtime**: the Playwright **Python** client (`src/applications/fake_ats_adapter.py` for the
  local fake ATS, `src/applications/assist_adapter.py` for a real board), driving the form
  through the **accessibility tree** (`src/applications/form.py`): the field map, the
  three question classes, and the answer rule. `src/applications/form_plan.py` is the plan the
  walker executes and the record of what it resolved — the pilot stops on `plan.unresolved`
  rather than guessing.
- **Semantic locators only**: a field is found by its label or its role. The only CSS in the
  module is the documented file-input exception and the validation-error sweep. The pilot's
  first live run found a real defect here: a trailing `*` in a board's label breaks the label
  locator on exactly the fields whose `aria-label` omits the star (`32-submission-readiness.md`
  §5.5).
- **Session isolation (SEC-07)**: every run gets an explicit, fresh browser context, so no
  cookie or storage survives it
- **Unknown questions stop the run**: a question the candidate's evidence does not cover ends the
  flow with `needs_human`; the agent never guesses (plan §24). The pilot found that this stops
  the walk *too* early, because every `unknown` question is unresolved even when it is optional
  — so an optional unclassified question prevents the fillable ones from ever being filled.
- **Challenges stop the run**: a CAPTCHA or an MFA prompt ends the flow with
  `blocked_human_review`; the agent never tries to solve one
- **Evidence is mandatory**: a screenshot, an ordered action trace and the Playwright trace
  archive. A submission that cannot produce them is downgraded, never reported as a success
- **The submit is the human's**: the assist-mode pilot never clicks the submit control. It fills
  the form and hands the open browser over (`awaiting_human`), so the irreversible action stays
  with a person. The payload it would have submitted is validated against the ATS's own
  published contract first, because Greenhouse does not reject an application that is missing a
  required field.
- **Development-time**: the Playwright MCP is for inspection and validation only. It is not the
  runtime browser layer.
- **The board probe** (`scripts/probe_board.py`, WS-32): a read-only instrument that fetches a
  board's form, lists what the walker resolves and never clicks submit. It is how the pilot's
  numbers are reproduced; liveness is read from the final URL and not the status code, because
  a closed posting answers `302` to a `/jobs/…?error=true` page — a `200`.

## 7. Data Architecture

The primary store is SQLite in development and PostgreSQL in deployment. **Twenty-one tables
across seventeen revisions**, each revision a feature so a rollback is per feature:

| Table | Model | Created by | Holds |
|---|---|---|---|
| `jobs` | `src/db/jobs.py` | `171f645abf1a` (initial) | the normalized listings. WS-15 added `last_seen_at` (`c3d4e5f6a7b8`), WS-23 `content_version` (`d2e3f4a5b6c7`), WS-23b `required_years` and `first_seen_at` (`f4a5b6c7d8e9`) |
| `application_evidence` | `src/db/evidence.py` | `171f645abf1a` (initial) | the submission evidence |
| `candidate_profiles` | `src/db/profiles.py` | `b8e2c94d1f57` (WS-04) | the parsed profile, as JSON; WS-20 added the application profile and the EEO selection |
| `job_matches` | `src/db/matches.py` | `b8e2c94d1f57` (WS-04) | the scores and the explanation |
| `tailored_resumes` | `src/db/tailored.py` | `c9a4f1e2d3b7` (WS-05) | the tailored content, the factuality report, the ATS report, the DOCX path; WS-22 added the style report, WS-31 the render report |
| `approval_requests` | `src/db/approval.py` | `d4e5f6a7b8c9` (WS-06) | the prepared payload and the human decision; WS-25 added the expiry and the profile-fact digest the approval is bound to |
| `audit_events` | `src/db/audit.py` | `d4e5f6a7b8c9` (WS-06) | the append-only trail; WS-14 added the principal (kind + id) |
| `applications` | `src/db/applications.py` | `e5f6a7b8c9d0` (WS-07) | the tracked application |
| `application_events` | `src/db/applications.py` | `e5f6a7b8c9d0` (WS-07) | every status change, with its actor |
| `users` | `src/db/users.py` | `f6a7b8c9d0e1` (WS-14) | the principal that owns data and acts |
| `access_tokens` | `src/auth/tokens.py` | `a1b2c3d4e5f6` (WS-14) | server-side sessions |
| `candidate_eeo` | `src/db/eeo.py` | `f1e2d3c4b5a6` (WS-20) | the voluntary EEO selections, isolated and never used for ranking |
| `visa_sponsors` | `src/db/sponsors.py` | `b3c4d5e6f7a8` (WS-22) | the verified sponsorship registers (USCIS, UK Home Office) |
| `llm_credentials` | `src/db/byok.py` | `b3c4d5e6f7a8` (WS-22) | one encrypted per-user provider key |
| `job_boards` | `src/db/boards.py` | `d2e3f4a5b6c7` (WS-23) | the board registry: slug, health, consecutive failures, listings seen |
| `form_questions` | `src/db/form_questions.py` | `f4a5b6c7d8e9` (WS-23b) | the questions the boards actually ask, with the count that makes the profile measurable |
| `job_runs` | `src/db/runs.py` | `a7b8c9d0e1f2` (WS-18) | one durable execution: status, lease, counters, checkpoint. WS-32 rides the same table for a submission |
| `job_work_items` | `src/db/runs.py` | `a7b8c9d0e1f2` (WS-18) | individually claimable work, with its own lease token and retry schedule |
| `job_run_events` | `src/db/runs.py` | `a7b8c9d0e1f2` (WS-18) | the append-only lifecycle history |
| `worker_heartbeats` | `src/db/runs.py` | `a7b8c9d0e1f2` (WS-18) | worker liveness and restart count |
| `circuit_breakers` | `src/db/runs.py` | `a7b8c9d0e1f2` (WS-18) | optional shared breaker state |

> Five of the seventeen revisions add columns rather than tables, which is why 21 tables come
> from 17 revisions: `b2c3d4e5f6a7` (WS-14, the audit actor), `c3d4e5f6a7b8` (WS-15,
> `jobs.last_seen_at`), `e3f4a5b6c7d8` (WS-25, approval expiry), `5cf9cea73955` (WS-28, the
> `required_years` sentinel) and `7a1b2c3d4e5f` (WS-31, the render report on
> `tailored_resumes`). The rest create at least one table, several also adding the columns
> their feature needed alongside it.

The vector store (Chroma, under `data/chroma`) holds the embeddings and the **model identity**
that produced them, so two embedding spaces can never be mixed. It also stores each vector's
`content_hash`, which is what lets a refresh ask "is *this version* embedded?" and lets the
worker **verify** a write before marking its work item complete.

**SQL is authoritative; Chroma is a projection.** A listing exists because `jobs` says so. A
vector is a derived index that can be deleted and rebuilt from `jobs`; the reconciler does
exactly that when the two disagree. There is no distributed transaction between them: the
work is at-least-once with idempotent effects (stable ids, stable content hashes).

## 8. Security Boundaries

- **Web Content**: treated as untrusted data; never as instructions
- **Prompt Injection**: a nonce-fenced untrusted block plus a deterministic injection filter,
  enforced in code rather than by model whim
- **Secrets**: isolated in environment variables, and a user's model key additionally encrypted
  at rest; never in prompts, logs or traces
- **Domain Allowlists**: an exact-match allowlist restricts fetch and browser navigation
- **Least Privilege**: the permission registry maps which adapter may `read`, `prepare`, `submit`
  and `verify`
- **Tenancy**: a caller reaches only their own rows (a scoped accessor, never a direct query)
  and only their own files (`data/users/{user_id}/…`); a foreign resource answers exactly as a
  missing one does
- **Audit Logs**: every external action is recorded, with the acting principal, without secrets
  or PII
- **Human Approval**: a recorded decision is required before an irreversible submission, and the
  pilot variant removes the agent's ability to submit at all
- **Bounds**: the rate limit, the body cap, the concurrency gate, the in-flight cap and the
  corpus/embedding budgets decide how much work an untrusted caller can cause

## 9. Development-time vs Runtime Components

| Category | Development-time | Runtime |
|----------|------------------|---------|
| Configuration | `.cursor/`, `.zcode/`, skills, rules | `pyproject.toml`, `.env`, `src/config/settings.py` |
| Orchestration | the workflows designed in the plan | the LangGraph runtime in `src/graph/` |
| Browser Automation | the Playwright MCP | the Playwright Python client in `src/applications/` |
| Security | rules and hooks | the middleware and the `src/security/` layer |
| Data Storage | not applicable | SQLite (dev) / PostgreSQL (deploy) + Chroma |
| The console | Vite, the React toolchain | static assets served as built, plus the operator's own browser session |

## 10. Directory Structure

```text
project-root/
├── src/
│   ├── api/             FastAPI routes, middleware, upload validation, the scope dependency
│   ├── applications/    the adapter contract, the Playwright adapters (fake ATS and assist),
│   │                    the form walker and plan, the ATS contracts, evidence, tracking
│   ├── auth/            identity, the two transports, sessions, CSRF, reset/verify delivery
│   ├── config/          settings and the fail-fast configuration checks
│   ├── core/            logging with PII masking, text helpers
│   ├── db/              the SQLAlchemy models and the session factory
│   ├── evaluation/      the metrics, the harness, the scenarios
│   ├── graph/           the LangGraph workflows, their states and their executors
│   ├── jobs/            the source adapters, the guarded HTTP client, normalization, dedup
│   ├── llm/             the provider clients, the fallback chain, embeddings, resilience, usage
│   ├── matching/        the eight scorers, the weights, the role classifier, the experience parser
│   ├── rag/             the Chroma vector store
│   ├── research/        the grounded research engine
│   ├── resume/          the parser, the profile, the tailoring, the in-place editor, the ATS
│   │                    analyzer, the renderer, the application profile
│   ├── runs/            the durable queue, the worker, the supervisor, the breakers
│   ├── security/        the allowlist, the policy, the permissions, the audit, the limits
│   └── storage/         the per-user path layout and its containment check
├── frontend/            the React operator console (WS-13/17) — its own package, its own toolchain
├── migrations/          the Alembic revisions
├── scripts/             the refresh, the worker, the evaluation runner, the live checks,
│                        the fake ATS, the board probe, the purge
├── tests/               the offline suite, the golden set, the fake-ATS pages
├── docs/
│   ├── PROJECT_PLAN.md  the intent, the phases, the reconciliation appendix
│   ├── ARCHITECTURE.md  this document
│   ├── SECURITY.md      the threat model and the control register
│   ├── RUNBOOK.md       how to run and maintain a deployment
│   ├── evaluations/     the measured evaluation reports
│   └── implementation/  the file-level roadmap, one document per workstream
├── .cursor/             the Cursor configuration (development-time)
├── .zcode/              the ZCode configuration (development-time)
├── pyproject.toml       the dependencies and the tool configuration
├── alembic.ini          the Alembic configuration
└── README.md            the operator's guide
```

## 11. Data Flow

1. **Resume upload**: file → validation (type, size, real-file check, the PDF's own magic number)
   → parser → `CandidateProfile` → validation against the document → persisted under the
   caller's id
2. **Job refresh**: boards → adapters (guarded HTTP) → normalization → the fake-job screen →
   deduplication (per-source identity, then the cross-source merge key) → persisted → embedded
   (new or changed text only, against a daily budget that counts cache misses)
3. **Job search**: profile + corpus → eight scorers + the semantic channel → the fixed-denominator
   blend → ranking → one `job_matches` row per survivor
4. **Tailoring**: profile + listing → requirements → tailored content → factuality validation →
   ATS analysis → the candidate's own document edited in place (or the from-scratch DOCX, where
   the original cannot be edited)
5. **Application**: job URL + candidate → allowlist → adapter → payload, validated against the
   ATS contract → approval request
6. **Decision**: a human approves or rejects, with an identity and a reason
7. **Submission**: the approval is enqueued on the durable queue (at most once) → the browser
   fills the form through the accessibility tree → the evidence is captured
8. **Verification**: the confirmation text is parsed, the evidence is checked, and the result is
   downgraded if an artifact is missing; an unprovable outcome is escalated, never claimed
9. **Tracking**: every status change is written as an event with its actor

## 12. Major Interfaces

- **FastAPI REST API** — 67 routes; the table is in the [README](../README.md) and is checked
  against the application's own OpenAPI schema by `tests/test_docs_accuracy.py`
- **Operator console** — the React app in `/frontend`, talking to the same API over HTTP with a
  session cookie (WS-13, WS-17)
- **Playwright client** — the runtime browser layer, in `src/applications/`
- **MCP tool calls** — development-time only (Cursor, ZCode)
- **CLI tools** — `scripts/refresh_jobs.py`, `scripts/run_worker.py`, `scripts/run_eval.py`,
  `scripts/serve_fake_ats.py`, `scripts/probe_board.py`, `scripts/purge_expired.py`,
  `scripts/import_visa_sponsors.py`, `scripts/verify_sources.py`, and the `scripts/verify_ws*.py`
  live checks

## 13. Status Legend and Current Status

- **Implemented**: exists, is tested, and is wired into a live path
- **Planned**: specified, not yet built
- **Experimental**: built but not fully supported (the `openai-compatible` LLM provider)
- **Out of scope**: deliberately not built (LinkedIn retrieval, CAPTCHA bypass, `AUTO_SUBMIT`)

**Current Status (2026-11-16, through WS-32)**

- **Implemented**: the FastAPI service (67 routes), the identity API and the per-user data
  isolation, the database schema and its 17 revisions, the LangGraph job and application
  workflows, the durable queue and worker, the job adapters and the board registry, the
  eight-scorer matching engine, the resume parser including PDF, the tailoring and factuality
  validator, the in-place résumé editor, the ATS analyzer and DOCX renderer, the research
  engine, the LLM client with the provider fallback chain, the bring-your-own-key credential
  store, the browser automation runtime with the assist-mode pilot, the security layer, the
  application tracking, the retention and purge, the operator console, and the evaluation
  harness
- **Planned**: the **submit half of the real-ATS path** — the pilot has filled a live Greenhouse
  form and never sent one, so no application has been submitted to a real board; URL-based web
  research behind the SSRF controls; malware scanning of uploads; per-tenant encryption keys and
  encryption at rest for the shared stores; an SMTP provider for the account tokens (the flow
  works and delivers to a mailbox file)
- **Experimental**: the `openai-compatible` LLM provider (verified against a mock transport
  only); the WS-30 fallback links (implemented, inactive until vendor keys are added, and the
  chain's second link's model id is unconfirmed against the vendor)
- **Out of scope**: LinkedIn retrieval, CAPTCHA/MFA bypass of any kind, `AUTO_SUBMIT`

## 14. Autonomous Submission: Confirmation and Runtime Capabilities

This project plan is explicitly intended to evolve from discovery and matching into a system
that can autonomously submit job applications under controlled conditions. The documented
Phase 2 work (see `docs/PROJECT_PLAN.md`) outlines the expected runtime capabilities required
to reach that goal.

Runtime components required for autonomous submission

- `ApplicationAdapter` implementations: API-backed adapters (Greenhouse, Lever, Ashby) and a
  Playwright-backed `GenericBrowserAdapter` for sites without APIs.
- `LangGraph` graphs that orchestrate prepare → present → approve → submit → verify with
  persisted evidence.
- Playwright Python client as the runtime browser automation layer; Cursor Playwright MCP
  remains development-only.
- A permission registry that maps which adapters/tools can `read`, `prepare`, `submit`, and
  `verify`.
- Evidence capture: screenshots, navigation traces, and confirmation parsing for
  non-repudiation.

Does the current project plan match the goal?

Yes — `docs/PROJECT_PLAN.md` and the architecture notes already target an autonomous end-to-end
flow. The added Phase 2 section explicitly prioritizes vendor APIs first, deterministic HTTP
where possible, and Playwright-based automation as a last resort; it also enforces
human-approval-by-default, evidence-based verification, and a staged adapter-first
implementation approach.

Next steps to implement runtime submission (high-level):

1. Implement `ApplicationAdapter` contract and the first API adapters (Greenhouse, Lever).
2. Implement `GenericBrowserAdapter` with Playwright client and fake-ATS tests.
3. Build LangGraph workflows with approval/verification nodes and evidence persistence.
4. Implement the MCP/permission registry and domain allowlist enforcement in runtime code.
5. Harden security controls per `docs/SECURITY.md` before enabling live autonomous submissions.

**Status (2026-11-16, through WS-32).** Steps 1, 3, 4 and 5 are done: the adapter contract, the
two-phase workflow with persisted evidence, the permission registry, the allowlist, the security
preconditions in `docs/SECURITY.md` §14.1, and the runtime attack-surface bounds of WS-12 and
WS-15. Step 2 is done as the **assist-mode pilot** (`src/applications/assist_adapter.py`), which
fills a real board's form through the same accessibility-tree walker and then stops — it never
clicks submit. There is no `GenericBrowserAdapter` that submits on its own, and no application
has been sent to a real board.

The Greenhouse and Lever adapters exist and are **read-only in practice**: each declares the
capabilities it exercises, and `submit()` raises `PermissionError` because the registry does not
grant it (WS-32). They are not placeholders returning a false success — they fail loudly.

Two WS-32 findings belong in the architecture record, because both are properties of real ATS
pages rather than of this codebase:

- **The ATS does not validate its own required fields.** Greenhouse's published contract is a
  specification for *us*; the board accepts a payload missing a required answer. The payload is
  therefore validated at the adapter, fail-closed, before anything is enqueued.
- **A submission whose outcome is unprovable is escalated, not assumed.** A crash between the
  board's acceptance and this system's bookkeeping leaves an uncertain attempt; the durable
  attempt marker makes it at-most-once and raises `submission.uncertain` for a human, because
  reporting it either way would be a guess.

---

# Historical record — the phase footprints (2026-10-11)

> These sections were written as each phase landed. They are kept as the record of the
> plan-vs-actual sequence. Their "Status" lines are dated: the roadmap in
> `docs/implementation/` is the current truth.

## 15. Phase 3 — Job Source Abstraction (Footprints)

### 3.1 JobSource Protocol
- Decision: Abstract `JobSource` with `search()` and `get_job()` methods.
- File: `src/jobs/contracts.py`
- Rationale: Separates discovery from submission; allows adapter-based expansion.

### 3.2 JobListing Normalization
- Decision: Canonical `JobListing` model for all sources.
- File: `src/jobs/contracts.py`
- Fields: id, source, title, company, description, location, skills, salary, etc.

### 3.3 First Adapter (LinkedIn)
- Decision: Placeholder `LinkedInAdapter` implementing `JobSource`.
- File: `src/jobs/linkedin_adapter.py`
- Status: Contract-compliant; real HTTP/API integration pending. **Still true — and it stays
  pending: LinkedIn has no public board API, so the adapter remains unregistered.**

### 3.4 Tests
- File: `tests/test_jobs.py`
- Status: Basic adapter and model tests created. **Superseded: the real adapters (Greenhouse,
  Lever, Ashby, Remotive) and their recorded-JSON fixtures were added in WS-02.**

## 16. Phase 4 — Normalization + Deduplication (Footprints)

### 4.1 JobSource Abstraction
- File: `src/jobs/contracts.py`
- Protocol: `JobSource` with `search()` and `get_job()`.

### 4.2 JobListing Normalization
- File: `src/jobs/contracts.py`
- Canonical model for all sources.

### 4.3 Deduplication
- File: `src/jobs/deduplicate.py`
- Deduplicates by `(source, source_job_id)` or URL.

### 4.4 DB Persistence
- File: `src/db/jobs.py`
- `JobDB` SQLAlchemy model for normalized listings.

### 4.5 First Adapter
- File: `src/jobs/linkedin_adapter.py`
- Placeholder adapter implementing `JobSource`.

### 4.6 Tests
- File: `tests/test_deduplicate.py`
- Status: Dedup logic tested; adapter async framework pending. **Superseded: the real dedup and
  the `JobDB` upsert are both wired into the live search path (WS-02, WS-04).**

## 17. Phase 5 — Matching Engine (Footprints)

### 5.1 Matching Contracts
- File: `src/matching/contracts.py`
- Model: `JobMatchResult` with scores, missing/matched requirements, explanation.

### 5.2 Hybrid Engine
- File: `src/matching/engine.py`
- Function: `calculate_match()` — deterministic-first with configurable weights.
- Components: semantic, skill, experience, seniority, location, preference scores.

### 5.3 Tests
- File: `tests/test_matching.py`
- Status: Basic match and explanation tests created. **Superseded: all six scorers are real and
  read from data (WS-03).**

## 18. Phase 6 — Full End-to-End LangGraph Workflow (Footprints)

### 6.1 Full Pipeline Graph
- File: `src/graph/job_workflow.py`
- Nodes: search → normalize → deduplicate → match → rank → END
- Uses `JobSource` (Phase 3) and `ApplicationWorkflowState` (Phase 2).

### 6.2 Integration
- Combines Phase 3 (job source), Phase 4 (dedup), Phase 5 (matching) into single graph.
- Placeholder nodes for search/normalize/deduplicate/match/rank.
- Ready for real adapter and DB integration in future phases. **Superseded: the nodes are real
  and the workflow is executed by `run_job_search`, with report, stats and degradation
  reporting (WS-04).**

### 6.3 Tests
- File: `tests/test_workflow_e2e.py`
- Status: Graph builds successfully; full execution pending adapter/DB wiring. **Superseded:
  the end-to-end execution is tested, and M1 was verified live over HTTP on 2026-10-11.**

## 19. Phase 7 — Research + RAG (Footprints)

### 7.1 RAG Module
- File: `src/rag/chroma_store.py`
- Note: Chroma DB selected per user preference for vector storage.
- Status: Placeholder store; full `chromadb` integration pending package setup. **Superseded:
  the real Chroma store landed in WS-03, with a content-hash cache and a drift guard that
  refuses to mix two embedding spaces.**

### 7.2 Research Engine
- File: `src/research/engine.py`
- Functions: `research_company()`, `research_job_description()`. **Superseded: the grounded
  research engine landed in WS-05 as `research_job()` and `research_company()`, with a
  deterministic grounding and injection filter. URL fetching is still deferred, behind the
  SSRF controls.**
