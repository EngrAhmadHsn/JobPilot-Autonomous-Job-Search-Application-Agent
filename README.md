# Autonomous AI Job Application Agent

A backend system that reads a resume, finds matching jobs on public job-board APIs, ranks
them with an explained score, tailors the resume without inventing facts, and prepares
applications for human approval — then drives a browser to fill and submit a form, with the
evidence recorded.

**Submissions run against a local fake ATS only.** Real job sites stay off limits until the
security gates in [`docs/SECURITY.md`](docs/SECURITY.md) §14 pass, and `AUTO_SUBMIT` is an
unreachable enum value in this version. The stack is Python 3.13, FastAPI, Pydantic,
LangGraph, SQLAlchemy with Alembic, Chroma and Playwright.

This repository holds the **backend**: the API, the agent workflows, the matching engine and
the browser layer. Any operator console is a separate package beside it, not part of the
runtime — see `docs/implementation/` for the workstream that defines it.

## Status

Milestones M1–M4 are done and live-verified. The offline suite is green (1,037 tests, ~110 s)
and needs no network, API key or database server. The workstream-by-workstream record is in
[`docs/implementation/`](docs/implementation/00-OVERVIEW.md).

| Area | State |
|---|---|
| Resume parsing (DOCX, TXT, MD) → validated `CandidateProfile` | Done (WS-01) — **PDF is not supported** |
| Job discovery: Greenhouse, Lever, Ashby, Remotive | Done (WS-02, FU-2, FU-3) — key-less public board APIs only |
| Normalization, deduplication, persistence | Done (WS-02, WS-04) |
| Hybrid matching: six scorers, Chroma vectors, local embeddings | Done (WS-03, FU-7) |
| End-to-end job workflow (LangGraph) | Done (WS-04) — verified live over HTTP |
| Resume tailoring with a deterministic factuality validator | Done (WS-05) |
| ATS analyzer, DOCX rendering, grounded research engine | Done (WS-05) |
| Two-phase approval flow with a recorded approver identity | Done (WS-06) |
| Security layer: allowlist, audit, evidence, injection filters, rate limits | Done (WS-06, WS-12) |
| Browser automation: accessibility-tree form walking, fake-ATS variants | Done (WS-08) |
| Application tracking and lifecycle | Done (WS-07) |
| Evaluation harness with a measured baseline | Done (WS-09) — [`docs/evaluations/`](docs/evaluations/) |
| LLM client hardening: timeout, retries, pacing, usage accounting | Done (WS-10) |
| **Live pilot on a real job board** | **Not started** — the M5 milestone |

## What you can do today

- Upload a resume (`POST /api/resumes`) and get a stored, validated profile.
- Refresh the job corpus (`POST /api/jobs/refresh` or `scripts/refresh_jobs.py`).
- Search the stored corpus (`POST /api/jobs/search`) and read the score breakdown, the
  matched skills and the missing skills for every result.
- Tailor a resume for one job (`POST /api/tailor`) and get back the tailored content, the
  ATS analysis and a **factuality report listing every claim the validator removed**.
- Run the application flow against the local fake ATS: prepare → approve → submit → verify,
  with the screenshot, the action trace and the Playwright trace archive written to disk.
- Read the application's own history (`GET /api/applications`) — every status change, who
  caused it and why.

## Architecture

```text
Resume ──► src/resume/parser.py ──► CandidateProfile ──► src/db/profiles.py
                                                      │
Greenhouse ┐                                             ▼
Lever      ├─► src/jobs/*_adapter.py ─► normalize ─► dedup ─► src/db/jobs.py ─► Chroma
Ashby      │   (guarded HTTP: src/jobs/http_client.py)                                  ▲
Remotive   ┘                                              │                          │
                                          refresh (daily) │                          │
                                                       src/graph/job_workflow.py ─────┘
                                          search (store only, no board fetch)
                                                       │
                                             src/matching/engine.py (6 scorers)
                                                       │
                                                       ▼
                                            ranked top N + per-component explanation

Tailor: src/resume/tailor.py ─► factuality validator ─► ATS ─► DOCX (src/resume/render.py)
                                        │
                                        ▼
   src/graph/application_workflow.py: prepare ─► approval (src/db/approval.py)
                                        ─► submit (Playwright) ─► verify
                                        ─► evidence (src/applications/evidence.py)
                                        ─► tracking (src/db/applications.py)
```

Development tooling (Cursor, ZCode, Playwright MCP, hooks, skills) is kept strictly separate
from the runtime application. The runtime browser layer is the Playwright **Python** client in
`src/applications/`, not the MCP server.

### The three request flows

1. **Resume upload** — `src/api/routes/resumes.py` validates the file (`src/api/validation.py`:
   type, size, real-file check, zip-bomb guard), the parser extracts the content, the profile
   is validated against the document (`src/resume/profile.py`), and the row is written. The
   profile id comes back.
2. **Job search** — `src/api/routes/jobs.py` loads the stored profile, `src/matching/engine.py`
   scores the corpus, `src/rag/chroma_store.py` supplies the semantic channel, and one
   `job_matches` row is persisted per result. A search never fetches a board.
3. **Application** — `src/api/routes/applications.py` checks the target against the domain
   allowlist, selects the adapter from the permission registry, writes an `approval_requests`
   row, and returns it. A **separate** call records the human decision. Only then does the
   graph execute, and success is claimed only if the confirmation page says so *and* the
   evidence files exist.

## Quick start

Windows (PowerShell) and POSIX (bash) differ only in the first two lines.

```powershell
py -3.13 -m venv env
env\Scripts\activate
```

```bash
python3.13 -m venv env
source env/bin/activate
```

Then, in either shell:

```bash
pip install -e .            # the project and its dependencies
playwright install chromium # the browser; this is a per-user install
cp .env.example .env        # Windows: copy .env.example .env
alembic upgrade head        # creates data/app.db and every table
uvicorn src.main:app --reload
```

The API is now on <http://localhost:8000>. The interactive docs are at
<http://localhost:8000/docs> (development only — the docs surface is removed outside
development, because it renders the OpenAPI schema as HTML).

Set `LLM_PROVIDER`, `LLM_API_KEY` and `LLM_MODEL` in `.env` only if you want the tailoring
stage to call a real model. Everything else works without a key: the embeddings are local, and
the job sources are key-less public APIs.

### Try the API

```bash
# 1. upload a resume -> a profile id
curl -F "file=@resume.docx" http://localhost:8000/api/resumes

# 2. refresh the corpus (the first run downloads ~300 MiB of embedding weights
#    and embeds every listing on CPU — this takes a while and is resumable)
curl -X POST http://localhost:8000/api/jobs/refresh

# 3. search the stored corpus for that profile
curl -X POST http://localhost:8000/api/jobs/search \
  -H "Content-Type: application/json" \
  -d '{"profile_id": "<profile id>", "top_n": 10}'

# 4. tailor the resume for one of the results
curl -X POST http://localhost:8000/api/tailor \
  -H "Content-Type: application/json" \
  -d '{"profile_id": "<profile id>", "job_id": "greenhouse:stripe:8172510"}'
```

### The application flow, end to end

The browser layer is exercised against a **local fake ATS** — a small applicant-tracking
system that serves the page variants the adapter has to survive. Start it in a second
terminal:

```bash
python scripts/serve_fake_ats.py        # http://127.0.0.1:8901
```

Then, with the API running:

```bash
# 1. prepare — nothing is submitted, an approval request is created
curl -X POST http://localhost:8000/api/applications/prepare \
  -H "Content-Type: application/json" \
  -d '{"job_title": "AI Engineer", "company_name": "Acme",
       "job_url": "http://127.0.0.1:8901/basic",
       "candidate_name": "Ada Lovelace", "email": "ada@example.com",
       "phone": "+44 20 7946 0000"}'

# 2. approve — a human records the decision, with an identity and a reason
curl -X POST http://localhost:8000/api/applications/<approval id>/approve \
  -H "Content-Type: application/json" \
  -d '{"approver": "your.name", "reason": "reviewed the payload"}'
```

The approval response carries the outcome, the confirmation text and the evidence paths. The
screenshot, the action trace and the Playwright trace archive are under `data/evidence/`.
There is deliberately **no** single-call submit route: a submission without a recorded human
approval is exactly what the security model forbids.

### Tests and evaluations

```bash
python -m pytest -q          # the offline suite; no network, no key, no server
python scripts/run_eval.py   # the evaluation harness and its threshold gate
```

The evaluation report is written to `docs/evaluations/` and the measured baseline is
committed alongside it.

## The operator console

The API is the product's engine; the console is how a human drives it. It lives
in [`frontend/`](frontend) — its own package, its own toolchain — and talks to
the API over HTTP. It is a **single-operator** console: there is no login,
because the API has no authentication either.

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so the browser makes
a same-origin request and the CORS configuration is not load-bearing in
development. To point the console at another API, set `VITE_API_BASE_URL`.

| Screen | What it is for |
|---|---|
| Resume | Upload a resume, and see what the parser understood — and what it could not state |
| Matches | Search the stored corpus, with the six component scores and the explanation behind each rank |
| Tailor | Tailor a resume for one job: the tailored text, the factuality report, the ATS report, the grounded insights |
| Approvals | Prepare an application, read exactly what will be submitted, then approve or reject it |
| Tracker | Every application, its full ordered history, its evidence, and the human outcome |
| Operations | Run the corpus refresh and read what it fetched, persisted and embedded |

The console makes the safety model visible: the approve button is the only
irreversible control, it says so, and no screen ever claims an outcome the API
did not return. Every string the API returns is rendered as plain text — an
ESLint rule forbids `dangerouslySetInnerHTML` and `innerHTML` in the console's
source, so "no HTML injection path" is enforced by the toolchain.

The console's own tests:

```bash
cd frontend
npm test        # Vitest: the client, the screens, the error handling
npm run e2e     # Playwright: upload → search → tailor → prepare → approve → tracker
```

The end-to-end test drives the **real** backend and the **real** fake ATS, so
both have to be running (`python scripts/serve_fake_ats.py` for the ATS).

## API reference

| Method and path | Purpose | Added by |
|---|---|---|
| `GET /` | Service status | WS-04 |
| `GET /api/health` | Service status | WS-04 |
| `POST /api/resumes` | Upload a resume, get a validated profile | WS-04 |
| `GET /api/resumes/{profile_id}` | Read a stored profile | WS-04 |
| `POST /api/jobs/refresh` | Fetch boards → normalize → dedup → persist → embed | WS-02, WS-04 |
| `POST /api/jobs/search` | Rank the stored corpus for a profile | WS-04 |
| `GET /api/jobs/{job_id}` | Read one stored listing | WS-04 |
| `GET /api/profiles/{profile_id}/matches` | Read the match history | WS-04 |
| `POST /api/tailor` | Tailor a resume for a job, with a factuality report | WS-05 |
| `GET /api/tailored/{tailoring_id}` | Read a stored tailoring run | WS-05 |
| `GET /api/tailored/{tailoring_id}/download` | Download the rendered DOCX of a tailoring | WS-13 |
| `POST /api/applications/prepare` | Check the target, select the adapter, create an approval request | WS-06 |
| `POST /api/applications/{approval_id}/approve` | Record a human approval and execute | WS-06 |
| `POST /api/applications/{approval_id}/reject` | Record a human rejection | WS-06 |
| `GET /api/applications/approvals/{approval_id}` | Read the state of an approval request | WS-06 |
| `GET /api/applications` | List the tracked applications | WS-07 |
| `GET /api/applications/{application_id}` | Read one application and its events | WS-07 |
| `PATCH /api/applications/{application_id}/status` | Change an application status | WS-07 |
| `GET /api/applications/{application_id}/evidence` | Read the evidence records of an application | WS-13 |
| `GET /api/applications/{application_id}/evidence/{filename}` | Download one evidence artifact (screenshot, trace) | WS-13 |
| `POST /api/auth/register` | Create an account | WS-14 |
| `POST /api/auth/cookie/login` | Log in (browser transport: an HttpOnly session cookie) | WS-14 |
| `POST /api/auth/cookie/logout` | End the current session | WS-14 |
| `POST /api/auth/token/login` | Log in (bearer transport: an access token for scripts) | WS-14 |
| `POST /api/auth/token/logout` | End the current session | WS-14 |
| `POST /api/auth/forgot-password` | Request a password-reset token | WS-14 |
| `POST /api/auth/reset-password` | Set a new password with a reset token | WS-14 |
| `POST /api/auth/request-verify-token` | Request an e-mail verification token | WS-14 |
| `POST /api/auth/verify` | Verify the account with a verification token | WS-14 |
| `GET /api/auth/me` | The authenticated principal | WS-14 |
| `PATCH /api/auth/me` | Change the caller's own e-mail, password or name | WS-14 |
| `DELETE /api/auth/me` | Request the account's deletion (deactivates it and ends its sessions) | WS-14 |
| `GET /api/auth/sessions` | The caller's live sessions (without their tokens) | WS-14 |
| `POST /api/auth/sessions/revoke` | End every session of the caller | WS-14 |
| `POST /api/auth/sessions/revoke-others` | End every session except the current one | WS-14 |
| `DELETE /api/auth/sessions/{token}` | End one session of the caller | WS-14 |

The table is checked against the running application by `tests/test_docs_accuracy.py`, so a
route added without a line here fails the suite.

**Every route except `/` and `/api/health` needs a credential** (WS-14). A request
without one is refused with a `401`. There are two transports, one identity: a browser
uses the **cookie** (an `HttpOnly`, `SameSite=Lax` session cookie, with a double-submit
`X-CSRF-Token` header on every unsafe request), and a script uses the **bearer token**
(`Authorization: Bearer …`). Both resolve to the same account, and a session is a
server-side row, so it can be revoked the moment it is revoked.

## Configuration

Copy `.env.example` to `.env`. Every variable the runtime reads is in that file, with a
comment explaining what it bounds — and `tests/test_env_docs.py` fails if the file and the
code ever disagree. The settings you are most likely to change:

| Variable | Meaning | Default |
|---|---|---|
| `GREENHOUSE_BOARDS`, `LEVER_COMPANIES`, `ASHBY_ORGS` | The boards to watch, comma separated | empty (a curated list is in the example file) |
| `EMBEDDING_PROVIDER` | `fastembed` (local, no quota) or `gemini` (API) | `fastembed` |
| `EMBEDDING_MODEL` | The embedding model; its identity is persisted with the vectors | `google/embeddinggemma-2@int8` |
| `FASTEMBED_CACHE_PATH`, `CHROMA_DIR` | Model weights and vector store | `./data/fastembed`, `./data/chroma` |
| `MATCH_WEIGHTS` | JSON override for the six match weights, summing to 1.0 | the built-in weights |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` | The tailoring model (Google Gemini is the supported path; `openai-compatible` is experimental) | unset |
| `LLM_TIMEOUT`, `LLM_MAX_RPM`, `LLM_MAX_RETRIES` | Seconds per call, calls per minute, retries after the first attempt | 60, 10, 2 |
| `DATA_DIR` | The root of all runtime state | `./data` |
| `DATABASE_URL` | SQLite by default, PostgreSQL for deployment | `sqlite:///./data/app.db` |
| `SUBMISSION_POLICY` | `PREPARE_ONLY` or `REQUIRE_APPROVAL` | `REQUIRE_APPROVAL` |
| `ALLOWED_DOMAINS` | The hosts the browser may navigate to | the public ATS hosts |
| `APP_ENV`, `CORS_ORIGINS` | Production start fails when the origins are unset or `*` | `development` |
| `PLAYWRIGHT_HEADLESS` | Run the browser without a window; `false` lets you watch it | `true` |

Changing the embedding model or its dimension requires deleting `CHROMA_DIR` and re-running
the refresh: the model identity is stored with the vectors, and the store raises
`VectorStoreMismatch` rather than mixing two embedding spaces.

## Security posture

The default submission policy is `REQUIRE_APPROVAL`: an application is prepared, a human
records a decision with an identity and a reason, and only an approved record may execute.
`AUTO_SUBMIT` is defined but unreachable, and the API refuses it.

Web content is **data, never instructions**. Board HTML is neutralized at the contract, the
listing's text reaches the model inside a nonce-fenced untrusted block, and every project
bullet is stripped of injection patterns. Navigation is checked against an exact-match domain
allowlist before *and* after every hop, including on every page of a multi-step form. A
CAPTCHA or an MFA prompt stops the flow with `blocked_human_review`; the system never tries
to solve one. Every run gets a fresh browser context, so no cookie or storage survives it.
Secrets stay in the environment and out of the prompts, the logs and the browser traces.

The full threat model, the control register and the open rows are in
[`docs/SECURITY.md`](docs/SECURITY.md).

## Repository layout

```text
src/
  api/           routes, middleware (rate limit, body cap, concurrency gate), upload validation
  applications/  the adapter contract, the Playwright fake-ATS adapter, form walking, evidence
  config/        the settings object and the fail-fast configuration checks
  core/          logging with PII masking, text helpers
  db/            the SQLAlchemy models and the session factory
  evaluation/    the metric functions, the harness and the scenarios
  graph/         the LangGraph workflows (job pipeline, application) and their executors
  jobs/          the source adapters, the guarded HTTP client, normalization, dedup, requirements
  llm/           the provider clients, the embedding providers, the resilience layer, usage accounting
  matching/      the six scorers, the weights, the experience parser
  rag/           the Chroma vector store
  research/      the grounded research engine
  resume/        the parser, the profile, the tailoring, the ATS analyzer, the DOCX renderer
  security/      the allowlist, the policy, the permissions, the audit, the limits, the guards
frontend/        the operator console (Vite + React + TypeScript), its own package
migrations/      the Alembic revisions, one per workstream
scripts/         the refresh, the evaluation runner, the live-verification scripts, the fake ATS
tests/           the offline suite, the evaluation golden set, the fake-ATS pages
docs/            the plan, the architecture, the security model, the implementation roadmap
```

## Roadmap

| Milestone | Work | Outcome | State |
|---|---|---|---|
| M1 | WS-01…WS-04: foundation, discovery, matching, pipeline and API | Resume → ranked top 10 with explanations, over HTTP | Done |
| M2 | WS-05: tailoring, ATS, DOCX, research | A tailored, factuality-checked, ATS-scored DOCX per job | Done |
| M3 | WS-06, WS-07, WS-10: security preconditions, tracking, LLM hardening | A fail-closed, approval-gated, evidence-backed submission path | Done |
| M4 | WS-08, WS-09: browser depth, evaluation | Fake-ATS variants and a reproducible metrics report | Done |
| M5 | WS-11, WS-13, then the live pilot | One real posting, `PREPARE_ONLY` first, then `REQUIRE_APPROVAL` with a human in the loop; the operator console that drives it | **In progress** |

`AUTO_SUBMIT` stays unreachable. The roadmap detail lives in
[`docs/implementation/`](docs/implementation/00-OVERVIEW.md), one document per workstream.

## Known issues

These are the open ones. The defects that earlier versions of this file listed (the
substring domain match, the placeholder adapters that returned `success=True`, the boolean
approval flag, the temperature that never reached the provider) were fixed in WS-06, WS-08 and
WS-10.

- **No real job site is supported yet.** The browser layer is proven against the local fake
  ATS. A live pilot — one posting, `PREPARE_ONLY`, then `REQUIRE_APPROVAL` — is the M5
  milestone and the gate for a real-ATS adapter.
- **PDF resumes are not parsed.** DOCX, TXT and Markdown are.
- **The API has no authentication.** The rate limit bounds abuse; it does not identify a
  caller. The API is a single-operator surface and says so.
- **No data-retention policy, no malware scanning of uploads, and PII still lives inside the
  stored resume documents.** These are the open rows in `docs/SECURITY.md` §12.
- **A full-corpus search with no filter can return one result fewer than requested** and
  report `degraded=true`. This is a Chroma edge case, not a matching bug.
- **The `openai-compatible` LLM provider is experimental.** It is verified against a mock
  HTTP transport, never against a live OpenAI-compatible endpoint.
- **Six Remotive tests fail intermittently** when DNS resolution stalls, because the SSRF
  guard resolves real DNS under the mock transport. It is environmental.

## Documentation

- [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) — the intent, the phases, and the
  reconciliation appendix that records what was actually built
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the components, the runtime flows, the
  data model
- [`docs/SECURITY.md`](docs/SECURITY.md) — the threat model, the control register, the
  preconditions for autonomous submission
- [`docs/implementation/00-OVERVIEW.md`](docs/implementation/00-OVERVIEW.md) — the
  file-level roadmap, one document per workstream
- [`docs/evaluations/`](docs/evaluations/) — the evaluation harness and its measured baseline
