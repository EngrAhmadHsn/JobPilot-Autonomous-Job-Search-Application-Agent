# WS-41 (WS-UX-09) · UX redesign: mobile, accessibility, hardening and final polish

Status: **In progress — 2026-11-17; the responsive and accessibility gate is measured and green,
and the per-screen state matrix is what remains** (what landed: [§5](#5--what-landed); what is
still open: [§6](#6--what-is-not-done)) · Source directive:
[JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md](../JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md) §7, §10, §8 (WS-UX-09) ·
Depends on: WS-35…WS-40 all complete · Visual authority:
[Redesign Image.png](../Redesign%20Image.png) (panel 8, the mobile companion)

> **Where this starts.** The screen workstreams each verified their own viewports; this
> workstream is the **cross-cutting gate**: the responsive system as a whole, the
> keyboard/screen-reader flows, the empty/loading/error/disabled matrix, reduced motion,
> overflow, and the full-suite + end-to-end completion proof (master prompt §10.4's ten
> journeys). It is also where the whole-branch review findings land.

## Non-negotiable invariants for this workstream

WCAG 2.2 AA is part of completion: semantic controls, keyboard use, visible focus, labels,
status announcements, sufficient contrast, reduced-motion support, usable touch targets.
No test is deleted to go green; `AGENTS.md`'s Windows invocation rules and known
environmental flakes apply (Remotive/Ashby DNS flakes are environmental; do not debug
them). No new dependencies. The safety invariants of WS-33…40 hold unchanged here.

## File-ownership boundary

Cross-cutting by nature: edits go through the lead. This workstream's agents **audit and
report**; isolated fixes are assigned to exactly one agent at a time (master prompt §8B,
Subagent F's rule). No two agents ever edit `index.css`, `routes.tsx`, the same screen,
or shared status components simultaneously.

## 1 — Task 1: the responsive sweep

- [ ] Every surface at **1440×1000, 1280×800, 768–900 (one tablet width), 390×844,
      360×800** against the real backend: no horizontal page scroll anywhere at 360 px;
      drawers/menus/dialogs contain their own scroll and return focus; no sticky bottom
      action hides inputs, keyboard focus or system safe areas; touch targets meet
      platform guidance with separation.
- [ ] Mobile-specific interactions from the master prompt §7 confirmed in place: bottom
      nav ≤5 destinations; Discover results-first; Resume comparison stacked/toggle;
      Review keeps unresolved questions + approval state legible; tracker cards preserve
      job/company/status/next action.

## 2 — Task 2: accessibility sweep

- [ ] Keyboard: every primary journey operable (sign-in → discover → tailor → review →
      tracker), visible focus throughout (the WS-17 note that focus rings were "never
      actually seen" in the IAB gets closed here with real evidence).
- [ ] Screen reader: status changes announced politely (queued/running/blocked/failed),
      one `h1` per route, per-screen `document.title`, skip link, `<main>` landmarks (the
      WS-UX interface-review lineage), named controls everywhere.
- [ ] Contrast re-measured for every token pair introduced since WS-34; reduced-motion
      honored by every new animation (the existing `lib/motion.ts` system).
- [ ] Use the repository's accessibility skills (`accessibility-audit`,
      `accessibility-inspect`, `accessibility-scan`) where they run in this environment;
      state any tool that could not run rather than claiming it did.

## 3 — Task 3: the state matrix and hardening

- [ ] Every screen renders honestly in: initial load (skeleton), populated, empty,
      pending, error, degraded source, missing question, blocked challenge, durable run
      in progress, approval accepted/queued, submitted, verified, uncertain, failed.
      No clipped text, overlap, sideways scroll, inaccessible modal, hidden focus, or
      false success state anywhere.

## 4 — Task 4: the completion gate (master prompt §10, §14)

- [ ] `cd frontend && npm run typecheck && npm run lint && npm run test && npm run build
      && npm run format:check` — all green, known baseline failures recorded separately.
- [ ] Backend suites for anything touched: `./env/Scripts/python.exe -m pytest …`
      (targeted first, then tenant-isolation/security/docs-accuracy/OpenAPI).
- [ ] `npm run e2e` with the configured Playwright browser; the ten §10.4 journeys pass
      against the real backend or accurate MSW fixtures.
- [ ] Committed screenshots at the required viewports for every surface, inspected for
      real rendering defects; visible defects fixed before done.
- [ ] The final implementation report: files changed, API/backend changes (proposed vs
      landed), tests run + results, screenshots captured, known limitations, follow-ups.

## Acceptance (master prompt §14, abbreviated for this gate)

- The authenticated workspace looks and feels like the approved reference; Home stays
  job-first with no decorative analytics; every workflow reachable from nav and deep
  links; every state honest; mobile completes the core tasks; all suites green; the
  running application was driven and visually inspected — not just generated.

## 5 — What landed

The 2026-11-17 pass built the measurement first and then acted only on what it proved.

### 5.1 The audit instrument

`frontend/scripts/ws41-audit.mjs` drives the **running** console against the **real**
backend, signs in as the local operator, and records for every surface × viewport:
horizontal page scroll, elements outside the viewport, controls with no accessible name,
the heading outline, `<main>` and skip-link presence, console errors, and a screenshot.
It clicks nothing destructive — it never approves, submits, or saves.

Three false-green bugs in the first version are worth recording, because each one
produced a confident wrong answer:

1. **Invented paths.** The script asked for `/app/discover` and `/app/applications`.
   Neither route exists (the real ones are `/app/matches` and `/app/tracker`), so the
   route tree's catch-all redirected to the public landing page — and the script
   photographed the marketing site and reported `discover` **clean**. The instrument now
   asserts `pathname` equals the requested path, which catches that redirect *and* the
   sign-in redirect, and cannot be satisfied by a page that merely mentions a word.
2. **Overflow without a scroll container.** Every child of a horizontally scrollable chip
   row counted as "outside the viewport". A filter row that scrolls on a phone is the
   correct treatment, so it was reported as a defect. The probe now walks ancestors and
   skips an offender whose container legitimately clips or scrolls horizontally.
3. **The rate limiter read as a layout defect.** The API allows 60 requests/minute per
   client; a sweep costs far more. The 429s surfaced as console errors and, worse, as
   screens that "did not render". The proof run therefore uses an **isolated API
   instance** (`DATABASE_URL` pointed at a copy, `RATE_LIMIT_REQUESTS` raised) on its own
   port, so the shared development database is never hammered and the sweep measures the
   UI rather than the limiter.

### 5.2 The responsive result (measured, not asserted)

**60 of 60** surface × viewport combinations — 10 surfaces at `1440×1000`, `1280×800`,
`900×1000`, `768×1024`, `390×844` and `360×800` — reported:

- `sideways=false` (no horizontal page scroll) at **every** width including 360 px;
- `unnamed=0` (every interactive control has an accessible name);
- `overflow=0` (nothing outside the viewport outside a legitimate scroll container);
- `h1=1` (exactly one `h1` per route).

Evidence: `frontend/.scratch/ws41-final/` (60 PNGs + `audit.json`). The committed subset
is `docs/design/ws41/`.

### 5.3 The two defects it proved, and the fixes

**a. A transient identity failure read as a sign-out** (`components/layout/app-shell.tsx`).
The shell rendered the sign-in screen for *any* error from `GET /api/auth/me`. The live
sweep caught the consequence: a rate-limited screen became a sign-in page. A 429, a 500 or
a dropped connection is the console failing to ask the question, not the session ending —
and telling a signed-in operator they are logged out invites them to retype a password
that was never wrong. Only `401`/`403` now means refusal; anything else renders an honest
error with a real retry, and the gate stays **fail-closed** (no console chrome until the
server confirms the identity). Regression test:
`app-shell.test.tsx` → "does not read a failed identity request as a sign-out", verified
to fail when the fix is reverted.

**b. Mobile Home put four metrics before the work** (`screens/overview-screen.tsx`).
Master prompt §7 requires dashboard priorities before metrics, and the mobile reference
panel leads with the featured job and its action. The stat strip was written first in the
DOM, so a 360 px screen opened on numbers and pushed the next action below the fold. The
strip now `order-2` below `lg` and `order-1` at `lg`+, so the phone reads opportunity →
actions → activity → metrics while the desktop layout is untouched (verified by
re-capturing `1440×1000` and `1280×800`).

### 5.4 Where the redesign's foundations already satisfied this gate

Verified in source rather than assumed: the focus treatment lives **outside** `@layer
base` in `index.css:200`, so a utilities-layer `outline-none` cannot silence it (the
WS-34 review finding); the skip link targets the `#main-content` that both surfaces
actually render; one `<main>` per route; per-route `document.title` via
`hooks/use-document-title.ts`; reduced motion is the default in `lib/motion.ts` with the
OS preference as the query; and `progress-state.tsx:34` carries `role="status"` +
`aria-live="polite"`.

### 5.5 The end-to-end suite found four stale contracts

`npm run e2e` against the isolated stack found **four** places where the redesign changed
a control and the spec still named the old one. None was a product regression — each was
a spec that had stopped describing the console — and none was repaired by weakening an
assertion:

1. **Discover's result link → a row button.** `smoke.spec.ts` waited for
   `getByRole("link", { name: "Open the job" })`. WS-36 replaced that link with the
   reference's split view: a result is a row **button** inside the `Ranked matches` list,
   and choosing it opens the detail beside the list. The spec now clicks the row button in
   that list by role.
2. **The keyboard walk's 14-tab budget.** The grouped navigation of WS-34 (six
   destinations, their indented pages, the System group, the skip link, the top bar and the
   account footer) is more than 14 stops, so the walk was exhausted inside the sidebar and
   never reached the upload control it asserts on. The budget is 60 and the walk **breaks
   when it reaches "Choose a file"**, so it no longer depends on an exact count. It still
   requires a **painted focus ring** at some stop — the real-browser evidence the WS-17
   record said had never been seen.
3. **The approve control and its new confirmation.** The page button said "Approve and
   submit"; WS-38 renamed it "Approve & continue" (the route answers `202`, it does not
   submit) and added a confirmation dialog that states the queued consequence. The spec
   walks both steps and asserts the dialog says nothing is submitted by the click — so a
   regression that removed the confirmation would now fail.
4. **"History (n)" → "Timeline (n)".** WS-39 named the tracker's chronology "Timeline" (the
   board/list/timeline triple took the word) and kept the outcome editor underneath. The
   spec accepts the editor in either state (`Record a human outcome` for an open
   application, `The outcome is final` for a closed one), because a queued run may have
   already closed it.

One further failure was in **this pass's own new assertion**, not in the console: matching
`/Nothing has been submitted yet/i` tripped Playwright's strict mode because that true
sentence legitimately appears three times on the approval page (the payload panel, the
queued banner and the evidence panel). The assertion is now scoped to the one sentence
that carries the run id, which is the statement it was always meant to check.

That is worth recording as a finding about the earlier workstreams rather than about this
one: **four of five end-to-end specs had silently stopped describing the UI** while every
unit test stayed green (345 of them). Unit tests render components in isolation and cannot
notice that a route's primary affordance changed shape; only the browser could.

After the repairs, the suite is **5/5 green against the real backend and the real fake
ATS** (7.1 min, one worker): the full journey (resume → discover → tailor → prepare →
approve → `202` queued → tracker), the keyboard walk with a painted focus ring, the
account menu, the narrow-screen drawer, and the query suggestions.

## 6 — What is not done

Stated plainly, because this workstream's own standard is that a gate is not passed
because a page renders:

- **The backend suite was not run for this pass.** No backend contract changed — every
  edit is in `frontend/` — so the targeted backend suites named in §4 were not executed.
  That is a gap in the proof, not a claim that they are green.
- **Task 3's full state matrix is not proven per screen.** The sweep proves the
  *populated* render at six widths plus the console's own error states; it does not
  enumerate `blocked challenge`, `submission.uncertain`, `degraded source` and `durable
  run in progress` on every surface. That remains a per-screen audit, and it is the
  largest piece of this workstream still open.
- **The `900×1000` tablet width** was measured but its screenshots are not committed;
  `768×1024` covers the same band and both widths are in `audit.json`.
- **Focus return and modal trapping** were verified by reading the primitives (Base UI
  `Dialog`/`AlertDialog`/`Sheet`, all with a labelled title) but were **not** driven with a
  keyboard in a browser in this pass. The two dialogs that matter — the nav drawer and the
  approval decision — are covered by the e2e keyboard and account-menu tests only
  indirectly.
- **Ten §10.4 journeys are not ten passing specs.** `smoke.spec.ts` covers journeys 1–4
  and 8 partly (resume → discover → tailor → prepare → approve → track) and
  `suggestions.spec.ts` covers a UI slice. Journeys 5–7, 9 and 10 (exact-payload
  approval, the `202` durable run observed after reload, the real-board assist handoff,
  the worker-unavailable path, and cross-user isolation in the browser) are not
  end-to-end specs.

## Tests

The full frontend suite + e2e; backend targeted suites if any backend contract landed;
the journey list of master prompt §10.4 as the acceptance script.

**This pass measured:** `typecheck`, `lint`, `build` and `format:check` all green;
`vitest` **345 tests across 44 files, all passing** (exit 0, run with `--maxWorkers=2`
because the default worker count exhausts memory on this machine — a worker aborted with
exit 134 at full parallelism, and the same file passed 12/12 in isolation); `playwright`
**5 tests, 5 passing** (7.1 min) after the four stale contracts and the one strict-mode
assertion described in §5.5 were repaired — against the real backend and the real fake ATS,
including the full journey and the keyboard walk with a painted focus ring.
