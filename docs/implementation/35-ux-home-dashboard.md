# WS-35 (WS-UX-03) · UX redesign: the Home dashboard — the reference screen

Status: **Delivered 2026-11-17** (commits `cbe0dcb`, `9353d63`, `a00ad19`): the job-first dashboard on real server totals, honest windows, no invented analytics · Source directive:
[JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md](../JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md) §6.1, §8 (WS-UX-03) ·
Depends on: WS-34 (shell + shared primitives + status presentation) ·
Visual authority: [Redesign Image.png](../Redesign%20Image.png) (panel 1),
[JobPilot Career Dashboard.png](../JobPilot%20Career%20Dashboard.png)

> **Where this starts.** `frontend/src/screens/overview-screen.tsx` (test:
> `overview-screen.test.tsx`, polling test: `activity-screen-polling.test.tsx` pattern)
> is the current `/app` index. The reference image's dashboard panel gives the approved
> composition: greeting, four compact stat cards, a featured top-match card with match
> highlights and next actions, an agent-activity column, and a shortlist row. Several
> elements of the image are **illustrative only** and must be grounded or dropped: the
> 96 % match arc, the `+2` trend deltas, the "Live" badge (the API polls; it does not
> stream), the "Last 7 days" progress chart, employer logos, and "Pro Plan". The master
> prompt's rule outranks the picture: **the dashboard answers "what is my next useful
> action", it is not an analytics product.**

## Non-negotiable invariants for this workstream

Every number on the screen is a real value returned by the API, with its true denominator.
No fabricated rates (interview/response/conversion), no time-series unless the API
provides a complete, correctly timestamped dataset (label window + denominator), and
"not enough history yet" is a valid rendering. No "Live" label — polling is labelled
polling with its interval, using the existing `lib/polling.ts` constants
(`OVERVIEW_POLL_MS = 30_000`) and helpers; no new aggressive intervals, no screen-wide
ticking state. Empty data renders an honest empty state, never a fake card. The featured
job and the shortlist are real API results or are not rendered. Match explanations come
from the API's component data (states included — unknown stays unknown).

## File-ownership boundary (exclusive)

`frontend/src/screens/overview-screen.tsx`, `frontend/src/screens/overview-screen.test.tsx`,
and **new** screen-local components under `frontend/src/screens/overview/**`. Shared
primitives (`components/ui/**`, `lib/status.ts`, layout) are consumed, not edited —
proposals go to the lead. `lib/api/**` is read-only.

## 1 — Task 1: inventory the real data available to Home

- [ ] From the WS-33 audit, list exactly which endpoints the overview can call today
      (profile, search/matches, applications list + statuses, audit/activity page, runs)
      and what each actually returns. Record, per planned UI element, its exact data
      source and shape — an element with no real source is cut from the design, not
      faked.
- [ ] Counts must come from server totals (the applications list is paginated — use the
      server's total, not the loaded page length). If a total is unavailable, the element
      shows the honest subset label or is dropped.

## 2 — Task 2: composition

- [ ] Page header: greeting ("Good morning," + the profile's name if present, no emoji)
      and a one-line statement of the workspace's purpose, as in the reference.
- [ ] Stat strip (only real counters): matched/top-fit opportunities, applications in
      progress, submitted, **need your attention** (approvals waiting + blocked/uncertain
      items — the one terracotta card, linking to Approvals). "Need your attention" first
      in the reading order on mobile.
- [ ] "Your attention" / next-actions area: approvals awaiting review, unresolved
      employer questions, blocked or uncertain tasks, ready packets — each row links to
      its real destination (`/app/approvals`, `/app/tracker/:id`, …). When there is
      nothing, render the honest empty state ("Nothing needs you right now") instead of
      padding.
- [ ] Featured opportunity: the top real match (or the application with the most
      meaningful next action) — company, title, location, the real score, a compact
      match-highlights breakdown from the real components, primary action
      (Prepare/Tailor → `/app/tailor/:jobId`, or Review → `/app/approvals`). Follow the
      reference card's composition (logo-free identity block, chips for a few real skill
      signals from the match data, restrained actions) at the reference's density, not
      oversized.
- [ ] Recent activity: the last few real audit events with actor attribution (agent vs
      human, lime/terracotta semantics) and links to the job/application/run. Label the
      feed "updated every 30 s" truthfully; no "Live" badge.
- [ ] Shortlist: 3–4 additional real matches only when match data exists; otherwise the
      row is omitted entirely (no placeholder cards).
- [ ] Charts: the 7-day progress chart is rendered **only** if a complete, timestamped
      application-event dataset is available from the API; otherwise a stage strip built
      from server-side status totals, or nothing. No decorative chart.

## 3 — Task 3: implementation and tests

- [ ] Rebuild the screen from the WS-34 primitives (`PageHeader`, `StatusBadge`,
      `EmptyState`, `ErrorState`, skeletons from the WS-24c pattern for initial loads).
- [ ] Tests (extend `overview-screen.test.tsx`, MSW-backed as the existing suite does):
      (a) stat counters come from server totals, not page length — assert against a
      fixture where the server total differs from the loaded page; (b) "need your
      attention" aggregates approvals-waiting + blocked + uncertain from real statuses;
      (c) with zero data every section renders the honest empty state and no fabricated
      number appears; (d) the activity feed attributes actors correctly and links
      correctly; (e) polling uses the existing overview interval helper and pauses per the
      existing pattern (mirror `activity-screen-polling.test.tsx`); (f) a featured match
      renders `unknown` component states as unknown, not as values.

## 4 — Task 4: the reference gate (master prompt §8 WS-UX-03)

- [ ] Browser-verify at **1440×1000, 1280×800, 390×844, 360×800** against the real
      backend on the assigned ports (backend 8002 / Vite 5175):
      `VITE_API_PROXY_TARGET=http://127.0.0.1:8002 npm run dev -- --port 5175`.
- [ ] A user must be able to identify the next action within seconds: screenshot evidence
      into `docs/design/ws35-home/`, confirm job/application-first ordering, no
      horizontal scroll at 360 px, no clipped text, focus visible, and every metric
      traceable to an API response. Fix before the same system is applied to the other
      screens (WS-36…40).

## Acceptance

- The rendered Home matches the reference panel's composition and density with real
  data, and every element from §2 renders honestly or is absent.
- All tests green; no shared files touched; polling budget unchanged.

## Tests

`npm run test -- src/screens/overview-screen.test.tsx` plus any new screen-local test
files; full suite at the lead's integration gate.
