# WS-41 (WS-UX-09) · UX redesign: mobile, accessibility, hardening and final polish

Status: **Planned — not started** · Source directive:
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

## Tests

The full frontend suite + e2e; backend targeted suites if any backend contract landed;
the journey list of master prompt §10.4 as the acceptance script.
