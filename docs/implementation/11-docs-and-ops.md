# WS-11 · Docs, Ops, and Reconciliation

Status: **Done (2026-10-21)** · Milestone: **M5** · Depends on: all workstreams (documents their outcomes) · Blocks: nothing

> **Executed 2026-10-21.** The specification is Part 2, the plan is Part 3, and the outcome —
> including the live verification — is Part 4. The acceptance criteria below are checked, with
> the evidence, in Part 4.

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

- [x] A fresh machine can go from clone to running API + passing tests following the README alone (verified by actually doing it on this machine). — **Met**, see Part 4.
- [x] Every env var read by `src/config/settings.py` appears in `.env.example` (grep-verified both directions). — **Met**, and now permanent: `tests/test_env_docs.py`.
- [x] `docs/ARCHITECTURE.md` contains no status claims contradicted by the codebase. — **Met**, Part 4, Phase E.
- [x] `docs/PROJECT_PLAN.md` reconciliation names every known deviation with evidence. — **Met**: §53, with eleven named deviations.
- [x] `docs/evaluations/` contains at least one baseline report from WS-09. — **Already met** (`report-2026-10-21.md` / `.json`).

## Tests

- `tests/test_env_docs.py` (small but permanent) — parses `.env.example` and `settings.py`, asserts the env-var sets match; keeps docs honest automatically.
- `tests/test_docs_accuracy.py` — the README's API table against the live OpenAPI schema, both directions, plus the redaction check.
- `tests/test_ws11_docs.py` — the `PLAYWRIGHT_HEADLESS` behaviour the env file documents.
- `scripts/verify_ws11.py` — the live acceptance run: the documents against the code, and the quickstart from a fresh database to the evidence on disk.
- The clean-environment run (P4.4b) — a second virtual environment, `pip install -e .` from
  `pyproject.toml` alone, then the full suite.
- No other new tests; this workstream is verified by the acceptance checklist.

## New dependencies

**`pytest-asyncio>=1.4.0`** — a test-runner plugin, no runtime code. It was **found** by this
workstream, not planned by it: 53 tests are `async def`, the plugin was present in the
developer's environment but undeclared, and a clean `pip install -e .` produced 68 failures.
See P4.4b.

Nothing else. The workstream adds no runtime dependency.

---

# Part 2 — Detailed specification (added 2026-10-21)

## S0. Scope, invariants, non-goals

**Goal.** Make the project's public face describe the system that actually exists, and — more
importantly — make the description **impossible to let rot**. A README that is wrong on the
day it is written is a liability; a README that is wrong *because nobody noticed the code
changed* is worse. The deliverable is therefore a set of documents **and** the machine checks
that keep them true.

**Invariants (binding).**

| # | Invariant | Enforced by |
|---|---|---|
| I1 | Every environment variable the runtime reads appears in `.env.example` | `tests/test_env_docs.py`, direction A |
| I2 | Every variable in `.env.example` is actually read by the runtime | `tests/test_env_docs.py`, direction B |
| I3 | A documented value equals the code's own default (no drift between the file and `Settings`/`SecurityLimits`) | `tests/test_env_docs.py`, the default check |
| I4 | The README's API table lists **exactly** the routes the app exposes — no missing route, no removed route | `tests/test_docs_accuracy.py` |
| I5 | No document claims a status the code contradicts | the accuracy test, plus a line-by-line read of every status claim in the four documents |
| I6 | No secret, key, token, cookie or candidate PII enters a tracked document | a redaction check in the docs test, plus a manual review of every literal in the diff |
| I7 | Every doc change is accompanied by the check that keeps it true | each phase below names its verification |
| I8 | The reconciliation is honest: a plan item that is *not* done says so plainly | the appendix table has a `Status` column with no "probably" values |
| I9 | Nothing in the runtime changes behaviour except where a phase explicitly says so | the diff is reviewed path by path |

**Non-goals.**

- Not a marketing rewrite. The README is an **operator's** document: how to run it, what it does,
  what it will not do.
- Not a documentation site, a mkdocs build, a doc pipeline or a docs theme. Markdown in the
  repository is the deliverable.
- No new runtime dependency. `pytest` and `ruff` are already declared project dependencies.
- Not a Docker/deployment deliverable — see **S7** for the decision and its rationale.
- Not a rewrite of `docs/PROJECT_PLAN.md`'s intent sections. The plan is a record of intent; the
  reconciliation is an **appendix**, not a rewrite. Rewriting history would destroy the only
  record of what was intended.

## S1. What the audit found (2026-10-21)

The audit compared every tracked document against the code, route by route and variable by
variable. The documents are not "slightly stale" — several of them describe a system that no
longer exists, and two of them make promises the code does not keep.

| # | Document | Finding | Severity |
|---|---|---|---|
| D1 | `README.md` | The API table lists `POST /api/applications/submit` — **that route was removed in WS-06**, because it was the `approval: bool` hole SEC-05 forbids. A reader following the README calls a 404 route, and worse, believes a one-call submit exists. | High |
| D2 | `README.md` | The status table says WS-05…WS-09 are "Not started" and that the approval gate "is a boolean flag". All four workstreams are done, and the approval gate records an approver identity, a reason and a timestamp. | High |
| D3 | `README.md` | "Known issues" lists six defects that were **fixed** in WS-06/08/10 (the substring allowlist, the placeholder adapters returning `success=True`, the boolean approval, `LLM_TEMPERATURE` never being sent). It does not list the four that are genuinely open. | High |
| D4 | `README.md` | The quickstart exercises two of the seventeen routes and never shows the **application flow** — the project's centerpiece — nor `POST /api/tailor`. There is no runnable fake ATS for a reader to point it at. | Medium |
| D5 | `README.md` | "searching about 5,300 stored listings from 15 configured boards" is a stale snapshot number, presented as a current fact. | Low |
| D6 | `docs/ARCHITECTURE.md` | §14 "Current Status" labels the FastAPI service, the LangGraph orchestration, the database schema, the job adapters, the matching engine, the resume tailoring and the application submission workflow **PLANNED**. Every one of them exists and is tested. | High |
| D7 | `docs/ARCHITECTURE.md` | §11 "Directory Structure (Planned)" describes `src/models/`, `src/services/`, `src/utils/`, `src/agent/`. **None of those directories exist.** The real layout is `src/api`, `src/jobs`, `src/matching`, `src/rag`, `src/llm`, `src/graph`, `src/applications`, `src/security`, `src/db`, `src/resume`, `src/research`, `src/evaluation`, `src/core`, `src/config`. | High |
| D8 | `docs/ARCHITECTURE.md` | §6 says the runtime Playwright client is "to be implemented". It is implemented (`src/applications/fake_ats_adapter.py`, `src/applications/form.py`), and it is the WS-08 deliverable. | Medium |
| D9 | `docs/ARCHITECTURE.md` | The Phase 3–7 footprint sections (§8–12) still read "Placeholder store; full `chromadb` integration pending" and "Ready for real adapter and DB integration in future phases". Both are false now. | Medium |
| D10 | `docs/PROJECT_PLAN.md` | The plan's phases 2–8 carry ad-hoc completion footprints from 2026-10-11 describing a 68-test codebase, and the "Deviations From Plan (open gaps)" list still calls ATS analysis and tailoring metrics open — both were delivered in WS-05/WS-09. There is no reconciliation table anywhere. | High |
| D11 | `docs/SECURITY.md` | §2 "Implemented today" describes the 2026-10-11 state: Cursor config, a minimal FastAPI app, a health endpoint. The control register in §5 and the summary in §12 are current — so the document contradicts itself, in the same file. | High |
| D12 | `.env.example` | Six variables the runtime reads are absent or commented out: `DATA_DIR`, `EMBEDDING_RPM_LIMIT`, `EMBEDDING_RPD_LIMIT`, `RESUME_UPLOAD_DIR`, `EVIDENCE_DIR`, `TAILORED_DIR`. | Medium |
| D13 | `.env.example` | Two variables are documented but **read by nothing**: `PLAYWRIGHT_HEADLESS` (the browser is launched with a hard-coded `headless=True`) and `BROWSER_ISOLATION` (session isolation is unconditional, not configurable). A reader would reasonably believe they control something. | Medium |
| D14 | `.env.example` | `DATABASE_URL=sqlite:///./app.db` contradicts the code's default `sqlite:///./data/app.db` — the copy-paste path puts the database **outside** the gitignored `data/` tree, so it can be committed by accident. | Low |
| D15 | `docs/evaluations/` | The WS-09 baseline report is present and current (`report-2026-10-21.md` / `.json`). **No finding.** | — |
| D16 | `.gitignore` | `data/`, `app.db`, `.env` and the caches are all ignored. **No finding.** | — |
| D17 | The `docs/implementation/` roadmap | Every workstream document except this one is written as a *plan*. A reader cannot tell from the folder which workstreams shipped. | Medium |

**What the audit did not find.** No secret, key or token is present in any tracked document; the
`react/` directory is empty and untracked; `todo` is an empty tracked placeholder; the
`docs/evaluations/` reports are the only generated artifacts that are committed on purpose.

## S2. Phase A — the env file becomes the single source of truth

**The problem.** `.env.example` is the file an operator copies to `.env`. It is therefore the
file that most needs to be exactly right, and it is the file that has drifted.

**The fix.** Three parts.

1. **Completeness.** Every variable the runtime reads gets an entry, with the comment that
   explains *what it bounds* rather than *what it is called*.
2. **Truthfulness.** A variable that is read by nothing is removed. `BROWSER_ISOLATION` goes:
   WS-08 made a fresh browser context per run **unconditional**, so exposing a switch that
   disables it would be a switch that removes a security control. The isolation control is
   documented where it belongs — in `docs/SECURITY.md` — and the env file says so in one line.
   `PLAYWRIGHT_HEADLESS` stays and becomes **real** (Phase B): a hard-coded `headless=True` is
   not a policy, it is a leftover, and being able to watch the browser is how you debug a
   browser layer.
3. **Default agreement.** A documented value must equal the code's own default (I3). The
   `DATABASE_URL` default becomes `sqlite:///./data/app.db`, so copying the example file puts
   the database inside the gitignored tree.

**The comment style.** The existing file is already good at this: it explains *why* a knob
exists and what happens at the limit. The new entries follow the same voice.

**Files.** `.env.example` (rewritten in place, keeping the existing comments and adding the
missing entries), `src/applications/fake_ats_adapter.py` (Phase B).

## S3. Phase B — `PLAYWRIGHT_HEADLESS` becomes real

**The change.** `src/applications/fake_ats_adapter.py` launches Chromium with
`headless=True` hard-coded. It becomes
`headless=os.getenv("PLAYWRIGHT_HEADLESS", "true").strip().lower() != "false"`, read at launch
time, defaulting to headless (the safe, CI-friendly default).

**Why this is in a documentation workstream.** Because the alternative is to delete the variable
from `.env.example` and lose the ability to watch the browser — which is a debugging capability
the WS-08 browser layer genuinely benefits from. The change is one line in one file, it cannot
weaken a security control (headless is not a control; the isolation and the allowlist are), and
it makes a documented knob honest.

**The verification.** A unit test that sets the variable to `false` and asserts the launch
configuration follows, without launching a browser: the adapter's launch options are computed
by a small pure helper (`_launch_options()`) that the test calls directly.

**Files.** `src/applications/fake_ats_adapter.py`, `tests/test_ws11_docs.py`.

## S4. Phase C — the env-document test (`tests/test_env_docs.py`)

The acceptance criterion says "grep-verified both directions". A grep is a one-time check that
rots on the next commit; this is the same check, made permanent.

**How the runtime's variables are discovered.** The test walks `src/**/*.py` and collects every
literal environment-variable name the code reads, from four access patterns:

- `os.getenv("NAME")`
- `os.environ.get("NAME")`
- `os.environ["NAME"]`
- `_int_env("NAME", …)` / `_float_env("NAME", …)` — the dynamic accessor `src/security/limits.py`
  uses, where the name is a literal at the call site.

The set is then intersected with a small allowlist of names that are **not** runtime
configuration but appear as literals in the source (there are none today; the allowlist exists
so a future match does not silently break the test).

**How the document is parsed.** `.env.example` is read line by line. A line is an entry when it
matches `^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=`. The *value* is the text after the first `=`, trimmed
of trailing comments only for the comparison in the default check.

**The three assertions.**

| Assertion | What it proves |
|---|---|
| A: every variable the runtime reads is documented | I1 — an operator can configure anything the code reads |
| B: every documented variable is read by the runtime | I2 — no documented knob is a lie (D13) |
| C: every documented value equals the code's default | I3 — the example file cannot drift from the code |

**How assertion C is computed.** The test removes every documented variable from
`os.environ` (via `monkeypatch.delenv`), constructs a fresh `Settings()`, and reads the
attribute. For the WS-12 limits it calls `reset_limits()` and `get_limits()`. The comparison
uses `str(Path(value))` normalisation so that `./data/tailored` and `data/tailored` compare
equal, and the boolean-ish variables are compared as booleans.

**The mapping tables.** `SETTINGS_VAR_TO_ATTR` and `LIMITS_VAR_TO_ATTR` in the test file map
each documented variable to the attribute that holds it. They are explicit on purpose: a
variable that is read but has no attribute to compare against is reported by the test rather
than silently skipped, so the table cannot rot unnoticed.

**Files.** `tests/test_env_docs.py` (new).

## S5. Phase D — the README rewrite

The README becomes the document a new operator actually needs. Its sections, in order:

| Section | Content | Source of truth |
|---|---|---|
| 1. Title + one paragraph | What the system is, what it will not do (no real-site submission), the stack | this document, §S0 |
| 2. Status | A per-area table, each row naming the workstream that delivered it and the current state | `docs/implementation/00-OVERVIEW.md` |
| 3. Architecture | An ASCII diagram with the **real** module paths, and the three flows | `src/` tree |
| 4. Quickstart | Clone → venv → install → Playwright → `.env` → migrations → server → exercise the API → fake-ATS demo → tests → evals | verified by the Phase J run |
| 5. API reference | One row per route: method, path, purpose, which workstream added it | the FastAPI app's route table |
| 6. Configuration | The env vars an operator changes most, with the default | `.env.example` |
| 7. Security posture | The approval default, the allowlist, the untrusted-content rule, `AUTO_SUBMIT` being unreachable, and a link to `docs/SECURITY.md` | `docs/SECURITY.md` |
| 8. Repository layout | The real tree | `src/` |
| 9. Roadmap | M1…M5 with their outcome and their workstream documents | `docs/implementation/00-OVERVIEW.md` |
| 10. Known issues | **Only the open ones** | the audit, D3 |
| 11. Documentation | The index of the four documents plus the roadmap | this repository |

**Rules for the rewrite.**

- Every command in the quickstart is one that was actually run in Phase J, on this machine.
- No route appears in the API table that the app does not expose, and none is missing.
- The "Known issues" list is **short and true**: the Chroma `count - 1` edge case, the
  `openai-compatible` provider never having been exercised against a live endpoint, the Remotive
  DNS flake, the four still-open security rows, and the absence of PDF parsing. The fixed ones
  are not listed as issues.
- The README does not promise anything the code does not do, and it says plainly that the
  browser path is exercised against a **local fake ATS**, not a real job site.

**Files.** `README.md` (rewritten).

## S6. Phase E — `docs/ARCHITECTURE.md` refresh

The document keeps its structure — it is a good skeleton — and every stale status is replaced
with the real one.

| Section | Change |
|---|---|
| §2.1 "Planned Components" | Becomes a component-status table: component → state → where it lives → how it is verified. Nothing is labelled PLANNED that exists. |
| §2.2 "Implemented Components" | Kept (the development-time tooling) and clearly marked as the development-time half. |
| §3 "Runtime Architecture" | Gains the **three actual request flows** — resume upload, job search, application (prepare → approve → submit → verify) — each naming the modules that execute it. |
| §6 "Browser Automation Architecture" | The runtime client is stated as implemented, with the semantic-locator, one-context-per-run and evidence rules, and the development-time/runtime split kept. |
| §7 "Data Architecture" | The real tables, in the real names, with the migration that creates each. |
| §11 "Directory Structure (Planned)" | The real tree, including the `docs/implementation/` roadmap. |
| §13 "Major Interfaces" | The real route list. |
| §14 "Current Status" | Rewritten: what is implemented, what is planned (the live-ATS pilot, web research behind SSRF controls), what is experimental. |
| §8–12 (the Phase 3–7 footprints) | Kept as history, under a heading that says so, with the two false "Status:" lines corrected and a pointer to the workstream documents that superseded them. |

**Files.** `docs/ARCHITECTURE.md` (edited in place).

## S7. Phase F — `docs/PROJECT_PLAN.md` reconciliation appendix

A new section **§53**, appended, not woven in: the plan's intent sections stay as written, and
the appendix is the record of what happened.

**53.1 The table.** One row per plan item: plan reference → status → evidence (file paths, test
names, evaluation numbers) → deviation note.

**53.2 The named deviations.** Each one is stated as *plan said X → reality is Y → why*, with
the reason and the date:

1. The dict-based candidate profile → the validated Pydantic `CandidateProfile`. The deviation
   is **closed**: the plan's own §2 pipeline (parse → profile → validate) is now what the code
   does.
2. The unplanned LLM client. Not in the plan at all; added on 2026-10-11 to make the tailoring
   stage real, kept, and hardened by WS-10.
3. Phase 8 (tailoring) shipped before Phases 3–7 were real. Rationale: a vertical proof of the
   factuality-first principle — one real resume, one real listing, one real draft, zero
   fabricated claims. The order was then restored by WS-01…WS-04.
4. ATS analysis and evaluation were not in the plan's phase list as delivered stages; they
   arrived as WS-05 and WS-09.
5. The LinkedIn placeholder adapter. There is no public LinkedIn API; the adapter stays
   unregistered, and the roadmap says so.
6. The local embedding provider (FU-7) replaced the planned cloud embedding model; the model
   identity is persisted with the vectors so the two spaces can never be mixed.
7. The API surface grew a tracking and an approval surface that the plan did not specify in
   detail (WS-07).

**53.3 The pointer.** `docs/implementation/00-OVERVIEW.md` is the forward plan; this appendix is
the backward-looking record.

**Files.** `docs/PROJECT_PLAN.md` (appended).

## S8. Phase G — `docs/SECURITY.md` status reconciliation

§2 "Current implementation status" is rewritten to the present: the controls WS-06, WS-07,
WS-08 and WS-12 delivered, with their file paths, and the four rows that are genuinely open
(API authentication, malware scanning, retention, production secret management). The control
register (§5) and the summary (§12) are already current and stay.

**Files.** `docs/SECURITY.md` (§2 edited in place).

## S9. Phase H — the fake-ATS demo script

The quickstart needs something a reader can point the application flow at. The fake ATS exists
in `tests/fixtures/fake_ats/` but only as a test fixture. `scripts/serve_fake_ats.py` runs it
as a standalone server on a chosen port (`127.0.0.1:8901` by default), reusing the existing
page modules — no duplicated HTML, no second implementation.

The script is a **development-time** artifact, like the other `scripts/` entries. It imports the
fixture package from the repository root and adds that root to `sys.path` when it is not already
there, so `python scripts/serve_fake_ats.py` works from a clean checkout.

**Files.** `scripts/serve_fake_ats.py` (new).

## S10. Phase I — the API accuracy test

`tests/test_docs_accuracy.py` builds the FastAPI app, collects its routes, and asserts that the
README's API table contains **exactly** those paths and methods. A route added without a README
line fails the suite; a README line for a removed route fails the suite. This is the machine
check behind acceptance criterion "the README describes the current API", and it is what stops
D1 from ever recurring.

The same file carries the **redaction check**: the tracked documents must not contain a
credential-shaped literal (an `AIza…` Google key, an `sk-…` OpenAI key, a `Bearer <token>`).

**Files.** `tests/test_docs_accuracy.py` (new).

## S11. Phase J — the acceptance run

The acceptance criteria are checked by **doing them**, on this machine:

1. A **fresh database**: `alembic upgrade head` against a new SQLite file, and a check that
   every table the ORM expects exists.
2. The **server starts** and answers `GET /`, `GET /api/health`.
3. The **quickstart's own commands** are run, in order, from the README text — including the
   `curl` examples — and the responses are captured.
4. The **fake-ATS demo** is run end to end: prepare → approve → submit → verify, against the
   script from Phase H, with the evidence on disk.
5. The **full offline suite** is green.
6. `ruff` is clean.

**A fresh virtual environment.** The acceptance criterion says "a fresh machine can go from
clone to running API". The honest way to test that is a clean `venv` with a clean
`pip install -e .`, because the failure mode that matters is a **missing dependency in
`pyproject.toml`**, and that only shows up on a clean install. A second virtual environment is
created for the check and removed afterwards. The Playwright **browser** is a per-user install
(`playwright install chromium`), so it is shared, and the README says so.

## S12. Phase K — the roadmap documents

`docs/implementation/11-docs-and-ops.md` gets its implementation notes, and
`docs/implementation/00-OVERVIEW.md` gets the status line for WS-11 and the corrected
workstream table, so the folder says which workstreams shipped.

**Files.** `docs/implementation/11-docs-and-ops.md`, `docs/implementation/00-OVERVIEW.md`.

## S13. The commit strategy

AGENTS.md requires an explicit instruction before committing. This workstream therefore
**changes files and leaves the commit to an explicit instruction**. When that instruction comes,
the commits are discrete and per-area, following the convention of WS-06…WS-12:

1. `docs: the env example file matches the code` (`.env.example`, the adapter change, the env test)
2. `docs: the README describes the system that exists` (`README.md`, the accuracy test, the demo script)
3. `docs: the architecture document is reconciled` (`docs/ARCHITECTURE.md`)
4. `docs: the plan gets its reconciliation appendix` (`docs/PROJECT_PLAN.md`, `docs/SECURITY.md`)
5. `docs: the roadmap records WS-11` (the two `docs/implementation/` files)

---

# Part 3 — Execution plan (added 2026-10-21)

Phases, in dependency order. Each phase: implement → its own test → the full offline suite →
`ruff`.

| # | Phase | Files | Verification |
|---|---|---|---|
| A | The env file becomes the source of truth | `.env.example` | `tests/test_env_docs.py` (new in C) |
| B | `PLAYWRIGHT_HEADLESS` becomes real | `src/applications/fake_ats_adapter.py` | a unit test on the launch options |
| C | The env-document test | `tests/test_env_docs.py` | the test itself (3 assertion groups) |
| D | The README rewrite | `README.md` | `tests/test_docs_accuracy.py` (Phase I) + a manual read |
| E | The architecture refresh | `docs/ARCHITECTURE.md` | a manual read against `src/` |
| F | The plan reconciliation | `docs/PROJECT_PLAN.md` | a manual read against the workstream docs |
| G | The security status reconciliation | `docs/SECURITY.md` | a manual read against §5/§12 |
| H | The fake-ATS demo script | `scripts/serve_fake_ats.py` | the demo itself, in Phase J |
| I | The API accuracy test | `tests/test_docs_accuracy.py` | the test itself |
| J | The acceptance run | — | the five acceptance checks, on this machine |
| K | The roadmap documents | `docs/implementation/11-docs-and-ops.md`, `docs/implementation/00-OVERVIEW.md` | the status lines match reality |

**Order rationale.** A and B come first because C tests them. C comes before D because the README
quotes the env file. I comes after D because I tests the README. H comes before J because J
runs the demo. J comes last because it verifies everything above it. K is last because it
records the outcome.

**The gate.** Every phase is gated on the **full offline suite** being green and `ruff` being
clean. A phase that breaks the suite is not "done" — it is rolled back and redone.

**The stop conditions.**

- If the clean-venv install (Phase J, step 6) fails on a missing dependency, the fix is to add
  it to `pyproject.toml` with a justification line, exactly as the overview's dependency table
  does. The README is not changed to work around it.
- If a documented value and the code default genuinely cannot be made to agree (a value that
  is deliberately different, e.g. a curated board list), the variable is excluded from
  assertion C **with a comment saying why** — never silently.


---

# Part 4 — Implementation notes (2026-10-21 — executed)

## P4.1 What the audit found, and what happened to each finding

The audit in Part 2 (S1) produced seventeen findings. Every one of them was addressed, and
the one that was **not** a defect is recorded as such.

| # | Finding | What was done |
|---|---|---|
| D1 | The README advertised the removed `POST /api/applications/submit` | Rewritten; the route is gone, and `tests/test_docs_accuracy.py` now fails if it ever reappears in a table or in the text |
| D2 | The README's status table said WS-05…WS-09 were not started | Rewritten: a per-area table, each row naming the workstream that delivered it |
| D3 | The README's "Known issues" listed six **fixed** defects and none of the open ones | Rewritten: only the open ones, with the fixed ones named in a sentence so a reader who saw the old file knows they were addressed |
| D4 | The quickstart exercised two of seventeen routes and never showed the application flow | Rewritten: upload → refresh → search → tailor, and the full prepare → approve → submit → verify flow, with the fake ATS server |
| D5 | The README's corpus size was a stale snapshot presented as a current fact | Removed: the README no longer states a corpus size, because the corpus is the operator's own |
| D6 | The architecture §14 labelled seven implemented components PLANNED | Rewritten as a component-status table (state, module, verifying test) |
| D7 | The architecture §11 described four directories that do not exist | Replaced with the real tree |
| D8 | The architecture §6 said the runtime browser client was "to be implemented" | Rewritten: it is implemented, with the semantic-locator, one-context-per-run and evidence rules |
| D9 | The architecture's Phase 3–7 footprints carried two false "Status" lines | The footprints are kept as history under a heading that says so, and the two false lines are corrected with a pointer to the workstream that superseded them |
| D10 | The plan had no reconciliation, and its "open gaps" list named two delivered stages | `docs/PROJECT_PLAN.md` §53 was appended: a phase table with evidence, eleven named deviations, and the open items |
| D11 | The security §2 described the 2026-10-11 state while §5 and §12 described the present | §2 rewritten to the present, and the contradiction with §5 and §12 is gone |
| D12 | Six runtime variables were missing from `.env.example` | Added: `DATA_DIR`, `EVIDENCE_DIR`, `RESUME_UPLOAD_DIR`, `TAILORED_DIR`, `EMBEDDING_RPM_LIMIT`, `EMBEDDING_RPD_LIMIT` |
| D13 | Two documented variables were read by nothing | `BROWSER_ISOLATION` **removed** (session isolation is unconditional — WS-08 made it so, and a switch that disabled it would be a switch that removed a security control); `PLAYWRIGHT_HEADLESS` made **real** (Phase B) |
| D14 | `DATABASE_URL` in the example file contradicted the code's default | Both now say `sqlite:///./data/app.db`, so a copied file puts the database inside the gitignored tree |
| D15 | `docs/evaluations/` holds a current baseline | No change needed — confirmed by the live check |
| D16 | `.gitignore` covers the runtime state | No change needed — confirmed |
| D17 | The roadmap folder did not say which workstreams shipped | `00-OVERVIEW.md` gained a **Status** column in the workstream index, and the status line now names WS-11 and WS-12 |

## P4.2 The phases, and what each one changed

**Phase A — the env file.** `.env.example` was rewritten. Six variables were added, two were
removed or made real, and the database default was aligned with the code. The file now
carries **56** variables, and every one of them is read by the runtime.

**Phase B — `PLAYWRIGHT_HEADLESS` became real.** `src/applications/fake_ats_adapter.py` gained
a `launch_options()` helper that reads the variable at launch time:

```python
raw = os.getenv("PLAYWRIGHT_HEADLESS", "true").strip().lower()
return {"headless": raw not in {"false", "0", "no", "off"}}
```

The change is one line in the launch call, it cannot weaken a control (headless is not a
control — the allowlist, the fresh context and the challenge stop are independent of it), and
it buys the ability to watch the browser while debugging a form.

**Phase C — `tests/test_env_docs.py`.** Five tests, three of them the assertions from the
specification:

- **A** — every variable the runtime reads is documented. The names are discovered by
  walking `src/**/*.py` for four access patterns, including the `_int_env` / `_float_env`
  helper that `src/security/limits.py` uses for its twenty knobs.
- **B** — every documented variable is read by the runtime. This is what caught
  `BROWSER_ISOLATION` and `PLAYWRIGHT_HEADLESS`.
- **C** — a documented value equals the code's own default. The test clears the environment
  (the developer's `.env` is loaded at import time, so it has to be cleared), builds a fresh
  `Settings()`, resets the limits, and compares 33 defaults attribute by attribute.
- Plus the coverage test (every documented variable has a rule) and the secret check.

The curated board lists are excluded from assertion C, with the reason recorded in the test:
the code's default is an empty list, and the example file is more useful with real boards in
it.

**Phase D — the README.** Rewritten around the eleven sections of the specification. Every
command in it was run in Phase J.

**Phase E — the architecture document.** Rewritten: the component-status table, the three
request flows, the real data model (nine tables, each mapped to the migration that creates
it), the real directory tree, the real interface list, and the reconciled §13. The historical
phase footprints are kept, under a heading that says they are a record.

**Phase F — the plan reconciliation.** `docs/PROJECT_PLAN.md` §53 was appended, with the
plan's own sections left untouched. The appendix is CRLF-consistent with the rest of the
file.

**Phase G — the security status.** `docs/SECURITY.md` §2 rewritten to the present. The
browser-session-isolation row moved from "Planned" to "Implemented", because WS-08 closed it.

**Phase H — the fake-ATS server.** `scripts/serve_fake_ats.py` serves the existing fixture
pages on `127.0.0.1:8901`. It reuses `tests/fixtures/fake_ats/variants.py` — no duplicated
HTML, no second implementation of a form.

**Phase I — the accuracy test.** `tests/test_docs_accuracy.py` compares the README's API
table with the application's own OpenAPI schema, in both directions, and carries the
redaction check over the five tracked documents.

**Phase K — the roadmap.** `00-OVERVIEW.md`: the status line, the new Status column in the
workstream index, and the M5 block.

## P4.3 The live verification

`scripts/verify_ws11.py` runs the acceptance criteria for real, on this machine, against a
throwaway database and a throwaway evidence directory. **29/29 checks passed** (2026-10-21):

| Group | Checks | What it proves |
|---|---|---|
| The documents | 17 | the env file agrees with the code in both directions; the README's API table is exactly the 17 routes the app exposes; the removed route is not advertised; the quickstart's commands are the real ones; the architecture carries no stale status claim; the plan carries the reconciliation and names the deviations; the security document describes the present; the evaluation baseline exists |
| The quickstart, live | 12 | `alembic upgrade head` creates the database and all ten tables; the server starts; `/` and `/api/health` answer; a resume uploads; a search answers; the match history answers; prepare → approve → submit → verify succeeds against a real browser; the screenshot, the action trace and the trace archive are on disk; the tracking API lists the application |

The run is repeatable: `env\Scripts\python.exe scripts/verify_ws11.py`.

## P4.4 The suite and the lint

- **1,037 tests pass**, 0 failed, in ~110 s. The suite is offline: no network, no API key, no
  database server. (The count is the one at the end of this workstream; the tree has since
  grown with the concurrent WS-13/WS-14 work.)
- `ruff check src tests scripts` — **clean**.
- `ruff format --check src tests scripts` reports four files it would reformat
  (`scripts/verify_live_search.py`, `tests/test_injection_policy.py`, `tests/test_jobs_api.py`,
  `tests/test_resume_parser.py`). All four are **pre-existing and untouched by this
  workstream**; reformatting another workstream's files is not this workstream's business,
  and the gate for every commit in this repository is `ruff check`.
- The six Remotive tests failed **once** during this workstream, and passed on a re-run. This
  is the known DNS flake: the SSRF guard resolves real DNS for `remotive.com` under the mock
  transport. It is documented in `AGENTS.md` and in the README's known issues.

## P4.4b The clean environment — and the defect it found

The acceptance criterion says "a fresh machine can go from clone to running API". The honest
way to test that is a clean virtual environment, so one was created (`env_verify/`, removed
afterwards) and the project was installed into it with `pip install -e .` — nothing but
`pyproject.toml`.

**The install succeeded. The suite did not: 68 of 1,037 tests failed.** The cause was not
environmental. Fifty-three tests are `async def` and carry `@pytest.mark.asyncio`, and
**`pytest-asyncio` was never declared as a dependency**. It was present in the developer's
`env/` — installed by hand, pulled in by nothing (`pip show` reported `Required-by:` empty) —
so the suite was green there and broken everywhere else. A new machine running the README's
own quickstart would have hit it.

The fix is one line in `pyproject.toml`:

```toml
"pytest-asyncio>=1.4.0",
```

It is a test-runner plugin, in the same class as the `pytest-xdist` the project already
declares, and the justification is recorded in the roadmap's dependency table. With it
declared, the clean environment ran **1,031 passed and 6 failed** — and all six failures were
the known Remotive DNS flake, which passes in isolation in both environments.

Two further environment facts, recorded so the next person is not surprised:

- The clean environment resolved **playwright 1.64.0** (the project declares `>=1.51.0`),
  which expects a newer Chromium build than the one on this machine, and
  `playwright install chromium` **could not download it** — `cdn.playwright.dev` is
  unreachable from here. Pinning the clean environment to the 1.62.0 build that was already
  present made the browser tests pass. The README's `playwright install chromium` step is the
  documented fix on a machine that can reach the CDN.
- Everything else — the migration, the app import, the 17 routes, the server, the fake-ATS
  flow — worked in the clean environment exactly as the README describes.

## P4.5 What was decided and deliberately not done

- **Docker artifacts (the original task 5) were not built.** The plan's §47 forbids
  over-engineering, and no deployment testing has started; a `Dockerfile` and a compose file
  would be untested artifacts that read as if a deployment path existed. The decision is
  recorded here so it is a decision rather than an omission.
- **The data directories were not re-derived.** `EVIDENCE_DIR` and `RESUME_UPLOAD_DIR` have
  their own literal defaults and do not follow `DATA_DIR` (only `TAILORED_DIR` does). Making
  them follow would be a behaviour change, and this workstream changes behaviour only where
  it says so. The `.env.example` comment now states the rule, so an operator who moves
  `DATA_DIR` knows to move the other two.
- **The `openai-compatible` provider was not touched.** It stays experimental, and the
  README says so.

## P4.6 The commit strategy

The commits are **discrete and per-concern**, so that a reviewer can take one idea at a time
and so that a revert is one commit rather than a rebase. Nine of them:

| # | Commit | Files |
|---|---|---|
| 1 | `feat: the browser reads its headless setting from the environment` | `src/applications/fake_ats_adapter.py`, `tests/test_ws11_docs.py` |
| 2 | `docs: the env example file matches the code` | `.env.example`, `tests/test_env_docs.py` |
| 3 | `fix: the async test plugin is a declared dependency` | `pyproject.toml` |
| 4 | `feat: the fake ats server runs as a standalone demo` | `scripts/serve_fake_ats.py` |
| 5 | `test: the readme api table is checked against the application` | `tests/test_docs_accuracy.py` |
| 6 | `test: the ws-11 live acceptance run` | `scripts/verify_ws11.py` |
| 7 | `docs: the architecture document is reconciled` | `docs/ARCHITECTURE.md` |
| 8 | `docs: the plan gets its reconciliation appendix` | `docs/PROJECT_PLAN.md` |
| 9 | `docs: the roadmap records ws-11` | `docs/implementation/11-docs-and-ops.md` |

The order is not arbitrary. Commit 1 lands **before** commit 2, because the env test asserts
that every documented variable is read by the runtime — and `PLAYWRIGHT_HEADLESS` is only
read once the adapter reads it. Commit 3 stands alone, because it is a dependency declaration
with no test of its own. Commits 7–9 are the documents, and they come last, because they
describe the code that the earlier commits land.

**A note on the concurrent session.** While this workstream was in flight, another session
committed several of the files it had touched — `README.md`, `docs/SECURITY.md`,
`docs/implementation/00-OVERVIEW.md` and `AGENTS.md` — as part of its own WS-13 work. Their
changes and this workstream's changes to those files are therefore already in the history,
and the nine commits above cover what remained. The one line of `.env.example` that came
from that session (the Vite dev-server origin in `CORS_ORIGINS`) was committed separately, so
that no commit in this sequence mixes another session's work into its own.

## P4.7 The acceptance criteria, checked

| Criterion | Verdict | Evidence |
|---|---|---|
| A fresh machine can go from clone to running API + passing tests, following the README alone | **Met** | `scripts/verify_ws11.py` ran the documented commands in order on this machine: the migration, the server, the upload, the search, and the full application flow. A clean virtual environment was also created and `pip install -e .` was exercised there — which found the undeclared `pytest-asyncio` dependency (P4.4b). After the fix, the clean environment runs the suite green apart from the known DNS flake |
| Every env var read by `src/config/settings.py` appears in `.env.example`, both directions | **Met** | `tests/test_env_docs.py` (assertions A and B), 56 variables, and assertion C on the defaults |
| `docs/ARCHITECTURE.md` contains no status claim contradicted by the codebase | **Met** | Part 4, Phase E; the component-status table names the verifying test for every implemented component |
| `docs/PROJECT_PLAN.md` reconciliation names every known deviation with evidence | **Met** | §53.2 (the phase table) and §53.3 (eleven named deviations) |
| `docs/evaluations/` contains at least one baseline report from WS-09 | **Met** | `report-2026-10-21.md` and `.json` |

## P4.8 What is still open after WS-11

- The **M5 live pilot** — one real posting, `PREPARE_ONLY` first, then `REQUIRE_APPROVAL`
  with a human in the loop. This is the gate for a real-ATS adapter.
- The four open security rows: retention and purge, malware scanning, PII minimisation inside
  the stored resumes, and API authentication.
- PDF resume parsing.
- URL-based web research, behind the SSRF controls.
