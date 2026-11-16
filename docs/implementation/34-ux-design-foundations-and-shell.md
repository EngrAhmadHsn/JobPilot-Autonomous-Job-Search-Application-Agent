# WS-34 (WS-UX-02) · UX redesign: design foundations and the application shell

Status: **Planned — not started** · Source directive:
[JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md](../JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md) §4, §5, §8 (WS-UX-02) ·
Depends on: WS-33 for the design contract, but may start against the master prompt's
already-approved §4 direction (the contract reconciles, not invents) ·
Visual authority: [Redesign Image.png](../Redesign%20Image.png)

> **Where this starts.** The console already has a coherent token system and a working
> shell: `frontend/src/index.css` (ivory/forest/lime/terracotta tokens, Bricolage +
> Geist), `frontend/src/components/layout/{app-shell,nav-drawer,nav-groups,account-menu,
> brand-mark,profile-chip}.tsx`, and ten ui primitives under
> `frontend/src/components/ui/`. The reference image wants a deep forest sidebar with a
> clear active state, warm paper surfaces, compact dense cards and a premium, calm
> career-operations feel. This workstream rebuilds the **frame and the shared primitives**
> so every later screen workstream composes on top of them.

## Non-negotiable invariants for this workstream

Preserve route semantics, lazy loading and the React Router view transitions in
`frontend/src/routes.tsx` (only navigation *labels/grouping* may change, inside
`nav-groups.tsx`). Preserve the semantic colors (lime = agent, terracotta = human, forest
= brand/primary) — a change needs a documented decision plus migration of all affected
states. Preserve `frontend/src/lib/status.ts`'s public API
(`describeStatus`, `StatusTone`, `APPLICATION_STATUS_NAMES`, `isHumanOutcomeStatus`) while
extending it so **one backend state has one label, tone, icon and explanation** across
Home, Review, Tracker and Activity. Preserve Operations/Administration as real
destinations backed by server authorization — they move to a secondary System/Workspace
navigation group, never deleted. No new dependencies (master prompt §3.20). No emoji
icons; Lucide only. Respect `prefers-reduced-motion` (the existing motion system in
`lib/motion.ts` / `lib/stagger.ts` stays the substrate).

## File-ownership boundary (exclusive — other workstreams must not touch)

`frontend/src/index.css`, `frontend/src/components/layout/**`,
`frontend/src/components/ui/**`, `frontend/src/lib/status.ts`, `frontend/src/lib/motion.ts`,
`frontend/src/lib/stagger.ts`, and their test files. **Not** `routes.tsx` (lead-owned),
**not** `lib/api/**` (frozen), **not** any screen. New shared components proposed by later
workstreams are flagged to the lead, who lands them here.

## 1 — Task 1: reconcile the tokens to the approved reference

- [ ] Compare `index.css` tokens against the reference image (forest sidebar depth, paper
      surface warmth, border warmth, active-nav treatment). Adjust only through the token
      layer; raw hex in components is a defect. Keep the existing dark-theme support wired
      and tested; the light warm-paper theme is the default authenticated look.
- [ ] Verify every adjusted token passes WCAG 2.2 AA against its expected background
      (muted text on paper, chips on ivory, sidebar active state on forest); record the
      measurements in the workstream doc when done.
- [ ] Test: extend `frontend/src/components/layout/app-shell.test.tsx` with the cases the
      restyle could break (active nav state renders; account menu opens; the shell's
      identity gate still hides console chrome from an unauthenticated caller).

## 2 — Task 2: the shell — sidebar, account affordances, responsive navigation

- [ ] Sidebar: forest surface, brand lockup, grouped destinations per master prompt §5 —
      Home, Discover, Applications, Resume Studio, Profile & Documents, Activity in the
      primary group; Operations + Administration in a labelled System/Workspace group.
      Map the conceptual groups onto the **existing routes** (Discover → `/app/matches`
      and `/app/matches/:jobId`; Applications → `/app/tracker*` and `/app/approvals`;
      Resume Studio → `/app/tailor*`; Profile & Documents → `/app/profile` and
      `/app/resume`) so no deep link changes.
- [ ] Active state: one clearly rendered selected destination, keyboard-focusable, with a
      visible focus ring (the reference's look without dropping focus visibility).
- [ ] Account area: keep the existing `account-menu.tsx` / `profile-chip.tsx` behaviors
      (sign-out, theme, credentials) restyled into the sidebar footer, as in the reference.
- [ ] Mobile: compact top bar + bottom navigation ≤5 primary destinations, with the
      secondary destinations reachable through the existing drawer pattern
      (`nav-drawer.tsx`); drawers contain their own scroll and return focus on close.
- [ ] Preserve the shell's existing a11y contract: the tests in `app-shell.test.tsx`,
      `nav-drawer.test.tsx`, `account-menu.test.tsx` must pass unmodified unless a
      behavior they pin was itself wrong — in that case change the test deliberately, with
      a comment, not silently.

## 3 — Task 3: shared primitives and status centralization

- [ ] Audit `components/ui/**` against master prompt §8C's list; add only what is missing
      via the installed shadcn/Base UI layer (`badge`, `progress`, `tabs`, `alert-dialog`,
      `accordion`, `sonner`/toast are the likely gaps — check `components.json` and
      installed packages first).
- [ ] Extend `lib/status.ts` so every backend state the tracker/approvals/activity render
      has exactly one presentation object (label, tone, icon name, plain-language
      explanation), including the honest states: `awaiting approval`, `queued (202)`,
      `running`, `submitted`, `verified`, `blocked`, `uncertain`, `failed`, and the
      human outcomes. States the backend does not have must not appear.
- [ ] Build the shared presentation components the screens will consume, screen-agnostic
      and typed: a `StatusBadge`, a `PageHeader` (spacious heading + compact metadata, per
      the reference), an `EmptyState` (short list or explanation — never fake data), and
      an `ErrorState` (actionable recovery, matching `lib/errors.ts`).
- [ ] Test: a status-table test that walks every name in `APPLICATION_STATUS_NAMES` +
      `HUMAN_OUTCOME_STATUS_NAMES` and asserts `describeStatus` returns a complete,
      distinct presentation (no two states sharing a label; no empty explanation).

## 4 — Task 4: verification

- [ ] `cd frontend && npm run typecheck && npm run lint && npm run test && npm run build
      && npm run format:check` — all green.
- [ ] Browser check on the **assigned ports** (backend 8001, Vite 5174:
      `VITE_API_PROXY_TARGET=http://127.0.0.1:8001 npm run dev -- --port 5174`): shell at
      1440×1000, 768×900, 390×844 and 360×800 — sidebar/bottom-nav swap, active states,
      focus rings visible, no horizontal scroll. Screenshots into
      `docs/design/ws34-shell/`.
- [ ] Keyboard pass: tab through nav + account menu; drawer focus trap and return.

## Acceptance

- The authenticated frame is recognizably the reference image's shell: forest sidebar,
  grouped nav, active state, sidebar account footer, ivory canvas.
- Every existing route still loads through the same path; lazy loading unchanged; all
  pre-existing shell/layout tests pass.
- One status → one presentation, enforced by test.
- No dependency changes; no screen files touched.

## Tests

`npm run test -- src/components/layout` + the new status-table test; full-suite runs
happen at the lead's integration gate, not inside a parallel workstream.
