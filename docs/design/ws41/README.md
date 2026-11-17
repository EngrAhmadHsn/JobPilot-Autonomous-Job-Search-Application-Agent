# WS-41 evidence — the responsive and accessibility sweep

Captured 2026-11-17 by `frontend/scripts/ws41-audit.mjs`, driving the **built** console
(`vite build` + `vite preview`) against an isolated API instance (`src.main:app` on its
own port, `DATABASE_URL` pointing at a copy of the local DB, `RATE_LIMIT_REQUESTS`
raised so the sweep measures the UI rather than the limiter).

## `audit.json` — the measurement

60 records: 10 surfaces × 6 viewports, **0 failures**.

| Viewport | Width class |
|---|---|
| `1440x1000`, `1280x800` | the master prompt's two required desktop widths |
| `900x1000`, `768x1024` | the 768–900 "at least one tablet width" band, covered twice |
| `390x844`, `360x800` | the master prompt's two required mobile widths |

The ten surfaces are the real routes from `src/routes.tsx`, not invented ones:
`/app`, `/app/matches`, `/app/resume`, `/app/tailor`, `/app/approvals`, `/app/tracker`,
`/app/profile`, `/app/activity`, `/app/operations`, `/app/admin`.

Each record holds, per surface and viewport:

- `sideways` / `scrollWidth` / `clientWidth` — whether the page scrolls horizontally;
- `overflowCount` + the offenders — elements outside the viewport that are **not** inside a
  legitimate horizontal scroll container;
- `unnamedCount` + the offenders — interactive controls with no accessible name;
- `h1s` — the heading outline (exactly one `h1` per route);
- `hasMain`, `hasSkip`, `focusables`;
- `consoleErrors`;
- `landed` — the pathname the console actually reached, so a catch-all redirect or a
  sign-in bounce can never be recorded as a clean surface.

Across all 60: `sideways=false`, `unnamed=0`, `overflow=0`, `h1=1`.

## The PNGs — the required viewports

One screenshot per surface at `1440×1000`, `1280×800`, `390×844` and `360×800`, plus the
`768×1024` tablet capture where the surface has a distinct shape at that width. The
`900×1000` captures are **not** committed: `768` and `900` cover the same band and the
measurement for both widths is in `audit.json`.

`home-390x844.png` and `home-360x800.png` are the **post-fix** mobile captures: a phone now
reads opportunity → actions → activity → metrics, per master prompt §7. The pre-fix
captures (which led with four metric tiles) are deliberately not kept — an evidence
directory that shows a known defect beside its fix invites the reader to trust the wrong
one.

## What this set does not prove

The sweep proves the **populated** render at six widths, plus that the console's own
error states render. It does **not** enumerate every state in Task 3's matrix
(`blocked challenge`, `submission.uncertain`, `degraded source`, `durable run in
progress`) on every surface — see the workstream document's §6.
