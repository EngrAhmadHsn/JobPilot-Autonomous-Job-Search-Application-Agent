# WS-13 · Operator Console (React frontend)

Status: **In progress (2026-10-21)** · Milestone: **M5** · Depends on: WS-04 (API), WS-05 (tailoring), WS-06 (approval), WS-07 (tracking), WS-12 (hardening)

> This workstream adds the **first** frontend to the repository. The rule that
> said "no frontend in this iteration" (`AGENTS.md`, `CLAUDE.md`,
> `docs/implementation/00-OVERVIEW.md` § "Explicitly out of scope",
> `docs/PROJECT_PLAN.md` §30) is **lifted by this workstream**, for one
> reason: the backend can prepare, approve, submit and verify an application,
> but until now a human could only drive it with `curl`. The approval gate is
> the product's most important safety property and it was unusable without a
> UI.

---

## Goal

Ship a **single-user operator console** for the agent — a React client that
makes the safety model visible:

- a human **must** approve before anything is submitted, and the console
  shows exactly what will be submitted before the approve button exists;
- every outcome is **evidence-backed** — the confirmation text and the
  screenshot are shown, never paraphrased away;
- the console **never claims** an outcome the backend did not return. No
  optimistic UI, no invented status, no "submitted ✅" without a `verified`
  status from the server.

The backend remains the source of truth. The console is a thin, honest
projection of what the API returned.

## Current state

The backend is finished and live. The facts that shape this workstream, all
verified against the code on 2026-10-21:

| Fact | Where | Consequence for the UI |
|---|---|---|
| 16 API routes, no auth, CORS is env-driven | `src/main.py`, `src/api/routes/*` | a single-origin dev client; no login screen |
| `POST /api/resumes` returns `{profile_id, warnings[], profile}` | `src/api/routes/resumes.py` | the resume screen shows the parsed profile *and* the deterministic warnings |
| Search is **store-only** (FU-1): the corpus comes from the `jobs` table, not from live boards | `src/api/routes/jobs.py` | the Matches screen searches the stored corpus; "refresh" is a separate, explicit operation |
| A match carries six component scores, matched/missing requirements and an explanation | `src/matching/contracts.py` | the ranked list can show *why* a job ranked |
| `degraded` and `source_errors` are first-class fields of the search response | `src/api/routes/jobs.py` | both get a banner; `degraded` is never hidden |
| A **factuality failure is a normal 200** | `src/api/routes/tailoring.py` | the Tailor screen renders stripped items and violations as *content*, not as an error |
| Approval is two-phase: `prepare` persists the payload, `approve` executes **the persisted payload** | `src/api/routes/applications.py` | the Approvals screen reviews the prepared summary, then the decision is a separate call |
| `AUTO_SUBMIT` is unreachable; `prepare` returns 403 if the policy is `AUTO_SUBMIT` | `src/api/routes/applications.py`, `src/security/policy.py` | the console has no "submit without approval" control, by construction |
| Result statuses: `needs_human`, `form_error`, `blocked_human_review`, `verification_failed`, `unsafe_navigation`, `submitted` | `src/applications/fake_ats_adapter.py`, `src/graph/nodes.py` | each needs a distinct, honest label and a "what must a human do next" line |
| `needs_human` carries the **unanswered question text** in `metadata.questions` | `src/applications/fake_ats_adapter.py` | the UI must show the question, not just "it failed" |
| A human outcome (`interview`/`offer`/`rejected`/`withdrawn`) requires a `human:<name>` actor; the agent may never set it | `src/applications/tracking.py` | the Tracker form always sends `human:<approver>` and never an agent actor |
| An illegal transition is 409, a wrong actor is 403, an unknown status is 400 | `src/api/routes/tracking.py` | three distinct messages, not one generic "failed" |
| The rate limiter answers 429 with `Retry-After`; the concurrency gate answers 503 with `Retry-After: 5` | `src/api/middleware.py` | the console must honour `Retry-After` and say what to do |
| Evidence screenshots and the tailored DOCX are **server-side paths** | `src/applications/fake_ats_adapter.py`, `src/resume/pipeline.py` | the browser cannot read them — see BA-2 and BA-3 |
| There is **no endpoint that lists stored profiles** and none that browses jobs | `src/api/routes/` | the console persists the current `profile_id` client-side and browses only what a search returned — see BA-4 |

## Scope

The frontend lives in **`/frontend`** — its own package, its own
`package.json`, its own toolchain. The runtime backend stays exactly where it
is; `src/` is not restructured.

Six screens:

| # | Screen | Route |
|---|---|---|
| 1 | Resume — upload, parsed profile, validation warnings | `/resume` |
| 2 | Matches — search, ranked list, job detail | `/matches`, `/matches/:jobId` |
| 3 | Tailor — tailored resume, factuality, ATS, insights | `/tailor/:jobId` |
| 4 | Approvals — prepare, review, approve/reject | `/approvals` |
| 5 | Tracker — list, timeline, evidence, human outcome | `/tracker`, `/tracker/:applicationId` |
| 6 | Operations — refresh the job corpus | `/operations` |

The backend is not changed except for the two additive, read-only endpoints
in [Backend asks](#backend-asks) (BA-1, BA-2) and one config line (BA-5).
Every one of them is a **GET** that returns bytes or a file that already
exists; none of them changes the behaviour of an existing route.

## Out of scope

Not built, on purpose:

- authentication and multi-user support (the backend has none; the console
  is a single-operator tool bound to a local API);
- real-time streaming / SSE (FU-6 is deferred by the plan);
- i18n, dark mode, mobile polish, analytics;
- an admin UI for settings (the backend's settings are environment variables);
- **any `AUTO_SUBMIT` control** and **any control that bypasses the approval
  gate** — the console cannot submit an application that was not prepared
  and approved through the API;
- CAPTCHA / MFA handling (the backend stops with `blocked_human_review`; the
  console shows that status and the evidence, and does nothing else);
- a job *browser* over the whole corpus (the API has no such endpoint — BA-4).

## Screen-by-screen spec

### 1. Resume (`/resume`)

**Purpose.** Get a resume into the system and show the operator exactly what
the parser understood.

- **Upload**: a file input restricted to `.docx`, `.txt`, `.md`, with a
  client-side 5 MB check that mirrors the server's cap. The client check is
  a courtesy, not a control: the server's `validate_resume_upload` is the
  control, and its 400 is rendered verbatim.
- **In flight**: the upload button is disabled and shows a progress state
  (no double submit). The request has no client-side timeout beyond the
  browser default — the upload is fast and the server caps the body.
- **Success**: the parsed profile is rendered in sections — personal
  information, summary, skills, skill categories, experience, projects,
  education, certifications, achievements, work preferences. The
  **validation warnings** are rendered in their own block: they are
  deterministic statements about what the document did *not* state, and the
  operator needs to see them before trusting a match.
- **Current profile**: the `profile_id` is persisted in `localStorage` and
  shown at the top of every screen that needs it. "Use this profile" is the
  explicit action that writes it.
- **Errors**: 400 (bad extension, oversized, unparseable) → the server's
  `detail` string, verbatim, as the error body. 413 → "the file exceeds the
  server's body limit". 429 → honour `Retry-After`.

### 2. Matches (`/matches`, `/matches/:jobId`)

**Purpose.** Rank the stored corpus against the current profile and explain
the ranking.

- **Search form**: `query` (free text, optional), `location` (optional),
  `top_n` (1–50, default 10). The profile is the current one; the form does
  not ask for it, because there is no other profile to choose (BA-4).
- **In flight**: a progress state with the elapsed seconds. A search takes
  ~10 s, so a spinner with no text would read as a hang.
- **Degraded banner**: when `degraded` is true, a banner explains that
  semantic scoring was unavailable for part of the corpus and that the
  scores are therefore weaker. It is never collapsed into a footnote.
- **Source errors banner**: `source_errors` is a `{source: message}` map.
  Each entry is listed with its source name and message. A failing source
  degrades the report; it does not fail the search, and the UI says so.
- **Ranked list**: one row per match — title, company, location, the
  **overall score**, and the six component scores (`semantic`, `skill`,
  `experience`, `seniority`, `location`, `preference`). The explanation
  text and the matched / missing requirements are behind a disclosure, so
  the list stays scannable and the detail stays honest.
- **Job detail** (`/matches/:jobId`): the full listing (description, salary,
  remote policy, employment type, seniority, required and preferred skills,
  experience and education requirements, the application URL, the posting
  date, the source), the six component scores, the explanation, the matched
  and missing requirements, and a **Tailor for this job** action.
- **Every backend string is plain text.** No `dangerouslySetInnerHTML`, no
  markdown rendering, no HTML rendering — enforced by an ESLint rule
  (`no-restricted-syntax`), not only by convention.

### 3. Tailor (`/tailor/:jobId`)

**Purpose.** Show the tailored resume for one (profile, job) pair and — more
importantly — show whether the tailoring is *true*.

- **Run**: the tailor button starts `POST /api/tailor` for the current
  profile and the job. The call takes ~80 s, so the UI shows a progress
  state with an elapsed timer and a **Cancel** that aborts the request
  client-side (the server keeps working; the UI says so).
- **Tailored resume**: summary, highlighted skills, experience entries,
  projects, and the cover letter — all as plain text.
- **Factuality report**: the report is the product. `passed: false` means
  items were **stripped** because they were not supported by the resume:
  the removed skills, the removed experience, the removed projects and the
  violation strings are all listed. A failed report is rendered as a
  *successful* call with a warning — never as an error, and never hidden.
- **ATS report**: keyword coverage, section completeness, format risks,
  title alignment, score and notes.
- **Grounded insights**: responsibilities, tech stack, seniority signals,
  culture flags and the summary — the facts the research engine could
  ground in the listing text.
- **The DOCX**: the response carries a server-side `docx_path`. The console
  shows the path and, if the backend has the download endpoint (BA-1),
  offers a download; if the endpoint is absent the console says plainly
  that the file is on the server and where it is. It never pretends to
  download something it cannot.
- **Errors**: 404 (unknown profile or job) → the server's detail. 503 → "the
  language model is unavailable; try again later" — a distinct message, not
  a generic failure.

### 4. Approvals (`/approvals`)

**Purpose.** Make the irreversible step unmistakable.

- **Prepare**: a form for the job (title, company, the posting URL) and the
  candidate (name, email, phone), plus the optional `resume_path` and
  `cover_letter`. `profile_id` and `tailored_resume_id` are sent when they
  are known. The `custom_fields` map is a simple key/value editor bounded
  to the server's limits (the client mirrors the server's cap so the
  operator is not bounced).
- **What will be submitted**: the prepare response's `prepared_summary` is
  rendered in full — the job, the company, the URL, the adapter name, the
  **names** of the prepared form fields, the **names** of the profile facts
  the agent may answer a question with, the resume path, and the
  `requires_manual_review` flag. The summary deliberately lists field
  *names* and not the candidate's values; the console shows exactly what
  the server chose to show.
- **The decision**: approve or reject, each requiring an **approver name**
  and accepting a **reason**. Rejection does not require a reason, the
  approval does not either, but both record the approver.
- **The irreversible step is unmistakable**: the approve button is visually
  distinct (a destructive/irreversible treatment, not the primary action),
  it is disabled while the request is in flight, and the summary above it
  states in plain words what approving will do. There is no "submit" button
  anywhere in the console — the only way to reach the submission is
  `approve` on a prepared record.
- **The result**: the decision response is rendered as-is — `status`,
  `success`, `message`, and the evidence (the confirmation text, the
  screenshot, the trace path). A `needs_human` result lists the unanswered
  questions; a `blocked_human_review` result says the flow stopped at a
  challenge; a `form_error` result lists the server's errors. A
  `verification_failed` result says the submission could not be verified and
  shows the evidence that exists.
- **No optimistic UI**: the approve button shows a spinner and the result
  panel is empty until the server answers. The console never shows
  "submitted" before the server said so.

### 5. Tracker (`/tracker`, `/tracker/:applicationId`)

**Purpose.** Show the complete history of every application, and record what
actually happened to it.

- **List**: the tracked applications, newest first, with a **status filter**
  (a multi-select over the backend's status vocabulary) and **pagination**
  (`limit`/`offset` driven, with the total shown). The filter is sent as
  the backend expects it (repeated parameters or a comma-separated list).
- **Detail**: the application summary plus the **full ordered event
  timeline** — every event's type, actor, from/to status, timestamp and
  metadata. The timeline is the audit trail the operator reads; it is
  rendered in the order the server returned it.
- **Evidence**: the confirmation text (plain text, in a block) and the
  screenshot. The screenshot is a **server-side path**; if the backend
  serves it (BA-2) the console shows the image, otherwise it shows the
  path and says the file is on the server.
- **Human outcome**: a form to record `interview`, `offer`, `rejected` or
  `withdrawn`, with a note. The actor is always `human:<name>` — the
  console composes it from the approver name and **never** sends `agent`
  or `system`. The four human-outcome statuses are the only ones the form
  offers, because they are the only ones the backend will accept from a
  human actor.
- **Errors**: 400 (unknown status) → the list of known statuses. 403 (the
  actor may not set this status) → "a human outcome must be recorded by a
  human actor". 409 (illegal transition) → the message names the legal
  moves, and the console refreshes the application so the operator sees the
  real current state.

### 6. Operations (`/operations`)

**Purpose.** Run and watch the corpus refresh.

- **Trigger**: one button that calls `POST /api/jobs/refresh`. The call
  takes minutes, so the UI shows an elapsed timer, the button is disabled
  while it runs, and a Cancel aborts the client-side wait (the server's
  refresh keeps going and is resumable — the UI says so).
- **Report**: the refresh stats — `found`, `dropped`, `deduped`,
  `persisted`, `embedded`, `screened_out`, `admission_capped` — the
  embedding request budget (`planned` / `used`), `quota_exhausted`,
  `degraded_embedding` and the `source_errors` map. A run stopped by the
  daily quota says so explicitly: the rows are persisted, the next run
  resumes.
- **Concurrency**: the refresh is one of the endpoints behind the
  concurrency gate, so a 503 here is expected and the UI says "the server
  is busy, retry shortly" with the `Retry-After` value.

## API contract table

Every route the console uses, and where it is used. Verified against the
code on 2026-10-21; the shapes are generated from `/openapi.json`, not
hand-copied.

| Method | Path | Request | Success shape | Screen | Failure shapes the UI must handle |
|---|---|---|---|---|---|
| GET | `/api/health` | — | `{status, service, environment}` | app shell | 503 (backend down) → the shell shows "the API is unreachable" |
| POST | `/api/resumes` | multipart `file` | `{profile_id, warnings[], profile}` | Resume | 400 (extension/size/parse), 413 (body cap), 429 |
| GET | `/api/resumes/{profile_id}` | — | `{profile_id, profile}` | Resume | 404 |
| POST | `/api/jobs/search` | `{profile_id, query?, location?, top_n}` | `{profile_id, results[{job, match}], source_errors{}, stats{}, degraded}` | Matches | 404 (unknown profile), 422 (validation), 429, 503 (concurrency gate) |
| GET | `/api/jobs/{job_id}` | — | `{job: JobListing}` | Job detail | 404 |
| GET | `/api/profiles/{profile_id}/matches` | — | `{profile_id, matches[]}` | Matches (history) | 404 |
| POST | `/api/tailor` | `{profile_id, job_id}` | `{tailoring_id, profile_id, job_id, tailored{}, factuality{}, ats_report{}, insights{}, docx_path}` | Tailor | 404, 503 (LLM), 429, 503 (concurrency) |
| GET | `/api/tailored/{tailoring_id}` | — | the same plus `created_at` | Tailor | 404 |
| POST | `/api/applications/prepare` | `{job_title, company_name, job_url, candidate_name, email, phone, resume_path?, cover_letter?, custom_fields{}, profile_id?, tailored_resume_id?}` | `{approval_id, workflow_id, adapter_name, status:"awaiting_approval", prepared_summary{...}, application_id?}` | Approvals | 400 (domain not allowlisted / no adapter / bad custom fields), 403 (policy), 404, 429 |
| POST | `/api/applications/{approval_id}/approve` | `{approver, reason?}` | `{approval_id, workflow_id, adapter_name, status, success, message, evidence?, metadata?}` | Approvals | 403 (policy), 404, 409 (already decided) |
| POST | `/api/applications/{approval_id}/reject` | `{approver, reason?}` | the same | Approvals | 404, 409 |
| GET | `/api/applications/approvals/{approval_id}` | — | `{approval_id, workflow_id, adapter_name, job_url, job_title, company_name, status, approver?, decision_reason?, created_at, decided_at?, success?, message?}` | Approvals | 404 |
| GET | `/api/applications` | `?status=&profile_id=&limit=&offset=` | `{items[], total, limit, offset}` | Tracker | 400 (unknown status) |
| GET | `/api/applications/{application_id}` | — | the summary plus `events[]` | Tracker detail | 404 |
| PATCH | `/api/applications/{application_id}/status` | `{status, actor, notes?}` | the detail | Tracker | 400, 403 (actor), 404, 409 (illegal move) |
| POST | `/api/jobs/refresh` | — | `{stats{}, source_errors{}, embedding_requests_planned, embedding_requests_used, quota_exhausted, degraded_embedding}` | Operations | 429, 503 (concurrency) |

### Error contract

The console has exactly one error surface, and every failure lands in it.

| Class | HTTP | What the operator sees |
|---|---|---|
| Validation | 400 | the server's `detail` string, verbatim |
| Not found | 404 | "not found" plus the id that was not found |
| Conflict | 409 | the server's `detail` — for a decision already taken, or an illegal status move |
| Payload too large | 413 | "the request exceeds the server's body limit" |
| Unprocessable | 422 | the server's `detail` (the FastAPI validation array), rendered as a list |
| Rate limited | 429 | "rate limited — retry in N seconds" where **N comes from `Retry-After`** |
| Busy / unavailable | 503 | "the server is busy, retry shortly" (concurrency gate) or "the language model is unavailable" (tailoring) — the two are distinguished by the endpoint |
| Network | — | "the API is unreachable" with a retry action |

The `detail` of a FastAPI error is a string for `HTTPException` and a list of
objects for a request-validation error. The console handles both and never
renders an object as `[object Object]`.

### Status vocabulary

The console never invents a status. The backend's vocabulary is mapped
one-to-one onto a label and a "what must a human do next" line.

| Backend status | Label | What a human must do |
|---|---|---|
| `awaiting_approval` | Awaiting approval | review the prepared summary, then approve or reject |
| `needs_human` | Needs a human answer | answer the listed questions in the application form, then re-run the flow |
| `form_error` | The form was rejected | the server refused the form — read the error list and fix the inputs |
| `blocked_human_review` | Blocked by a challenge | a CAPTCHA or MFA prompt stopped the flow; complete it by hand |
| `verification_failed` | Could not be verified | the submission is not confirmed; inspect the evidence and finish by hand |
| `unsafe_navigation` | Blocked by the domain allowlist | the page redirected somewhere not on the allowlist |
| `submitted` | Submitted, not yet verified | wait for the verification step |
| `verified` | Verified | nothing — the evidence confirms it |
| `rejected` | Rejected | the application was declined (by the operator or the employer) |
| `interview` / `offer` / `withdrawn` | Interview / Offer / Withdrawn | a human outcome — nothing further from the agent |
| `discovered` / `matched` / `shortlisted` / `prepared` | Discovered / Matched / Shortlisted / Prepared | an intermediate state |
| `unknown status` | The server reported a status the console does not know | the raw status is shown verbatim — the console does not hide what it does not understand |

## Safety model in the UI

The approval gate is a *property of the backend*, and the console's job is to
make it **visible**, not to re-implement it:

1. There is no control anywhere in the console that submits an application
   without an `approve` call on a prepared record.
2. The approve action shows the prepared summary — the same payload the
   backend persisted — and the irreversible treatment.
3. The approver identity is required, and the actor string is built as
   `human:<name>`.
4. No optimistic updates on `approve`, `reject`, the status PATCH, the
   refresh, the search or the tailor. Every mutation renders the server's
   answer, and only the server's answer.
5. All backend text is rendered as plain text. An ESLint rule forbids
   `dangerouslySetInnerHTML` and `innerHTML` in `src/`.
6. The frontend holds no secrets. The API base URL is `VITE_API_BASE_URL`;
   nothing else is configurable from the browser.

## Tech choices

| Choice | Why |
|---|---|
| Vite + React 19 + TypeScript (strict) | required; strict mode plus `noUncheckedIndexedAccess` keeps the client's types honest against a generated client |
| TanStack Query v5 | the console is a server-state application: caching, refetch, loading and error state per query, and mutation lifecycle for the long calls. Hand-rolling that is the classic way to end up with two disagreeing caches |
| React Router (data router) | six screens with two nested detail views; the router gives the URLs the operator can share and reload |
| Tailwind CSS + shadcn/ui | a small, accessible component kit with no runtime dependency beyond React; the components live in the repo (they are copied in, not installed as a package) |
| react-hook-form + zod | only where a form is non-trivial (prepare, the human outcome, the search). The resume upload is a plain file input |
| Vitest + React Testing Library | component and hook tests at the speed of the Python suite; jsdom, no browser needed |
| MSW v2 | the API is mocked at the network layer, so the components talk to a real `fetch` — the same code path as production |
| Playwright (`@playwright/test`) | the end-to-end smoke path against the real backend and the fake ATS |
| No Redux | there is no client-side state machine: the server is the state. Query's cache is the store |

### Dependencies (repo rule: one line of justification each)

| Package | Justification |
|---|---|
| `react`, `react-dom` | the UI runtime |
| `react-router-dom` | routing for the six screens |
| `@tanstack/react-query` | server state: caching, loading/error state, mutation lifecycle |
| `tailwindcss`, `@tailwindcss/vite` | the styling layer the shadcn components are written against |
| `clsx`, `tailwind-merge`, `class-variance-authority` | the class-composition helpers the shadcn components use |
| `lucide-react` | the icon set the shadcn components render |
| `@radix-ui/react-dialog`, `-dropdown-menu`, `-label`, `-separator`, `-slot`, `-tooltip` | the accessible primitives shadcn/ui is built on |
| `react-hook-form`, `zod`, `@hookform/resolvers` | the three non-trivial forms, validated client-side before the request |
| `vitest`, `@vitest/coverage-v8`, `jsdom` | the unit/component test runner and its environment |
| `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event` | component tests driven the way a user drives them |
| `msw` | the API mocked at the network boundary |
| `@playwright/test` | the end-to-end smoke path |
| `eslint`, `typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `prettier`, `prettier-plugin-tailwindcss` | lint and format |
| `tw-animate-css` | the animation utility the shadcn components reference |

No other dependency is added. Nothing in the list is a runtime service: the
console talks to the API over `fetch` and nothing else.

## Execution plan

Phases run in order. Each phase ends with: **implement → unit tests green →
typecheck → lint → a live check against a running uvicorn → one commit**.
Commits are discrete, tests travel with their feature, and docs are
separate.

### Phase A — Scaffold, tooling, client, shell

- `/frontend` with Vite + React + TS strict; Tailwind; shadcn/ui (`button`,
  `card`, `dialog`, `dropdown-menu`, `input`, `table`); ESLint + Prettier;
  Vitest + RTL + MSW; Playwright.
- **Typed client generated from `/openapi.json`**: the OpenAPI document is
  fetched from the running backend, and the TypeScript types are generated
  from it (`openapi-typescript`), so the client's shapes cannot drift from
  the server. The generated file is committed and a `pnpm`/`npm run
  api:types` script regenerates it.
- **HTTP layer** (`src/lib/api/`): one `fetch` wrapper that
  - reads the base URL from `VITE_API_BASE_URL` (default: same-origin, with
    a Vite dev proxy to the API),
  - sets `Accept: application/json`,
  - attaches no credentials and no auth header,
  - converts a non-2xx into a typed `ApiError` carrying `status`,
    `detail` (string or validation array), and `retryAfter`,
  - converts a network failure into a typed `NetworkError`.
- **Error boundary + error surface**; a `QueryClient` with a deliberate
  retry policy: **no automatic retry** for 4xx, one retry for 5xx/network
  failures, and **never** a retry for `429` (the console honours
  `Retry-After` and asks the operator instead).
- **App shell**: the navigation between the six screens, the current-profile
  banner, the API-reachability indicator (`/api/health`), and the routing.
- **The ESLint rule** that forbids `dangerouslySetInnerHTML`/`innerHTML`.

### Phase B — Resume

Upload form, the parsed profile, the validation warnings, the current-profile
store (`localStorage`), and the resume error states.

### Phase C — Matches + job detail

The search form, the degraded and source-error banners, the ranked list with
the six component scores, the disclosure of the explanation and the
matched/missing requirements, and the job detail view.

### Phase D — Tailor

The tailor run with its long-call progress state, the tailored resume, the
factuality report (including the failed-but-successful case), the ATS report,
the grounded insights, and the DOCX path / download.

### Phase E — Approvals

The prepare form, the prepared summary, the approve/reject decision with the
approver name and the reason, the irreversible treatment, and the result
panel with the evidence.

### Phase F — Tracker + status PATCH

The list with the status filter and pagination, the detail with the ordered
event timeline and the evidence, and the human-outcome form.

### Phase G — Operations

The refresh trigger with its long-call state and the report.

### Phase H — End-to-end, docs, acceptance

- Playwright smoke tests against the **real** backend and the **fake ATS**:
  upload → search → tailor → prepare → approve → tracker.
- The README section.
- The final acceptance pass over this document: the deviations table filled
  in, the verification log written down, and the phase statuses updated.

## Backend asks

Each gap below was **verified against the code** on 2026-10-21, not assumed.
Each entry states the smallest change that closes it. The two marked
*implemented* are additive, read-only GETs; they change no existing route's
behaviour, and the console degrades gracefully when they are absent.

| # | Gap | Verified in | Smallest proposed change | Status |
|---|---|---|---|---|
| **BA-1** | The tailored DOCX is a server-side path (`docx_path`); the browser cannot fetch it | `src/api/routes/tailoring.py`, `src/resume/pipeline.py` | one additive route: `GET /api/tailored/{tailoring_id}/download` → a `FileResponse` of the stored DOCX, with the resolved path contained inside `TAILORED_DIR` (the containment helper already exists: `src/security/paths.py`) | **implemented** in this workstream |
| **BA-2** | The evidence screenshot is a server-side path; the browser cannot load it | `src/applications/fake_ats_adapter.py`, `src/api/routes/tracking.py` | one additive route: `GET /api/applications/{application_id}/evidence/{filename}` → a `FileResponse` of the artifact, contained inside `EVIDENCE_DIR` and restricted to the artifacts of that application | **implemented** in this workstream |
| **BA-3** | The `needs_human` questions are in `metadata.questions` of the *approve* response, but the tracked application's events do not carry them | `src/applications/tracking.py` | **no change proposed.** The console shows the questions from the approval decision response, which is the authoritative place; a follow-up could copy them into the event metadata | no change |
| **BA-4** | There is no endpoint that lists the stored profiles, and none that browses the jobs table | `src/api/routes/` | **no change in this workstream.** The console persists the current `profile_id` client-side and browses only what a search returned. A `GET /api/profiles` and a `GET /api/jobs` listing would be the natural follow-up | no change (documented) |
| **BA-5** | The dev CORS origins do not include the Vite default (`http://localhost:5173`); the configured list is `http://localhost:3000,http://localhost:8000` | `.env`, `.env.example`, `src/config/settings.py` | **config only, no code change**: add `http://localhost:5173` to `CORS_ORIGINS` in `.env` and `.env.example`. The console also ships a Vite dev proxy, so same-origin mode needs no CORS at all | **implemented** (config) |
| **BA-6** | The rate limiter keys on the transport peer, so every browser on one machine shares one bucket | `src/security/rate_limit.py`, `src/api/middleware.py` | **no change proposed** — the transport peer is deliberately not a forwarded header. In dev the console uses the same-origin Vite proxy, so the peer is the proxy; the operator sees the 429 with its `Retry-After` and the console honours it | no change (documented) |

### The two implemented routes, in detail

Both are in `src/api/routes/`, both are `GET`, both are read-only, both
contain their path inside an allowed root, and both are covered by tests.

- `GET /api/tailored/{tailoring_id}/download`
  - 404 when the tailoring or the file is unknown;
  - `FileResponse` with the DOCX media type otherwise.
- `GET /api/applications/{application_id}/evidence/{filename}`
  - 404 when the application is unknown or the file is not one of that
    application's artifacts;
  - 400 for a filename that is not a plain file name (no separators, no
    traversal);
  - the PNG/JSON artifact otherwise.

The console's fallback when these routes are absent (an older backend) is
explicit: it shows the server-side path and a note that the artifact is on
the server — never a broken image and never a silent omission.

## Acceptance criteria

1. Every screen works against the **live** backend on the happy path.
2. Every screen handles its documented failure paths: a degraded search, a
   source error, a factuality failure, a `needs_human` result, a validation
   error, a 404, a 429 (with `Retry-After` honoured) and a 503.
3. No HTML injection path exists from backend text: no
   `dangerouslySetInnerHTML`, no markdown/HTML rendering, enforced by an
   ESLint rule and by a unit test that renders a hostile description.
4. The Playwright smoke test passes end to end against the real backend and
   the fake ATS.
5. `npm run typecheck`, `npm run lint`, `npm run test` are green.
6. The console never sends an agent or system actor, never optimistically
   updates a mutation, and never displays a status the backend did not
   return.
7. This document's deviations table and implementation notes are filled in,
   and the phase statuses are updated.

## Deviations

| # | Plan said | Reality | Why | Impact |
|---|---|---|---|---|
| 1 | "Do not start coding until I confirm" | the spec was written first, then executed in the same session | the instruction to execute autonomously ("everything is your responsibility") | the spec is the record of what was decided before the code was written; it is committed separately from the code |
| 2 | — | Two additive backend `GET` routes (BA-1, BA-2) | the console cannot fetch a server-side DOCX or screenshot without them | read-only, path-contained, separately committed, and the console degrades gracefully if they are absent |
| 3 | — | `CORS_ORIGINS` gained `http://localhost:5173` (config only) | the Vite dev origin was not allowlisted | the console ships a same-origin dev proxy as well, so CORS is not load-bearing in dev |
| 4 | — | The console persists the current `profile_id` in `localStorage` | the API has no profile listing (BA-4) | the profile is per-operator and per-browser; the console shows which profile is current and lets the operator switch |

## Verification log

Filled in as the phases complete — see the per-phase results in the commit
history and the final table below.

| Phase | Unit tests | Typecheck | Lint | Live check | Status |
|---|---|---|---|---|---|
| A | — | — | — | — | not started |
| B | — | — | — | — | not started |
| C | — | — | — | — | not started |
| D | — | — | — | — | not started |
| E | — | — | — | — | not started |
| F | — | — | — | — | not started |
| G | — | — | — | — | not started |
| H | — | — | — | — | not started |
