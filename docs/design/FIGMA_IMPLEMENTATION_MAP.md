# Figma Implementation Map — JobPilot "Job Pilot Updated"

**Status:** Both passes delivered — 2026-11-19 (shell, Home, Applications,
Discover exact) and 2026-11-20 (every remaining screen rebuilt or voiced to
its design node; see
[`IMPLEMENTATION_STATUS.md`](./IMPLEMENTATION_STATUS.md) for the honest
per-screen record and the named deviations) ·
**Design source (priority):** Figma MCP — <https://www.figma.com/design/7K6iWR1nxcAMMOiIYEUJW8/Job-Pilot>
(`node-id=0-1`). File key `7K6iWR1nxcAMMOiIYEUJW8`, page `0:1`, **20 screens**.
**Design source (offline fallback):** [`Job Pilot Updated.fig`](./Job%20Pilot%20Updated.fig) —
verified byte-for-byte equivalent by node id (`16:2`, `47:2`, …), read with FigLens.
**Reference renders:** [`docs/design/ws42/reference/`](./ws42/reference/) (20 PNGs at 1440).
**Current-state baseline:** [`docs/design/ws42/browser/current/`](./ws42/browser/current/).

This map is the Phase 1 deliverable: every Figma frame, its node id, the
application route it maps to, what it owns, and its state.

---

## 1. The design's frame system

The file is organised as **20 numbered screens × 4 viewports**, plus 4 overlays
and 3 reusable component sets. All 20 desktop screens are 1440×1000.

| Viewport group | Node range | Count | Notes |
|---|---|---|---|
| 1440 desktop | `16:2`…`16:322`, `47:298`…`47:716` | 20 | The authoritative layouts |
| 1024 intermediate | `49:5231`…`49:7447` | 20 | Desktop/tablet — same content, narrower columns |
| 768 tablet | `49:7534`…`49:10130` | 20 | Mostly single column, rail still present |
| 390 phone | `16:323`, `16:324`, `16:325`, `49:10390`…`49:12831` | 19 | Bottom navigation, stacked |
| Overlays | `49:12938`, `49:12963`, `49:12988`, `49:13012` | 4 | Job filters (480/350), Create account (480/350) |
| Component sets | `49:3196`, `49:3745`, `49:5091` | 3 | Interactive tables: Source status, Durable runs, Lifecycle activity |

### The shell is identical on all 20 desktop screens

| Element | Node | Measurement |
|---|---|---|
| Desktop navigation rail | `47:2` | **72 px wide**, `#1b3831` fill, full height |
| Rail brand "JP" | `47:3` | 22/600/32, lime `#d9f36a`, at (22, 22) |
| Rail expand affordance | `47:4` | 40×32, `#294c40`, r=8, glyph `›` |
| Rail nav item | `47:6` | **44×44, r=12**; positions y = 130, 188, 246, 304, 362, 420 … 840 |
| Rail active state | `47:6` | **lime `#d9f36a` fill**; idle = transparent |
| Rail nav glyph | `47:7` | 20×20, centred (12 px inset in the 44 box) |
| Rail account avatar | `47:27` | 36×36, r=18 (circle), at (18, 942) |
| Top bar | `47:28` | **1368×68**, `#fffdfa` fill |
| Breadcrumb | `47:29` | 11/600/16, `#6a6459`, `WORKSPACE / <SCREEN>` at x=40 |
| Context note | `47:32` | 10/400/15, `#6a6459`, right-of-centre (x=960) |
| Search anywhere | `47:30` | 12/400/17, `#6a6459`, `⌘ K` hint (x=1100) |
| Account avatar | `47:31` | 32×32, r=16 (circle), at (1304, 18) |
| Main viewport inset | `47:33` | x=104, y=102 → **32 px gutter** past the 72 rail |

**The expanded navigation** (`47:450`, screen 13) is the same rail widened to
**240 px** with the destinations spelled out — that is the `Nav:Expand` state,
not a separate destination.

---

## 2. Screen → route → status

`/app` is the console mount (`frontend/src/routes.tsx`). Status vocabulary:
`TODO` not started · `WIP` in progress · `DONE` implemented and verified.

### 2.1 Primary journey screens

| # | Figma frame | Node | Route | Frontend owner | Backend dependencies | Status |
|---|---|---|---|---|---|---|
| 01 | Home | `16:2` | `/app` | `screens/overview-screen.tsx` | `GET /api/admin/overview`, `GET /api/applications`, `GET /api/audit`, `GET /api/profiles/{id}/matches` | **EXACT** |
| 02 | Discover | `16:42` | `/app/matches` | `screens/matches-screen.tsx` | `POST /api/jobs/search`, `GET /api/jobs/suggest` | **EXACT** |
| 03 | Resume Studio | `16:82` | `/app/tailor` | `screens/tailor-screen.tsx` + `screens/studio/*` | `POST /api/tailor`, `GET /api/tailored/{id}/download` | **EXACT** |
| 04 | Review | `16:122` | `/app/approvals` | `screens/approvals-screen.tsx` | `POST /api/applications/prepare`, `POST …/approve`, `POST …/reject` | **EXACT** |
| 05 | Applications | `16:162` | `/app/tracker` | `screens/tracker-screen.tsx` | `GET /api/applications`, `PATCH …/status` | **EXACT** |
| 06 | Profile & documents | `16:202` | `/app/profile` | `screens/profile-screen.tsx` | `GET/PUT /api/profiles/{id}/application-profile`, `GET /api/documents` | **EXACT** |
| 07 | Activity | `16:242` | `/app/activity` | `screens/activity-screen.tsx` | `GET /api/audit` | **EXACT** |
| 08 | Operations | `16:282` | `/app/operations` | `screens/operations-screen.tsx` | `GET /api/runs`, `POST /api/jobs/refresh` | **EXACT** |

### 2.2 Secondary and state screens

| # | Figma frame | Node | Route | Frontend owner | Backend dependencies | Status |
|---|---|---|---|---|---|---|
| 09 | Search suggestions | `47:298` | `/app/matches` (open combobox) | `screens/discover/search-panel.tsx` | `GET /api/jobs/suggest` | **EXACT** |
| 10 | Administration | `47:336` | `/app/admin` | `screens/admin-screen.tsx` | `GET /api/admin/overview`, `POST /api/admin/workers` | **EXACT** |
| 11 | Application profile | `47:374` | `/app/profile` (tab 2) | `screens/profile-screen.tsx` | `GET/PUT /api/profiles/{id}/application-profile`, `GET /api/profiles/countries` | **EXACT** |
| 12 | Forms & feedback | `47:412` | reference sheet | shared primitives | — | **EXACT** |
| 13 | Expanded navigation | `47:450` | any `/app/*` | `components/layout/app-shell.tsx` | — | **EXACT** |
| 14 | Match details | `47:488` | `/app/matches/:jobId` | `screens/job-detail-screen.tsx` | `GET /api/jobs/{job_id}`, match row | **EXACT** |
| 15 | Account & security | `47:526` | `/app/profile` (account) | `screens/facts/profile/*` | `GET /api/auth/me`, `GET /api/llm/credentials` | **VOICE** |
| 16 | Resume intake | `47:564` | `/app/resume` | `screens/resume-screen.tsx` | `POST /api/resumes` | **VOICE** |
| 17 | Authentication | `47:602` | `/sign-in`, `/` | `screens/sign-in-screen.tsx` | `POST /api/auth/cookie/login` | **VOICE** |
| 18 | Application details | `47:640` | `/app/tracker/:applicationId` | `screens/tracker-screen.tsx` | `GET /api/applications/{id}`, `GET …/evidence` | **EXACT** |
| 19 | Run diagnostics | `47:678` | `/app/operations` (run drill-in) | `screens/operations-screen.tsx` | `GET /api/runs/{run_id}`, `GET /api/admin/runs/{id}` | **VOICE** |
| 20 | Questions & privacy | `47:716` | `/app/profile` (EEO) | `components/profile/application-profile-panel.tsx` | `GET/PUT /api/profiles/{id}/eeo` | **VOICE** |

### 2.3 Overlays

| Frame | Node | Rendered by |
|---|---|---|
| Job filters · 480 | `49:12938` | Discover filter sheet (`components/ui/sheet.tsx`) |
| Job filters · 350 | `49:12963` | Discover filter sheet (phone) |
| Create account · 480 | `49:12988` | Authentication dialog |
| Create account · 350 | `49:13012` | Authentication dialog (phone) |

---

## 3. Design tokens (measured from Figma, reconciled with `index.css`)

The Figma file's palette **already matches** the tokens WS-34 landed. The
deltas are geometry and type scale, not colour.

| Role | Figma value | Token in `index.css` | Match |
|---|---|---|---|
| Rail / brand surface | `#1b3831` | `--sidebar` | ✅ |
| Rail expand chip | `#294c40` | — (new: `--sidebar-control`) | ❌ add |
| Canvas | `#f7f5ef` | `--background` | ✅ |
| Paper / card / top bar | `#fffdfa` | `--card` `#fffdf8` | ⚠️ 2/255 delta — adopt `#fffdfa` |
| Card hairline border | `#e0e5db` | `--border` `#e3ddd0` | ⚠️ cool vs warm — adopt `#e0e5db` for cards |
| Ink / headings | `#173d32` | `--primary` / `--color-forest` | ⚠️ headings use forest, not `--foreground` |
| Body ink | `#23211c` | `--foreground` | ✅ |
| Muted text | `#6a6459` | `--muted-foreground` | ✅ |
| Agent lime | `#d9f36a` | `--color-lime` / `--sidebar-primary` | ✅ |
| Human clay | `#f1d6c8` | `--color-terracotta` | ✅ |
| Next-step wash | `#faeee6` | `--color-terracotta-soft` | ✅ |
| Stage · needs handoff | `#b99178` | — (new token) | ❌ add |
| Stage · in progress | `#d9f36a` | `--color-lime` | ✅ |
| Stage · outcome recorded | `#86a395` | — (new token) | ❌ add |
| Sage wash panel | `#e6ece8` | `--color-forest-soft` | ✅ |

### 3.1 Type scale (the load-bearing delta)

The current console uses `text-2xl` for the page h1 and `text-lg` for section
headings. Figma is markedly larger:

| Role | Figma | Family / weight | Current | Action |
|---|---|---|---|---|
| Page h1 | **36 px** / 47 line-height | Bricolage Grotesque 700 | `text-2xl` (24) | Raise to 36 |
| Page subtitle | 14 / 20 | Geist 400, muted | `text-lg` (18) | Lower to 14 |
| Section heading | **20 / 29** | Geist 600, forest | `text-xl` (20) | Keep, set forest ink |
| Hero statement | 27 / 39 | Geist 600, forest | — | New |
| Metric value | 28 / 41 | Geist 600, forest | `text-3xl` (30) | Keep, forest ink |
| Metric label | 12 / 17 | Geist 400, muted | `text-sm` (14) | Lower to 12 |
| Card title | 16 / 23 | Geist 600 | — | New |
| Body | 14 / 20 | Geist 400 | `text-sm` ✅ | Keep |
| Micro-label / eyebrow | **11 / 16, +0.06em** | Geist 600 | `text-xs` (12) | New `eyebrow` utility |
| Breadcrumb | 11 / 16 | Geist 600, muted | — | New |
| Meta caption | 10 / 15 | Geist 400, muted | — | New |

### 3.2 Geometry

| Element | Figma | Current | Action |
|---|---|---|---|
| Rail width | **72 px** (expanded 240) | 240 fixed | Collapse by default, expandable |
| Rail item | 44×44, r=12 | 40 tall row | Rebuild |
| Top bar | 68 px tall, `#fffdfa`, no border | 56 px phone-only | Add desktop top bar |
| Content gutter | 32 px past rail | `console-container` | Adjust |
| Card radius | **14 px** | 12 px (`--radius`) | `--radius-card: 14px` |
| Metric card pad | 16 | — | New |
| Panel pad | 20–24 | — | New |
| Column gap (2:1) | **24 px** | — | New |
| Row gap within column | **12 px** | — | New |
| Section gap | **20–24 px** | — | New |

---

## 4. Shared components to build or extend

| Component | Figma evidence | Action |
|---|---|---|
| `AppRail` | `47:2` | **New** — 72 px icon rail, expand/collapse, lime active |
| `TopBar` | `47:28` | **New** — breadcrumb, context note, search hint, avatar |
| `PageHeader` | `47:35` | **Extend** — 36 px h1, 14 px subtitle |
| `StatTile` / `MetricCard` | `49:774` | **Extend** — value 28, label 12, r=14, optional icon |
| `NextStepPanel` | `49:757` | **New** — clay hero with eyebrow, statement, subject, actions |
| `ActionQueue` | `49:786` | **New** — icon + title + subtitle + trailing action |
| `PipelineBar` | `49:1027` | **New** — 4-segment proportion bar with legend |
| `DigestFeed` | `49:805` | **New** — actor chip (AGENT/YOU) + time + title + body + action |
| `FeaturedMatch` | `49:836` | **New** — forest card, match chip, title, meta, rationale |
| `MatchChip` | `49:837` | **New** — `NN / 100 MATCH` lime chip |
| `ProofPanel` | `47:640` | **New** — sage panel, eyebrow, heading, provenance rows |
| `StageColumn` | `16:162` | **New** — board column with count chip + independently scrolling cards |
| `ApplicationCard` | `16:162` | **New** — company, title, stage chip, description, action, timestamp |
| `DiffBlock` | `16:82` | **Extend** — clay `−` / lime `+` pairs with legend |
| `KeywordProgress` | `49:997` | **Extend** — labelled progress with `n of m` |
| `BoardQuestionCard` | `16:122` | **Extend** — question n of m, required, options, save |
| `Stepper` | `49:1033` | **New** — numbered steps, active = forest pill |
| `Tabs` (pill) | `16:202`, `16:242` | **Extend** — active = forest fill |
| `FactsTable` | `16:242`, `16:282` | **New** — interactive sortable table with pager |
| `Toast` / `Banner` | `47:412` | **Extend** — lime success, clay warning, clay-error |
| `EmptyState` | — | Keep, restyle to r=14 |

---

## 5. Interaction and state specification

### 5.1 Navigation
- Rail is **collapsed by default** (72 px); `Nav:Expand` opens it to 240 px.
- Active destination = lime fill + forest glyph. `aria-current="page"` on exactly one row.
- Mobile: bottom navigation (5 slots) + drawer; the drawings show the same
  destinations, never a second set.

### 5.2 Home (`16:2`)
- **Next step** panel is the first thing the eye lands on — clay wash, eyebrow
  `YOUR NEXT STEP`, a 27 px statement, the job subject, one sentence of
  consequence, then the primary action and a count chip.
- Four metric tiles — values are **server totals**, never invented.
- Action queue rows lead somewhere real; each has icon, title, subtitle, action.
- Pipeline bar segments are proportional; **a stage with zero shows no segment**.
- Digest entries carry an actor chip: `AGENT` lime, `YOU` clay.
- Featured match card is forest; the rationale may state an absence
  ("Kubernetes experience is not in the source résumé").

### 5.3 Discover (`16:42`)
- Split view: list column ~30 %, detail column ~68 %, gap 24.
- Selected listing gets a sage wash + a progress bar showing the score.
- Detail shows match chip, title, `company · location · type`, posted/source
  caption, "Why this could be a good fit", matched-skill chips, an
  **evidence gap** panel in clay when a requirement is missing, the
  sponsorship line (must say *unknown* when unknown), and the 8-component
  breakdown link.
- Search field is the widest element; filters are removable chips.

### 5.4 Resume Studio (`16:82`)
- Tabs: `Inline diff` (active) · `Original` · `Cover letter` · `Preview DOCX` · `Download DOCX`.
- The diff is **per passage**: original in clay, tailored in lime, with a legend.
- Every diff carries a provenance line ("Source: experience, bullet 2 · wording changed, no new claims added").
- Rail: required/preferred keyword progress, matched chips, not-evidenced chips,
  and the sentence that missing keywords are **gaps, not permission to invent**.
- `0 unsupported claims` chip + the reminder that the original is preserved.

### 5.5 Review (`16:122`)
- Stepper: `1 Evaluate → 2 Prepare → 3 Review & approve → 4 Employer handoff`.
- Packet rows: résumé, cover letter, candidate details — each with provenance
  and a preview affordance.
- `5 of 6 answers confirmed` + `View all questions`.
- Question card: `QUESTION 6 OF 6`, `Required`, the board's own wording, the
  consequence, `Yes`/`No`, `Previous`, `6 / 6`, `Save answer`.
- The sage notice **must** say the final submit stays the human's.
- A blocked state is clay: "Not ready to authorize — confirm the required answer
  to unlock approval."

### 5.6 Applications (`16:162`)
- Four columns: `Awaiting review`, `Needs you`, `In progress`, `Outcome recorded`.
- Each column header has a count chip and its **own scroll**; the header stays.
- Cards: company eyebrow, title, stage chip, one line of what it means, action
  link, timestamp.
- The legend is load-bearing: *"Queued does not mean sent. Employer handoff does
  not mean submitted."*

### 5.7 Profile (`16:202`) and Application profile (`47:374`)
- Tabs: `Documents` · `Application answers` · `Work preferences` · `Upload résumé`.
- `ORIGINAL` / `TAILORED` provenance chips on each document.
- "What your source actually says" — a sage panel of the parsed facts.
- Profile form: labelled fields, required marked, an invalid control in clay,
  and the sentence that a missing answer **stops form filling instead of
  triggering a guess**.

### 5.8 Activity (`16:242`)
- Tabs: `All activity` · `Needs you` · `Agent work`, plus a refresh cadence note.
- Grouped by day; each row has time, actor chip, title, one-line meaning, and a details link.
- Right rail: the selected event's state, as an ordered 3-step proof.

### 5.9 Operations (`16:282`)
- Explain-panel that separates search from refresh.
- A recoverable run: progress, `120 completed`, `60 remaining · 180 total`, and
  an admin action.
- Corpus freshness facts (last refresh, adapters, availability).
- Source status table with sort affordances and a pager.

### 5.10 Motion
- Every state change has a **static** cue; motion only reinforces it.
- Respect `prefers-reduced-motion` (already wired in the project).
- No motion on the pipeline bar or the score bars beyond a width transition.

---

## 6. Assets

The design is **vector and type only** — no photographic or illustration
assets to extract. The only image fills are the two account avatars
(`47:27`, `47:31`), which render as placeholder portraits; production keeps
the existing initials-based `ProfileChip`/`AccountMenu` treatment, which is
more honest than a stock face.

Icons are 20 px / 1.6 px stroke line glyphs (lucide-equivalent): home,
search, briefcase, file-text, user, activity, sliders. The project already
ships `lucide-react`, so the same set is used with `strokeWidth={1.6}`.

---

## 7. Ambiguities and decisions

| # | Ambiguity | Decision |
|---|---|---|
| A1 | The 20 screens include admin/operations surfaces that are *not* part of the candidate journey | Keep them, but keep them in the secondary rail group, as the design's `Operations` slot at y=840 shows |
| A2 | `Forms & feedback` (`47:412`), `Expanded navigation` (`47:450`), `Search suggestions` (`47:298`) are **component specimens**, not destinations | Render them as real states of the screens that own them; do not add routes |
| A3 | The pipeline bar shows 5 applications across 4 stages | Segment width = count / total; a zero stage renders no segment |
| A4 | `Concept · example data` in the top bar | A design-file annotation. The console shows a real environment marker instead (`API online · development`) |
| A5 | `Search anywhere ⌘ K` | Wire to the existing workspace search palette; show the real shortcut for the platform |
| A6 | Avatars are stock photos | Use initials; never ship a fabricated face |
| A7 | `86 / 100 match` formatting | Use the real score from the API, one decimal only when the backend provides one |

---

## 8. Verification plan

1. `npm run typecheck`, `npm run lint`, `npm run test`, `npm run build`.
2. `node scripts/ws41-audit.mjs` across 1440/1280/1024/768/390/360 — expect
   0 sideways scroll, 0 unnamed controls, 0 overflow, exactly one `h1`.
3. Browser screenshots at 1440 and 390 for every primary screen, compared
   against `docs/design/ws42/reference/`.
4. `figlens compare_image` where a like-for-like crop is possible.
5. Backend suite unchanged and green (the change is frontend-only unless a gap
   is found).
