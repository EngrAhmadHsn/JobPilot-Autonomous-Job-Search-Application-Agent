# Implementation Roadmap — Overview

Status: **In progress** — **WS-01…31 delivered** (the per-workstream record is the status line below; the three open items the 2026-11-13 pass carried were closed on 2026-11-13 — the console now calls the measured question surface, cross-source dedup exists, and the corpus artifacts rebuild is incremental); next: the M5 live pilot · Owner: project · Created: 2026-10-11 · WS-01…14 done (WS-01…04 on 2026-10-11; M1 achieved, live over HTTP — WS-05 on 2026-10-21, live-verified — WS-09 on 2026-10-21: evaluation harness with measured baseline, extended 2026-10-21 with the system/browser/§7 metric families and an honest `--live` mode — WS-06 on 2026-10-21: security preconditions, live-verified with a real browser (12/12 checks) — WS-07 on 2026-10-21: application tracking, live-verified (21/21 checks) — WS-08 on 2026-10-21: browser-automation depth, live-verified (25/25 checks) — WS-10 on 2026-10-21: LLM client hardening, live-verified (14/14 checks) — WS-12 on 2026-10-21: runtime attack-surface hardening, live-verified — WS-11 on 2026-10-21: the docs, the env file and the ops surface, reconciled and live-verified (29/29 checks)) · **WS-13 done 2026-10-21: the React operator console (in `/frontend`), live-verified with a real browser and a real fake ATS — see [13-frontend.md](13-frontend.md)** · **WS-14 done 2026-10-22: the multi-user hardening — the API now has an identity, the data is per-user, the audit trail is attributable, and the deployment refuses to start unsafely — see [14-appsec-hardening.md](14-appsec-hardening.md)** · **WS-17 done 2026-11-05: the public site and the console's experience — see [17-frontend-experience.md](17-frontend-experience.md)** · **WS-18 done 2026-11-05: durable background execution, crash recovery, circuit breakers and the administrator recovery surface — see [18-durable-execution.md](18-durable-execution.md)** · **WS-19 done 2026-11-07: the console follow-up pass — see [19-console-follow-ups.md](19-console-follow-ups.md)** · **WS-20 done 2026-11-07: matching accuracy, BM25 lexical relevance and the candidate application profile — see [20-matching-and-profile.md](20-matching-and-profile.md)** · **WS-21 done 2026-11-08: occupational-role relevance, targeted console updates, one Work Preferences source, the suggestion-panel clip and the Tailor relevance order — see [21-recommendation-quality-and-updates.md](21-recommendation-quality-and-updates.md)** · **WS-22 done 2026-11-08: bring-your-own model key, the two-way PII mask, the résumé style policy, verified sponsorship registers and the console gap diagnosis — see [22-byok-and-reference-adoptions.md](22-byok-and-reference-adoptions.md)** · **WS-23 done 2026-11-11 (with WS-23b): the corpus — the eviction, the board registry, field completion, the age bound and ingest-time experience mining — see [23-corpus-correctness.md](23-corpus-correctness.md)** · **WS-24 done 2026-11-12 (with 24b/24c): the search path — the vectorized scan, the corpus fingerprint, the BM25 inverted index, the per-search constants and the scan memo — see [24-search-performance.md](24-search-performance.md)** · **WS-25 done 2026-11-11 (with 25b): provider depth — the form schema, the liveness check, approval expiry and the measured board questions, both libraries wired — see [25-provider-depth-and-approvals.md](25-provider-depth-and-approvals.md)** · **WS-26 Phase 2 done 2026-11-13: cross-source dedup (the merge key, the precedence rule, both admission paths); WS-26b delivered the verifier and the docstring correction — Phases 3–6 (proposals, source ordering, the robots policy, the tier-A adapters) are still not built — see [26-source-expansion.md](26-source-expansion.md)** · **WS-27 done 2026-11-12: a rejected model key reads as a configuration error — see [27-llm-key-guidance.md](27-llm-key-guidance.md)** · **WS-28 done 2026-11-13: the cold search — the rebuild left the request path (58.6 s → 11.5 s), the resident vector matrix, and the residual broken to the millisecond — see [28-cold-search-and-residual-latency.md](28-cold-search-and-residual-latency.md)** · **WS-29 done 2026-11-13: the scoring loop — two of the three ideas landed (the survivors-only materialization and the bulk lexical path), and the query-vector memo was attempted and **reverted** when it tripped the WS-14 · Phase G guard and saved nothing in the product — see [29-scoring-loop-optimization.md](29-scoring-loop-optimization.md)** · **WS-30 done 2026-11-13: the model provider fallback chain (Groq / TokenHarbor / Pollinations behind the primary), live-verified 22/22 — see [30-llm-provider-fallback.md](30-llm-provider-fallback.md)** · **WS-31 done 2026-11-13: the tailored résumé is edited into the candidate's own document, so their formatting survives, live-verified 30/30 — see [31-in-place-resume-format.md](31-in-place-resume-format.md)**

This folder is the concrete, file-level implementation roadmap that closes the gap between
`docs/PROJECT_PLAN.md` (intent) and the current codebase (reality). It was produced from a
full code audit on 2026-10-11 (68 tests green, ~2,300 LOC in `src/` + `tests/`).

Each workstream has its own document with: **Goal → Current state (file references) →
Concrete tasks (files, functions, models, routes) → Acceptance criteria → Tests →
New dependencies**.

## Document index

| Doc | Workstream | Plan phase | Milestone | Status |
|---|---|---|---|---|
| [01-data-foundation.md](01-data-foundation.md) | Alembic migrations, CORS, settings, DB models | Phase 1 (finish) | M1 | Done 2026-10-11 |
| [02-job-discovery.md](02-job-discovery.md) | Greenhouse / Lever / Remotive adapters, search planner, persistence | Phase 3–4 | M1 | Done 2026-10-11 |
| [03-matching-engine.md](03-matching-engine.md) | Real Chroma store, gemini-embedding-2, real scorers | Phase 5 + §18 | M1 | Done 2026-10-21 |
| [04-pipeline-and-api.md](04-pipeline-and-api.md) | Job workflow rewrite, resume/search/match REST API | Phase 6 + §30 | M1 | Done 2026-10-11 (live) |
| [05-tailoring-and-research.md](05-tailoring-and-research.md) | ATS analyzer, DOCX rendering, research engine | Phase 7–8 | M2 | Done 2026-10-21 (live) |
| [06-security-preconditions.md](06-security-preconditions.md) | SECURITY.md §14 gates: allowlist, approval flow, evidence, audit | Phase 2 security + §28 | M3 | Done 2026-10-21 (live, 12/12) |
| [07-application-tracking.md](07-application-tracking.md) | Application lifecycle tables, transitions, tracking API | Phase 12 | M3 | Done 2026-10-21 (live, 21/21) |
| [08-browser-automation.md](08-browser-automation.md) | Fake-ATS variants, generic adapter hardening, unknown-question pause | Phase 9 | M4 | Done 2026-10-21 (live, 25/25) |
| [09-evaluation.md](09-evaluation.md) | Golden datasets, metrics (nDCG@k, factuality rate), eval runner | Phase 13 | M4 | Done 2026-10-21 (live, 34/34) |
| [10-llm-client-hardening.md](10-llm-client-hardening.md) | Retries/timeouts, temperature fix, usage logging, provider abstraction | Cross-cutting | M1/M3 | Done 2026-10-21 (live, 14/14) |
| [11-docs-and-ops.md](11-docs-and-ops.md) | README quickstart, `.env.example`, docs reconciliation | §52 / portfolio | M5 | Done 2026-10-21 (live, 29/29) |
| [12-runtime-attack-surface-hardening.md](12-runtime-attack-surface-hardening.md) | Rate limiting, body caps, the embedding flood, XSS neutralization, the prompt fence, path containment | Cross-cutting | M3 | Done 2026-10-21 (live) |
| [13-frontend.md](13-frontend.md) | React operator console: resume, matches, tailor, approvals, tracker, operations | Plan §30 (lifted by WS-13) | M5 | Done 2026-10-21 (live, e2e green) |
| [14-appsec-hardening.md](14-appsec-hardening.md) | Multi-user security: authentication, **authorization**, per-user data isolation, audit identity, retention, CI, production posture | Cross-cutting | M3 → M5 | **Done 2026-10-22** — A0…G, all nine phases |
| [17-frontend-experience.md](17-frontend-experience.md) | The public site, the console under `/app`, the Overview/Activity/Administration screens, the motion control | Cross-cutting | M5 | **Done 2026-11-05** |
| [18-durable-execution.md](18-durable-execution.md) | Durable queue, worker isolation, embedding crash recovery, reconciliation, circuit breakers, health, admin recovery | Cross-cutting | M5 | **Done 2026-11-05** — the reliability audit matrix and six phases |
| [19-console-follow-ups.md](19-console-follow-ups.md) | Console follow-ups: the résumé library, the tailor way-in, page sizes, collapsed executions, outcome-led copy, one durable-run panel for operator and administrator | Cross-cutting | M5 | **Done 2026-11-07** — six reported items, verified live (64 documents, 41 applications, 100 audit events) |
| [20-matching-and-profile.md](20-matching-and-profile.md) | Matching accuracy: score states + a fixed denominator, BM25 lexical retrieval over the whole posting, embedding-status-aware ranking, and the candidate application profile with a question taxonomy and isolated EEO | Phase 5 + §18 | M5 | **Done 2026-11-07** — the neutral-70 defaults and the weight redistribution are gone; all suites green |
| [21-recommendation-quality-and-updates.md](21-recommendation-quality-and-updates.md) | Occupational-role relevance (a deterministic 20-family classifier, editable target roles, a mismatch cap), targeted console polling with a local clock, one shared Work Preferences editor, the suggestion-panel clip and the Tailor relevance order | Phase 5 + §18 + §30 | M5 | **Done 2026-11-08** — the named unrelated roles are gone from the top 10, measured before/after |
| [22-byok-and-reference-adoptions.md](22-byok-and-reference-adoptions.md) | Bring-your-own model key (per-user credentials, encrypted at rest, live-verified), the two-way PII mask in the tailoring prompt, the deterministic style policy, verified visa-sponsorship registers, and the console gap diagnosis; 12 reference ideas dispositioned (adopted / adapted / rejected / pending) | Cross-cutting | M5 | **Done 2026-11-08** — 27/27 live checks; two real defects found by the run (the scope dependency never published its tenant to a sync route, and the openai-compatible provider dropped the prompt on structured calls) |
| [23-corpus-correctness.md](23-corpus-correctness.md) | The corpus's correctness: the eviction that was deleting the rows that failed to refresh, the board registry and its health, the per-board field completion, the delta refresh, and the response cap that was dropping whole boards | Phase 5 + §18 | M5 | **Done 2026-11-11** (WS-23 + WS-23b) — the 8 MiB cap had silently dropped three live boards (1,696 listings); the field population went from 0%/11%/0.2% to **50%/38%/38%** (`seniority`/`remote_policy`/`salary`); the age bound, `first_seen_at` and `experience_requirements` mining all landed in WS-23b. **Still open:** cross-source dedup and the role-family allowlist |
| [24-search-performance.md](24-search-performance.md) | The search path: the vectorized similarity scan, the corpus fingerprint that survives a refresh, and the candidate context that is computed once per search | Phase 5 | M5 | **Done 2026-11-11** (WS-24 + 24b + 24c) — the scan is 68× faster; a refresh no longer costs the first search a 32 s rebuild (64.58 s → 10.63 s). **The WS-28 latency work is now its own document:** [28](28-cold-search-and-residual-latency.md). **§4a.2 closed 2026-11-13:** the rebuild is incremental — the per-listing artifacts are re-used by `content_version`, and measured at 8,558 listings a one-listing change costs **21.1 s against a 52.8 s full build**; the global BM25 index is still rebuilt whole (16 s of that 21.1 s) because its document frequencies change with any document. **§4a.1 is superseded by measurement, not open:** it described a ~9 s per-request score that WS-29's two-phase scoring has since cut to **1.47 s of a 2.18 s warm search** (measured 2026-11-13), so a per-listing score cache no longer has the win its premise assumed |
| [25-provider-depth-and-approvals.md](25-provider-depth-and-approvals.md) | The provider APIs in full: Greenhouse's published application form schema, the closed-job check, the approval expiry and its profile binding, the board registry, and the verified boards | Phase 5 + M5 | M5 | **Done 2026-11-11** (WS-25 + WS-25b) — the form schema and the liveness check verified live against stripe; all 29 boards fetched with 0 failures; **both libraries are now wired** into prepare and approve, and the board questions are measured (75 rows). **The console gap closed 2026-11-13:** the profile screen renders the measured gaps (`GET /api/profiles/{id}/question-gaps`, most-asked first, with the board count) and the approval panel renders the board's **own** question order from `form_questions`, naming each blocker. Wiring it exposed two real defects, both fixed: the coverage map had no entry for the categories the taxonomy gained in WS-25b (a profile holding "Ada Lovelace" was asked for a First Name — 30 sightings across 3 boards), and `_profile_has` walked a hand-kept attribute list that predated `work_preferences`, so a stated employment type read as unset. **WS-25c (§11) then acted on the measurement:** the boards ask authorization **qualified by the job's country** ("Are you authorized to work in the country for which you apply?", required, 12 listings), which one boolean cannot answer — so work eligibility is now stated per country with a picker on the profile screen, resolved from the posting's own location. Measured on the live corpus: the resolver reads **91.0%** of 8,558 locations and leaves 772 honestly unresolved (a resolved country is never guessed — see §11.2 on the CA→Canada collision that mis-resolved 1,004 listings) |
| [26-source-expansion.md](26-source-expansion.md) | The source expansion machinery: a repeatable board verifier, cross-source dedup, honest source ordering, a robots-aware crawl policy, and the tier-A ATS adapters | Phase 5 | M5 | **Phase 2 done 2026-11-13** — the cross-source merge key (`sha256(company|title|location)`), the field-completeness precedence rule, and the wiring into **both** admission paths (`registry.search_all` and `fetch_and_persist`), 27 tests. §3.2's fuzzy MinHash clustering is **deliberately not built**: the live 8,558-listing corpus contains **zero** cross-source groups under three normalization strengths, and a fuzzy matcher with no duplicate to collapse only adds a way to merge two different postings. **Phases 3–6 are still absent:** no proposals, no cost-aware ordering or staggered sync, no robots.txt policy, **no new adapters** |
| **WS-23b** (in [23](23-corpus-correctness.md) §12) | The unfinished field (`experience_requirements` mined at ingest), the corpus expiry signal, cross-source dedup, and **the board registry's missing test coverage** | Phase 5 | M5 | **Done 2026-11-11** — the age bound (`MAX_JOB_AGE_DAYS=120`), `first_seen_at`, ingest-time mining and 13 registry tests all landed; **cross-source dedup deferred to WS-26 Phase 2, which landed 2026-11-13** |
| **WS-24b** (in [24](24-search-performance.md) §8) | The lexical channel: the candidate set and lowered text hoisted into the shared context, the per-job record extended, and an **inverted index** for BM25 — all exact, no approximation | Phase 5 | M5 | **Done 2026-11-11** — the inverted index took `lexical_score` from 3.02 s to 1.09 s with **0 of 8,558 scores changed** |
| **WS-24c** (in [24](24-search-performance.md) §10) | The per-listing residual and a skeleton instead of a stopwatch: the per-search constants, the seniority rank as an artifact, capped evidence lists, and the in-process scan memo | Phase 5 | M5 | **Done 2026-11-12** — warm search 9.3 s → 5.7 s (4.5 s with the memo), 0 scores changed; the four "Loading…" screens now show a skeleton |
| **WS-25b** (in [25](25-provider-depth-and-approvals.md) §9) | Wiring the form schema into prepare and the liveness check into approve, then **measuring the questions the boards actually ask** and driving the profile from the measurement | Phase 5 + M5 | M5 | **Done 2026-11-11** — both wirings are in the routes; the questions are measured (75 `form_questions` rows). **The console closed 2026-11-13:** the profile screen calls the endpoint and the approval panel renders the board's own form order. The open item that made this row incomplete — "the console has not been changed to call the endpoint" — no longer holds |
| **WS-26b** (in [26](26-source-expansion.md) §11) | `scripts/verify_sources.py`, and fixing the dedup docstring that overclaims | Phase 5 | M5 | **Done 2026-11-11** — the verifier exists (284 lines, stdlib only, 17 tests) and `registry.py` now states that dedup is per-source. **Updated 2026-11-13:** the docstring now states both dedups (the per-source identity and the cross-source merge), because both exist |
| [27-llm-key-guidance.md](27-llm-key-guidance.md) | A rejected model key must read as a **configuration error**, not an outage: the four defects in the key boundary and the error taxonomy, and where the credential card belongs | Cross-cutting | M5 | **Done 2026-11-12** — 19 backend cases and 3 console cases; both gates verified to fail when reverted. **Extracted from [22](22-byok-and-reference-adoptions.md) §13 on 2026-11-13** |
| [28-cold-search-and-residual-latency.md](28-cold-search-and-residual-latency.md) | Why a cold search took 70 s: the overloaded `required_years` NULL, the miner that discarded readable bars, the startup warm, the resident vector matrix and the memo key — and where the residual 4–14 s actually goes | Phase 5 | M5 | **Done 2026-11-13** — first search after restart **58.6 s → 11.5 s**; the rebuild moved into the startup lifespan. **Still open:** the query embedding (the only large lever left, gated on [WS-09](09-evaluation.md)). **The per-listing scoring it named is closed:** WS-29's two-phase scoring plus the 2026-11-13 incremental rebuild leave a warm search at **2.18 s** (measured), so §4a.1's cache is superseded rather than pending. **Extracted from [24](24-search-performance.md) §11 on 2026-11-13** |
| [29-scoring-loop-optimization.md](29-scoring-loop-optimization.md) | The scoring loop after WS-28: the two-phase scoring so 99.6 % of `JobMatchResult` objects are never built, and the bulk lexical path skipping the evidence lists — **and the query-vector memo that it tried and reverted** | Phase 5 | M5 | **Done 2026-11-13** — commits `788434e` (survivors only) and `c75bee5` (the bulk lexical path). **The query-vector memo was reverted in `7554967`:** the WS-24c scan memo never reaches the embedder on a repeat search, so it saved nothing in the product, and it tripped `test_the_query_is_embedded_fresh_every_time`, which pins the WS-14 · Phase G rule as absolute. **Still open:** none of the three ideas changed a user-visible number |
| [30-llm-provider-fallback.md](30-llm-provider-fallback.md) | The provider fallback chain: Groq (Qwen 3.8), TokenHarbor (DeepSeek V4.1 Flash) and Pollinations (the community GLM-5.3-flash-free) behind the primary, each with its own key, model and circuit breaker | Cross-cutting | M5 | **Done 2026-11-13** — the chain lives at the provider seam so pacing, retries, breakers and the usage row are unchanged; the answering link is recorded in the usage row; **22/22 live checks**, both vendor endpoints confirmed at their key boundary. **Open:** the links are inactive until keys are added; TokenHarbor's model id is unconfirmed against the vendor |
| [31-in-place-resume-format.md](31-in-place-resume-format.md) | The deliverable keeps the uploaded résumé's format: the tailored wording is edited **into** the candidate's own document (fonts, section order, extra sections and line endings preserved), and the whole-document rewrite becomes the reported fallback | Phase 7–8 | M5 | **Done 2026-11-13** — the editor matches by identity, refuses hyperlinks/tables rather than corrupting them, and counts every edit; **30/30 live checks**. The run found two defects no unit test looked for: a text deliverable scored as an unreadable DOCX (−20 ATS points), and a text résumé's line endings rewritten by `write_text` |

## Current state — feature gap table (audit of 2026-10-11)

| Feature (plan phase) | Extent | Key evidence |
|---|---|---|
| Resume parsing → CandidateProfile (Ph 2) | ~90% | Real deterministic DOCX/TXT/MD parser (`src/resume/parser.py`), validated Pydantic profile (`src/resume/profile.py`); persisted + upload API (WS-04); no PDF parsing |
| LLM brain (unplanned addition) | **Production-shaped** | Gemini via google-genai Interactions API, structured output, `store=False` (`src/llm/client.py`); **WS-10 (2026-10-21)**: the temperature now reaches the provider, every call is bounded by a timeout, retryable failures are retried with jittered backoff, the call is paced inside the provider's per-minute budget, the token spend is written to the audit trail (counts only), and a second `openai-compatible` path exists behind the same taxonomy. Live-verified 14/14; the live run found the SDK's own retry layer sleeping for 14 hours on a `Retry-After` header — both internal retry layers are now off |
| Job sources + adapters (Ph 3) | ~90% | Real Greenhouse/Lever/Remotive adapters with recorded-JSON fixtures, SSRF-guarded HTTP client, planner + registry (WS-02); LinkedIn deliberately unregistered |
| Normalization + dedup (Ph 4) | ~90% | Normalization at the source boundary, real dedup + JobDB upsert both wired into the live search path (registry persist + the WS-04 pipeline's persist node) |
| Hybrid matching engine (Ph 5) | ~95% | Six real scorers from data (`src/matching/engine.py`), real Chroma store + `gemini-embedding-2` with content-hash cache and drift guard (`src/rag/chroma_store.py`); semantic wiring live since WS-04; FU-7 switched embeddings to the local fastembed provider (EmbeddingGemma-2 int8, default) with Gemini kept selectable |
| End-to-end job workflow (Ph 6) | 100% | Real LangGraph pipeline search→normalize→deduplicate→persist→match→rank over a dedicated Pydantic state (`src/graph/job_workflow.py`, `job_state.py`), executed by `run_job_search` with report/stats/degradation; **M1 verified live over HTTP 2026-10-11** |
| Research + RAG (Ph 7) | ~85% | Real Chroma vector store (WS-03) + a grounded research engine (WS-05: `src/research/engine.py` — listing facts verified by a deterministic grounding/injection filter); web research still deferred behind SSRF controls |
| Tailoring + factuality (Ph 8) | ~95% | `src/resume/tailor.py` LLM tailoring + deterministic factuality validator, `src/jobs/requirements.py` extraction, plus the WS-05 ATS analyzer (`src/resume/ats.py`), DOCX renderer (`src/resume/render.py`), persistence and `POST /api/tailor` |
| Application workflow graph (Ph 2#3) | ~80% | Full LangGraph prepare→approval→submit→verify with evidence DB write; the most complete area |
| Browser automation runtime (Ph 9) | **~85%** | WS-08: the adapter **walks the form** through the accessibility tree (`src/applications/form.py` — the field map, the three classes, the answer rule), fills only what the candidate's evidence covers, and stops with `needs_human` on an unknown question (plan §24). Semantic locators only (label/role), multi-page wizards, widget controls, a validation-error retry, a fresh browser context per run (SEC-07), and the fake-ATS variant suite (`tests/fixtures/fake_ats/`) driven through the full workflow. Still open: the real-ATS adapter (M5 pilot) and SEC-15 retention |
| Human approval gate (Ph 10) | **100%** | Two-phase flow with a persisted decision: `POST /api/applications/prepare` → `ApprovalRequest` row → `POST /api/applications/{id}/approve` (or `/reject`) with an approver identity, reason and timestamp; `SubmissionPolicy` (`REQUIRE_APPROVAL` default, `AUTO_SUBMIT` unreachable); the in-graph approval node still fails closed |
| Submission verification (Ph 11) | **100%** (fake ATS) | Confirmation-text verification **plus** evidence: screenshot, ordered action trace and the Playwright trace archive are captured and stored; the verify node downgrades a result whose artifacts are missing |
| Application tracking (Ph 12) | **100%** | `Application` + `ApplicationEvent` tables (WS-07), a transition matrix with an actor rule (a human outcome is only settable by a human), the graph and the API wired to it, and a tracking API (list/detail/PATCH); live-verified 21/21 |
| Evaluation (Ph 13) | **~100%** | Golden dataset (4 synthetic resumes, 25 labeled listings, 6 tailoring pairs, 8 application scenarios); pure metric modules for extraction, dedup, ranking, tailoring, ATS, relevance, the application-lifecycle (WS-07 tracking) and browser-automation (WS-08) families; one-command runner with a threshold gate; a measured baseline in `docs/evaluations/`. The `--live` mode now really uses the configured LLM and embedding provider and names them in the report; the system and browser metrics are live-verified over a real browser and a real database (34/34 checks) |
| Runtime security controls (SEC-01…21) | **~90%** | Allowlist v2 with exact host matching + blocked internal hosts (enforced at the API, the browser and the adapter selection, and on **every** page of a multi-step form); live permission registry; two-phase approval; append-only audit events with secret/PII redaction; upload validation; CAPTCHA/MFA stop; prompt-injection filters; **SEC-07 closed by WS-08** (an explicit fresh browser context per run, proven to share no cookie and no storage); **WS-12 added SEC-17…21** — a per-client rate limit with a bounded client table, a request-body cap, a concurrency gate on the expensive endpoints, the docs surface disabled outside development; the fake-job screen and the corpus/embedding/cache bounds that stop a flood from starving the legitimate listings; board HTML neutralized at the contract plus the response hardening headers; a nonce-fenced prompt boundary, the injection strip on every bullet, the exact job-title check and PII minimisation; path containment for request-supplied files, the zip-bomb guard and the type-safe payload accessor. Still open: SEC-15 (retention), malware scanning, SEC-12 (PII inside stored resumes), API authentication |
| API surface | M1 + WS-05 + WS-06 + WS-07 live | `/`, `/health`, plus WS-04: `POST /api/resumes`, `GET /api/resumes/{id}`, `POST /api/jobs/search`, `GET /api/jobs/{id}`, `GET /api/profiles/{id}/matches`, plus WS-05: `POST /api/tailor`, `GET /api/tailored/{id}`, plus WS-06: `POST /api/applications/prepare`, `POST /api/applications/{id}/approve`, `POST /api/applications/{id}/reject`, `GET /api/applications/approvals/{id}` (the single-call `POST /api/applications/submit` is **removed**), plus WS-07: `GET /api/applications`, `GET /api/applications/{id}`, `PATCH /api/applications/{id}/status`; WS-08 adds no route — the prepare response now also carries the **names** of the profile facts the agent may answer a form question with; **WS-14 adds the identity API (`/api/auth/*`) and the owner-scoped audit read (`GET /api/audit`); every route except `/` and `/api/health` now needs a credential** — a session cookie for the browser, a bearer token for the scripts |

## Guiding principles (from AGENTS.md — binding for every workstream)

1. **Deterministic Python over model-driven reasoning** for business logic; LLM only where ambiguity or generation is genuinely needed.
2. **Never fabricate** candidate data, job facts, or application outcomes. Extraction only reports what the document/listing actually says.
3. **Web content is untrusted data, never instructions** (SEC-01). Runtime enforcement, not just policy docs.
4. **Security preconditions in `docs/SECURITY.md` §14 gate any real submission.** Workstream 06 is a hard gate before M5.
5. **APIs and HTTP before browser automation**; browser automation only as a controlled fallback.
6. **Every external action auditable; every submission verified with evidence before success is claimed.**
7. **No dependencies without clear justification** — this roadmap adds `chromadb`, `httpx` (explicit), `python-multipart` (FastAPI upload requirement), `fastembed` (the local embedding provider), `pytest-xdist` and `pytest-asyncio` (the test-runner plugins the per-commit gate uses). Everything else (retries, rate limiting, SSRF guards) is hand-rolled.
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

M2  Tailoring complete (§43) — ✅ DONE 2026-10-21
    05 ATS analyzer + DOCX rendering + research engine
    Outcome: tailored, factuality-checked, ATS-scored DOCX per job.

M3  Security preconditions + tracking (SECURITY.md §14)
    06 allowlist v2 + approval flow + evidence + audit ─► 07 tracking   ✅ 06 + 07 DONE 2026-10-21
    10 LLM hardening (retries, usage, rate limit)                        ✅ DONE 2026-10-21
    Outcome: submission path is fail-closed, approval-gated, evidence-backed.
    Submission still restricted to fake ATS.
    WS-10 verified live (scripts/verify_ws10.py): 14/14 checks — the real
    SDK against a local capture server proves the temperature is on the wire
    and the privacy flag is sent, a throttled call fails in seconds instead
    of sleeping for Retry-After, a 429-then-200 is one logical call and two
    attempts, and the usage row carries the counts and no prompt. The run
    found three real defects, all fixed (see the workstream doc).
    WS-06 verified live (scripts/verify_ws06.py): 12/12 checks against a real
    HTTP server and a real Chromium browser.
    WS-07 verified live (scripts/verify_ws07.py): 21/21 checks — the whole
    lifecycle is tracked, and the history survives a restart.

M4  Depth + proof
    08 browser variants + adapter hardening ─► 09 evaluation harness   ✅ 08 + 09 DONE
    Outcome: measurable metrics (extraction, ranking, factuality, form
    completion) reproducible via scripts/run_eval.py.
    WS-08 verified live (scripts/verify_ws08.py): 25/25 checks against a real
    HTTP server, a real Chromium browser and a real database — every fake-ATS
    variant through the full prepare → approve → submit → verify flow, the
    unknown-question pause, the challenge stop, the validation retry, the
    session-isolation proof, and the evidence on disk.
    WS-09 verified live (scripts/verify_ws09.py): 34/34 checks against a real
    HTTP server, a real Chromium browser and a real database — the eight
    application scenarios through the real workflow, the application-lifecycle
    and browser-automation metrics computed from the tracking rows the
    workflow actually wrote, and the offline report regenerated. The live
    verification also found and fixed a real defect in the submit node: a
    failed evidence write used to cancel the tracking writes, leaving the
    audit trail claiming an application had never been submitted.

M5  Controlled live pilot + docs
    Single real Greenhouse posting, PREPARE_ONLY → REQUIRE_APPROVAL with a
    human in the loop; 11 README/docs reconciliation.
    AUTO_SUBMIT remains disabled and out of scope.
    ✅ 11 README/docs reconciliation DONE 2026-10-21 (live-verified 29/29)
    ⬜ The live pilot itself — the remaining M5 work
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
| `pytest-xdist>=3.8.0` | 07 | Test-runner plugin only — no runtime code. The suite runs in ~90 s serially and ~31 s with `-n 4`, and every commit in a workstream is gated on a green suite, so the gate is the cost centre. `pytest` and `ruff` are already project dependencies, so this follows the existing convention |
| `pytest-asyncio>=1.4.0` | 11 | Test-runner plugin only — no runtime code. 53 tests are `async def` and carry `@pytest.mark.asyncio`; the plugin was present in the developer environment but **undeclared**, so a clean `pip install -e .` produced a suite with 68 failures. Found by the WS-11 clean-environment acceptance run, and declared here |

Retries, backoff, rate limiting, SSRF guards, and audit sanitization are implemented by hand — no `tenacity`, no `slowapi`, per the no-unjustified-dependencies rule.

## Risk register

| Risk | Mitigation |
|---|---|
| Gemini free-tier quota exhaustion (embeddings + tailoring) | Content-hash embedding cache (03), token-bucket rate limiter (10), Batch API documented as future option at 50% price |
| `gemini-embedding-2` space is version-locked (incompatible with 001) | Model name + dimension persisted in Chroma collection metadata; re-embed procedure documented in 03 |
| Greenhouse/Lever/Remotive response shape changes | Adapter isolation, recorded-JSON fixtures via `httpx.MockTransport`, normalizer never trusts optional fields |
| SQLite (dev) vs PostgreSQL (deploy) JSON/type differences | Alembic migrations authored once, tested on both engines (01); JSON columns kept portable |
| Untrusted job text influencing the agent | **Done (WS-06)**: allowlist + navigation guards + the shared injection filter (`src/security/injection.py`) + `tests/test_injection_policy.py`, proving page text only ever flows as data |
| Placeholder adapters claiming success (`greenhouse_adapter.submit` returns `success=True`) | **Done (WS-06)**: they now raise `PermissionError`; the permission registry makes it impossible for an unregistered adapter to reach the submit node |
| Windows dev-environment quirks (Playwright browsers, paths) | Playwright already proven on this machine (fake ATS adapter); evidence/output paths under `data/` are created by code, not assumed |
| ToS/legal exposure from job sources | Only public, documented board APIs (no scraping, no LinkedIn); polite rate limiting per host (02) |

## Explicitly out of scope

- ~~React/frontend (plan §30)~~ — **lifted by WS-13** (2026-10-21). A React
  operator console now lives in `/frontend`, as its own package with its own
  toolchain; the runtime backend in `src/` is unchanged and the console
  consumes the existing API over HTTP. The scope, the API contract and the
  acceptance criteria are in [13-frontend.md](13-frontend.md).
- LinkedIn job retrieval (no public API; the placeholder adapter stays disabled).
- CAPTCHA/MFA bypass of any kind (SEC-09) — flows stop with `blocked_human_review`.
- `AUTO_SUBMIT` policy enablement — implemented as unreachable enum value until a future, separately-approved decision.
- Kubernetes/microservices/message brokers (plan §47) — modular monolith.
- Web-crawl company research in v1 (05) — research is grounded in listing text only; URL fetching comes later behind SSRF controls.
