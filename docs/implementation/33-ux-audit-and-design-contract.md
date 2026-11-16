# WS-33 (WS-UX-01) · UX redesign: repository audit and the design contract

Status: **Planned — not started** · Source directive:
[JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md](../JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md) §2, §4, §8 (WS-UX-01) ·
Depends on: nothing · Baseline: tag `v1.0.1` (`80af039`) ·
Visual authority: [Redesign Image.png](../Redesign%20Image.png) · Dashboard detail:
[JobPilot Career Dashboard.png](../JobPilot%20Career%20Dashboard.png)

> **Where this starts.** The master prompt §2 requires a fresh audit of the current branch
> before any edit, because workstream docs lag code. This workstream produces the audit and
> the shared design contract that every later WS-UX workstream consumes. **It changes no
> application code** — its only writes are the two `docs/design/` documents and the baseline
> screenshots.

## Inherited invariants (master prompt §3 — bind every WS-UX workstream)

The backend is the source of truth; the agent proposes and the human decides; real-board
assist never submits; fake-ATS and real-board stay visibly distinct; never fabricate
candidate facts, keywords, metrics, states, routes or outcomes; keep unknown distinct from
negative; approval `202` means queued, not submitted; ownership and tenant isolation are
authoritative; job-board content is untrusted text; secrets and PII are never rendered;
EEO never influences matching; polling is labelled polling, not "live"; the request budget
follows `frontend/src/lib/polling.ts`'s documented intervals; WCAG 2.2 AA is part of done;
tests are never deleted to go green; no backend rewrite and no surprise dependencies.

## File-ownership boundary (for parallel dispatch)

This workstream writes **only**: `docs/design/JOBPILOT-UX-01-AUDIT.md`,
`docs/design/JOBPILOT-DESIGN-SYSTEM.md`, `docs/design/baseline/**`. Read-only everywhere
else. It must not run `npm run api:types` (it reads the *running* server and has silently
deleted types before) — the backend is unchanged, so the API types are frozen.

## 1 — Task 1: route, screen, API and status map

- [ ] Read `frontend/src/routes.tsx` and enumerate every route with its lazy screen module.
- [ ] Read every file in `frontend/src/screens/**` plus its test, and record per screen:
      purpose, API calls made (via `frontend/src/lib/api/endpoints.ts`), states rendered
      (loading/empty/error/populated), polling used (from `frontend/src/lib/polling.ts`
      constants), and tests that pin behavior.
- [ ] Cross-check every frontend call against the backend's real routes: start the API and
      dump `env/Scripts/python.exe -c "from src.main import app; import json;
      print(json.dumps(sorted({m + ' ' + r.path for r in app.openapi()['paths'].items()
      for m in r[1]}), indent=0))"` — `app.routes` lies (lazily mounted); only
      `app.openapi()` reports the true 67-route surface.
- [ ] Read `frontend/src/lib/status.ts` and record the status-presentation contract
      (`describeStatus`, `StatusTone`, `APPLICATION_STATUS_NAMES`, human-outcome names) —
      one backend state must keep exactly one label/tone/explanation everywhere.
- [ ] Record where the current UI already violates the master prompt's truth rules
      (e.g. any "live" label on polling, any count computed from a partial page) and where
      the reference image's elements are illustrative-only (96 % match arc, "Pro Plan",
      employer logos, the 7-day progress chart) and must be grounded or dropped.

## 2 — Task 2: stale-documentation check

- [ ] Compare the frontend-facing claims in `docs/implementation/13`, `17`, `19`–`22`,
      `25`, `31`, `32` against current source; record drift in the audit doc with
      file:line evidence. Source outranks docs; do not silently invent a contract.
- [ ] Verify the ATS weighting claim (45/20/20/15) against `src/resume/ats.py` before any
      later workstream may print those numbers in UI copy.

## 3 — Task 3: baseline screenshots

- [ ] Start the stack on the **default ports** (backend 8000, Vite 5173) — this workstream
      owns them while it runs; parallel workstreams must use their assigned alternates
      (`VITE_API_PROXY_TARGET=http://127.0.0.1:<backend> npm run dev -- --port <frontend>`).
- [ ] Authenticate by **registering a throwaway local account** through the real API
      (per-user isolation means a fresh account starts honestly empty). Seed only what the
      product itself produces: upload a checked-in fixture résumé
      (`tests/fixtures/**` or `frontend/e2e/fixtures/**`), run a real stored-corpus search,
      and, to populate tracking, run the real prepare step for one job (prepare only —
      never approve-and-forget). No mock data may be hardcoded anywhere.
- [ ] Capture with a real browser (Playwright is installed): Home, Discover + a job detail,
      Tailor, Approvals, Tracker, Profile, Activity, Operations — at **1440×1000** and
      **390×844** — into `docs/design/baseline/`, one PNG per surface and viewport, named
      `<surface>-<width>.png`. Empty states are required evidence, not a failure.
- [ ] Kill both servers afterwards so the ports are free for the next workstream.

## 4 — Task 4: the design-system contract

- [ ] Write `docs/design/JOBPILOT-DESIGN-SYSTEM.md`: the token table (ivory `#F7F5EF`,
      paper `#FFFDF8`, forest `#173D32`, agent lime `#D9F36A`, human terracotta `#F1D6C8`,
      sage `#E6ECE8`, warm border `#E3DDD0`, ink `#23211C`, muted `#6A6459`; Bricolage
      Grotesque display / Geist interface) reconciled against what `frontend/src/index.css`
      actually declares; the semantic rules (lime = agent-originated, terracotta =
      human-originated, forest = brand/primary); status→tone mapping from
      `lib/status.ts`; spacing/surface/elevation rules from the reference image; and the
      component-strategy rules of master prompt §8C (shadcn/Base UI foundation, Lucide
      only, no card-in-card, no glassmorphism, reduced motion).
- [ ] Measure text contrast for the status tones (WCAG 2.2 AA) and record any token that
      fails — later workstreams may only adjust tokens through this document.

## Acceptance

- `docs/design/JOBPILOT-UX-01-AUDIT.md` holds the route/API map, per-screen inventory,
  stale-doc findings, and the illustrative-vs-grounded list for the reference image.
- `docs/design/JOBPILOT-DESIGN-SYSTEM.md` exists and agrees with `index.css` and
  `lib/status.ts`.
- `docs/design/baseline/` holds ≥16 PNGs (8 surfaces × 2 viewports).
- Zero application-code changes: `git status` shows only the three new doc/screenshot
  paths.

## Tests

No new tests (documentation workstream). The audit's correctness is checked by the
consuming workstreams: any contract a later workstream cites must carry a file:line
reference into this audit.
