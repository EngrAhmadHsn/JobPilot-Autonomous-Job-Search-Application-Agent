# WS-48 — shadcn/animate-ui adoption at the base + motion wiring

Status: **In progress — 2026-11-21** · Owner: sprint WS-43…49 · Skill: `animate-ui` (installed at sprint start) · Deps: `@animate-ui/react@2.4.6`, `motion@14.14.0` (installed 2026-11-21, unused so far)

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
