# WS-11 · Docs, Ops, and Reconciliation

Status: **Not started** · Milestone: **M5** · Depends on: all workstreams (documents their outcomes) · Blocks: nothing

## Goal

Bring the project's public face in line with reality: a README that gets a new machine running
in five minutes, env docs for every new setting, and the three planning documents reconciled
with what was actually built — including the deviations already identified in the plan-vs-actual
audit.

## Current state

- `README.md` — exists but predates the parser/tailoring/graph work; no quickstart reflecting the current API.
- `.env.example` — documents zai/openai providers that don't exist yet (fixed by [10](10-llm-client-hardening.md)), and lacks every new setting from [01](01-data-foundation.md) (sources, embedding, policy, evidence dirs).
- `docs/ARCHITECTURE.md` — **status sections are stale**: "Current Status" (§14) still labels FastAPI service, LangGraph orchestration, matching engine, and application submission workflow as *PLANNED* while they exist and are tested; the "Implemented Components" list predates `src/` entirely.
- `docs/PROJECT_PLAN.md` — has completion footprints for Phases 2–8 appended ad hoc, but no reconciliation of the known plan-vs-actual deviations (dict-based profile → now resolved by Pydantic `CandidateProfile`; unplanned LLM client; Phase 8 completed before 3–7; missing ATS/eval stages).
- `docs/SECURITY.md` — register updated by [06](06-security-preconditions.md); only the deployment-hardening rows remain open.
- No Dockerfile / compose (acceptable — modular monolith, plan §47); optional here.

## Concrete tasks

### 1. README rewrite

- What it is (one paragraph), architecture snapshot (diagram mirroring plan §50's flow with actual module paths).
- **Quickstart**: `py -3.13 -m venv env` / activate → `pip install -e .` (or equivalent) → `playwright install chromium` → copy `.env.example` to `.env` and set `LLM_*` → `alembic upgrade head` → `uvicorn src.main:app --reload` → exercise `POST /api/resumes`, `POST /api/jobs/search`, `POST /api/tailor`, fake-ATS demo; run tests (`pytest -q`); run evals (`scripts/run_eval.py`).
- Security posture summary (approval default, allowlist, no AUTO_SUBMIT) with links to `docs/SECURITY.md`.
- Status table linking each `docs/implementation/` workstream doc.

### 2. `.env.example` completion

Every setting from 01/02/03/06/10 with comments: `GREENHOUSE_BOARDS`, `LEVER_COMPANIES`, `JOB_SOURCE_*`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONALITY`, `CHROMA_DIR`, `SUBMISSION_POLICY`, `ALLOWED_DOMAINS`, `DATA_DIR`/`EVIDENCE_DIR`/`RESUME_UPLOAD_DIR`, `LLM_TIMEOUT`, `LLM_MAX_RPM`, `MATCH_WEIGHTS`. Provider note updated to match reality (google supported; openai-compatible experimental).

### 3. `docs/ARCHITECTURE.md` refresh

- §2.2/§14 status lists rewritten to Implemented/Planned reality (FastAPI, LangGraph workflows, adapters, matching, tailoring, security layer, tracking; Planned: live-ATS pilot, web research).
- Runtime architecture section gains the actual request flows: resume upload path, job-search path, application path (prepare → approve → submit → verify) with the module names from this roadmap.
- Add the implementation-roadmap folder to the doc map.

### 4. `docs/PROJECT_PLAN.md` reconciliation appendix

- One table: plan item → status → evidence (file paths / test names / eval numbers) → deviation note.
- Named deviations recorded honestly: Pydantic `CandidateProfile` (closes the dict-profile deviation), unplanned-but-kept LLM client, Phase 8 before 3–7 (rationale: vertical proof of the factuality-first principle), ATS + evaluation deferred to WS-05/09, LinkedIn placeholder (no public API).
- Cross-reference `docs/implementation/00-OVERVIEW.md` as the forward plan.

### 5. Optional: Docker artifacts

- `Dockerfile` (python:3.13-slim, `pip install .`, `playwright install --with-deps chromium`, non-root user, uvicorn entrypoint) + `docker-compose.yml` (api + postgres:16, volume for `data/`, DATABASE_URL wired) — **optional**, only if deployment testing starts; the plan's §47 anti-over-engineering rule applies.

### 6. Repo hygiene

- Verify `.gitignore` covers `data/`, `app.db`, evidence artifacts, golden eval outputs that shouldn't be committed (reports themselves are committed by design).
- Decide and execute the commit strategy for the currently uncommitted modules + this roadmap (separate commits per workstream area; requires explicit user instruction per AGENTS.md).

## Acceptance criteria

- [ ] A fresh machine can go from clone to running API + passing tests following the README alone (verified by actually doing it on this machine).
- [ ] Every env var read by `src/config/settings.py` appears in `.env.example` (grep-verified both directions).
- [ ] `docs/ARCHITECTURE.md` contains no status claims contradicted by the codebase.
- [ ] `docs/PROJECT_PLAN.md` reconciliation names every known deviation with evidence.
- [ ] `docs/evaluations/` contains at least one baseline report from WS-09.

## Tests

- `tests/test_env_docs.py` (small but permanent) — parses `.env.example` and `settings.py`, asserts the env-var sets match; keeps docs honest automatically.
- No other new tests; this workstream is verified by the acceptance checklist.

## New dependencies

None.
