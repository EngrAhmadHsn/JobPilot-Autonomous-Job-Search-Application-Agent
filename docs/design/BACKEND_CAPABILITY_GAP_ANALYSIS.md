# Backend Capability Gap Analysis — Figma-driven implementation (2026-11-19)

**Method:** every capability the 20 Figma screens require was checked against
the **live OpenAPI surface** (60 paths, enumerated via `app.openapi()` — not
`app.routes`, which reports 5 and lies because routes mount lazily) and against
the real data in `app.db` (8,558 jobs, 45 applications, 195 application events,
2,517 audit events, 75 form questions, 27 boards).

**Headline:** the backend is **substantially ahead** of the design. Almost every
screen is a *frontend* build against contracts that already exist. Two genuine
gaps were found, and both are real defects rather than new features.

---

## 1. Capability classification

### 1.1 Already implemented and usable (no backend work)

| Design feature | Evidence |
|---|---|
| Match scoring with an **8-component breakdown** | `src/matching/` — 8 scorers; the design's Match details (`47:488`) lists Semantic, Skill, Experience, Seniority, Location, Preference, Lexical, Occupational role — the exact set |
| Match evidence + gaps ("Kubernetes not found") | `job_matches` rows carry component evidence; `MATCH_WEIGHTS` |
| Per-passage résumé diff | `src/resume/edit.py` pairs by normalized `(title, company)` and bullet **ordinal**; `TailorResponse.tailored` + candidate profile give both sides. `frontend/src/screens/studio/diff-model.ts` already mirrors those rules |
| Keyword coverage, required vs preferred, matched vs missing | `AtsReport.keyword_coverage` (`required_hit`/`required_missing`/`preferred_hit`/`preferred_missing`) — exactly the Studio rail's "7 of 9" / "2 of 4" |
| Factuality report ("0 unsupported claims") | `FactualityReport` (`passed`, `removed_*`, `violations`) |
| ATS + style + render reports | `AtsReport`, `StyleReport`, `RenderReport` |
| Cover letter generate / store / retrieve | `TailoredResume.cover_letter`; persisted in `tailored_resumes` |
| Download the tailored document | `GET /api/tailored/{id}/download` |
| **Board questions in the board's own order**, with verdict and blockers | `ApplicationPrepareResponse.form_questions` + `blocking_questions`; 75 measured `form_questions` rows |
| Question gaps ranked by what boards actually ask | `GET /api/profiles/{id}/question-gaps` — `times_seen`, `boards`, `required`, `coverage` |
| Two-phase approval (prepare → approve/reject), `202` + run id | `POST /api/applications/prepare`, `POST /api/applications/{id}/approve` → `ApprovalDecisionResponse.run_id`, status `QUEUED` |
| Application tracking, per-application event history, human outcome recording | `GET /api/applications/{id}`, `application_events` (195 rows), `PATCH /api/applications/{id}/status` |
| Evidence listing and download | `GET /api/applications/{id}/evidence`, `…/evidence/{filename}` |
| Activity/audit trail with agent-vs-human attribution | `GET /api/audit`; 2,517 rows |
| Durable runs, worker health, admin recovery | `GET /api/runs`, `/api/runs/{id}`, `/api/admin/runs`, `/api/admin/health/workers`, `POST /api/admin/workers` |
| Corpus refresh + source status + freshness | `POST /api/jobs/refresh`, `GET /api/admin/jobs/metrics`, `job_boards` (27) |
| Search suggestions from the stored corpus | `GET /api/jobs/suggest` |
| Work eligibility per country + country picker | `GET /api/profiles/countries`, `application-profile.work_eligibility` (WS-25c) |
| EEO answers, stored separately | `GET/PUT/DELETE /api/profiles/{id}/eeo` |
| Identity, sessions, password reset | `/api/auth/*` (FastAPI-Users) |
| Per-user model credentials | `/api/llm/credentials` (GET/PUT/DELETE/test) |

### 1.2 Implemented but missing a frontend integration

| Feature | Backend | Frontend gap |
|---|---|---|
| Question gaps ("Ready for the questions that matter") | `GET /api/profiles/{id}/question-gaps` exists | Profile screen does not render the ranked-gap panel the design's `16:202` right column shows |
| Application profile (tab 2 of Profile) | `GET/PUT /api/profiles/{id}/application-profile` exists | Needs the design's 3-step stepper form (`47:374`) with the required-from-missing distinction |
| Evidence panel on application detail | `GET /api/applications/{id}/evidence` exists | Design's `47:640` "Proof, not assumptions" panel is new |
| Durable run drill-in | `GET /api/runs/{id}` exists | Design's `47:678` diagnostics screen is new |

### 1.3 Partially implemented — requires extension

| Feature | State | What the design needs |
|---|---|---|
| **Multi-status application filtering** | `_parse_statuses` accepts a list, then `status_filter = statuses[0].value if len(statuses)==1 else None` — **silently returns the unfiltered list** | See §2.1 — a real defect and a blocker for grouped stage columns |
| Stage grouping for the Applications board | The board does 5 separate single-status reads, one per column | Design groups into **4** columns (Awaiting review / Needs you / In progress / Outcome recorded) — each maps to 2+ real statuses, so it needs the multi-status fix |

### 1.4 Not implemented — requires a decision, not code

| Item | Decision |
|---|---|
| A single "home summary" aggregate endpoint | **Do not build.** The design's numbers derive from `GET /api/applications` totals (already per-status), `GET /api/audit`, and match history. Adding a bespoke aggregate would duplicate canonical state and risk drift. The console composes the four reads it already makes. |
| Persisted per-change accept/reject proposals | **Do not build.** The design shows a **read-only** diff with a legend and provenance, not per-change toggles. The backend's in-place editor already produces the final document deterministically; adding a proposal table with no design surface to drive it would be speculative. Documented as a deliberate non-goal. |
| Cover-letter versioning | **Not built.** The design shows one draft per application, which `tailored_resumes` already holds. |
| Trend/analytics history | **Not built.** The design shows no trend line — only current stage counts. Nothing fabricated is needed. |

---

## 2. The two genuine gaps

### 2.1 DEFECT: multi-status filtering silently returns everything

`src/api/routes/tracking.py`:

```python
statuses = _parse_statuses(status)
status_filter = statuses[0].value if len(statuses) == 1 else None
```

The parameter is documented as *"Filter by one or more statuses (repeat the
parameter, or pass a comma-separated list)"*, and both spellings are parsed —
then all but one are discarded. Measured against the live API:

| Query | Expected | Actual |
|---|---|---|
| *(none)* | 45 | **45** ✅ |
| `status=verified` | 24 | **24** ✅ |
| `status=verified&status=awaiting_approval` | 45 | **45** ⚠️ *coincidence* |
| `status=verified,awaiting_approval` | 45 | **45** ⚠️ *coincidence* |

With this corpus the two selected statuses happen to sum to the whole set, so
the bug is invisible — a smaller or different corpus returns **unfiltered
rows under a filtered request**. That is a silent wrong answer, which is worse
than an error.

**Why it matters for this design:** the Applications board (`16:162`) groups
four columns over a 13-value status vocabulary. Each column is a *set* of
statuses, so a correct board needs multi-status filtering. Today the console
works around it with five separate single-status reads.

**Fix:** pass the whole list through to the accessor, and keep the shareable
behaviour exact.

### 2.2 DEFECT: `Session.get_bind()` where a `sessionmaker` is expected

Already recorded in `docs/implementation/32-submission-readiness.md` as an open
item: `src/api/routes/applications.py:685` hands a `Session.get_bind()` where a
`sessionmaker` is expected, so WS-25c's country-qualified work authorization is
**inert on the API prepare path**. The design's Review screen (`16:122`) renders
board questions that depend on that answer, so this is in scope.

**Fix:** hand the session factory, not a bind.

---

## 3. Contract table for the design's screens

| Screen | Endpoint(s) | Exists? |
|---|---|---|
| Home | `GET /api/applications?status=…` (totals), `GET /api/audit`, `GET /api/profiles/{id}/matches`, `GET /api/admin/jobs/metrics` | ✅ |
| Discover | `POST /api/jobs/search`, `GET /api/jobs/suggest`, `GET /api/jobs/{id}` | ✅ |
| Match details | `GET /api/jobs/{id}` + the stored match row (8 components) | ✅ |
| Resume Studio | `POST /api/tailor`, `GET /api/tailored/{id}`, `GET …/download` | ✅ |
| Review | `POST /api/applications/prepare`, `POST /api/applications/{id}/approve`, `…/reject`, `GET /api/applications/approvals/{id}` | ✅ |
| Applications board | `GET /api/applications?status=a&status=b` — **groups of statuses** | ❌ §2.1 |
| Application details | `GET /api/applications/{id}`, `GET …/evidence`, `PATCH …/status` | ✅ |
| Profile & documents | `GET /api/documents`, `POST /api/resumes`, `GET /api/resumes/{id}`, `GET/PUT …/application-profile`, `GET/PUT …/eeo`, `GET …/question-gaps` | ✅ |
| Activity | `GET /api/audit` | ✅ |
| Operations | `GET /api/admin/jobs/metrics`, `GET /api/runs`, `GET /api/admin/health/workers` | ✅ |
| Run diagnostics | `GET /api/runs/{id}` | ✅ |
| Administration | `GET /api/admin/overview`, `POST /api/admin/workers`, `POST /api/admin/runs/{id}/resume` | ✅ |
| Authentication | `POST /api/auth/cookie/login`, `/register`, `/forgot-password` | ✅ |
| Account & security | `GET/PATCH/DELETE /api/auth/me`, `GET /api/auth/sessions`, `GET/PUT /api/llm/credentials` | ✅ |

**Conclusion: exactly one new contract is required — a correct multi-status
filter. Everything else is frontend work against existing endpoints.**
