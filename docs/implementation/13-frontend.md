# WS-13 · Operator Console (React frontend)

Status: **Done (2026-10-21)** · Milestone: **M5** · Depends on: WS-04 (API), WS-05 (tailoring), WS-06 (approval), WS-07 (tracking), WS-12 (hardening) · Live-verified: the console against the real backend and the real fake ATS

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
| GET | `/api/tailored/{tailoring_id}/download` | — | the DOCX file | Tailor | 404 (no tailoring, or no file) |
| GET | `/api/applications/{application_id}/evidence` | — | `{evidence[{confirmation_text, status, screenshot_path, trace_path, job_url, recorded_at}]}` | Tracker | 404 |
| GET | `/api/applications/{application_id}/evidence/{filename}` | — | the artifact file | Tracker, Approvals | 400 (not a file name), 404 |
| GET | `/api/documents` | — | `{documents[{id, kind, title, filename, path, size_bytes, created_at, profile_id, job_id}], count}` | Resume, Approvals | 401 |
| GET | `/api/documents/{document_id}/download` | — | the document file | Resume, Approvals | 404 |

The last three rows are the endpoints this workstream added (BA-1, BA-2,
BA-7). They are read-only `GET`s; no existing route changed.

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

## The design system

The console is a **dossier on a desk**: an ivory page, a sheet of paper on
it, ink for the text, a lime highlighter for the marks the *agent* makes, and
a warm clay wash for the marks a *human* makes.

That last rule is the one that carries the meaning. If a mark is lime, the
agent did it — a match score, a tailored resume, a progress bar. If it is
terracotta, a person did it — the current profile, a recorded outcome, a
decision waiting for a name. The operator learns the colour once and reads
the screen faster.

### The tokens

| Token | Light | Dark | What it is for |
|---|---|---|---|
| Canvas | `#F7F5EF` ivory | `#16150F` warm charcoal | the page |
| Paper | `#FFFDF8` | `#1E1D17` | the cards |
| Ink | `#23211C` | `#F2EFE6` | the text |
| Primary | `#173D32` forest | `#D9F36A` lime | the one action |
| Agent's mark | `#D9F36A` lime | `#D9F36A` | match scores, agent progress |
| Human's mark | `#F1D6C8` terracotta | — | the operator's own decisions |
| Border | `#E3DDD0` | `#35332A` | hairlines only |
| Muted text | `#6A6459` | `#A8A294` | secondary text |

Every text pair clears WCAG AA: the lowest is the muted text on ivory at
5.4:1, the rest run from 6.3:1 to 14.8:1.

### Type and space

- **Display**: Bricolage Grotesque Variable — the headings, the brand, the
  section titles.
- **Body**: Geist Variable — everything else.
- **Container**: 1120 px, with a 68-character reading column inside it.
- **Motion**: 150–200 ms transitions that answer an action (a hover, an
  expand, a state change), one orchestrated entrance on the onboarding, and
  an agent-progress bar that moves while a long call runs. `prefers-reduced-motion`
  turns all of it off.

### What the redesign changed

| Before | After |
|---|---|
| Monochrome shadcn tokens, black primary | the ivory/forest/lime/clay system above |
| A row of plain text links | a product mark, the workflow grouped as Discover / Prepare / Track, and Operations set apart as maintenance |
| A small file input | a drop zone with the file rules, a drag target, and a keyboard-reachable button |
| One long form | the prepare form in four groups, with the candidate's details prefilled from the profile |
| A spinner for a long call | a sentence that says what the agent is doing, over a moving bar |
| A black active nav pill | a soft green wash and a hairline underline |

The rules the redesign did **not** touch: the approval gate, the statuses,
the error classes, the plain-text rule for backend strings, and the fact that
no screen claims an outcome the API did not return.

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
| `@tanstack/react-query` | server state: caching, loading/error state, the mutation lifecycle |
| `tailwindcss`, `@tailwindcss/vite` | the styling layer the shadcn components are written against |
| `cn` | the class-composition helper the shadcn components use (the current style's replacement for `clsx` + `tailwind-merge`) |
| `class-variance-authority` | the variant helper the shadcn components use |
| `@base-ui/react` | the accessible primitives the shadcn components are built on (the current style's replacement for Radix) |
| `lucide-react` | the icon set the shadcn components render |
| `react-hook-form`, `zod`, `@hookform/resolvers` | the three non-trivial forms (prepare, decision, and the validation they share), checked before the request |
| `vitest`, `@vitest/coverage-v8`, `jsdom` | the unit/component test runner and its environment |
| `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event` | component tests driven the way a user drives them |
| `msw` | the API mocked at the network boundary — the components exercise the same `fetch` path as in production |
| `@playwright/test` | the end-to-end smoke path |
| `openapi-typescript` | generates the typed client from the API's own OpenAPI schema |
| `eslint`, `typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `prettier`, `prettier-plugin-tailwindcss` | lint and format |
| `shadcn` (dev) | the component registry's CLI, and the stylesheet the components import |
| `tw-animate-css` | the animation utility the shadcn components reference |
| `@fontsource-variable/geist` | the console's typeface, installed locally (no external font request) |

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
| **BA-1** | The tailored DOCX is a server-side path (`docx_path`); the browser cannot fetch it | `src/api/routes/tailoring.py`, `src/resume/pipeline.py` | one additive route: `GET /api/tailored/{tailoring_id}/download` → a `FileResponse` of the stored DOCX, with the resolved path contained inside the allowed roots (the containment helper already exists: `src/security/paths.py`) | **implemented** — `src/api/routes/artifacts.py`, 10 tests |
| **BA-2** | The evidence screenshot is a server-side path; the browser cannot load it | `src/applications/fake_ats_adapter.py`, `src/api/routes/tracking.py` | one additive route: `GET /api/applications/{application_id}/evidence/{filename}` → a `FileResponse` of the artifact, contained inside the evidence directory | **implemented** — same file, with the bare-file-name resolution (the browser layer stores `b3046adb.png`, not a path) |
| **BA-3** | The `needs_human` questions are in `metadata.questions` of the *approve* response, but the tracked application's events do not carry them | `src/applications/tracking.py` | **no change.** The console shows the questions from the approval decision response, which is the authoritative place; a follow-up could copy them into the event metadata | no change |
| **BA-4** | There is no endpoint that lists the stored profiles, and none that browses the jobs table | `src/api/routes/` | **no change in this workstream.** The console persists the current `profile_id` client-side, and the Tailor screen's job list is built from the profile's **match history** — the jobs the profile was actually scored against | no change (documented) |
| **BA-5** | The dev CORS origins did not include the Vite default (`http://localhost:5173`) | `.env`, `src/config/settings.py` | **config only, no code change.** The console also ships a Vite dev proxy, so the same-origin mode needs no CORS at all | **done** — the origin is in `.env`, `.env.example` and the settings default |
| **BA-6** | The rate limiter keys on the transport peer, so every browser on one machine shares one bucket | `src/security/rate_limit.py`, `src/api/middleware.py` | **no change.** The transport peer is deliberately not a forwarded header. In dev the console uses the same-origin Vite proxy, so the peer is the proxy; the operator sees the 429 with its `Retry-After`, and the console honours it | no change (documented) |
| **BA-8** | The operator had no way to attach a document to an application: the prepare form asked for a **server-side path**, which no human can type, and the console had no list of the documents the account already has | `src/api/routes/applications.py`, `src/db/profiles.py`, `src/db/tailored.py` | two read-only routes: `GET /api/documents` (the account's uploaded résumés and tailored résumés) and `GET /api/documents/{id}/download`. The list is the union of the caller's profiles and tailorings, read through the scoped accessors — no new table, no migration, and no way to see another account's files | **implemented** — `src/api/routes/documents.py`, 7 tests |
| **BA-7** | The Tracker cannot show the confirmation text of a **past** submission: the tracking API answers with the application's history, not with its evidence, and the evidence rows are not exposed | `src/db/evidence.py`, `src/api/routes/tracking.py` | one additive route: `GET /api/applications/{application_id}/evidence` → the evidence records (confirmation text, status, artifact paths) | **implemented** — `src/api/routes/artifacts.py` |

### The three implemented routes, in detail

All three are in `src/api/routes/artifacts.py`, all three are `GET`, all three
are read-only, and none of them changes the behaviour of an existing route.

- `GET /api/tailored/{tailoring_id}/download`
  - 404 when the tailoring is unknown, when the file is missing, or when the
    stored path points outside the directories the application owns;
  - the DOCX file otherwise.
- `GET /api/applications/{application_id}/evidence`
  - 404 when the application is unknown;
  - the evidence records otherwise: the confirmation text, the status, the
    artifact paths and the time.
- `GET /api/applications/{application_id}/evidence/{filename}`
  - 400 when the name is not a plain file name (a separator, a parent
    reference);
  - 404 when the application, the artifact or the file is unknown;
  - the PNG or the JSON trace otherwise.

Two details the live run taught, and the tests now pin:

1. **The browser layer stores an evidence artifact as a bare file name**
   (`b3046adb.png`), relative to the evidence directory — not as a path. The
   route resolves a bare name inside the evidence directory and then applies
   the containment check, which is what actually decides.
2. **The DOCX path is relative to the working directory** (`data/tailored/…`),
   so the containment check resolves it against the process's working
   directory. A path that resolves anywhere else is refused.

The console's fallback when these routes are absent (an older backend) is
explicit: it shows the server-side path and a note that the artifact is on
the server — never a broken image and never a silent omission.

## Acceptance criteria

1. **Every screen works against the live backend on the happy path.** ✅
   Verified in a real browser against a running `uvicorn`: the resume, the
   matches (a real search over the stored corpus), the tailor, the approvals
   (a real prepare → approve against the fake ATS), the tracker and the
   operations screen.
2. **Every screen handles its documented failure paths.** ✅
   degraded search, source errors, a factuality failure, `needs_human`,
   validation errors, 404, 409, 413, 422, 429 (with `Retry-After` honoured),
   503 and the network failure each have a test and a distinct message.
3. **No HTML injection path exists from backend text.** ✅
   `no-restricted-syntax` forbids `dangerouslySetInnerHTML`, `innerHTML`,
   `outerHTML` and `insertAdjacentHTML`; a unit test renders a hostile
   description and a hostile job title and proves they stay text.
4. **The Playwright smoke test passes end to end.** ✅
   `npm run e2e` — upload → search → tailor → prepare → approve → tracker,
   in a real Chromium, against the real backend and the real fake ATS.
5. **`npm run typecheck`, `npm run lint` and `npm test` are green.** ✅
6. **The console never sends an agent or system actor, never optimistically
   updates a mutation, and never displays a status the backend did not
   return.** ✅
7. **This document's deviations table and implementation notes are filled in.**
   ✅
8. **The backend is unchanged apart from the three additive routes.** ✅
   `src/api/routes/artifacts.py` (new), `src/main.py` (one import, one
   `include_router`), and the tests.

## Deviations

| # | Plan said | Reality | Why | Impact |
|---|---|---|---|---|
| 1 | "Stop after writing it and summarize it. Do not start coding until I confirm." | the spec was written first, then executed in the same session | the instruction that accompanied the brief was to plan **and** execute, autonomously | the spec is the record of what was decided before the code was written; it is committed separately from the code |
| 2 | "Tailwind + shadcn/ui (or similar)" with Radix primitives | shadcn v4 (`base-nova`) builds on **Base UI** (`@base-ui/react`), and the class helper is the `cn` package | the component registry's current style | the primitives are still accessible and still local to the repo; no behaviour changes |
| 3 | "Vitest + React Testing Library, MSW" | MSW **v3** (the current major) | the version the registry installs | `onUnhandledRequest` became `onUnhandledFrame`; a request the mock does not answer is a test failure, which is stricter |
| 4 | TypeScript "strict" | TypeScript pinned to **5.9** | `openapi-typescript` (the generator the typed client depends on) declares a `typescript@^5.x` peer | the console loses nothing; the generator works |
| 5 | "a small component kit" | a `LinkButton` component was added | Base UI's `render` prop turns a link into an element with `role="button"` — wrong for a navigation, and it hides the destination from a middle-click | a link that navigates is a link; the button's *styling* is kept |
| 6 | "only the minimum agreed in the backend asks" | **three** additive, read-only `GET` endpoints | the console cannot fetch a server-side DOCX or screenshot without them, and cannot show a past submission's confirmation text | all three are in one new file, all three are covered by tests, and none changes an existing route's behaviour |
| 7 | The Tailor screen takes a job id | `/tailor` also lists the jobs | there is no job-listing endpoint (BA-4), and a bare input box for a `source:id` is not an operator tool | the list is built from the profile's **match history** — the jobs the profile was actually scored against |
| 8 | The client is generated from `/openapi.json` | the generated schema marks every defaulted field as optional, so the client's types would be full of `?? []` | FastAPI marks a field with a default as optional because a *request* may leave it out; a *response* always carries it | one `DeepRequired` helper in `src/lib/api/types.ts` says so in a single place |
| 9 | "the Pydantic models they return" | two shapes are written by hand | `GET /api/jobs/{id}` declares no response model, and the evidence records are not in the schema at all | both are next to the generated types, with the reason beside them |
| 10 | The console was monochrome (the shadcn defaults) | a warm ivory/forest/lime/clay system, a display typeface, a content container, restrained motion | the product had no personality and the brief asked for one | the tokens live in `src/index.css`; the shadcn components inherit them, so no component had to be rewritten to get the new look |
| 11 | The navigation was a row of plain text links | a product mark, the workflow grouped as Discover / Prepare / Track, Operations set apart, and an account menu | the operator has to find the one irreversible step in a hurry | the account menu shows the current profile and the theme; **it does not fake a signed-in user** — the API's identity work is not finished, and the menu says so |
| 12 | The e2e test proves the tailor step | the test accepts *either* the tailored resume *or* the "the language model is unavailable" message | the configured provider's daily quota is exhausted in this environment, and a console that hid that would be broken | the test still fails if the console shows neither — the honest outcome is asserted, not a specific one |

## Verification log

Every phase was run with the same gate: the console's own tests, the
typecheck, the lint, and a **live** check against a running `uvicorn` and the
local fake ATS. The backend's suite was run with the backend's changes.

| Phase | Unit tests | Typecheck | Lint | Live check | Status |
|---|---|---|---|---|---|
| A | 19 passed | clean | clean | the shell renders, the API answers through the Vite proxy (browser screenshot) | done |
| B | 24 passed | clean | clean | a resume uploaded to the real API, parsed, stored and shown with its warnings | done |
| C | 31 passed | clean | clean | a real search over the 5 854-listing corpus: 10 ranked matches with their scores; a hostile description rendered as text | done |
| D | 36 passed | clean | clean | the tailor screen against the real API; the provider's daily quota is exhausted, so the live call returns the honest 503 | done |
| E | 43 passed | clean | clean | a real prepare → approve against the fake ATS: the browser submitted the form, the evidence was captured | done |
| F | 50 passed | clean | clean | the tracked application, its ordered history and its evidence, read back from the real API | done |
| G | 54 passed | clean | clean | the refresh endpoint's report shape verified against the real API | done |
| H | 1 e2e passed | clean | clean | the whole path, end to end, in a real Chromium against the real backend and the real fake ATS | done |
| Design | the same 54 tests, re-run, plus a **keyboard-navigation e2e** in a real Chromium | clean | clean | every redesigned screen inspected in a real browser, at 1180 px and at 375 px, in both themes; the contrast of every text pair measured (the lowest is 5.4:1) | done |
| Polish | 58 tests (the suite grew with the identity work) | clean | clean | the six reported defects fixed and re-checked in a real browser at 420 px and 1180 px: no nav scrollbar, a tooltip on the profile handle, an honest search summary, a disclosure with room to breathe, no broken words in the listing, and a shine on the button | done |
| Documents | 62 tests + 7 backend tests | clean | clean | the document library, the picker (with its upload button) and the "Your documents" list, all checked against the live API in a real browser; the sticky panel's top measured at 129 px against a 113 px header, so it is no longer cut | done |
| Profiles | 66 tests | clean | clean | a document can be **chosen** from the library and is read as the current profile, and a profile the account cannot read is reported in words instead of a raw 404; checked live: the stale handle showed the explanation, and choosing the account's own résumé loaded its parsed summary | done |

**The backend's own suite**: 10 new tests for the three artifact routes, and
the whole suite green (the count moves as other workstreams land).

### What could not be verified here

- **A successful tailoring run.** The configured provider (Gemini, free tier)
  answered `429 — daily quota exhausted`, so every live tailoring call ended
  in the 503 the console renders. The *successful* tailoring path is covered
  by the unit tests against the real response shape, and the console renders
  the report; what the live run could not exercise is the model actually
  producing a tailored resume. The e2e test accepts either outcome and fails
  if the console shows neither.
- **A real job board.** The refresh and the search ran against the **stored**
  corpus, not against Greenhouse or Lever: the corpus is what the API serves
  (FU-1), and the refresh calls the boards, which is a different exercise
  (the backend's own scripts cover it).
- **A multi-user deployment.** The console is single-operator by design; the
  API has no authentication.

### Implementation notes

- **The console is a separate package.** `/frontend` has its own
  `package.json`, its own toolchain and its own tests. The runtime backend in
  `src/` is untouched apart from the three additive routes above.
- **The typed client is generated, not written.** `npm run api:types` fetches
  the running API's `/openapi.json` and regenerates
  `src/lib/api/schema.ts`. The file is committed, and the generator fails
  loudly if the API is not running — it is a development-time tool.
- **The retry policy is deliberate.** A query (a read) may be retried once,
  and only for a 5xx or a dead socket. A 429 is **never** retried
  automatically: the server said when to come back, and the console says so
  instead of hiding the refusal. A **mutation is never retried** — `approve`
  drives a browser against a third-party site, and repeating it could submit
  twice.
- **The untrusted-text rule is a lint rule.** `no-restricted-syntax` forbids
  `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`,
  `insertAdjacentHTML`, `eval` and the `Function` constructor in the
  console's source. A hostile description is rendered as text, and a unit test
  proves it.
- **No optimistic UI anywhere.** The Approvals screen shows the prepared
  summary before the decision, and the decision's result only afterwards. The
  Tracker's status form re-reads the application from the server after the
  PATCH. There is no path in the console where a status appears before the
  API returned it.
- **The human actor.** The Tracker composes `human:<name>` and offers only
  `interview`, `offer`, `rejected` and `withdrawn` — the four statuses the
  backend's actor rule accepts from a human. It never sends `agent` or
  `system`.
- **The console holds no secret.** The only configuration is
  `VITE_API_BASE_URL`. The client sends no credential and no cookie.
- **The server is the authority about the profile.** The console keeps the
  current profile's id in the browser, and that handle can go stale: it may
  name a profile another account owns, or one that has been removed. A 404
  is therefore reported in words ("that profile is not available to this
  account") with the way out — choose one of your documents — rather than as
  a raw server message.
- **The header's height is measured, not assumed.** The header is sticky,
  and the navigation wraps on a narrow screen, so its height is not a
  constant. The shell publishes it as `--header-height` (a
  `ResizeObserver`, not a state update) and the sticky panels read it — a
  hard-coded offset cut the top off the "Before you prepare" panel.
