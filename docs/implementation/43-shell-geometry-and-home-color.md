# WS-43 — Shell & sidebar geometry, Home featured-match color

Status: **In progress — 2026-11-21** · Owner: sprint WS-43…49 · Design authority: `docs/Job Pilot (Copy).pdf` + the resolution-matched renders in `docs/design/Images-figma/Job Pilot/`

## Goal

Fix the shell defects the user pass found against the live console: the violent layout shift when the sidebar rail expands, the toggle button's position/size/radius, the rail's active-pill radius, the account footer's alignment, and the wrong text color on Home's featured-match card. Restyle the mobile navigation drawer to the design's expanded-navigation treatment.

## Design references (primary)

- `docs/design/Images-figma/Job Pilot/13 · Expanded navigation · 1440.png` / `· 1024.png` — expanded rail at desktop sizes: chevron **in the header row adjacent to the wordmark**, lime active pill with a large radius, footer aligned to the nav rows.
- `docs/design/Images-figma/Job Pilot/13 · Expanded navigation · 768.png` / `· 390.png` — below 1024 the expanded navigation is an **overlay drawer over dimmed content**.
- `docs/design/Images-figma/Job Pilot/01 · Home · 1440.png` — the featured-match card: forest background, **white title**, lime score chip, light CTA; the next-step panel: terracotta-soft background, **dark forest text**.
- Zoom detail: `docs/design/Images-figma/43.jpg`, `48.jpg`, `51.jpg`.

**User-directed deviation from the design reading:** at ≥1024 the expansion **overlays** the content (content gutter constant at 72px; expanded rail floats over it) instead of the design's push — the push reflows the whole content column on every toggle, which is the defect being fixed. Recorded in the sprint ledger.

## Current state

- `frontend/src/components/layout/app-rail.tsx` — fixed aside; `w-60`/`w-[72px]` with a width transition; toggle chevron `size-4` floating `absolute top-[86px] left-1/2` when collapsed, `justify-between px-6` when expanded; rail rows `rounded-xl`; footer `px-6` vs nav `px-3.5`.
- `frontend/src/components/layout/app-shell.tsx` — content column shifts via `railExpanded ? "lg:pl-60" : "lg:pl-[72px]"` → the reflow defect.
- `frontend/src/components/layout/nav-drawer.tsx` — Base-UI Sheet, `w-[290px]`, generic rows.
- `frontend/src/screens/overview/featured-match.tsx` — title `text-primary-foreground` inside a card `bg-primary`, with an inner `PlainText` span that can drop the inherited color.

## Concrete tasks (atomic commit per feature)

1. **Rail overlay geometry** — `app-shell.tsx` content gutter constant `lg:pl-[72px]`; expanded rail `w-60` gains an elevated shadow; auto-collapse on navigation. Commit: `fix: the rail expands over the content instead of reflowing it (ws-43)`.
2. **Toggle position & icon size** — chevron adjacent to the wordmark when expanded (small gap, not far-right); collapsed keeps its design slot; icon `size-5 strokeWidth={1.8}` matching nav glyphs. Commit: `fix: the rail toggle sits with the wordmark and uses the nav icon size (ws-43)`.
3. **Radius unification** — rail rows `rounded-2xl` (current/hover), toggle `rounded-lg`, drawer rows on the same scale. Commit: `fix: the rail's active pill takes the design's radius (ws-43)`.
4. **Footer alignment** — expanded footer adopts the nav's exact padding structure so the avatar sits under the icon column and the identity block under the labels. Commit: `fix: the rail's account footer lines up with the navigation rows (ws-43)`.
5. **Home featured-match color** — reproduce in the real browser, fix so the title is white on the forest card (and dark text on the terracotta next-step panel) in both themes. Commit: `fix: the featured match title reads white on the forest card (ws-43)`.
6. **Nav drawer restyle** — labeled rows, lime active pill, avatar footer, ~58% width at 768 / near-full at 390, per the 768/390 expanded-navigation references. Commit: `feat: the mobile navigation drawer matches the expanded-navigation design (ws-43)`.

## Acceptance criteria

- Toggling the rail at 1440 and 1024 causes **zero content reflow** (content x-positions constant; only the rail changes).
- The toggle, icon sizes, radii, and footer alignment match the `13 · Expanded navigation · 1440` render.
- The mobile drawer matches `13 · Expanded navigation · 768/390` (scrim, width, rows, footer).
- Featured-match title is legible white-on-forest in light and dark themes.
- `ws41-audit.mjs` stays clean at 1440×1000, 1024×1000, 768×1024, 390×844.

## Tests

- `frontend/src/components/layout/app-shell.test.tsx`, `nav-drawer.test.tsx` updated; new assertions for constant gutter + overlay behavior.
- Manual: browser pass at the four design frames against the reference PNGs.

## New dependencies

None.
