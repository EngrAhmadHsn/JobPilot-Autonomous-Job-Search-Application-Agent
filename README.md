# Autonomous AI Job Application Agent

A backend system that reads a resume, finds matching jobs on public job-board APIs, ranks them with an explained score, tailors the resume without inventing facts, and prepares applications for human approval.

Submission runs against a local fake ATS only. Real sites stay off limits until the security gates in `docs/SECURITY.md` section 14 pass. The stack is Python 3.13, FastAPI, Pydantic, LangGraph, SQLAlchemy with Alembic, Chroma and Playwright. This iteration has no frontend.

## Status

Milestone 1 is done. You can upload a resume and get a ranked top 10 with per-component explanations over HTTP, searching about 5,300 stored listings from 15 configured boards. The last recorded test run (12 Oct 2026) had 345 passing tests, all offline.

| Area | State |
|---|---|
| Resume parsing (DOCX, TXT, MD) | Done. PDF is unsupported |
| Job discovery: Greenhouse, Lever, Ashby, Remotive | Done (WS-02, FU-2, FU-3) |
| Hybrid matching with six scorers | Done (WS-03) |
| Pipeline and REST API | Done (WS-04) |
| Daily refresh separate from search, local embeddings | Done (FU-1, FU-4, FU-7) |
| Resume tailoring with factuality validator | Core done. ATS analysis, DOCX output and research engine pending (WS-05) |
| Application workflow on a fake ATS | Works. Approval is a boolean flag and the Greenhouse and Lever adapters are placeholders |
| Security gates, tracking, browser depth, evaluation, docs | Not started (WS-06 to WS-09, WS-11). LLM hardening is partial (WS-10) |

## What you can do today

- Upload a resume with `POST /api/resumes` and get a stored profile with validation warnings.
- Refresh the job corpus with `POST /api/jobs/refresh` or `scripts/refresh_jobs.py`.
- Search the stored corpus with `POST /api/jobs/search` and read the score breakdown, matched skills and missing skills for each result.
- Run the prepare, approve, submit and verify workflow against the local fake ATS with `POST /api/applications/submit`.
- Call `tailor_resume()` from Python to get tailored content plus a report of every claim the validator removed.

## Architecture

```text
Resume ──► Parser ──► CandidateProfile ──► SQLite / PostgreSQL
                                                │
Greenhouse ┐                                    ▼
Lever      ├─► Adapters ─► Normalize ─► Dedup ─► jobs table ─► Chroma vectors
Ashby      │   (guarded HTTP)                        ▲              │
Remotive   ┘                                         │              ▼
                                     refresh (daily) │     Hybrid match ─► Rank ─► Top N + explanation
                                                     │
                                  search (store only, no board fetch)

Tailor (LLM + factuality validator) ─► Approval gate ─► Submit (Playwright) ─► Verify ─► Evidence
```

Development tooling (Cursor, ZCode, Playwright MCP, hooks, skills) stays separate from the runtime application. The runtime browser layer is the Playwright Python client.

## Approach

**Deterministic code first.** Parsing, normalization, deduplication, scoring and validation use plain Python and Pydantic models. The LLM drafts tailored text and nothing else. A deterministic validator then checks the draft against the profile.

**Public APIs only.** Each source has a documented, key-less endpoint. The project does not scrape pages and does not use LinkedIn. A guarded HTTP client blocks loopback, private and metadata addresses, spaces requests per host, retries transient failures twice and refuses redirects.

**One canonical listing.** Every adapter maps to `JobListing` with ids such as `greenhouse:stripe:8172510`. A repeated run upserts rows instead of creating duplicates.

**Explainable hybrid score.** Overall score is a weighted mean of semantic similarity (0.2), skills (0.3), experience (0.2), seniority (0.1), location (0.1) and preference (0.1). A component scores 70 when the data is missing and 25 on a hard conflict. If embeddings fail, the semantic weight spreads over the other components and the report sets `degraded`.

**Refresh and search are separate jobs.** The free Gemini embedding tier allows 20 requests a day, about 2,000 texts. The daily refresh fetches boards, deduplicates, persists and embeds only new or changed text. Search reads the store and sends one query embedding.

**Local embeddings by default.** EmbeddingGemma-2 (int8 ONNX, 768 dimensions) runs in-process through fastembed. Against the fp32 variant, 20 of 20 test queries kept at least 9 of the top 10 results. Gemini stays available through `EMBEDDING_PROVIDER=gemini`. Chroma stores the model identity with the vectors and raises `VectorStoreMismatch` instead of mixing embedding spaces.

**Truth over keyword coverage.** The tailoring validator strips skills, employers, projects and year counts that the profile does not support, then reports each removal. It returns safe content with the report instead of failing.

**Fail closed.** The approval node rejects when no decision exists. The workflow reports success only after the confirmation page text shows a submission.

**Degrade, do not crash.** A failing source lands in `source_errors`. A vector store failure sets `degraded`. A quota stop leaves completed batches in place so the next run resumes.

## Quick start

These steps use Windows PowerShell and a virtual environment named `env`.

```powershell
py -3.13 -m venv env
env\Scripts\activate
pip install -e .
playwright install chromium
copy .env.example .env        # set LLM_* only if you use tailoring
alembic upgrade head
python scripts/refresh_jobs.py
uvicorn src.main:app --reload
```

The first refresh downloads about 300 MiB of model weights into `data/fastembed` and embeds the whole corpus on CPU. Expect several hours. Each run resumes where the last one stopped.

Try the API:

```powershell
curl -F "file=@resume.docx" http://localhost:8000/api/resumes
curl -X POST http://localhost:8000/api/jobs/search -H "Content-Type: application/json" -d "{\"profile_id\": \"<id>\", \"top_n\": 10}"
```

Interactive docs are at `http://localhost:8000/docs`. Run the tests with `env\Scripts\python.exe -m pytest -q`. The suite needs no network, API key or database server.

## API

| Method and path | Purpose |
|---|---|
| `GET /`, `GET /api/health` | Service status |
| `POST /api/resumes`, `GET /api/resumes/{id}` | Upload and read a profile |
| `POST /api/jobs/refresh` | Fetch, normalize, deduplicate, persist and embed |
| `POST /api/jobs/search` | Rank the stored corpus for a profile |
| `GET /api/jobs/{id}` | Read one stored listing |
| `GET /api/profiles/{id}/matches` | Read match history |
| `POST /api/applications/submit` | Run the application workflow (fake ATS only) |

## Configuration

Copy `.env.example` to `.env`. The settings you change most often:

| Variable | Meaning |
|---|---|
| `GREENHOUSE_BOARDS`, `LEVER_COMPANIES`, `ASHBY_ORGS` | Boards to watch, comma separated |
| `EMBEDDING_PROVIDER` | `fastembed` (default) or `gemini` |
| `FASTEMBED_CACHE_PATH`, `CHROMA_DIR` | Model weights and vector store locations |
| `MATCH_WEIGHTS` | JSON override for the six weights, summing to 1.0 |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` | Tailoring model (Google Gemini) |
| `DATABASE_URL` | SQLite by default, PostgreSQL for deployment |
| `APP_ENV`, `CORS_ORIGINS` | Production start fails when origins are unset or `*` |

Changing the embedding model or dimension requires deleting `CHROMA_DIR` and re-running the refresh.

## Repository layout

```text
src/
  api/routes/     resumes, jobs, applications, health
  jobs/           adapters, guarded HTTP client, planner, registry, skills, dedup
  resume/         parser, CandidateProfile, tailoring
  matching/       scorers, weights, experience parsing
  rag/            Chroma vector store
  llm/            Gemini client, embedding providers
  graph/          job pipeline and application workflow (LangGraph)
  applications/   adapter contract, fake ATS adapter
  db/, security/, research/, config/
migrations/       Alembic revisions
tests/            offline suite and fixtures
scripts/          refresh, backfill, fixture recording, live checks
docs/             plan, architecture, security model, implementation roadmap
```

## Roadmap

| Milestone | Work | Outcome |
|---|---|---|
| M2 | WS-05: ATS analyzer, DOCX renderer, research engine, `POST /api/tailor` | A tailored, factuality-checked, ATS-scored DOCX for each job |
| M3 | WS-06 security gates, WS-07 tracking, WS-10 LLM hardening | Fail-closed, approval-gated submission with evidence and audit events |
| M4 | WS-08 browser depth, WS-09 evaluation harness | Fake-ATS variants and a reproducible metrics report |
| M5 | Controlled pilot on one real Greenhouse posting, WS-11 docs | `PREPARE_ONLY`, then `REQUIRE_APPROVAL` with a human in the loop |

`AUTO_SUBMIT` stays unreachable. The roadmap detail lives in `docs/implementation/`, one file per workstream.

## Security posture

The default policy is `REQUIRE_APPROVAL`. Web content is data, never instructions. Secrets stay in the environment and out of prompts and logs. The LLM client sends `store=False` on every call. The rules for CAPTCHA, MFA, allowlists and audit events are in `docs/SECURITY.md`. Most of them are planned for WS-06, so treat the submission path as unsafe for real sites today.

## Known issues

- The Greenhouse and Lever application adapters return `success=True` without submitting. WS-06 makes them raise.
- `is_domain_allowed()` matches by substring, so a spoofed host can pass, and no code calls it yet.
- `POST /api/applications/submit` takes approval as a boolean field with no approver identity.
- In degraded mode, listings with no stated skills score a neutral 70 and can outrank real partial matches (FU-5, to be settled with the WS-09 metrics).
- `LLM_TEMPERATURE` is read but never sent to the model.
- A full-corpus search with no filter can return one result fewer than requested and report `degraded=true`. This comes from Chroma.
- Six Remotive tests fail now and then when DNS resolution stalls, because the SSRF guard resolves real DNS under the mock transport.

## Documentation

- `docs/PROJECT_PLAN.md`: intent and phases
- `docs/ARCHITECTURE.md`: components (status sections need a refresh, WS-11)
- `docs/SECURITY.md`: threat model and control register
- `docs/implementation/00-OVERVIEW.md`: roadmap index, risks and milestones
