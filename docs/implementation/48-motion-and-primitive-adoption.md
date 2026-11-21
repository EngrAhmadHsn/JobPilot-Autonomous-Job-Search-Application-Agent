# WS-48 — shadcn/animate-ui adoption at the base + motion wiring

Status: **Delivered 2026-11-21** — the primitive inventory is closed with a ruling per component, three primitives were rebased on their canonical bases, the provider and the sprint's new surfaces moved onto the library's tokens, and the motion audit's 126 facts are adjudicated below.

## What shipped

| Commit | Feature |
|---|---|
| `b60ee70` | the ui primitives animate through `@animate-ui/react` (the CLI sweep, 8 primitives) |
| `fc09991` | the jsdom shims the animated primitives need |
| `76c71dd` | the animate-ui skill joins the project tooling |
| `eb1d228` | badge sits on its canonical base without clipping the skill chips |
| `02d31e1` | separator sits on its canonical base |
| `9b76f28` | the pagination shell sits on its canonical base |
| `fbb71aa` | motion runs through the animate-ui provider and its tokens |

### The primitive inventory (every `components/ui/*`, with its ruling)

`button`, `input`, `card`, `table`, `skeleton` and `empty-state`'s structure were diffed byte-wise
against the canonical `base-nova` sources (the registry the project's `components.json` style
resolves to) and are **already on their canonical bases**: the only deltas are the token restyle
and the console's measured geometry (control heights, radius scale), each documented in-file.
`card`'s single divergence is a token rename (`cn-font-heading` → our own `font-heading`).

Three primitives genuinely diverged and were **rebased**: `badge` (now `useRender` + `mergeProps`
with the canonical variant family; export/prop API a superset), `separator` (the canonical
`data-horizontal:`/`data-vertical:` variants and `self-stretch`), and the `pagination` shell (both
pagers are now `<nav aria-label="pagination">` landmarks).

Five were **rejected** as compositions, with the reasons recorded in the agent's inventory
(`.scratch/ws43-sprint/c1-report.md`, which also keeps the fetched canonical sources for a
re-diff): `status-badge` (no canonical base exists, and composing it would import `shrink-0` /
`overflow-hidden` plus `[a]:hover:` washes that would tint a status chip when its parent link was
hovered), `page-header` (404s in every shadcn registry style; it owns `document.title` and the
screen's single `h1` — app contracts, not primitive styling), `link-button` (no canonical base; it
already rides the canonical button's cva via `buttonVariants`), `error-state` and `empty-state`
(their part trees were evaluated part-by-part and rejected: the canonical parts would have to be
overridden on nearly every one, leaving a fork wearing a canonical costume — `empty-state`'s
`text-balance` could not even be overridden cleanly through `cn()`).

Every **registry adoption** (liquid/flip buttons, animated icons, a theme toggler, backgrounds) was
**rejected**: the design frames draw plain controls on data-dense screens, and the console's theme
control is the account menu's radio group ("Ivory / Charcoal / Match the system"), not a sun/moon
button.

### The motion audit, adjudicated (task 5)

`npx @animate-ui/cli@latest audit --json` reports **126 facts across 20 files**. Judged in context,
not fixed blindly:

| Kind | Count | Ruling |
|---|---|---|
| `animated-properties` | 91 | Almost all are `transition-colors` — a paint-only transition on a hover/focus state, which is exactly what a colour change should be. The flagged pattern is `transition-all`, which appears **nowhere** in the console. |
| `no-reduced-motion` | 17 | The per-file check cannot see the console's **global** reduced-motion path: `html[data-motion="reduced"] *` zeroes animation durations and narrows transitions to non-moving properties (`index.css`), `motion.ts` sets that attribute before the first render, and `AnimateUIProvider reducedMotion="user"` does the same job for the library's own primitives. The skeleton's `animate-pulse` is already zeroed by that block — a `motion-reduce:` class beside it would be redundant, not safer. |
| `long-duration` | 7 | The console's own entrance timings (420–700 ms for section reveals and the agent-progress sweep). These are page-reveal affordances, not control feedback, and the reduced-motion block collapses them to a fade. |
| `layout-animation` | 5 | **False positives**: the `layout` prop in `screens/studio/resume-diff.tsx` is the diff's stacked/side-by-side domain prop, not Motion's `layout` attribute. No Motion layout animation exists in the console. |
| `hover-scale` | 3 | The canonical button's `hover:scale-[1.02]` and the landing page's `hover:scale-[1.03]`. Tailwind v4 scopes its `hover:` variant to `@media (hover: hover)` already, so a touch screen never sticks in the hovered state. |
| `infinite-loop` | 2 | The skeleton pulse and the agent-progress sweep — the console's honest "work in progress" affordances, both collapsed by the reduced-motion block. |
| `hover-not-gated` | 1 | **Fixed**: the hand-written `.shine:hover::before` rule ran outside `@media (hover: hover)`, so a tap on a touch screen left the light at the end of its travel. The hover sweep is now gated the way Tailwind's own variant is; `:focus-visible` keeps its sweep everywhere, because a focus ring is not a hover state. |

### What the motion itself is

`AnimateUIProvider` (tempo 1, `reducedMotion: "user"`) wraps the app in `main.tsx`, so every
library primitive and every hand-written value reads one clock. Hand-motion is written only from
`@animate-ui/react/utils/motion` — never a hand-typed spring or duration — and only on properties
the compositor can take:

- the Discover result row's selection wash is an absolutely positioned layer whose opacity eases on
  `transition.fade` (not a background class that snaps, and deliberately **not** a `layoutId`:
  the row list is a hot path, and a projected move over board-supplied row heights is main-thread
  work exactly where it must not go);
- the question counter chips swap on `transition.swap`, with `popLayout` so the chip row does not
  reflow mid-swap;
- the Profile skeleton hands over to content (fade out, `blur.surface` reveal in), with the gate
  read during render rather than in an effect;
- the sheet's CSS transition classes are gone — the animate-ui Base-UI dialog primitive owns the
  panel and backdrop travel now, on its own curve.

**Reader's notes.**

- The `animate all` CLI sweep ran in Wave 0, before the feature waves, so the new surfaces were
  built on the animated primitives instead of retrofitted.
- `verify-motion-control.mjs` is green (2026-11-21, isolated stack): with the machine reporting
  `reduce`, the landing page sets `data-motion="reduced"` and its heading animates on
  `reduced-fade 0.32s`; after the visitor chooses **Full**, `data-motion="full"` and the heading
  animates on `enter-up 0.42s`, the animated colour field repaints, and the demo walkthrough still
  advances. Both halves of the contract are therefore real: the OS preference is honoured *and*
  the in-app override restores motion.
- The `jsdom` shims (`fc09991`) are load-bearing: the animated primitives need browser APIs jsdom
  does not implement, and without them the suite is red on a pristine checkout. The earlier
  "verification" that missed this had piped vitest through `tail`, which masked the exit code —
  the lesson is recorded in the sprint ledger.

## Goal

Our UI primitives are hand-rolled on `@base-ui/react` with bespoke CSS motion while canonical shadcn/animate-ui implementations exist for the same parts. Rebase the primitives **on the canonical bases** — modified only to fit our design tokens — so future maintenance is upgrading a known component, not maintaining a fork. Explicitly authorized to affect as many components as needed. Then wire `AnimateUIProvider` and put Motion (via `motion/react` + animate-ui tokens) on the surfaces that deserve it.

## Rules (from the animate-ui skill + this repo's motion contract)

- Path detection per component: shadcn/ui-shaped → `@animate-ui/cli animate`; built on Radix/Base-UI/React-Aria → import swap to `@animate-ui/react/primitives/…`; anything else → Motion recipes or a registry component.
- Every motion value comes from `@animate-ui/react/utils/motion` (springs/tokens) or `AnimateUIProvider`'s `tempo` — never a hand-typed spring.
- Motion rules that must pass: reduced motion (`reducedMotion: "user"` + `motion-reduce:` paths), keyboard, trigger-anchored origins, compositor-only properties (no layout animation on hot paths), no `transition: all`, no ease-in entrances, nothing stretching as it resizes.
- Call-site safety: export names and prop APIs of `components/ui/*` stay stable — screen tests prove behavior unchanged.

## Current state

- `frontend/components.json` — `registries["@animate-ui"]` configured; style `base-nova`, icon library lucide; all `components/ui/*` on `@base-ui/react` (no radix imports).
- `frontend/package.json` — `@animate-ui/react` + `motion` installed; zero imports in `src/`.
- Existing motion: CSS (`use-reveal.ts` IntersectionObserver, `stagger.ts` `--i` delays, `motion.ts` preference mirror to `<html data-motion>`, `tw-animate-css`, `.shine/.agent-progress/.skeleton` utilities).

## Concrete tasks (atomic commit per primitive/pair)

1. **CLI sweep** — `npx @animate-ui/cli@latest animate all --dry-run`, review, apply; re-run after feature waves so new components are covered. Commit: `chore: the ui primitives animate through @animate-ui/react (ws-48)`.
2. **Primitive inventory + rebase** (agent C1) — map every `components/ui/*` to its canonical shadcn/animate-ui base; rebase and restyle to our tokens (ivory/forest/lime, radius scale, surface radii), keeping exports/props. One commit per primitive or tight pair, each with the touched screen tests green: `refactor: <primitive> sits on its canonical base (ws-48)`.
3. **Registry adoptions where they genuinely fit** — animated icons (nav, form controls), backgrounds, liquid/flip buttons, theme toggler via the `@animate-ui` registry / shadcn MCP; adopted only where the design calls for them, never as decoration on data-dense surfaces.
4. **Provider wiring + hand-motion** (agent C2) — `AnimateUIProvider` (tempo 1, `reducedMotion: "user"`) in `main.tsx`; motion on: the nav sheet drawer (incl. the WS-43 expanded-drawer treatment), the filters dialog, the results selection indicator, save-answer success, skeleton→content swaps. Compositor-only properties. Commit: `feat: motion runs through the animate-ui provider and tokens (ws-48)`.
5. **Audit + gates** — `npx @animate-ui/cli@latest audit` (facts judged in context, not blind fixes), `frontend/scripts/verify-motion-control.mjs`, and the WS-41 sweep. Fix flagged patterns (transition-all, ease-in entrances, missing reduced-motion). Commit: `fix: the motion audit's real findings (ws-48)`.

## Acceptance criteria

- Every `components/ui/*` either sits on its canonical base or carries a ledgered ruling why not.
- Zero hand-typed springs/durations outside the token utilities; `AnimateUIProvider` governs tempo; reduced-motion paths everywhere.
- Screen tests stay green across every rebase; the motion audit's actionable findings are fixed or ruled.
- The console at the four design frames is visually unchanged except where the sprint's features intentionally changed it.

## Tests

- Full FE suite after each rebase (`npm run test -- --maxWorkers=2`); `verify-motion-control.mjs`; `animate audit` review.

## New dependencies

None beyond the installed `@animate-ui/react` + `motion` (registry components pull their own peers when adopted — installed explicitly, justified per adoption).
