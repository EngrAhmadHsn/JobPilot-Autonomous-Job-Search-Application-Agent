# WS-21 · Job recommendation quality, targeted UI updates, profile consistency & the match experience

Status: **In progress (plan written 2026-11-08)** · Milestone: **M5** · Depends on: WS-03 (matching engine), WS-09 (evaluation harness), WS-13/17/19 (console), WS-18 (durable execution), WS-20 (matching accuracy, application profile)

> Five reported problems, one workstream:
>
> 1. **Periodic updates** re-fetch and re-render more than they need to — a run's
>    elapsed time, the Recent Activity list, run/embedding progress, worker status.
> 2. **Recommendation quality**: for a Web Developer, a *Data Analyst* and a
>    *Physical Design Engineer* listing rank in the top 10. The matcher has no
>    concept of an **occupational role** at all.
> 3. The Resume and Profile pages show **different Work Preferences** from
>    different sources, and clearing a preference silently resurrects it.
> 4. The Matches query suggestion box is **clipped** by its card.
> 5. The Tailor job picker is in **reverse similarity order** and contains
>    duplicates.
>
> The work started from a full audit of the local repository (2026-11-08) —
> §1 below — with every defect reproduced before it is fixed. Measurements are
> in §9; the plan per part follows.

---

## 1. Repository audit (2026-11-08)

### 1.1 Git and workstream state

- `git status` is clean; `main` is at `1c41e60` and **level with `origin/main`**
  (0 unpushed, 0 uncommitted, no stashes, no untracked files). Earlier
  workstream notes about unpushed work are stale — everything is pushed.
- `docs/implementation/` holds `00`–`20`; **WS-21 is the next free identifier**.
- Conventions followed here: workstream doc first, then code in reviewable
  phases with focused commits (`feat:` / `fix:` / `test:` / `docs:`, `(ws-21)`
  suffix), **nothing pushed**; `pytest` via
  `cmd.exe /c "env\Scripts\python.exe -m pytest ..."`; lint gate is
  `ruff check src tests scripts`; frontend suite is `npm test` in `frontend/`.

### 1.2 Environment facts that bound the design

| Fact | Value | Where |
|---|---|---|
| API rate limit | **60 requests / 60 s / client address** | `RATE_LIMIT_REQUESTS` default, `.env.example:176-179` |
| Running dev server | 56 OpenAPI paths, `/api/health` → 200 | live check |
| Corpus | 6 696 listings; 6 071 have vectors (90.7 %) | `app.db` + live search |
| Match history | 1 042 rows (no unique constraint on `(profile_id, job_id)`) | `app.db`, `src/db/matches.py` |
| Audit trail | 2 235 rows; `GET /api/audit` returns newest ≤ 500, default 100 | `src/api/routes/audit.py:36` |
| Durable runs | 4 rows; work items 4 002 | `app.db` |
| Console stack | React 19, TanStack Query 5, React Router 7, Base UI (`@base-ui/react` 1.9) | `frontend/package.json` |
| QueryClient defaults | `staleTime 30 s`, `refetchOnWindowFocus false`, retry 5xx once, **429 never** | `frontend/src/lib/query-client.ts:30-44` |
| Hidden-tab polling | already paused by TanStack default (`refetchIntervalInBackground` appears nowhere) | console audit |

The console's request budget must stay well below the 60 rpm API ceiling while
user actions, other screens and a second visible window share it. The user's
stated bound — **≤ 10 requests/minute per polled resource** — is the number the
plan below holds each individual query to (§2.3).

---

## 2. Part 1 — periodic updates without screen-wide re-rendering

### 2.1 What exists today (audit of every timer and poll)

Timers:

| Site | Cadence | Touches | Blast radius |
|---|---|---|---|
| `frontend/src/hooks/use-elapsed.ts:15-27` | 1 s | local counter state | only `ProgressState` (a mount counter, **not** an elapsed-since-start clock) |
| `frontend/src/screens/activity-screen.tsx:52-56` | 15 s | screen-level `now` state | **entire Activity screen** re-renders to refresh one header string |
| `frontend/src/screens/overview-screen.tsx:48-52` | 15 s | screen-level `now` state | **entire Overview screen** |
| `frontend/src/screens/landing/agent-demo.tsx:59-65` | 5.2 s | landing stage index | landing page only, gated by `IntersectionObserver` |

`refetchInterval` polls:

| Query key | Interval | Screen | Requests/min |
|---|---|---|---|
| `["health"]` | 30 s | shell (isolated component) | 2 |
| `["audit","activity"]` | 30 s | Activity | 2 |
| `["applications","overview"]`, `["audit","overview"]` | 30 s | Overview | 4 |
| `["runs","history"]` | **10 s, always** | Operations | 6 |
| `["run", trackedId]` | **2 s while non-terminal**, stops when terminal | Operations | **30** |
| `["run", childId]` (embedding child) | **2 s while non-terminal** | Operations | **30** (when present) |
| `["admin","overview"]` | 30 s | Admin | 2 |
| `["admin","runs",filter]` | **5 s, always** | Admin | **12** |
| `["admin","workers"]` | 10 s | Admin | 6 |

### 2.2 Root causes (each verified in code)

1. **The largest poller is 30 rpm.** The active-run query polls every 2 s
   (`operations-screen.tsx:73-81`), and when a refresh has an embedding child
   run there are **two** such queries — 60 rpm from one screen, i.e. the whole
   per-client API budget before anything else runs. This is the single request
   that most needed a bound.
2. **A screen-wide `now` tick.** Activity and Overview hold a 15 s ticking state
   *at screen level* purely so a header string ("last updated …") can advance.
   No component in `frontend/src` is memoised, so each tick re-renders the whole
   tree (Activity: header, banner, 4 stat tiles, up to 5 run timelines, the
   event list, pagination).
3. **The elapsed clock freezes when polling stops.** `RunProgress` renders
   `formatRelativeTime(run.started_at)` (`run-progress.tsx:119-121`,
   `lib/observability.ts:167-170`) — a pure function of `Date.now()` evaluated
   only when something re-renders it. While a run is active that is the 2 s
   poll; once the run is terminal the interval is `false` and the "started …"
   text stops advancing forever. So the one display that must keep ticking is
   the one that cannot.
4. **Duplicate polling keys.** `/api/audit` is fetched under two keys
   (`["audit","activity"]`, `["audit","overview"]`) and run detail under two
   (`["run",id]` operator, `["admin","run",id]` admin). Different screens, so
   not simultaneous — but the duplication is a cache-ledger smell, noted for
   the shared helpers introduced here.
5. **One unfiltered invalidation.** Sign-out calls
   `queryClient.invalidateQueries()` with no filter
   (`components/layout/account-menu.tsx:47`). On a session change that is
   acceptable (identity changed ⇒ nothing cached is trustworthy), and it is
   left as-is deliberately; every *other* invalidation in the app is already
   key-scoped.
6. **No visible-tab bug.** `refetchIntervalInBackground` is unset everywhere,
   so TanStack already pauses interval fetches in hidden tabs. This is
   confirmed, documented and *kept* — no code change needed, one test added to
   pin it.

### 2.3 Decisions (Option A/B/C/D from the brief)

| Option | Decision | Why |
|---|---|---|
| **A. Targeted, state-aware polling** | **Adopt** | Poll-onlies that change; every resource ≤ 10 rpm; hard stop on terminal; slow idle heartbeat for discovery. |
| **B. Local elapsed time** | **Adopt** | An isolated `useNow` + `RelativeTime` pair — the clock must tick from the server's start timestamp, locally, with zero requests, and keep ticking after polling stops. |
| **C. Incremental activity (`since` cursor)** | **Not now — documented** | `GET /api/audit` is already bounded (newest ≤ 500, default 100, ~2 rpm) and the screen computes summary stats over that window and pages 10 rows client-side. A cursor would not reduce the request count (the cost driver), would complicate the stats, and the trail (2 235 rows) does not justify it. Revisit only if the window grows past its bound. |
| **D. SSE** | **Not now — documented** | Run progress changes on a minutes scale; polling at ≤ 10 rpm plus a local clock is responsive. SSE would add a streaming route (auth per connection, heartbeats, `Last-Event-ID` replay), a rate-limiter exemption, proxy buffering considerations and new test infrastructure — all real costs for a latency win the UX does not need. The WS-17 "honest polling" decision stands; SSE remains the documented step-up if real-time activity ever becomes a requirement. |

### 2.4 The implementation plan

1. **`frontend/src/hooks/use-now.ts`** — a visibility-aware ticking clock:
   `useNow(intervalMs)` returns `Date.now()`, ticks on an interval, **pauses
   while `document.hidden`** and catches up immediately on `visibilitychange`.
2. **`frontend/src/components/common/relative-time.tsx`** —
   `<RelativeTime value={iso} />`: renders `formatRelativeTime(value, now)` from
   its own clock, so the ticking state lives **inside one leaf component**.
   Activity's and Overview's screen-level `now` states are deleted; the header
   strings become `<RelativeTime>`; `RunProgress`'s "started/finished" texts
   become `<RelativeTime>`.
3. **`frontend/src/lib/polling.ts`** — every cadence as a named constant, one
   place, with the budget table in a comment:
   - `RUN_ACTIVE_POLL_MS = 6_000` (≤ 10 rpm) — active run detail;
   - `RUN_ACTIVE_WITH_CHILD_POLL_MS = 15_000` — the parent cannot change while
     its child runs, so it slows down (4 rpm) while the child polls at 6 s;
   - terminal → `false` (unchanged policy, now tested);
   - `RUNS_LIST_ACTIVE_POLL_MS = 20_000` (3 rpm) while any non-terminal run is
     in the list, `RUNS_LIST_IDLE_POLL_MS = 60_000` (1 rpm) otherwise — an idle
     Operations screen becomes almost silent while still discovering a run
     queued elsewhere;
   - `ADMIN_RUNS_ACTIVE_POLL_MS = 10_000` / `ADMIN_RUNS_IDLE_POLL_MS = 60_000`,
     `WORKER_HEALTH_POLL_MS = 20_000`.
4. **No loading flashes**: every poll is a background refetch (TanStack keeps
   the previous data); the plan adds a test pinning that a poll replacing data
   never unmounts the list.
5. **Tests** (Vitest, first use of fake timers in this repo — `vi.useFakeTimers`
   + `advanceTimersByTimeAsync`):
   - `useNow`/`RelativeTime`: ticks, unmounts clean, pauses while hidden and
     catches up on visible;
   - **elapsed isolation**: with an active run, advancing 5 s re-renders the
     ticking component but not its parent/siblings (render counters);
   - **terminal stop**: a terminal run detail is fetched once and never again;
     an active run keeps updating;
   - **no unrelated requests**: an Activity poll cycle issues `GET /api/audit`
     and nothing else (MSW request log);
   - **hidden tab**: with `document.visibilityState` stubbed to `"hidden"`, no
     interval fetch fires; it resumes on `"visible"`;
   - **no duplicates on append**: new audit events append without duplicating
     existing rows (stable `key={event.id}`);
   - regression: existing operations/activity/admin tests still green.

---

## 3. Part 2 — occupational-role relevance (the important one)

### 3.1 Reproduction (live, 2026-11-08, `scripts/ws21_repro.py`)

The reference profile is the local Web Developer / Full Stack Developer profile
(skills: JavaScript, Python, SQL, React, Node.js, Django, … ; confirmed: 5 years,
Senior, remote, full-time). `POST /api/jobs/search`'s own code path
(`search_stored_jobs`) against the live corpus returned (top 15 of 30 requested;
semantic scoring **available** — 6 071/6 696 covered; the user's screenshot
caught an earlier run where the store was momentarily unavailable, which made
every semantic cell `unknown`):

| # | Score | Listing | Why it ranked (component breakdown) |
|---|---|---|---|
| 1 | 80.9 | Manager, Applied AI Engineering — OpenAI | skill 100 (Python, JavaScript — 2-token list), exp 100, location 100, pref 100, semantic 67 |
| 2 | 80.8 | same title (duplicate id) | as above |
| 3 | 80.8 | Product Operations Manager — Notion | skill 100 (MySQL/Python/C++/Java!), exp 100, loc 100, pref 100 |
| 4 | 77.1 | Compliance, International Investigations — Coinbase | skill 100 (**SQL**), exp 100, sen 70 |
| 5 | 76.6 | Capacity Planning Lead — Coinbase | skill 100 (SQL), exp 100, sen 70 |
| 6 | **74.8** | **Physical Design Engineer — OpenAI** | skill 100 (**Python**), exp 100, loc 40, pref 100 |
| 7 | **74.3** | **Senior Analyst, France & Netherlands — Airbnb** | skill 100 (**SQL**), exp 100, sen 100 ("Senior"="Senior"), loc 40 |
| 8 | 73.4 | Software Engineer, Safety Engineering — OpenAI | skill 67, semantic 71 — a legitimately adjacent role |
| … | | | |
| **19** | **70.7** | **Senior React Full-stack Developer — Lemon.io** | skill **14** (the job lists .NET/Android/AWS/C#/… — a *real* list), semantic 73 — the actual best match, ranked 19th |

The inversion is the headline: the **closest occupational match scores 14 % on
the skill component** (because its requirement list is long and honest) while
**unrelated roles score 100 %** (because their prose-mined lists are 1–4 tokens
long). The user's screenshot shows the identical failure with the store down
(`Skill: 100.0 / Matched skills: SQL. Missing skills: none.`).

### 3.2 Root causes (verified in code)

1. **The skill denominator is only the listing's own extracted list**
   (`engine.py:180-194`): one matched token (`SQL`, `Python`) ⇒ 100 %, zero
   missing, with no minimum evidence and no penalty for the job's *unlisted*
   needs. Lists are prose-mined by the adapters
   (`greenhouse_adapter.py:137`, `ashby_adapter.py:118`, lexicon
   `src/jobs/skills.py`), so a one-token list is common — and a one-token list
   scores *better* than a real requirement list.
2. **No occupational-role concept exists anywhere.** A repo-wide search for
   `job_family|target_role|role_family|occupation` returns nothing. Title
   enters scoring only as BM25 weight, seniority-ladder tokens and the client
   query filter (`lexical.py:208`, `engine.py:253`,
   `job_executor.py:746-753`). Nothing compares *what the work is*.
3. **Experience 100 is cheap** and its parser has a real trap: the degree
   sentence `"BS w/ 4+ or MS with 2+ years …"` yields the **earliest** number
   (`2+ years`) via `_years_in_sentence` (`experience.py:152-176`), so an
   education-alternative sentence becomes the bar.
4. **Seniority compares ladder tokens across domains** (`engine.py:253,267`):
   "Senior Analyst" == confirmed "Senior" ⇒ 100 for an analyst role.
5. **Semantic similarity is not a domain gate**: the candidate query text is
   the whole (broad, multi-tool) résumé, so any technical JD lands 63–74
   cosine — enough to carry a score once skills/experience/preferences are 100.
6. **Unknowns stay in the denominator (by design, WS-20)** — correct, and it
   means the *only* fix that scales is a real role signal, not more weight
   fiddling.

### 3.3 Design

**3.3.1 A deterministic role classifier — `src/matching/roles.py` (new).**
No LLM, no per-pair calls; pure functions over the listing and the profile.

- **Taxonomy** (families; chosen from the corpus's own title vocabulary —
  6 696 listings: software 1 005, product 579, AI/ML 384, operations 346,
  data 339, sales 313, platform/infra 525, security 232, support 202, marketing
  158, design 137, finance/legal ~215, people/HR ~150):
  `web_development`, `software_engineering`, `mobile_development`,
  `data_analytics`, `data_science_ml`, `data_engineering`,
  `devops_cloud_infrastructure`, `security`, `qa_testing`,
  `hardware_physical_design`, `embedded_firmware`, `product_management`,
  `design_ux`, `operations_program`, `sales`, `marketing`, `customer_support`,
  `finance_legal_compliance`, `people_hr`, `research`, `other`.
- **Signals, three tiers** — title phrases (weight 5; e.g. "physical design",
  "data analyst", "web developer", "site reliability", "account executive"),
  responsibility phrases from the description (weight 2; e.g. "tape-out",
  "timing closure", "sales quota", "customer inquiries", "responsive web
  applications"), technologies (weight 1.5; e.g. RTL/VLSI/Cadence → hardware;
  React/Next.js/Shopify → web; PyTorch/TensorFlow → ML; Tableau/Power BI →
  analytics). Technologies shared across families (Python, SQL, Git) are
  deliberately weak or cross-assigned so they cannot carry a classification.
  Title beats description beats technology — the spec's rule that a technology
  mention does not confer a profession.
- **Level vs family**: "Manager, Applied AI Engineering" is *AI engineering*
  (family) at *management* level (track). The classifier records
  `track ∈ {ic, manager, unknown}` from title tokens (manager/director/head/
  vp/chief ⇒ manager).
- **Output**: `RoleClassification(family, second_family, confidence, track,
  evidence, ambiguous)`; confidence from the top-two score margin; no
  signals ⇒ `family=None, ambiguous=False, unknown`.
- **Compatibility bands** (one coarse table, symmetric; documented as policy
  not tuning): `SAME 100`, `NEAR 85` (frontend↔full-stack, analytics↔ML,
  analytics↔data-eng, backend↔full-stack), `ADJACENT 65` (web↔backend,
  software↔devops, software↔QA, software↔mobile, ML↔software,
  analytics↔software, hardware↔embedded), `TANGENT 40` (web↔devops,
  web↔security, web↔ML, data↔web, product↔engineering), `WEAK 20`
  (web↔analytics, web↔product, web↔design, web↔support, ops↔engineering),
  `UNRELATED 5` (web↔hardware, web↔sales, web↔finance, web↔HR,
  hardware↔analytics, …). Unlisted pairs default to `WEAK`.
- **Candidate targets — explicit first, inferred labelled.** Free-text
  `target_roles` are mapped through the same title classifier; held in
  `JobSearchPreferences.target_roles` (§4.1) and marked confirmed in
  `confirmed_fields` as `preferences.target_roles`. Fallback inference when the
  field was never confirmed, in priority order: confirmed `current_title` →
  résumé headline → the 3 most recent experience titles; the source
  (`user` / `inferred`) is carried into the explanation and the UI. An
  explicitly cleared target is never re-inferred while the field stays
  confirmed.
- **Scoring**: `role_value = max over candidate families of
  band(candidate_family, job_family)`; for an ambiguous job, blend the top two
  families by confidence (`top*conf + second*(1-conf)`) so an ambiguous job
  cannot win a high score from one of its readings; a manager-track job against
  an IC target multiplies by **0.5** (track mismatch is a real mismatch).
  States reuse the WS-20 vocabulary: measured when both sides are known;
  `CANDIDATE_DATA_MISSING` when no targets (value 0, weight kept — everyone is
  penalised equally, ranking unaffected, note says "set target roles");
  `JOB_REQUIREMENT_MISSING` when the listing cannot be classified.

**3.3.2 The engine gains an eighth component.** `DEFAULT_WEIGHTS` becomes:

| Component | WS-20 | WS-21 | Rationale |
|---|---|---|---|
| semantic | .15 | .13 | domain-sensitive but corpus-relative |
| lexical | .10 | .08 | |
| skill | .25 | .22 | still the strongest positive signal |
| experience | .20 | .17 | |
| seniority | .10 | .08 | |
| location | .10 | .09 | |
| preference | .10 | .08 | |
| **role** | — | **.15** | the new domain gate; second-largest |

Plus **the mismatch guard**: when the role component is *measured* and below
`UNRELATED_ROLE_MAX = 25` (WEAK×track or UNRELATED), the overall score is
**capped at `ROLE_MISMATCH_CAP = 25`** — deliberately below the evaluation's
decision threshold (30), so a role-unrelated listing can never read as a
match. This is the spec's "generic skill overlap must not overpower a major
occupational-role mismatch", made explicit and testable rather than emergent
from weights. The cap is reported (`role_capped` in the result, a sentence in
the explanation), never silent.

**3.3.3 Thin-evidence damping in the skill component.** After the existing
coverage computation, the value is multiplied by
`min(1, (len(required) + 0.5·len(preferred)) / 2)` — one listed requirement
scores at most 50 %, a one-token list cannot deliver 100 %. General rule, not
a patch for the two examples; tested with both.

**3.3.4 Experience parse fix.** A sentence containing a degree-alternative
pattern (`BS/BA/MS/MA/PhD`/bachelor/master/doctorate/degree) takes the **max**
of its stated bars (the `"BS w/ 4+ or MS with 2+"` case), while ordinary
sentences keep first-match semantics. Correctness fix with its own tests.

**3.3.5 Explanations.** `JobMatchResult` gains `role_score` (+ all role fields
in `component_states`), and the explanation sentence gains the role cell and,
where relevant: `Role: 5% (classified: hardware/physical design; your targets:
web development — unrelated)`. Persisted via `build_match_rows`'s score fields;
console match cards gain a **Role** tile and the mismatch/ambiguity evidence in
"Why this score" (§ below).

**3.3.6 Frontend.** The match card component that renders the seven component
bars gets a Role row (label: "Occupational fit"); the reasoning block shows the
classified family, confidence/ambiguity and the candidate's target roles — and
for a capped match, why. `target_roles` are editable on the Profile/Resume
Work Preferences surfaces (§4) with suggestions drawn from the corpus's own
titles (`GET /api/jobs/suggest` already exists).

### 3.4 Benchmark (before/after, multi-profile)

- Extend `tests/evaluation/golden/` with **hard negatives** (a Data Analyst
  and a Physical Design Engineer listing, sanitized synthetic fixtures) and
  **more profiles** across families (web/frontend/full-stack, data analyst,
  AI/ML, software, hardware — the existing Alex/Web/Data resumes are extended
  rather than replaced; labels kept graded 0/1/2).
- New metrics in `src/evaluation/metrics.py`: `role_mismatch_rate_at_k`
  (top-k share whose classified family is WEAK/UNRELATED against the profile's
  target family) and `uncertain_classification_rate`.
- Snapshot runs: `scripts/run_eval.py` before and after, reports under
  `docs/evaluations/ws21-*.md`; P@5, P@10, R@10, MRR, NDCG@10, mismatch rate,
  uncertainty rate — before vs after.
- A test pins the golden jobs' classifications (`tests/test_roles.py`) so the
  classifier cannot drift silently.

---

## 4. Part 3 — Work Preferences: one source of truth

### 4.1 What exists today (audit)

- **Resume page**: read-only card `ProfileView` "Work preferences"
  (`components/profile/profile-view.tsx:221-249`) rendering
  `CandidateProfile.work_preferences` — the **parser's** output
  (`src/resume/parser.py:498`), never editable anywhere.
- **Profile page**: `ApplicationProfilePanel` "Work preferences"
  (`components/profile/application-profile-panel.tsx:163-314`) editing
  `ApplicationProfile.preferences` + `answers.compensation.expected_salary`,
  saving via `PUT /api/profiles/{id}/application-profile`.
- The two documents are shown side by side on the Profile page as **two cards
  with the same title**, and neither shows the **effective** value the matcher
  actually uses (`_effective_preferences`, `engine.py:82-110`).

Mismatches (all verified):

1. Fields only on the résumé card: `min_salary` (verbatim), `work_authorization`
   (verbatim — a *preferences* card containing a visa field, which the brief
   itself flags as the wrong home for it).
2. Fields only on the profile card: expected salary (amount/currency/period),
   `willing_to_relocate` (model field, rendered nowhere).
3. Option sets differ: the app select offers `"any"`, the résumé model does not.
4. **Truthiness resurrection** (`engine.py:99-104`): a confirmed value wins only
   when truthy; a *cleared* remote mode (`null`) or cleared list (`[]`) leaves
   the résumé value in place — the user's clear is silently undone.
5. **Salary precedence inverted** (`engine.py:107`): the résumé's `min_salary`
   beats the user's confirmed `expected_salary` — the opposite of the
   function's own docstring; period/currency are dropped when stringified.
6. Saving on either page never invalidates the other page's query; the screens
   can disagree until a reload.
7. Each card PUTs the whole document built from its **render-time snapshot** —
   two cards saving near-simultaneously can clobber each other's fields.

### 4.2 Design

- **One authoritative, editable source**: `ApplicationProfile.preferences`
  (+ `answers.compensation`), written through the existing PUT — with
  `target_roles` added (`JobSearchPreferences.target_roles: list[str]`, ≤ 20
  entries, cleaned/deduped, part of §3).
- **One shared component**: extract `WorkPreferencesCard`
  (`frontend/src/components/profile/work-preferences-card.tsx`) from the
  panel and render it on **both** screens — same fields, validation, options,
  formatting, defaults, save, error handling, same query key
  (`["application-profile", profileId]`) and cache updates.
- **Field set** (semantic split per the brief): work mode, preferred
  locations, employment types, expected salary (amount + currency + period),
  **target roles**. Work authorization stays an *application answer* (it
  already lives in `ApplicationAnswers.work_authorization`); the résumé's
  verbatim value is shown in the provenance banner only.
- **Résumé-derived values are labelled, never auto-merged**: a "detected from
  your résumé" strip shows the detected values with an explicit **Use
  detected** action that fills the draft; only the user's Save confirms. This
  is the 3.3 rule (never provided / inferred / confirmed / cleared) made
  visible.
- **Merge semantics** (`_effective_preferences` rewritten, tested):
  a field is taken from the application profile **iff its group is confirmed**
  (`confirmed_fields` contains `"preferences"` / `"answers.compensation"` /
  `"preferences.target_roles"`), *including empty values* — explicit clear
  wins over the résumé, and the résumé is the fallback for fields the user
  never confirmed. Confirmed salary (normalised to the comparison as
  amount+currency, period-aware where both sides are annual-or-unstated)
  beats the résumé's `min_salary`, fixing the inversion. Backward compatible:
  pre-WS-21 rows keep their existing confirmed markers, and
  `target_roles` is only treated as confirmed when its own fine-grained
  marker is present (so older saves never suppress inference).
- **Concurrency**: `commit()` builds the PUT body from the **latest cached
  document** (`queryClient.getQueryData`) merged with the card's own fields,
  so two cards in one tab cannot clobber each other; the cache is updated from
  the mutation response. Cross-tab last-write-wins remains (documented).
- **Module copy rule** stays: "résumé" in prose, "Resume" in UI labels.
- **Tests**: backend unit tests for merge precedence (confirmed > résumé;
  cleared ⇒ not resurrected; salary inversion fixed; legacy markers), frontend
  tests for the shared card on both screens (edit on Resume → visible on
  Profile through the shared cache, persists via MSW), and no-clobber test.

---

## 5. Part 4 — the Matches suggestion box is clipped

### 5.1 Root cause

The panel is an **inline absolutely-positioned `ul`** inside the search field's
`div.relative` (`query-combobox.tsx:77,101-106`, z-50, `.suggest-panel`
animation `index.css:521-545`), and the element that clips it is the **shared
Card** wrapping the search form — `card.tsx:14` sets `overflow-hidden`, consumed
bare at `matches-screen.tsx:236`. The clip is the card's border-box bottom
edge: panel bottom = input top + 15 px margin + up to 20 rem, far past the
card. No other ancestor between panel and card sets any overflow; there is no
Popover/Combobox primitive in `components/ui/` (Base UI is used for
Menu/Portal/Positioner patterns in `dropdown-menu.tsx` and `tooltip.tsx`).

### 5.2 Options evaluated

| Option | Robustness | Cost/risk | Verdict |
|---|---|---|---|
| 1. Local `overflow-visible` on this one Card | Fixes the actual clip; panel scrolls with the page natively; z-50 above following cards | One class; must not leak to other screens (it is applied at the call site, not in `card.tsx`) | **Chosen** — with an ancestor audit (the screen and shell set no clipping) and a browser test |
| 2. Portal the panel (manual `createPortal` + anchored positioning) | Immune to any future ancestor clipping | Hand-rolled scroll/resize repositioning; duplicates what Base UI's Positioner already solves | Not now |
| 3. Rebuild on a Base UI Popover/Combobox primitive | Most robust, viewport-aware | Rewrites keyboard/ARIA/blur semantics the brief requires preserved; highest regression risk | Not now |

### 5.3 Plan

- `<Card className="overflow-visible">` at the one call site
  (`matches-screen.tsx:236`), with a comment saying why; `card.tsx` untouched.
- Verify every ancestor (screen container, `<main>`, shell) carries no
  overflow/clip/transform clipping; drop the one that does if any is found.
- Keep the panel's `max-h-80` and add `overscroll-contain`.
- **Browser-level regression test** (Playwright, production build): open
  Matches, type a query, assert the suggestion panel's bounding box **extends
  below the search card's bottom edge** and is visible; assert Escape closes,
  arrows move, Enter selects — the existing behaviours.
- Also assert the panel is not painted under the results card (z-order check
  via hit-testing at a point inside the overlap).

---

## 6. Part 5 — Tailor job ordering

### 6.1 Root cause

- The Tailor picker fetches `GET /api/profiles/{id}/matches` and renders
  `entries.slice(0, 25)` with **no sort and no dedupe**
  (`tailor-screen.tsx:425-441, 533`).
- The endpoint returns `ORDER BY id DESC` (`access.py:220`) — the newest
  search batch first, but **reversed within the batch** (rows are inserted in
  rank order, so `id DESC` returns the worst-ranked rows of the newest search
  first). Its docstring says "oldest first" — both descriptions are wrong.
- Rows are re-inserted on every search (no unique constraint on
  `(profile_id, job_id)`), so the 25-row window can be filled with duplicates
  of one job; `overall_score` lives inside the `scores` JSON (no column).
- The UI copy even claims "newest search first" while the order is inverted.

### 6.2 Design

- **New scoped accessor** `list_ranked_job_matches(db, scope, profile_id,
  limit)` in `src/db/access.py`: SQLAlchemy window function
  `row_number() over (partition by job_id order by id desc)` (portable
  SQLite ≥ 3.25 / PostgreSQL) to take the **most recent match per job**, then
  in Python: drop malformed scores safely, sort by
  `(score desc, created_at desc, job_id asc)` — stable deterministic
  tie-breaks — and slice after dedupe. Owner/profile scoping via the existing
  `_owned` pattern (isolation tests must pass unchanged).
- **Endpoint**: `GET /api/profiles/{id}/matches` gains
  `ranked: bool = False` and `limit: int | None = None` (bounded). Default
  behaviour (unranked history, newest first) is preserved for any consumer
  that wants the audit view; the docstring is corrected. The Tailor screen
  uses `ranked=true&limit=25` under its own query key, so
  `job-detail-screen.tsx`'s use of the history keeps its semantics.
- **Frontend**: no client-side sorting; render server order; key rows by
  `job_id` (duplicates gone by construction); show a 0-score like any other
  number (the current `overall > 0` check hides it); copy states "ordered by
  relevance (latest score per job)".
- **Regression tests** (the brief's fixture): jobs A=45, B=91, C=72, D=84 with
  a duplicate of one job carrying an older score ⇒ rendered B, D, C, A; the
  newest duplicate's score wins; limit applied after dedupe; missing scores
  last; backend accessor tests for the same, including profile isolation.

---

## 7. Cross-cutting

- **`MATCH_WEIGHTS` is a breaking 8-component change** (WS-20 precedent):
  `validate_weights` now names 8 components; `.env.example`'s comment and the
  README/docs that say "seven components" are updated. No env var is added, so
  `.env.example` stays declaratively complete (`tests/test_env_docs.py` must
  stay green).
- **No new dependencies** — backend and frontend. (The classifier is
  hand-rolled over the existing tokenizer.)
- **Docs**: this file, `00-OVERVIEW.md` (index row + status ledger), README
  matching/console sections if they name component counts, WS-20's
  `docs/evaluations/ws20-comparison.md` gets a WS-21 successor.
- **Isolation and security invariants** are part of the acceptance run:
  `tests/test_tenant_isolation.py` (new accessor), scoped audit read unchanged,
  `current_scope` on the matches route (already present), no personal data in
  new logs/fixtures/docs (fixtures are synthetic; the live repro prints only
  public listings).
- **Preserve WS-18/WS-20**: durable runs, lease fencing, embedding recovery,
  SQLite/PostgreSQL compatibility, BM25, missing-data states, EEO isolation,
  approval gates — each named in the acceptance checklist.

## 8. Verification plan

1. **Phase gates**: `ruff check src tests scripts`; backend
   `pytest -m "not browser"`; frontend `npm test`; `npm run build`;
   `npx tsc --noEmit` (per existing scripts).
2. **Part 1**: new Vitest suites (fake timers, request-log assertions) +
   one Playwright spec (no reload, no loading flash, panel-not-clipped for
   Part 4 can share the launch).
3. **Part 2**: unit (classifier, bands, targets, damping, cap, parse fix) +
   golden-set classification pin + harness before/after
   (`docs/evaluations/ws21-*.md`) + **live** `scripts/ws21_repro.py` with
   explicit target roles: the two named bad listings must leave the top 10
   and the React/Full-Stack listing must rise; recorded in §9.
4. **Part 3**: backend merge tests + frontend cross-screen test.
5. **Part 5**: accessor + endpoint + screen order test (fixture B/D/C/A).
6. **End-to-end (live)**: `scripts/verify_ws21.py` — the repeatable acceptance
   script for the backend-visible checks (profile targets round-trip, ranked
   matches order, merge precedence, capped scoring), mirroring the WS-20
   precedent.

## 9. Results

_(filled during implementation — before/after tables, test counts, live
acceptance output)_

## 10. Remaining limitations

_(filled at completion)_