# Autonomous AI Job Application Agent - Architecture Document

Status: **reconciled 2026-10-21 (WS-11)** · Supersedes the status sections written on 2026-09-13

> This document describes the system that exists. The file-level plan that produced it is
> [`docs/implementation/00-OVERVIEW.md`](implementation/00-OVERVIEW.md); the intent it was built
> from is [`docs/PROJECT_PLAN.md`](PROJECT_PLAN.md); the security model is
> [`docs/SECURITY.md`](SECURITY.md).
>
> The sections at the end (§14–§18) are **historical records** — the Phase footprints written
> as the work landed. They are kept because they are the only record of the plan-vs-actual
> sequence, but their "Status" lines are dated and are superseded by §13.

## 1. System Overview

The Autonomous AI Job Application Agent is a production-oriented system that:

- Accepts candidate resumes and parses them into a validated `CandidateProfile`
- Searches and normalizes job listings from multiple public job-board APIs
- Matches jobs against the candidate profile using hybrid scoring
- Ranks jobs and explains each match score component by component
- Tailors resumes without inventing facts, and validates every claim deterministically
- Navigates application websites with browser automation when necessary
- Submits applications with human approval, and verifies the outcome with stored evidence

## 2. System Architecture

The system is a **modular monolith** (plan §47): one Python package, one process, one database.
The separation that matters is not between services but between **development-time components**
(Cursor, ZCode, MCP servers, hooks, skills) and **runtime components** (the application that
actually runs).

### 2.1 Component status

| Component | State | Where it lives | Verified by |
|---|---|---|---|
| FastAPI service | **Implemented** | `src/main.py`, `src/api/routes/` | `tests/test_health.py`, `tests/test_resumes_api.py` |
| REST API (17 routes) | **Implemented** | `src/api/routes/` | `tests/test_docs_accuracy.py` (the route table is checked against the app) |
| API middleware: rate limit, body cap, concurrency gate, response headers | **Implemented** | `src/api/middleware.py`, `src/security/limits.py` | `tests/test_ws12_hardening.py` |
| Database schema and migrations | **Implemented** | `src/db/`, `migrations/versions/` (5 revisions) | `tests/test_migrations.py` |
| LangGraph job workflow | **Implemented** | `src/graph/job_workflow.py` | `tests/test_job_workflow.py` |
| LangGraph application workflow | **Implemented** | `src/graph/application_workflow.py` | `tests/test_application_workflow.py` |
| Job source adapters (Greenhouse, Lever, Ashby, Remotive) | **Implemented** | `src/jobs/*_adapter.py` | `tests/test_jobs.py` |
| Normalization and deduplication | **Implemented** | `src/jobs/normalize.py`, `src/jobs/deduplicate.py` | `tests/test_deduplicate.py` |
| Matching engine (six scorers) | **Implemented** | `src/matching/engine.py` | `tests/test_matching.py` |
| Vector store and embeddings | **Implemented** | `src/rag/chroma_store.py`, `src/llm/embeddings.py` | `tests/test_chroma_store.py`, `tests/test_embeddings.py` |
| Resume parsing and profile validation | **Implemented** | `src/resume/parser.py`, `src/resume/profile.py` | `tests/test_resume_parser.py` |
| Resume tailoring and factuality validation | **Implemented** | `src/resume/tailor.py` | `tests/test_tailor.py` |
| ATS analysis and DOCX rendering | **Implemented** | `src/resume/ats.py`, `src/resume/render.py` | `tests/test_ats.py`, `tests/test_render.py` |
| Grounded research engine | **Implemented** | `src/research/engine.py` | `tests/test_research.py` |
| LLM client with timeout, retries, pacing and usage accounting | **Implemented** | `src/llm/client.py`, `src/llm/resilience.py` | `tests/test_llm_client.py`, `tests/test_llm_resilience.py` |
| Browser automation runtime (Playwright Python client) | **Implemented** | `src/applications/fake_ats_adapter.py`, `src/applications/form.py` | `tests/test_browser_variants.py`, `tests/test_isolation.py` |
| Security layer: allowlist, policy, permissions, audit, injection, limits, paths | **Implemented** | `src/security/` | `tests/test_allowlist.py`, `tests/test_policy.py`, `tests/test_permissions.py`, `tests/test_audit.py`, `tests/test_injection.py`, `tests/test_page_guards.py`, `tests/test_ws12_hardening.py` |
| Application tracking and lifecycle | **Implemented** | `src/applications/tracking.py`, `src/db/applications.py` | `tests/test_tracking.py`, `tests/test_tracking_api.py` |
| Evaluation harness and measured baseline | **Implemented** | `src/evaluation/`, `scripts/run_eval.py` | `tests/test_eval_runner.py`, `tests/test_eval_metrics.py` |
| **Real-ATS (live job site) adapter** | **Planned** | the M5 pilot | — |
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
  → src/matching/engine.py             six deterministic scorers
  → src/rag/chroma_store.py            the semantic channel
  → src/db/matches.py                  one job_matches row per result
  → src/security/audit.py              an audit event
```

The daily refresh is the same pipeline with the board adapters in front of it
(`src/graph/job_workflow.py`: search → normalize → deduplicate → persist → match → rank). A
search never fetches a board.

**Flow 3 — application (prepare → approve → submit → verify)**

```text
POST /api/applications/prepare
  → src/security/allowlist.py          the target host is checked
  → src/security/permissions.py        the adapter is selected from the registry
  → src/graph/nodes.py (prepare)       the payload is built
  → src/db/approval.py                 an approval_requests row is written
  ── a human decides, in a separate call ──
POST /api/applications/{id}/approve
  → src/db/approval.py                 the decision, with an identity and a reason
  → src/security/policy.py             only an approved record may execute
  → src/graph/application_workflow.py  prepare → approval → submit → verify
  → src/applications/fake_ats_adapter.py  the browser fills the form
  → src/applications/evidence.py       screenshot, action trace, Playwright trace
  → src/db/applications.py             the tracked application and its events
```

### 3.2 Runtime components

- **FastAPI application** (`src/main.py`) — the REST surface, the middleware stack, the lifespan
- **LangGraph runtime** (`src/graph/`) — two workflows with explicit state, branching and gates
- **Job adapters** (`src/jobs/`) — Greenhouse, Lever, Ashby, Remotive behind a guarded HTTP client
- **Matching engine** (`src/matching/`) — six deterministic scorers over stored data
- **Vector store** (`src/rag/chroma_store.py`) — Chroma, with the model identity persisted
- **Embedding providers** (`src/llm/embeddings.py`) — local EmbeddingGemma-2 (default) or Gemini
- **LLM client** (`src/llm/`) — Gemini (supported) and an openai-compatible path (experimental)
- **Browser automation** (`src/applications/`) — the Playwright Python client and the form walker
- **Security layer** (`src/security/`) — allowlist, policy, permissions, audit, limits, guards
- **Database** (`src/db/`) — SQLAlchemy models, Alembic migrations, SQLite (dev) or PostgreSQL

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

- **Runtime**: the Playwright **Python** client (`src/applications/fake_ats_adapter.py`), driving
  the form through the **accessibility tree** (`src/applications/form.py`): the field map, the
  three question classes, and the answer rule
- **Semantic locators only**: a field is found by its label or its role. The only CSS in the
  module is the documented file-input exception and the validation-error sweep
- **Session isolation (SEC-07)**: every run gets an explicit, fresh browser context, so no
  cookie or storage survives it
- **Unknown questions stop the run**: a question the candidate's evidence does not cover ends the
  flow with `needs_human`; the agent never guesses (plan §24)
- **Challenges stop the run**: a CAPTCHA or an MFA prompt ends the flow with
  `blocked_human_review`; the agent never tries to solve one
- **Evidence is mandatory**: a screenshot, an ordered action trace and the Playwright trace
  archive. A submission that cannot produce them is downgraded, never reported as a success
- **Development-time**: the Playwright MCP is for inspection and validation only. It is not the
  runtime browser layer

## 7. Data Architecture

The primary store is SQLite in development and PostgreSQL in deployment. Nine tables, each
created by its own migration so a rollback is per feature:

| Table | Model | Created by | Holds |
|---|---|---|---|
| `jobs` | `src/db/jobs.py` | `171f645abf1a` (initial) | the normalized listings |
| `application_evidence` | `src/db/evidence.py` | `171f645abf1a` (initial) | the submission evidence |
| `candidate_profiles` | `src/db/profiles.py` | `b8e2c94d1f57` (WS-04) | the parsed profile, as JSON |
| `job_matches` | `src/db/matches.py` | `b8e2c94d1f57` (WS-04) | the scores and the explanation |
| `tailored_resumes` | `src/db/tailored.py` | `c9a4f1e2d3b7` (WS-05) | the tailored content, the factuality report, the ATS report, the DOCX path |
| `approval_requests` | `src/db/approval.py` | `d4e5f6a7b8c9` (WS-06) | the prepared payload and the human decision |
| `audit_events` | `src/db/audit.py` | `d4e5f6a7b8c9` (WS-06) | the append-only trail |
| `applications` | `src/db/applications.py` | `e5f6a7b8c9d0` (WS-07) | the tracked application |
| `application_events` | `src/db/applications.py` | `e5f6a7b8c9d0` (WS-07) | every status change, with its actor |

The vector store (Chroma, under `data/chroma`) holds the embeddings and the **model identity**
that produced them, so two embedding spaces can never be mixed.

## 8. Security Boundaries

- **Web Content**: treated as untrusted data; never as instructions
- **Prompt Injection**: a nonce-fenced untrusted block plus a deterministic injection filter,
  enforced in code rather than by model whim
- **Secrets**: isolated in environment variables; never in prompts, logs or traces
- **Domain Allowlists**: an exact-match allowlist restricts fetch and browser navigation
- **Least Privilege**: the permission registry maps which adapter may `read`, `prepare`, `submit`
  and `verify`
- **Audit Logs**: every external action is recorded, without secrets or PII
- **Human Approval**: a recorded decision is required before an irreversible submission
- **Bounds**: the rate limit, the body cap, the concurrency gate and the corpus/embedding bounds
  decide how much work an untrusted caller can cause

## 9. Development-time vs Runtime Components

| Category | Development-time | Runtime |
|----------|------------------|---------|
| Configuration | `.cursor/`, `.zcode/`, skills, rules | `pyproject.toml`, `.env`, `src/config/settings.py` |
| Orchestration | the workflows designed in the plan | the LangGraph runtime in `src/graph/` |
| Browser Automation | the Playwright MCP | the Playwright Python client in `src/applications/` |
| Security | rules and hooks | the middleware and the `src/security/` layer |
| Data Storage | not applicable | SQLite (dev) / PostgreSQL (deploy) + Chroma |

## 10. Directory Structure

```text
project-root/
├── src/
│   ├── api/             FastAPI routes, middleware, upload validation
│   ├── applications/    the adapter contract, the Playwright adapter, forms, evidence, tracking
│   ├── config/          settings and the fail-fast configuration checks
│   ├── core/            logging with PII masking, text helpers
│   ├── db/              the SQLAlchemy models and the session factory
│   ├── evaluation/      the metrics, the harness, the scenarios
│   ├── graph/           the LangGraph workflows, their states and their executors
│   ├── jobs/            the source adapters, the guarded HTTP client, normalization, dedup
│   ├── llm/             the provider clients, the embedding providers, the resilience layer
│   ├── matching/        the six scorers, the weights, the experience parser
│   ├── rag/             the Chroma vector store
│   ├── research/        the grounded research engine
│   ├── resume/          the parser, the profile, the tailoring, the ATS analyzer, the renderer
│   └── security/        the allowlist, the policy, the permissions, the audit, the limits
├── migrations/          the Alembic revisions
├── scripts/             the refresh, the evaluation runner, the live checks, the fake ATS
├── tests/               the offline suite, the golden set, the fake-ATS pages
├── docs/
│   ├── PROJECT_PLAN.md  the intent, the phases, the reconciliation appendix
│   ├── ARCHITECTURE.md  this document
│   ├── SECURITY.md      the threat model and the control register
│   ├── evaluations/     the measured evaluation reports
│   └── implementation/  the file-level roadmap, one document per workstream
├── .cursor/             the Cursor configuration (development-time)
├── .zcode/              the ZCode configuration (development-time)
├── pyproject.toml       the dependencies and the tool configuration
├── alembic.ini          the Alembic configuration
└── README.md            the operator's guide
```

## 11. Data Flow

1. **Resume upload**: file → validation → parser → `CandidateProfile` → validation against the
   document → persisted
2. **Job refresh**: boards → adapters (guarded HTTP) → normalization → deduplication → persisted →
   embedded (new or changed text only)
3. **Job search**: profile + corpus → six scorers + the semantic channel → ranking → one
   `job_matches` row per result
4. **Tailoring**: profile + listing → requirements → tailored content → factuality validation →
   ATS analysis → DOCX
5. **Application**: job URL + candidate → allowlist → adapter → payload → approval request
6. **Decision**: a human approves or rejects, with an identity and a reason
7. **Submission**: the browser fills the form through the accessibility tree → the evidence is
   captured
8. **Verification**: the confirmation text is parsed, the evidence is checked, and the result is
   downgraded if an artifact is missing
9. **Tracking**: every status change is written as an event with its actor

## 12. Major Interfaces

- **FastAPI REST API** — 17 routes; the table is in the [README](../README.md) and is checked
  against the running application by `tests/test_docs_accuracy.py`
- **Playwright client** — the runtime browser layer, in `src/applications/`
- **MCP tool calls** — development-time only (Cursor, ZCode)
- **CLI tools** — `scripts/refresh_jobs.py`, `scripts/run_eval.py`, `scripts/serve_fake_ats.py`,
  and the `scripts/verify_ws*.py` live checks

## 13. Status Legend and Current Status

- **Implemented**: exists, is tested, and is wired into a live path
- **Planned**: specified, not yet built
- **Experimental**: built but not fully supported (the `openai-compatible` LLM provider)
- **Out of scope**: deliberately not built (LinkedIn retrieval, CAPTCHA bypass, `AUTO_SUBMIT`)

**Current Status (2026-10-21)**

- **Implemented**: the FastAPI service (17 routes), the database schema and its migrations, the
  LangGraph job and application workflows, the job adapters, the matching engine, the resume
  parser, the tailoring and factuality validator, the ATS analyzer and DOCX renderer, the
  research engine, the LLM client, the browser automation runtime, the security layer, the
  application tracking, and the evaluation harness
- **Planned**: a real-ATS adapter and the live pilot (M5); URL-based web research behind the
  SSRF controls; data retention, malware scanning and API authentication
- **Experimental**: the `openai-compatible` LLM provider (verified against a mock transport
  only)
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

**Status (2026-10-21).** Steps 1, 3, 4 and 5 are done: the adapter contract, the two-phase
workflow with persisted evidence, the permission registry, the allowlist, the security
preconditions in `docs/SECURITY.md` §14.1, and the runtime attack-surface bounds of WS-12. Step
2 is done for the **fake ATS** only (`src/applications/fake_ats_adapter.py`); the
`GenericBrowserAdapter` for real sites is the M5 pilot and is not built. The Greenhouse and
Lever adapters exist but **raise** `PermissionError` when asked to submit — they are
placeholders that fail loudly rather than pretending to succeed.

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
