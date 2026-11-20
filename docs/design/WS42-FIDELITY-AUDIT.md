# Figma fidelity audit — the 83 frames, measured and corrected

**Date:** 2026-11-20 · **Design source:** Figma file `7K6iWR1nxcAMMOiIYEUJW8`
("Job Pilot") · **Local copy:** `docs/design/Job Pilot Updated.fig`, verified
pixel-identical to the live file (`compare_image` against a live export:
`nonTextMismatch: 0.0`) · **Method:** `figlens compare_image` on every
screen × viewport pair, region-by-region classification, fix, re-measure.

## 0. What the 83 links are

The user's 83 node links are **20 screens × 4 viewports (1440 / 1024 / 768 /
390) + 3 interactive-table component sets** — 80 designed frames plus 4
overlays, and the component sets that define sort/pager states. They are not
83 distinct screens.

## 1. How the audit was run

1. **Ground truth first.** The saved `.fig` was proven identical to the live
   Figma file before a single comparison, so the whole audit could run offline
   against a stable snapshot (no seat, no quota, no network).
2. **Captures at the design's own size.** The committed instrument
   `frontend/scripts/ws42-shot.mjs` signs in as the local operator, seeds the
   chosen profile (`--profile`, because profile-dependent screens render their
   empty state on a fresh browser), and screenshots each route at the frame's
   exact viewport — 1440×1000, 1024×1000, 768×1024, 390×844. A `--no-login`
   flag covers the unauthenticated sign-in surface.
3. **Measured comparison, not eyeballing.** `compare_image` draws the design
   node over the screenshot and reports `mismatch`, `nonTextMismatch` and the
   largest differing regions with the deepest design layers under each.
   A faithful build measures 0.14–0.35 % `nonTextMismatch`; the first pass
   here measured 4.4–26 %.
4. **Every region classified** as a **defect**, **data** (the design's example
   content where real data now sits), **state** (a designed state a read-only
   capture cannot produce), or **deliberate** (an honesty ruling that
   overrides the drawing). Only defects were fixed.

Ledgers per family (with per-viewport numbers and exact design geometry) live
in `.figlens/exports/ws42-audit/ledger/`:
`discover-family.md`, `track-family.md`, `operate-family.md`,
`voice-family.md`, `special-states.md`.

## 2. What was wrong (and is now fixed)

### 2.1 The shell — one fix that lifted every mobile screen

| Defect | Evidence | Fix |
|---|---|---|
| Phone/tablet chrome was a light utility bar with a hamburger | ~48 000 differing pixels **per screen** at 768; the design's bar is a full-bleed forest `#1b3831` 64 px band | Rebuilt to nodes `49:7561` / `49:10263`: forest wordmark bar ("JobPilot" 21/600 white), environment marker and account control |
| Bottom navigation had five flat items | Design `49:10379` carries three destinations + "More" | 4-slot bar (Home / Discover / Applications / **More**); "More" opens the drawer; active = 600-weight label, no pill |
| The nav drawer was a paper-white sheet | Design `49:11961` is the forest expanded rail | Forest skin, lime active pill, account block at the foot |
| **Expanding the rail painted over the content** | Shell gutter was fixed at `lg:pl-[72px]` while the rail grows to 240 px | Expand state lifted into `AppShell`; content padding animates 72 ↔ 240 px on the same clock as the rail |
| Content gutters were 24/32 px at all widths | Design: 20 px below 1024, 32 px above | `console-container` now 20 px < 1024 |
| Type scale was one size | The design measures **28/37 @ 390, 30/40 @ 768, 32/42 @ 1024, 36/47 @ 1440** | `type-display` is responsive; tracking is **0** everywhere (the old −0.02 em was itself a defect) |
| The account email bled out of the 72 px rail | Visible in the Profile capture | Compact variant drops the text; avatar only |

### 2.2 Screen-level defects

| Screen | Defects fixed |
|---|---|
| **Home** | h1 was the label "Overview"; now the design's statement ("Your next career move.") with a stable tab title via `PageHeader documentTitle`. Action queue listed records with status badges → task-phrased rows ("Review your Acme application" / "…packet is ready"). Digest was a timeline → the design's chips (AGENT / YOU / SYSTEM), titles, quiet actions, dividers, three rows. Featured card was a score-bar panel → the forest "Recommended role" card. Pipeline had a legend row the design does not draw. Metrics were single-column at 390 → 2×2 |
| **Discover** | h1 label → "Find your kind of work."; match reasoning rebuilt as verdict + narrative + clay evidence-gap + "How the match is explained" rows (raw enums removed); suggestions popup anatomy; integer score format |
| **Applications board** | The board-integrity legend was **entirely absent** — now verbatim ("A stage is a fact, not a guess. Queued does not mean sent…"); Board/List pills lifted to screen level as filled pills; Filters / count / "Find another role →" toolbar; card CTA pill + timestamp + divider |
| **Application details** | h1 → "Every step, with evidence."; id/metadata fields → the design's state fact rows (Approval / Execution / Form interaction / Submission / Evidence); timeline rows in human voice |
| **Review** | Approval-boundary panel now carries the design's own sentence ("Your approval is specific. Your final submit stays yours.") on the real-board path, keeping the no-submit-capability honesty sentence |
| **Profile** | Per-row "Preview ↗" now exists (real download route, new tab); ORIGINAL chip → sage wash; tabs wrap at 390 as drawn |
| **Operations** | **Two whole panels were missing**: "Corpus freshness" (last completed refresh, adapters configured, search availability) and the sortable "Source status" table. Both built on a new endpoint. The recoverable-run treatment (chip + "An administrator can resume only the unfinished work." + Open administration) added. Runs table now sortable with the design's pager; duplicated "Progress" header fixed |
| **Administration** | Statement h1; the design's section chips (Overview / Runs / Workers / Metrics) + ADMIN ONLY chip; the four operational metric tiles (Recoverable run / Queued application / Source adapters / Active workers) sharing the sections' query cache; "Start bounded worker" and "No active worker" are the design's own words; the design's pager |
| **Studios / intake / auth** | Intake copy and the "Your original is kept…" line; the auth surface rebuilt toward the design's console composition |

### 2.3 Backend addition (the one API change)

`GET /api/jobs/sources` — the source registry (watched boards and their
health, per-adapter counts), the last completed refresh and the stored-corpus
size. The registry is **shared** exactly like the corpus; the route reads the
board table on the **request's own session** (the module-level helper would
bypass the dependency-injected session and break every test). Covered by
`tests/test_jobs_api.py::test_source_status_reports_registry_and_freshness`,
and the README's API table (machine-checked) now lists it.

## 3. Verification

| Gate | Result |
|---|---|
| Frontend unit tests | **349 / 349** (44 files) |
| Typecheck | clean |
| Lint | clean (fixed a React 19 `react-hooks/refs` error and a memo dependency) |
| Production build | ✓ 1.32 s |
| **Responsive / a11y sweep** (`frontend/scripts/ws41-audit.mjs`, the committed instrument) | **60 / 60 surface × viewport clean** — 0 sideways scroll, 0 unnamed controls, 0 overflow, exactly one h1, at 1440 / 1280 / 1024 / 768 / 390 / 360 |
| Backend suite | **2,189 passed, 8 skipped, 0 failed** (742 s; the 10 deselected are the known Remotive DNS flake) |
| Tenancy gate (`test_tenant_isolation_api`) | passes — the new route reads `job_runs` through `src.db.access`, never directly |
| Docs contract (README API table) | 9 / 9 |
| Live endpoint verification | `GET /api/jobs/sources` → 27 boards / 3 adapters / 0 failing / last refresh Nov 7 / 8,558 stored jobs |

### Measured improvement (1440 unless noted)

| Screen | Before | After |
|---|---|---|
| Home | 13.0 % | 10.7 % (1024: 10.6, 768: 9.2, **390: 20.1 → 9.3**) |
| Discover | — | 6.3 % |
| Applications board | 6.1 % | 5.3 % (**390: 16.7 → 8.4**) |
| Application details | 4.4 % | 4.8 % |
| Review | 6.5 % | 6.5 % (mostly a state difference) |
| Profile | 7.4 % | 7.2 % |
| Activity | 5.4 % | 5.0 % |
| Operations | 5.6 % | 5.5 % (structure now complete) |
| Administration | 5.9 % | 5.9 % (structure now complete) |

The residual percentages are dominated by the accepted classes below, not by
layout drift: every remaining large region carries design example text
("Northstar Labs", "Platform Engineer") where the real corpus now renders, or
a designed state the capture cannot reach.

## 4. Accepted differences (named, not silently kept)

| Class | What | Why it stays |
|---|---|---|
| Font metrics | Bricolage Grotesque **Variable** vs the design file's static cut renders glyphs a pixel or two differently | The project ships the variable font; the size, weight, colour and tracking are verified equal via `inspect` |
| Real data | Document lists, application cards, digest rows, source boards | The product shows the corpus, never the design's example rows |
| Designed states not reachable read-only | Studio's post-run diff, Review's post-prepare question flow, a recoverable run | Capturing them needs live mutations; the states exist and are test-verified |
| Honesty rulings (design overridden) | No per-question "Save answer" (no endpoint); approve stays available with blockers; the top bar shows the real environment marker, not "Concept · example data"; initials avatars; no ⌘K hint; `verified` never reads as "awaiting submit" | Repository rules: never claim an unprovable outcome |
| Copy the design itself draws | "Needs you" column name, the board legend, "Every application, in context." | Implemented verbatim — these *are* the honesty contract |

## 5. Open items (honest)

1. **Three designed surfaces have no route yet** — the dedicated EEO /
   "Questions & privacy" screen (`47:716`), the run-diagnostics drill-in
   (`47:678`) and **Account & security** (`47:526`, with session list and
   revoke). The last needs HTTP endpoints that do not exist
   (`src/auth/sessions.py` has `list_sessions` / `revoke_*` with no routes).
   These are new-surface work, not fidelity corrections.
2. **Auth composition** — the sign-in screen is being rebuilt toward the
   design's console composition; any panel the backend cannot honour (reset
   password, verify email, register) must stay unbuilt rather than fake.
3. **The three fix workstreams that ran out of quota** (Discover verification
   sweep, Voice, Profile/Activity) were completed by the lead for the defects
   verified above; their remaining P3s are listed in the ledgers.
