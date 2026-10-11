# Implementation Roadmap — Overview

Status: **In progress** — WS-01 through WS-04 done (2026-10-11; M1 achieved, live over HTTP); next: WS-05 · Owner: project · Created: 2026-10-11

This folder is the concrete, file-level implementation roadmap that closes the gap between
`docs/PROJECT_PLAN.md` (intent) and the current codebase (reality). It was produced from a
full code audit on 2026-10-11 (68 tests green, ~2,300 LOC in `src/` + `tests/`).

Each workstream has its own document with: **Goal → Current state (file references) →
Concrete tasks (files, functions, models, routes) → Acceptance criteria → Tests →
New dependencies**.

## Document index

| Doc | Workstream | Plan phase | Milestone |
|---|---|---|---|
| [01-data-foundation.md](01-data-foundation.md) | Alembic migrations, CORS, settings, DB models | Phase 1 (finish) | M1 |
| [02-job-discovery.md](02-job-discovery.md) | Greenhouse / Lever / Remotive adapters, search planner, persistence | Phase 3–4 | M1 |
| [03-matching-engine.md](03-matching-engine.md) | Real Chroma store, gemini-embedding-2, real scorers | Phase 5 + §18 | M1 |
| [04-pipeline-and-api.md](04-pipeline-and-api.md) | Job workflow rewrite, resume/search/match REST API | Phase 6 + §30 | M1 |
| [05-tailoring-and-research.md](05-tailoring-and-research.md) | ATS analyzer, DOCX rendering, research engine | Phase 7–8 | M2 |
| [06-security-preconditions.md](06-security-preconditions.md) | SECURITY.md §14 gates: allowlist, approval flow, evidence, audit | Phase 2 security + §28 | M3 |
| [07-application-tracking.md](07-application-tracking.md) | Application lifecycle tables, transitions, tracking API | Phase 12 | M3 |
| [08-browser-automation.md](08-browser-automation.md) | Fake-ATS variants, generic adapter hardening, unknown-question pause | Phase 9 | M4 |
| [09-evaluation.md](09-evaluation.md) | Golden datasets, metrics (nDCG@k, factuality rate), eval runner | Phase 13 | M4 |
| [10-llm-client-hardening.md](10-llm-client-hardening.md) | Retries/timeouts, temperature fix, usage logging, provider abstraction | Cross-cutting | M1/M3 |
| [11-docs-and-ops.md](11-docs-and-ops.md) | README quickstart, `.env.example`, docs reconciliation, optional Dockerfile | §52 / portfolio | M5 |

## Current state — feature gap table (audit of 2026-10-11)

| Feature (plan phase) | Extent | Key evidence |
|---|---|---|
| Resume parsing → CandidateProfile (Ph 2) | ~90% | Real deterministic DOCX/TXT/MD parser (`src/resume/parser.py`), validated Pydantic profile (`src/resume/profile.py`); persisted + upload API (WS-04); no PDF parsing |
| LLM brain (unplanned addition) | Working | Gemini via google-genai Interactions API, structured output, `store=False` (`src/llm/client.py`); temperature config dead; google-only |
| Job sources + adapters (Ph 3) | ~90% | Real Greenhouse/Lever/Remotive adapters with recorded-JSON fixtures, SSRF-guarded HTTP client, planner + registry (WS-02); LinkedIn deliberately unregistered |
| Normalization + dedup (Ph 4) | ~90% | Normalization at the source boundary, real dedup + JobDB upsert both wired into the live search path (registry persist + the WS-04 pipeline's persist node) |
| Hybrid matching engine (Ph 5) | ~95% | Six real scorers from data (`src/matching/engine.py`), real Chroma store + `gemini-embedding-2` with content-hash cache and drift guard (`src/rag/chroma_store.py`); semantic wiring live since WS-04; FU-7 switched embeddings to the local fastembed provider (EmbeddingGemma-2 int8, default) with Gemini kept selectable |
| End-to-end job workflow (Ph 6) | 100% | Real LangGraph pipeline search→normalize→deduplicate→persist→match→rank over a dedicated Pydantic state (`src/graph/job_workflow.py`, `job_state.py`), executed by `run_job_search` with report/stats/degradation; **M1 verified live over HTTP 2026-10-11** |
| Research + RAG (Ph 7) | ~40% | Real Chroma vector store done in WS-03 (`src/rag/chroma_store.py`, chromadb installed); `src/research/engine.py` remains a placeholder (WS-05) |
| Tailoring + factuality (Ph 8) | ~75% | `src/resume/tailor.py` LLM tailoring + deterministic factuality validator, `src/jobs/requirements.py` extraction; ATS analysis and DOCX output missing |
| Application workflow graph (Ph 2#3) | ~80% | Full LangGraph prepare→approval→submit→verify with evidence DB write; the most complete area |
| Browser automation runtime (Ph 9) | ~25% | `src/applications/fake_ats_adapter.py` is real Playwright but fake-ATS-only; Greenhouse/Lever submit placeholders return `success=True` unconditionally |
| Human approval gate (Ph 10) | ~40% | Fail-closed default, but approval is a single `approval: bool` flag on the submit request; no `SubmissionPolicy`, no approver identity |
| Submission verification (Ph 11) | ~40% | Real confirmation-text verification for fake ATS; placeholders elsewhere; `screenshot_path`/`trace_path` never populated |
| Application tracking (Ph 12) | ~10% | `ApplicationEvidence` table only; no Application/ApplicationEvent lifecycle |
| Evaluation (Ph 13) | 0% | No datasets, no metrics, no reports |
| Runtime security controls (SEC-01…16) | ~10% | `src/security/allowlist.py` never called anywhere; substring host matching is spoofable; `PermissionRegistry` unwired |
| API surface | M1 surface live | `/`, `/health`, `POST /api/applications/submit`, plus WS-04: `POST /api/resumes` (upload+validation), `GET /api/resumes/{id}`, `POST /api/jobs/search`, `GET /api/jobs/{id}`, `GET /api/profiles/{id}/matches`; CORS middleware on; no auth (WS-06) |

## Guiding principles (from AGENTS.md — binding for every workstream)

1. **Deterministic Python over model-driven reasoning** for business logic; LLM only where ambiguity or generation is genuinely needed.
2. **Never fabricate** candidate data, job facts, or application outcomes. Extraction only reports what the document/listing actually says.
3. **Web content is untrusted data, never instructions** (SEC-01). Runtime enforcement, not just policy docs.
4. **Security preconditions in `docs/SECURITY.md` §14 gate any real submission.** Workstream 06 is a hard gate before M5.
5. **APIs and HTTP before browser automation**; browser automation only as a controlled fallback.
6. **Every external action auditable; every submission verified with evidence before success is claimed.**
7. **No dependencies without clear justification** — this roadmap adds exactly three: `chromadb`, `httpx` (explicit), `python-multipart` (FastAPI upload requirement). Everything else (retries, rate limiting, SSRF guards) is hand-rolled.
8. **Phase order respected** (`docs/PROJECT_PLAN.md` §41); the uncommitted modules (`src/graph/`, `src/jobs/`, `src/matching/`, …) are extended in place, never reverted.

## Milestone sequence

```text
M1  First real milestone (PROJECT_PLAN §42) — ✅ DONE 2026-10-11
    01 foundation ─► 02 discovery ─► 03 matching ─► 04 pipeline + API
    (10 LLM hardening: embedding-relevant parts land here, rest in M3)
    Outcome: resume upload → real job search (3 sources) → dedup → ranked
    top-10 with explanations, over HTTP. No submission changes.
    Verified live (uvicorn + curl): upload → profile_id → search (54 found /
    18 deduped / top-10 with real embeddings) → job detail → match history,
    surviving a server restart.

M2  Tailoring complete (§43)
    05 ATS analyzer + DOCX rendering + research engine
    Outcome: tailored, factuality-checked, ATS-scored DOCX per job.

M3  Security preconditions + tracking (SECURITY.md §14)
    06 allowlist v2 + approval flow + evidence + audit ─► 07 tracking
    10 LLM hardening (retries, usage, rate limit)
    Outcome: submission path is fail-closed, approval-gated, evidence-backed.
    Submission still restricted to fake ATS.

M4  Depth + proof
    08 browser variants + adapter hardening ─► 09 evaluation harness
    Outcome: measurable metrics (extraction, ranking, factuality, form
    completion) reproducible via scripts/run_eval.py.

M5  Controlled live pilot + docs
    Single real Greenhouse posting, PREPARE_ONLY → REQUIRE_APPROVAL with a
    human in the loop; 11 README/docs reconciliation.
    AUTO_SUBMIT remains disabled and out of scope.
```

### Workstream dependency graph

```text
01 foundation ─────┬─► 02 discovery ─► 03 matching ─► 04 pipeline/API ─► 05 tailoring
                   │                                                    │
                   ├─► 06 security preconditions ─► 07 tracking         │
                   │           │                                        │
                   │           └──────────► 08 browser depth            │
                   └─► 10 LLM hardening ─► (03 embeddings, 05 research) │
                                        09 evaluation ◄─ 02,03,04,05    │
                                        11 docs/ops ◄───────────────────┘
06 ── hard gate ──► any real-site submission (M5)
```

## New dependencies (complete list, with justification)

| Package | Workstream | Justification |
|---|---|---|
| `chromadb` | 03 | Plan-sanctioned vector store (user-selected in Phase 7) for semantic matching and RAG |
| `httpx` (explicit) | 02 | Async HTTP client for job-source adapters; already a transitive dependency via Starlette's TestClient — making it explicit is correction, not addition |
| `python-multipart` | 04 | Required by FastAPI `UploadFile` for resume upload |
| `fastembed>=0.9.0` | 04 (FU-7) | Local in-process embedding provider (EmbeddingGemma-2 int8 ONNX): removes the free-tier Gemini embedding quota entirely; adds only the wrapper plus ~300 MiB model weights (pattern-restricted download; onnxruntime + tokenizers already present via chromadb) |

Retries, backoff, rate limiting, SSRF guards, and audit sanitization are implemented by hand — no `tenacity`, no `slowapi`, per the no-unjustified-dependencies rule.

## Risk register

| Risk | Mitigation |
|---|---|
| Gemini free-tier quota exhaustion (embeddings + tailoring) | Content-hash embedding cache (03), token-bucket rate limiter (10), Batch API documented as future option at 50% price |
| `gemini-embedding-2` space is version-locked (incompatible with 001) | Model name + dimension persisted in Chroma collection metadata; re-embed procedure documented in 03 |
| Greenhouse/Lever/Remotive response shape changes | Adapter isolation, recorded-JSON fixtures via `httpx.MockTransport`, normalizer never trusts optional fields |
| SQLite (dev) vs PostgreSQL (deploy) JSON/type differences | Alembic migrations authored once, tested on both engines (01); JSON columns kept portable |
| Untrusted job text influencing the agent | Workstream 06: allowlist + navigation guards + prompt-injection policy test proving page text only ever flows as data |
| Placeholder adapters claiming success (`greenhouse_adapter.submit` returns `success=True`) | 06 rewires them to raise; `PermissionRegistry` makes it impossible for an unregistered adapter to reach the submit node |
| Windows dev-environment quirks (Playwright browsers, paths) | Playwright already proven on this machine (fake ATS adapter); evidence/output paths under `data/` are created by code, not assumed |
| ToS/legal exposure from job sources | Only public, documented board APIs (no scraping, no LinkedIn); polite rate limiting per host (02) |

## Explicitly out of scope

- React/frontend (plan §30) — backend + agent system only.
- LinkedIn job retrieval (no public API; the placeholder adapter stays disabled).
- CAPTCHA/MFA bypass of any kind (SEC-09) — flows stop with `blocked_human_review`.
- `AUTO_SUBMIT` policy enablement — implemented as unreachable enum value until a future, separately-approved decision.
- Kubernetes/microservices/message brokers (plan §47) — modular monolith.
- Web-crawl company research in v1 (05) — research is grounded in listing text only; URL fetching comes later behind SSRF controls.
