# JOBPILOT-UX-01 — Repository audit and design contract (WS-33 / WS-UX-01)

**Status:** Complete · **Date:** 2026-11-17 · **Baseline:** tag `v1.0.1` (`80af039`), branch `main`
**Scope:** read-only audit + baseline screenshots. No application code was changed.
**Visual authority:** [`docs/Redesign Image.png`](../Redesign%20Image.png) and
[`docs/JobPilot Career Dashboard.png`](../JobPilot%20Career%20Dashboard.png)
**Companion contract:** [`JOBPILOT-DESIGN-SYSTEM.md`](JOBPILOT-DESIGN-SYSTEM.md)

> Every claim about code carries a `file:line` reference. Source outranks docs;
> where a document disagrees with the source, the source is recorded as the
> contract and the document is listed as stale (§3).

---

## 1. Method

1. Read `frontend/src/routes.tsx`, every module in `frontend/src/screens/**`, the
   shared components they render (`components/common`, `components/ui`,
   `components/observability`, `components/profile`, `components/documents`,
   `components/layout`), and `lib/{api,polling,status,observability,profile}`.
2. Dumped the backend's real route surface with `app.openapi()` via the venv
   interpreter (`env/Scripts/python.exe`), because `app.routes` under-reports
   lazily mounted routers. Measured count: **67 operations**.
3. Cross-checked every frontend call site in `lib/api/endpoints.ts` and the three
   browser-constructed download/evidence URLs against that surface.
4. Started the stack on the default ports (backend 8000, Vite 5175 — see §6),
   registered a throwaway account through the real API, seeded it with the
   product's own flows (one fixture résumé upload, one stored-corpus search, two
   prepare-only applications — **nothing was approved or submitted**), and
   captured the baseline with Playwright/Chromium.
5. Measured WCAG 2.2 contrast for every status tone and the alpha-modified text
   colours the screens actually render (§5).

---

## 2. Route, screen and API map

### 2.1 Backend route truth (`app.openapi()`)

**67 operations** across 11 router modules (`src/api/routes/__init__.py`). The
master prompt's "67-route surface" is confirmed at the current `main`.

### 2.2 Frontend route tree (`frontend/src/routes.tsx`)

15 route objects: 2 public (`/` landing at :134, `/sign-in` at :135), the
`/app` shell at :137 with **12 authenticated children** (:146-161), and a
catch-all `Navigate to="/"` (:165). Every screen is lazy-loaded (:25-94);
`AppShell` and `SignInScreen` are eager.

| Route | Screen module | Nav label (nav-groups.tsx) |
|---|---|---|
| `/app` (index) | `screens/overview-screen.tsx` | Overview |
| `/app/resume` | `screens/resume-screen.tsx` | Resume |
| `/app/profile` | `screens/profile-screen.tsx` | Profile |
| `/app/matches` | `screens/matches-screen.tsx` | Matches |
| `/app/matches/:jobId` | `screens/job-detail-screen.tsx` | (linked from Matches) |
| `/app/tailor` | `screens/tailor-screen.tsx` `TailorIndexScreen` | Tailor |
| `/app/tailor/:jobId` | `screens/tailor-screen.tsx` `TailorJobScreen` | (linked from Matches/Tailor) |
| `/app/approvals` | `screens/approvals-screen.tsx` | Approvals (group "Prepare") |
| `/app/tracker` | `screens/tracker-screen.tsx` `TrackerScreen` | Tracker (group "Track") |
| `/app/tracker/:applicationId` | `screens/tracker-screen.tsx` `TrackerDetailScreen` | (linked from Tracker) |
| `/app/activity` | `screens/activity-screen.tsx` | Activity |
| `/app/operations` | `screens/operations-screen.tsx` | Operations (`ADMIN_NAV`, shown to all) |
| `/app/admin` | `screens/admin-screen.tsx` | Administration (`ADMIN_NAV`, superuser only, courtesy-only gate — server enforces) |

### 2.3 Frontend → backend call map

`frontend/src/lib/api/endpoints.ts` declares **49 call sites**. Every one matches
a real OpenAPI operation. Three further backend URLs are constructed directly in
components (all valid routes):

- `GET /api/documents/{document_id}/download` — `components/documents/document-picker.tsx:92`
- `GET /api/tailored/{tailoring_id}/download` — `screens/tailor-screen.tsx:542`
- `GET /api/applications/{application_id}/evidence/{filename}` — `screens/approvals-screen.tsx:346` and `screens/tracker-screen.tsx:439`

**Backend routes no console code calls (18):** `GET /` (root), `GET
/api/health/live`, `GET /api/health/ready`, `GET /api/auth/sessions`, `DELETE
/api/auth/me`, `PATCH /api/auth/me`, `DELETE /api/auth/sessions/{token}`, `POST
/api/auth/token/login`, `POST /api/auth/token/logout`, `POST /api/auth/verify`,
`POST /api/auth/request-verify-token`, `POST /api/auth/reset-password`, `POST
/api/auth/forgot-password`, `POST /api/auth/sessions/revoke`, `POST
/api/auth/sessions/revoke-others`, plus (notable product gaps) `GET
/api/documents/{document_id}/download` is called only from the picker,
`/api/applications/approvals/{approval_id}` has a typed client
(`endpoints.ts:333`) that **no screen currently uses** (the Approvals screen
reads the decision out of the prepare/approve response instead), and the
session-management surface is entirely unused. No frontend call points at a
route that does not exist — **zero contract mismatches at the path level**.

**Contract drift recorded (behavioural, not path-level):**

1. **Audit page cap.** `GET /api/audit` defaults to `limit=100`, max 500
   (`src/api/routes/audit.py:36`). The console calls `api.audit()` with **no
   limit** (`endpoints.ts:527`), so every consumer — Overview stat tiles
   (`overview-screen.tsx:37-41,150-154`), Activity summaries and pagination
   (`activity-screen.tsx:45-49,96-120,200-206`) — counts and pages the **newest
   100 events only**. The Activity tile hints this honestly ("In the trail the
   API returned", `activity-screen.tsx:100`); the Overview tile does not ("Agent
   and human steps in the audit trail", `overview-screen.tsx:153`).
2. **Overview application counts come from a 200-row page.**
   `api.listApplications({ limit: 200 })` (`overview-screen.tsx:33`); the
   "Tracked applications" tile and the approval/closed counts (:52-58) are
   computed from that page. An account with more than 200 applications
   undercounts silently. The Tracker itself uses server pagination and the
   server's `total` correctly (`tracker-screen.tsx:96-114,168-171`).
3. **Approve contract.** The backend still accepts an `approver` field but
   **ignores it** (`src/api/routes/applications.py:191-207`); the frontend
   correctly sends `{reason}` only (`approvals-screen.tsx:488`). Doc 13's API
   table still lists the approver as a live field (§3 below).
4. **Approval `202` + run id.** `POST /api/applications/{approval_id}/approve`
   answers 202 with a run id (`src/api/routes/applications.py:805,832`); the
   console's decision banner handles `submitted | queued | refused`
   (`approvals-screen.tsx:205-224`) — correct — but the primary action button
   still reads **"Approve and submit"** (`approvals-screen.tsx:788`), which doc
   32 itself flags as an open defect (§3).

### 2.4 Status-presentation contract (`frontend/src/lib/status.ts`)

> **Concurrency note:** while this audit ran, WS-34 (shell) modified
> `status.ts`, `index.css` and the layout components in the shared working
> tree (file mtimes 00:50-01:20). WS-34 **added an `icon` field per status**
> (Lucide export name, `status.ts:15-40`) and replaced the sidebar tokens; the
> status **vocabulary, tones and next-step lines are unchanged**, so the
> contract below holds. Line numbers for the three shell-owned files refer to
> the tree as of 2026-11-17 01:46; screen files are untouched by WS-34 and
> their references are stable.

One backend state → exactly one label/tone/next-step line
(`status.ts`, `APPLICATION_STATUSES`/`RESULT_STATUSES`/`APPROVAL_STATUSES`);
unknown statuses render verbatim in a neutral tone, never hidden, never
coloured as danger (the `describeStatus` fallthrough; null-prototype map
guards prototype pollution). Tones: `neutral | info | progress |
success | warning | danger`. Application states covered:
`discovered, matched, shortlisted, prepared, awaiting_approval, submitted,
verified, rejected, interview, offer, withdrawn` (:27-91); result states:
`needs_human, form_error, blocked_human_review, verification_failed,
unsafe_navigation, QUEUED` (:93-134); approval states: `pending, approved,
rejected, executed, failed` (:136-162). Human-settable outcomes are exactly
four (`status.ts:188-193`) and the backend enforces the actor rule
(`src/api/routes/tracking.py`, referenced from `13-frontend.md:50`).

Badges render these consistently via `components/common/status-badge.tsx:14-21`.
Audit action labels are a separate, equally closed vocabulary in
`lib/observability.ts:23-50` (unknown actions shown verbatim, :53-60).

---

## 3. Stale-documentation findings

Source outranks docs; each item names the doc's claim, the current source, and
the verdict. No contract was invented to reconcile them.

| # | Document claim | Current source | Verdict |
|---|---|---|---|
| 1 | `13-frontend.md:39` "16 API routes, no auth, CORS is env-driven" | 67 operations, session auth + CSRF (`src/api/middleware.py:102-107`, `src/auth/csrf.py`) | **Stale** — Phase-0 snapshot; the doc's own scope section (:55-72) already describes a later state, but the line remains misleading |
| 2 | `13-frontend.md:63-72` six screens at `/resume`, `/matches`, `/approvals`… | Routes live under `/app/*` with 12 children (`routes.tsx:146-161`); Overview/Activity/Admin/Profile exist | **Stale** — table predates WS-17's route split and four screens |
| 3 | `13-frontend.md:286` approve request body `{approver, reason?}` | `approver` is accepted but ignored (`src/api/routes/applications.py:203-207`: "Ignored. The approver is the authenticated principal.") | **Stale** — the frontend already sends reason-only (`approvals-screen.tsx:488`) |
| 4 | `17-frontend-experience.md:19-21` "no public page… sign-in at every path" and :27 "39 routes across ten router modules" | Public landing at `/` + `/sign-in`; 67 routes | **Stale** — §0 is a Phase-0 snapshot and is now the opposite of the shipped state (§3 of the same doc documents the split) |
| 5 | `20-matching-and-profile.md:121` "The profile screen displays work preferences but has no editing UI" | `WorkPreferencesCard` is rendered by the Profile screen (`application-profile-panel.tsx:97`) and the Résumé screen (`resume-screen.tsx:398`), sharing one source | **Stale** — superseded by WS-27 |
| 6 | `22-byok-and-reference-adoptions.md:421` "The console's `api:types` generation needs no running server: dumping…" | `frontend/scripts/generate-api-types.mjs:18-19` fetches `http://127.0.0.1:8000/openapi.json` from a **running** server | **Stale** — the tool changed; the "no running server" property no longer holds (and is why WS-33 is forbidden from running it) |
| 7 | `32-submission-readiness.md:457` "The button still says 'Approve and submit' while the route now answers 202 + a run id" | Still true: `approvals-screen.tsx:788` renders "Approve and submit" | **Known open defect, still open** — the decision banner tells the truth (:219-224) but the button label implies immediate submission |
| 8 | ATS weighting 45/20/20/15 (`JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md:98`) | `src/resume/ats.py:36-39` — `keywords 0.45, sections 0.20, title_alignment 0.20, format_safety 0.15` | **Confirmed current** — later workstreams may print these numbers; the ATS panel does not print them today (`tailor-screen.tsx:254-307`) |
| 9 | Docs 19, 21, 25, 31 behaviours (profile fallback :29-35, ranked dedup + 10-row paging `21:510,531`, question-gaps + countries `25:542-543,747-750`, in-place render report `31:62,210`) | All verified against `hooks/use-profile-fallback.ts`, `matches-screen.tsx:36,259`, `endpoints.ts:230-246`, `tailor-screen.tsx:122-184` | **Current** — no drift found |

---

## 4. Per-screen inventory

Polling constants come from `lib/polling.ts` (budget ≤10 req/min per resource;
hidden tabs pause, `polling.ts:24-28`). Screens are lazy-loaded
(`routes.tsx:7-24`). Tests: 40 unit files under `frontend/src/**` and 2 E2E
specs (`frontend/e2e/smoke.spec.ts`, `suggestions.spec.ts`).

### 4.1 Overview `/app` (`overview-screen.tsx`, 287 lines)
- **Purpose:** "what is going on" — next actions, four stat tiles, actor split, library count, recent audit feed.
- **API:** `listApplications({limit:200})` :33, `audit()` :39 (both poll 30 s, `OVERVIEW_POLL_MS`), `documents()` :45 (no poll).
- **States:** populated; `nextActions` empty state "Nothing needs you" :162-166; per-query error notices :129-130; loading only via skeletons of pending text.
- **Truth rules:** "Data read … · refreshes every 30s" :119-126 — honest polling label. **Gap:** tile counts derive from a 200-item page and an unparameterised audit call (§2.3).
- **Tests:** `overview-screen.test.tsx` (39 lines — thin: asserts render only).

### 4.2 Résumé `/app/resume` (`resume-screen.tsx`, 452 lines)
- **Purpose:** onboarding + upload + document library + shared work-preferences editor.
- **API:** `uploadResume` :166; documents + profile via `useProfileWithFallback` (`hooks/use-profile-fallback.ts:28-101`); `WorkPreferencesCard` PUTs the application-profile.
- **States:** no-profile upload flow :307-356; replace flow :252-305; file-error banner :266-271,316-321; upload pending (agent-progress bar) :272-279; success banner :283-293; parse warnings :359-375; library empty/loading/error (`document-picker.tsx:219-240`).
- **Tests:** `resume-screen.test.tsx` (241 lines), `document-accessibility.test.tsx`.

### 4.3 Profile `/app/profile` (`profile-screen.tsx`, 125 lines)
- **Purpose:** user-confirmed answers first (WS-27 order), model credential, résumé facts folded last.
- **API:** via `ApplicationProfilePanel` (GET/PUT application-profile, EEO GET/PUT/DELETE, countries), `ModelCredentialsCard` (llm credentials), résumé profile from the fallback hook.
- **States:** three distinct — resolving / needsResume / populated — deliberately not confused (`profile-screen.tsx:41-60`).
- **Tests:** `profile-screen.test.tsx` (105 lines), plus component tests for answers/credentials/countries/preferences.

### 4.4 Matches (Discover) `/app/matches` (`matches-screen.tsx`, 465 lines)
- **Purpose:** stored-corpus search with ranked results and reasons.
- **API:** `searchJobs` mutation :279-298 (store-only; copy says so :344-347); result carried by a disabled query + localStorage mirror :48-81.
- **States:** no-profile empty :300-310; pending skeleton :417-423; degraded + source-error banners :206-241; no-match empty :432-436; client-side 10-row pagination of the ranked slice :313-323 (server slice ≤ 50; not a partial server page — the search returned the whole ranked result).
- **Truth rules:** `describeSearch` prints stored-corpus scope, never "fetched from boards" (:93-110).
- **Tests:** `matches-screen.test.tsx` (382 lines).

### 4.5 Job detail `/app/matches/:jobId` (`job-detail-screen.tsx`, 273 lines)
- **Purpose:** complete listing + match reasoning rebuilt from persisted history (`matchFromHistory` :33-83, safe accessors for pre-role rows :54-56).
- **API:** `getJob` :95-99, `getProfileMatches` :101-106.
- **States:** skeleton :108-119; error :121-123; no-match-history empty :183-188; the one untrusted→link conversion is guarded by `isSafeLinkUrl` :239-255.
- **Tests:** covered indirectly via matches tests; no dedicated file (gap, minor).

### 4.6 Tailor `/app/tailor` and `/app/tailor/:jobId` (`tailor-screen.tsx`, 730 lines)
- **Purpose:** per-job tailoring with the full report stack (factuality, render, style, ATS, insights, tailored content).
- **API:** `tailor` :438-444 (300 s budget), `getJob`, ranked `getProfileMatches(limit:25)` :581-592, `useQueries` per entry :596-605.
- **States:** needs-résumé empty :446-461,619-637; unknown job (404) :463-479; pending with cancel (abandons the wait, server continues) :509-521; result banner with stored id + server path + format-true download label :527-552 (WS-31); factuality failure rendered as content, not error :51-119.
- **Truth rules:** the run is labelled as taking ~a minute; render panel distinguishes in-place vs regenerated :130-161.
- **Tests:** `tailor-screen.test.tsx` (333 lines, includes the download URL).

### 4.7 Approvals `/app/approvals` (`approvals-screen.tsx`, 862 lines)
- **Purpose:** prepare (persist the exact payload) → inspect (board questions in board order, WS-25b) → decide (approve/reject).
- **API:** `getResume` prefill :427-431, `prepareApplication` :450-475, `approve`/`reject` :477-490; `DocumentPicker` for the résumé path.
- **States:** before-prepare panel :814-850; prepared payload panel with `form_questions` + `blocking_questions` :118-163,687-690; decision outcome trichotomy submitted/queued/refused :205-224; queued shows run id and "Nothing has reached the employer yet" :265-273; challenge banner :306-315; evidence block incl. screenshot via the evidence-file route :342-356; no-approver field (WS-14) :53-64.
- **Truth rules:** "Approving executes exactly this payload — it is not rebuilt from the form" :682-684. **Gap:** the button label (§2.3-4); the sticky approval `GET` client is unused (§2.3).
- **Tests:** `approvals-screen.test.tsx` (318), `approvals-screen-form-questions.test.tsx` (176).

### 4.8 Tracker `/app/tracker` + detail (`tracker-screen.tsx`, 535 lines)
- **Purpose:** server-paginated application list with status filters; detail with fields, evidence, ordered history, human-outcome form.
- **API:** `listApplications({status,limit:10,offset})` :96-103; `getApplication` :290; `listApplicationEvidence` :296 (retry:false); `updateApplicationStatus` :303.
- **Truth rules:** the counter is the server's `total` :114,168-171; four human outcomes only, actor is the session :283-287; evidence emptiness says "Nothing is claimed" :395-400; history is the server's :520-529.
- **Responsive:** the table drops its two timestamp columns below `md` rather than scrolling :180-194.
- **Tests:** `tracker-screen.test.tsx` (184).

### 4.9 Activity `/app/activity` (`activity-screen.tsx`, 212 lines)
- **Purpose:** audit feed + executions grouped by `workflow_id` (`lib/observability.ts:110-138`), paged 10.
- **API:** `audit()` poll 30 s :45-49.
- **Truth rules:** "This is not a live stream" banner :83-90; "Data read … refreshes every 30s" :73-80; attention filter resets paging :157-175; executions capped at 5 with an honest count :133-141. **Gap:** everything is computed from the ≤100-row default page (§2.3-1).
- **Tests:** `activity-screen.test.tsx`, `activity-screen-polling.test.tsx`.

### 4.10 Operations `/app/operations` (`operations-screen.tsx`, 275 lines)
- **Purpose:** queue a corpus refresh; follow the durable run and its embedding child.
- **API:** `listRuns` (adaptive 20 s/60 s) :51-56, `refreshJobs` :74-80, `getRun` for tracked + child (terminal runs polled never) :82-107.
- **Truth rules:** the tracked run is **derived**, survives reload :58-72; progress is the backend's, no client stopwatch :39-45; "Queueing…" then the run id :127-148.
- **Tests:** `operations-screen.test.tsx`, `operations-screen-polling.test.tsx`.

### 4.11 Administration `/app/admin` (`admin-screen.tsx`, 989 lines)
- **Purpose:** platform aggregates + every run type + worker control. Server-authorized; the console only decides whether to ask (:57-71); 403 rendered as the server's decision :101-119.
- **API:** `identity`, `adminOverview` (30 s), `adminRuns` (adaptive), `adminWorkerHealth` (20 s), `adminRun`, `resumeEmbeddingRun`, `reconcileEmbeddings`, `startWorker`/`stopWorker` (:73-360).
- **Tests:** `admin-screen.test.tsx` (591).

### 4.12 Public surfaces
- `/` landing (`screens/landing/landing-page.tsx`, `color-field.tsx`, `agent-demo.tsx`): canvas-2D light field, reduced-motion aware; demo data isolated and labelled (`17-frontend-experience.md:166-192`).
- `/sign-in` (`sign-in-screen.tsx`): two modes; no token in JS; HttpOnly cookie (:11-29).

---

## 5. Accessibility and contrast (WCAG 2.2 AA)

Measured with a relative-luminance script (`.scratch/sdd-ux/contrast.py`,
recomputable). Token values from `frontend/src/index.css`.

**Passing (≥4.5:1):** ink on paper 15.82, ink on ivory 14.75, muted on paper
5.77, muted on ivory 5.38, muted on muted 5.01, muted on secondary 4.89,
ivory-on-forest (primary button) 11.01, forest on sage 10.02, forest on lime
9.70, forest on lime-soft 10.85, terracotta-foreground on terracotta-soft 8.07,
terracotta-foreground on terracotta 6.65, destructive on paper 6.80, destructive
on destructive/10 blend 5.85 (paper) / 5.45 (ivory), ink on accent 13.76, and
all six dark-theme pairs (worst 6.05).

**Failing (1):** `text-muted-foreground/80` on 12 px labels blends to
**3.55:1** on ivory — below AA 4.5:1 for normal text. Two live occurrences on
light surfaces: the non-forest branch of the nav group headings
(`components/layout/nav-groups.tsx:343`) and the admin worker-status note
(`screens/admin-screen.tsx:977`). Drop the `/80` (full `text-muted-foreground`
= 5.38:1) or darken the token through the design-system doc. WS-34's new forest
sidebar avoids the trap with a dedicated `--sidebar-muted` token
(`#a7bfb4` on `#1b3831` = **6.49:1** pass; its other measured pairs:
foreground 11.03, accent pill 6.14, ring 10.25).

**Verified good practice already present:** single focus treatment
(`index.css:230-235`), pointer-cursor restoration (`index.css:246-254`),
reduced-motion that keeps feedback and drops travel (`index.css:275-324`,
`lib/motion.ts`), skip link (`components/common/skip-to-content.tsx`),
`aria-pressed` filters (`activity-screen.tsx:165`), labelled custom fields
(`approvals-screen.tsx:611-627`).

---

## 6. Baseline screenshots (`docs/design/baseline/`)

Captured with Playwright/Chromium against the **real** backend (67-route
surface, corpus 8,558) and the dev console. Session: throwaway account
`ws33.baseline@example.com` (id `8a148c95d4b4`), seeded through the product's
own API — fixture résumé `frontend/e2e/fixtures/resume.txt` → profile
`d4876f889401`; one stored-corpus search (20 results, `degraded: true` — shown
honestly in the captures); two **prepare-only** applications (approvals
`d7e353c31cea`, in-session one) against the checked-in fake-ATS URL — never
approved, never submitted. A second throwaway account (`ws33.empty@example.com`)
provides the honestly-empty states. No mock data was hardcoded anywhere.

Populated account, 1440×1000: `home-1440`, `resume-1440`, `discover-1440`,
`job-detail-1440`, `tailor-1440`, `approvals-1440`, `approvals-prepared-1440`,
`tracker-1440`, `tracker-detail-1440`, `profile-1440`, `activity-1440`,
`operations-1440`.
Populated account, 390×844: `home-390`, `discover-390`, `job-detail-390`,
`tailor-390`, `approvals-390`, `tracker-390`, `profile-390`, `activity-390`,
`operations-390`.
Empty account, 1440×1000: `home-empty-1440`, `discover-empty-1440`,
`tailor-empty-1440`, `approvals-empty-1440`, `tracker-empty-1440`,
`profile-empty-1440`, `activity-empty-1440`, `operations-empty-1440`.

**Environment note:** the default Vite port 5173 was held by an unrelated
personal project of the user's (a SmartDiet dev server, PID 22088) and 5174 by
a parallel WS-UX workstream; this workstream's console therefore served on
**5175** with the default proxy target `http://127.0.0.1:8000`
(`frontend/vite.config.ts:30` — no alternate `VITE_API_PROXY_TARGET` was set).
The backend ran on the default 8000. A stale uvicorn for this repo found on
8000 at start was killed and replaced.

**Rate-limit note:** the dev proxy is one rate-limit bucket per client
(`src/security/rate_limit.py:22-23`; 60 req/min, `src/security/limits.py:140`),
shared by every console window through the proxy — including the parallel
workstream's. First capture pass hit 429s; affected surfaces were re-captured
after the window cleared with paced navigation and self-checking (no capture
shows a 429 banner or a session bounce).

**Concurrency note (which shell each capture shows):** the parallel WS-34
workstream modified the shared shell files while this audit ran
(`index.css` 00:50, `status.ts` 01:07, `nav-groups.tsx`/`app-shell.tsx` 01:20
on 2026-11-17). By PNG mtime:

- **Pre-WS-34 shell** (horizontal warm nav bar, old labels): all desktop
  captures shot 00:47-00:54 (`resume-1440`, `discover-1440`,
  `job-detail-1440`, `tailor-1440`, `approvals-1440`, `profile-1440`,
  `home-1440`, `tracker-1440`, `tracker-detail-1440`, `activity-1440`,
  `operations-1440`) and all 390×844 captures (01:05-01:08). This is the
  v1.0.1 baseline the audit's file:line evidence describes.
- **WS-34 in-progress shell** (deep-forest sidebar, new IA labels, bottom-nav
  work): the nine captures shot 01:41-01:46 — `approvals-prepared-1440` and
  the eight `-empty-1440` states. These are valid evidence of the *states*
  (honest empties, the full prepared-payload panel) but not of the old shell;
  WS-34's own verification covers its shell.

The state evidence (empty states, prepared payload, seeded populated screens)
is the point of the set; no capture was staged with data the product did not
produce.

---

## 7. The reference image: grounded vs illustrative

The approved images (`Redesign Image.png`, 7 panels; `JobPilot Career
Dashboard.png`, the Home detail) mix the real product's semantics with sample
data and capabilities that do not exist. Each element is classified; "grounded"
means a real backend field can render it today.

| Element in the reference | Verdict | Grounding |
|---|---|---|
| Ivory canvas, forest sidebar, paper cards, warm borders, Bricolage/Geist, lime/terracotta semantics | **Grounded** | `index.css:21-138`; semantics already in code |
| Stat tiles "12 Matched Jobs / 3 Applications in Progress / 5 Submitted / 2 Need Your Attention" | **Groundable** (numbers are samples) | real counts: ranked search length, `listApplications` by real statuses, `summarizeEvents().attention` — labels must use `lib/status.ts` vocabulary ("Applications in Progress" is not a status) |
| "+2 / +1" trend chips on tiles | **Illustrative** | no time-windowed backend data; must be dropped or a real dataset defined first |
| 96% match-score arc | **Illustrative** | the real `overall_score` (e.g. 58.2) is component-weighted and already rendered as a lime chip (`score-grid.tsx`); a hero arc invites misreading — keep the score, drop the arc, or scale honestly |
| "Key Match Highlights: Technical Skills 98% / Experience 95% / Location 100% / Company Fit 93%" | **Illustrative** | real components are `semantic/lexical/skill/experience/seniority/location/preference/role + evidence_coverage` (`job-detail-screen.tsx:46-66`); "Company Fit" does not exist; unknown/missing components must stay distinct (`master prompt §3.9`) |
| "Agent Online · Ready to help" pill; "Live" badge on Agent Activity | **Illustrative — truth-rule violation if copied** | backend has no agent-presence or streaming endpoint; the console already refuses to call polling live (`activity-screen.tsx:83-90`); ground to `/api/health` + worker health, label polling as polling |
| Agent Activity feed rows ("Job search completed — Found 24 relevant jobs…") | **Groundable** (wording/counts must come from the audit rows) | `lib/observability.ts:23-50` vocabulary; counts only from `metadata` the rows actually carry |
| "Your Progress — Last 7 days" line chart, "+40%" | **Illustrative — drop** | master prompt §6.1 forbids it without a complete timestamped dataset; the audit page is newest-100 only (`audit.py:36`) — no honest 7-day window exists |
| "Pro Plan" under the account name | **Illustrative — drop** | no subscription concept exists anywhere in the backend |
| Employer logos (Google/Microsoft/Meta/Amazon/TechFlow mark) | **Illustrative — replace** | jobs carry text `company` only; fabricated brand logos also misrepresent; use text/monogram |
| Discover: "Jobs (324)" | **Illustrative** | honest totals are the corpus size (`stats.stored` 8,558) and the ranked-slice length (`describeSearch`, `matches-screen.tsx:93-110`) |
| Discover: Filters + "Sort: Match" controls | **Illustrative** | `JobSearchRequest` supports query/location/top_n only; filters/sort need a real backend contract first |
| Discover: Required Skills (5) / Missing Skills (1) chips; match %, salary, posted-when | **Groundable** | `match.missing_requirements/missing_keywords`, `listing.required_skills`, `salary`, `posted_at` (`job-detail-screen.tsx:196-257`) |
| Discover: Save (shortlist) action | **Illustrative** | no shortlist endpoint exists (`endpoints.ts` has none); requires a documented backend addition or must be dropped |
| Application Workspace: Original vs Tailored tabs, side-by-side | **Groundable (read-only today)** | the tailored result + render report exist; there is **no persistent per-change accept/reject model** — master prompt §6.4B requires a truthful read-only diff first |
| "Keyword Matching 92% — 24/26" with per-keyword checks | **Groundable** | `AtsReport.keyword_coverage` (`tailor-screen.tsx:254-307`); percentages must be the real required/preferred coverage, never invented |
| "+12 keywords" chip | **Illustrative** | no such field |
| Review panel: package checklist, board question with Yes/No/Prefer-not-to-say | **Partially grounded** | `form_questions` in board order exists (WS-25b, `approvals-screen.tsx:118-163`); answering unresolved questions inline needs the profile-answers flow; "ATS score 96/100" bound to an exact document revision does not exist yet |
| "Approve & Continue" | **Groundable with care** | the approval must keep the 202/queued truth (`status.ts:128-134`); the current label problem is the opposite one (`approvals-screen.tsx:788`) |
| Applications board columns "Saved (8) / Preparing (12) / Awaiting Review (5) / Submitted (9) / Interview (2)" | **Partially illustrative** | "Saved" and "Preparing" are not backend statuses; real statuses are `discovered…withdrawn` (`status.ts:27-91`); complete stage counts need server-side per-status queries — a partial page must not be presented as totals (`master prompt §6.6`) |
| Profile: "Profile Complete" pill | **Illustrative** | no such backend field |
| Activity Center: "Mark all as read" | **Illustrative — drop** | no read-state backend |
| Nav destinations "Resume Studio / Documents / Settings / Help" | **Illustrative in part** | "Resume Studio" ≈ Tailor; "Documents" ≈ the résumé library; **"Settings" and "Help" have no real product behavior — do not invent them** (master prompt §5) |
| Mobile companion with bottom nav | **Design decision, not grounding** | a drawer exists today (`nav-drawer.tsx`); a ≤5-item bottom nav is the master prompt §7 direction |
| Greeting "Good morning, Ahmad! 👋" | **Groundable** | time-of-day greeting is derivable; replace the emoji with a Lucide icon (§8C: no emoji-as-icons) |

---

## 8. Known gaps and open items for the consuming workstreams

1. **Overview honesty (WS-35):** tile counts must say what they count (page of
   200; audit page of 100) or move to server aggregates. Smallest honest fix:
   copy the Activity tile's "In the trail the API returned" qualifier.
2. **Approvals button label (WS-38):** "Approve and submit" → an "Approved and
   queued" framing, per `status.ts:128-134` and doc 32's own defect note.
3. **Nav label contrast (WS-34):** drop `muted-foreground/80` on 12 px labels
   (§5).
4. **Unused approval-status client** (`endpoints.ts:333`): either wire the
   Approvals screen to re-read a stored approval (survives reload) or remove it
   in a later workstream with lead approval.
5. **Shortlist/save, filters/sort, read-state, subscription badges:** all
   require backend contracts before any UI prints them (master prompt §3.1,
   §6.2).
6. **Job-detail has no dedicated unit test file** — matches tests cover the
   shared components; a small direct test is cheap insurance for WS-36's
   redesign.
7. **Port occupancy:** 5173/5174 are held by other processes on this machine
   (§6). Later workstreams must keep using their assigned alternates and must
   not kill PIDs they do not own.
