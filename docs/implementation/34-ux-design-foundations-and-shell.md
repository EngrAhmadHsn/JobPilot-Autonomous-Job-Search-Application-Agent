# WS-34 (WS-UX-02) · UX redesign: design foundations and the application shell

Status: **Delivered 2026-11-17** (commits `959357e`, `0709c0e`, `28f4eba`, `ea31d2a` — integrated; the nav-group contrast and the focus-ring repair landed as review findings; what landed: [§5](#5--what-landed)) · Source directive:
[JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md](../JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md) §4, §5, §8 (WS-UX-02) ·
Depends on: WS-33 for the design contract, but may start against the master prompt's
already-approved §4 direction (the contract reconciles, not invents) ·
Visual authority: [Redesign Image.png](../Redesign%20Image.png)

> **Where this starts.** The console already has a coherent token system and a working
> shell: `frontend/src/index.css` (ivory/forest/lime/terracotta tokens, Bricolage +
> Geist), `frontend/src/components/layout/{app-shell,nav-drawer,nav-groups,account-menu,
brand-mark,profile-chip}.tsx`, and ten ui primitives under
> `frontend/src/components/ui/`. The reference image wants a deep forest sidebar with a
> clear active state, warm paper surfaces, compact dense cards and a premium, calm
> career-operations feel. This workstream rebuilds the **frame and the shared primitives**
> so every later screen workstream composes on top of them.

## Non-negotiable invariants for this workstream

Preserve route semantics, lazy loading and the React Router view transitions in
`frontend/src/routes.tsx` (only navigation _labels/grouping_ may change, inside
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

- [x] Compare `index.css` tokens against the reference image (forest sidebar depth, paper
      surface warmth, border warmth, active-nav treatment). Adjust only through the token
      layer; raw hex in components is a defect. Keep the existing dark-theme support wired
      and tested; the light warm-paper theme is the default authenticated look.
- [x] Verify every adjusted token passes WCAG 2.2 AA against its expected background
      (muted text on paper, chips on ivory, sidebar active state on forest); record the
      measurements in the workstream doc when done.
- [x] Test: extend `frontend/src/components/layout/app-shell.test.tsx` with the cases the
      restyle could break (active nav state renders; account menu opens; the shell's
      identity gate still hides console chrome from an unauthenticated caller).

## 2 — Task 2: the shell — sidebar, account affordances, responsive navigation

- [x] Sidebar: forest surface, brand lockup, grouped destinations per master prompt §5 —
      Home, Discover, Applications, Resume Studio, Profile & Documents, Activity in the
      primary group; Operations + Administration in a labelled System/Workspace group.
      Map the conceptual groups onto the **existing routes** (Discover → `/app/matches`
      and `/app/matches/:jobId`; Applications → `/app/tracker*` and `/app/approvals`;
      Resume Studio → `/app/tailor*`; Profile & Documents → `/app/profile` and
      `/app/resume`) so no deep link changes.
- [x] Active state: one clearly rendered selected destination, keyboard-focusable, with a
      visible focus ring (the reference's look without dropping focus visibility).
- [x] Account area: keep the existing `account-menu.tsx` / `profile-chip.tsx` behaviors
      (sign-out, theme, credentials) restyled into the sidebar footer, as in the reference.
- [x] Mobile: compact top bar + bottom navigation ≤5 primary destinations, with the
      secondary destinations reachable through the existing drawer pattern
      (`nav-drawer.tsx`); drawers contain their own scroll and return focus on close.
- [x] Preserve the shell's existing a11y contract: the tests in `app-shell.test.tsx`,
      `nav-drawer.test.tsx`, `account-menu.test.tsx` must pass unmodified unless a
      behavior they pin was itself wrong — in that case change the test deliberately, with
      a comment, not silently.

## 3 — Task 3: shared primitives and status centralization

- [x] Audit `components/ui/**` against master prompt §8C's list; add only what is missing
      via the installed shadcn/Base UI layer (`badge`, `progress`, `tabs`, `alert-dialog`,
      `accordion`, `sonner`/toast are the likely gaps — check `components.json` and
      installed packages first).
- [x] Extend `lib/status.ts` so every backend state the tracker/approvals/activity render
      has exactly one presentation object (label, tone, icon name, plain-language
      explanation), including the honest states: `awaiting approval`, `queued (202)`,
      `running`, `submitted`, `verified`, `blocked`, `uncertain`, `failed`, and the
      human outcomes. States the backend does not have must not appear.
- [x] Build the shared presentation components the screens will consume, screen-agnostic
      and typed: a `StatusBadge`, a `PageHeader` (spacious heading + compact metadata, per
      the reference), an `EmptyState` (short list or explanation — never fake data), and
      an `ErrorState` (actionable recovery, matching `lib/errors.ts`).
- [x] Test: a status-table test that walks every name in `APPLICATION_STATUS_NAMES` +
      `HUMAN_OUTCOME_STATUS_NAMES` and asserts `describeStatus` returns a complete,
      distinct presentation (no two states sharing a label; no empty explanation).

## 4 — Task 4: verification

- [x] `cd frontend && npm run typecheck && npm run lint && npm run test && npm run build
&& npm run format:check` — all green.
- [x] Browser check on the **assigned ports** (backend 8001, Vite 5174:
      `VITE_API_PROXY_TARGET=http://127.0.0.1:8001 npm run dev -- --port 5174`): shell at
      1440×1000, 768×900, 390×844 and 360×800 — sidebar/bottom-nav swap, active states,
      focus rings visible, no horizontal scroll. Screenshots into
      `docs/design/ws34-shell/`.
- [x] Keyboard pass: tab through nav + account menu; drawer focus trap and return.

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

## 5 — What landed

The application shell was rebuilt to the approved reference: a deep-forest fixed sidebar
(brand lockup, the journey group, a labelled System group, and an account footer carrying
ProfileChip, ApiStatus and AccountMenu) at ≥lg, and a compact top bar + 5-slot bottom
navigation + drawer below it. The navigation IA is held as data in
`nav-groups.tsx` — six journey destinations with indented children and two System
destinations, each with `matchPath` patterns mapped onto the **existing** routes (detail
routes listed explicitly), so no deep link changed; exactly one row per URL carries
`aria-current="page"` with the filled pill while its destination brightens via
`data-active`, and the same data drives the bottom bar. `lib/status.ts` now gives every
backend state one presentation (label, tone, Lucide icon, plain-language explanation),
enforced by a status-table test; the six §8C primitive gaps were added on the installed
Base UI layer (`badge`, `progress`, `tabs`, `alert-dialog`, `accordion`, `separator` —
`sonner`/toast was **not**: it is not installed and dependencies are frozen, flagged to
the lead), alongside the shared screen components `StatusBadge`/`StatusExplainer`,
`PageHeader`/`Section`, `EmptyState` and `ErrorState`.

### Recorded contrast measurements (WCAG 2.2 AA)

Light theme (`:root`) — sidebar was `#F2EFE6` paper; now the reference's deep forest.
Measured with the WCAG 2.2 relative-luminance formula:

| Pair                            | Foreground                      | Background                 | Ratio | Threshold | Result |
| ------------------------------- | ------------------------------- | -------------------------- | ----- | --------- | ------ |
| Sidebar text                    | `--sidebar-foreground #F2EFE6`  | `--sidebar #1B3831`        | 11.03 | 4.5       | PASS   |
| Sidebar muted text (nav idle)   | `--sidebar-muted #A7BFB4` (new) | `#1B3831`                  | 6.49  | 4.5       | PASS   |
| Active pill text                | `#F2EFE6`                       | `--sidebar-accent #3A6052` | 6.14  | 4.5       | PASS   |
| Muted text on hover wash        | `#A7BFB4`                       | `--sidebar-hover #24443B`  | 5.47  | 4.5       | PASS   |
| Focus ring (UI component)       | `--sidebar-ring #D9F36A`        | `#1B3831`                  | 10.25 | 3.0       | PASS   |
| Sidebar edge vs canvas          | `#1B3831`                       | `#F7F5EF`                  | 11.63 | 3.0       | PASS   |
| Account avatar bg vs sidebar    | `#E4D0C0`                       | `#1B3831`                  | 8.50  | 3.0       | PASS   |
| Terracotta foreground on avatar | `#6D3A27`                       | `#E4D0C0`                  | 6.16  | 4.5       | PASS   |

Dark theme (`.dark`): sidebar `#10241D` — foreground 14.14, muted `#9DB3A7` 7.31, accent
pill `#2B4A3E` with ivory text 8.49, lime ring 13.14 — all PASS.

Unchanged pairs re-verified: ink on ivory 14.75, muted-foreground on ivory 5.38 / on
paper 5.77, forest on forest-soft 10.02, lime-foreground on lime 9.70,
terracotta-foreground on terracotta-soft 8.07, destructive on paper 6.80. Bottom-nav
pairs: forest text on card 11.80, muted on card 5.77. (`--sidebar-border #2E5044` is a
decorative hairline, not a component boundary; the sidebar's identity edge against the
canvas measures 11.63.)

### Fix rounds

- **Round 1 (post WS-33 audit)** — the drawer's 12px group label used
  `text-muted-foreground/80`, which measured 3.55:1 on ivory (under the 4.5:1 a 12px
  label needs). Replaced with the full `text-muted-foreground` token (5.38:1 — PASS); no
  token value changed, the forest branch was already at 6.49:1.
- **Round 2 (reviewer findings, 2026-11-17)** — (1) the tracker/tailor **detail routes**
  (`/app/tracker/:applicationId`, `/app/tailor/:jobId`) lit no nav destination: a bare
  `matchPath` string is an exact match (`end` defaults true), so the comment claiming the
  opposite was inverted and the patterns were missing — both added following the Discover
  precedent, pinned by two new exactly-one-current tests in `app-shell.test.tsx`; (2) the
  **tabs underline rendered on every tab** — `after:bg-primary` was unconditional and the
  `data-active` variant dead code; now
  `after:bg-transparent data-active:after:bg-primary`, pinned by a new `tabs.test.tsx`
  (TDD: both new suites watched failing first); (3) this recording. Verification:
  `npm run typecheck` and `npm run lint` clean;
  `npm run test -- src/components/layout src/components/ui src/lib/status.test.ts` —
  5 files, 28/28 green; touched files prettier-clean.

Deviations the lead should know: the browser check ran on **8003/5177** (the assigned
8001/5174 and all other usual ports were occupied — see the round-0 report §9), and
`npm run format:check` still fails on pre-existing files outside this workstream's
ownership.
