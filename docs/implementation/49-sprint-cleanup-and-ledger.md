# WS-49 — Sprint cleanup, docs ledger, commit cutting

Status: **Delivered 2026-11-21** — the formatting gate is real again, the instrument improvements are in, and the sprint's docs and ledger record what shipped. Two items stay open and are named at the end of this document.

## What shipped

| Commit | Feature |
|---|---|
| `f6f2408` | the console's source formatting is real again, and the sweep tooling lands |

**Evidence.** `npm run format:check` is green for the first time since the redesign waves
(36 files were failing it); `npx tsc -b --force` and `eslint .` are clean; the full suites are
re-run against the formatted tree.

**What was actually removed, and what was not.**

- **The sprint's replaced implementations are gone**: the sheet's superseded CSS travel classes
  (the animate-ui primitive owns the panel's motion now), the answering card's duplicated
  taxonomy sets (one module, `screens/review/question-taxonomy.ts`), the tracker's old
  "Review the questions →" link (replaced by the application's own questions page), and the
  module-internal `export`s the new taxonomy module did not need.
- **No broad dead-export sweep was performed.** A scan finds ~66 exports with no reference outside
  their own module, but most are deliberate module contracts (the `lib/api/*` aliases, the
  `schema.ts` type vocabulary, presentation types) and deleting them wholesale is a different,
  riskier change than this sprint's cleanup. The rule this workstream actually enforces is that
  **nothing the sprint replaced is left standing**, and that holds.
- **The plan's `bombadil` assumption was wrong.** `bombadil` is a property-based exploration
  harness (Antithesis: it generates action sequences and checks invariants over time), not a
  dead-code sweeper. Its skill is committed as project tooling, but no property-based run was made:
  the package is not a dependency and this sprint added none. That is the one plan item this
  workstream did not deliver as written, recorded rather than quietly dropped.
- **`format:check` was failing on `.scratch/`** — the sweeps' own machine-written JSON reports,
  which are git-ignored artifacts rather than source. `.prettierignore` now excludes that directory
  so the gate reports on what people edit.

**Left open (carried, not hidden).**

- The design-frame **manual browser pass** the WS-43...47 docs each name (sidebar overlay geometry
  at 1440/1024, the drawer at 768/390, Home's card colors, Discover's default selection and pane
  scroll, the questions page's save→unlock, Profile pagination, `/app/account`'s key card, the
  studio's edit→save→revalidate). The automated sweep covers the mechanical half of it; a human
  comparing each screen against `docs/design/Images-figma/Job Pilot/NN · Screen · width.png`
  has not been done in this pass.
- The WS-41 state matrix and the per-screen keyboard focus-return item.

## Goal

Close the sprint the way the repo's waves always close: junk removed, the docs reconciled with what actually shipped, and the work cut into atomic per-feature commits — each verified green against its own tree.

## Concrete tasks

1. **Junk sweep** (`bombadil` skill + sweep agent) — dead code the sprint made removable: superseded CSS animation utilities the animate-ui CLI stripped, unused exports/components, stale comments referencing replaced behavior, leftover experimental helpers. Nothing behavioral changes; the full suites prove it. Commit: `chore: the sprint's dead code goes (ws-49)`.
2. **Docs finalize** — `docs/implementation/43…49-*.md` gain their "what shipped" records (commits, test evidence, reference-image evidence per feature, documented deviations); `00-OVERVIEW.md` ledger row updated; README API table updated (the machine-checked README test enforces it). Commit: `docs: the ws-43..49 sprint records what shipped (ws-49)`.
3. **Commit cutting** — the standing policy for this sprint: **one commit per feature, never per workstream**; each commit verified green (tests for the touched area) against its own tree before the next; messages in repo style (`feat:/fix:/test:/docs:/chore:/refactor: … (ws-NN)`). Staging is per-feature deliberate — the known `git add` trap of sweeping already-staged files applies: stage explicitly, `git status` before every commit.
4. **Push** — after the final gate, push `main` (the repo's waves push at sprint end).

## Acceptance criteria

- No dead code remains from the sprint's replaced implementations; suites green.
- Every feature of WS-43…48 exists as its own commit with green evidence; the ledger and the overview row reconcile with `git log`.
- README API table test green (new endpoints `/api/applications/{id}/answers`, `/api/jobs/locations`, `PUT /api/tailored/{id}` documented).

## Tests

- `./env/Scripts/python.exe -m pytest -q`; `cd frontend && npm run test -- --maxWorkers=2` + `typecheck` + `lint` + `format:check`; `ws41-audit.mjs`; e2e.

## Live verification (2026-11-21)

The sprint's own verification list asks for a live stack. It was run **isolated**, so it touched
nobody else's servers or data: a copy of the repository's `app.db` (84 MB, 45 applications) under
`.scratch/ws43-sprint/live.db`, the API on `:8021` against that copy (with the sweep's rate limit
raised — the default 60 req/min throttles a 12-surface sweep and the throttled pages photograph as
"no h1", the flake this workstream's own notes record), the fake ATS on `:8901`, and a Vite dev
server on `:5191` proxying to the isolated API. The running instance the workspace already had
(`:8000`) was left alone.

| Gate | Result |
|---|---|
| `alembic upgrade head` against the DB copy | **clean**, including `b9c8d7e6f5a4` (answers) → `c2d3e4f5a6b7` (studio `edited_at`) → `d3e4f5a6b7c8` (the approval's question plan) — the migration chain applies forward on a real 84 MB database |
| `ws41-audit.mjs`, 12 surfaces × 7 frames | **84/84 clean** — 0 sideways scroll, 0 unnamed controls, 0 overflow, exactly one `h1` per surface, including the new `/app/account` and the per-application questions page, with the repaired tab steps |
| `verify-motion-control.mjs` | green — OS `reduce` yields `data-motion="reduced"` and the fade entrance; choosing "Full" restores `enter-up 0.42s` and the animated field repaints; the demo walkthrough still advances |
| the questions loop, live over HTTP | answer saved (`PUT` 200) → the stored plan re-merged: the sponsorship question goes `needs_human` → `answerable` with `answer_from="you"`, `blocking_questions` → `[]`; an EEO answer is refused `422` with the policy text; a `PUT` without the CSRF token is refused `403` (the CSRF control working, not a bypass) |
### The e2e suite: what was repaired, and what is still stale

The suite had drifted from the console, exactly as the WS-41 notes predict, and the repairs are
product facts rather than loosened assertions:

| Repair | What was stale |
|---|---|
| the sign-in helper (`e2e/session.ts`, shared by both specs) | it waited for a heading literally named "Sign in"; the screen's heading has been "Welcome back." since the WS-33 copy rewrite, so the helper returned *believing* it was signed in and every test then hung on the first control of a screen it had never signed into |
| the account trigger | the console now ships **two** controls labelled "Account and display settings" (the top bar's and the rail footer, which WS-43 gave back), so a bare `getByRole` is a strict-mode violation; the helper takes the visible one |
| the drawer trigger and its rows | the standalone hamburger no longer exists (WS-49 removed the dead branch), and the drawer's rows are labelled "Discover"/"Applications", not the old "Matches"/"Tracker" |

**Verified individually against the isolated stack:** "the console is reachable by keyboard" and
"the account menu opens" both pass, along with the repaired drawer test's trigger step. **Still
open, and named:** the long smoke journey and the suggestions spec, which fail in this environment
with the browser being closed mid-journey (`Target page, context or browser has been closed`, and
one assertion that could not evaluate at all) while a dozen servers and two browser instances share
the machine — the same tests reach the journey's later API calls (the history read) before the
browser dies, so the failures are the environment, not the console. Neither spec's *remaining*
selectors were found stale; they were not re-verified to green.

| full backend suite | `2256 passed, 8 skipped, 16 failed` — every failure is the documented DNS flake in `tests/test_jobs.py` (each passes in isolation; the SSRF guard resolves real DNS under `MockTransport`) |
| full frontend suite | **407 passed / 49 files**, `tsc -b` clean, `eslint .` clean, `format:check` clean |

**One real defect the full backend suite caught, and it was mine:** `tests/test_migrations.py` pins
`approval_requests`' columns by hand, and the new `form_questions` column was not added to that
list — fixed in `e678944`. That is the whole reason the suite is run in full.

**The e2e suite needed repair, and the repair is a product fact, not a loosened assertion.** Its
`signIn` helper waited for a heading literally named "Sign in"; the screen's heading has been
"Welcome back." since the WS-33 copy rewrite, so the helper returned early *believing* it was
signed in, and every test then hung on the first control of a screen it had never signed into.
With that repaired, the next failure was a strict-mode violation: the console now ships **two**
controls labelled "Account and display settings" (the top bar's, and the rail's own footer, which
WS-43 gave back), so the helper now takes the visible one.

## New dependencies

None.
