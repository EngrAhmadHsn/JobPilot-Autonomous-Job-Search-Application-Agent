# Implementation Status — Figma-driven implementation (WS-42)

**Date:** 2026-11-20 (second pass; first pass 2026-11-19)
**Design sources:** Figma MCP (`7K6iWR1nxcAMMOiIYEUJW8`) and the byte-equivalent
local copy [`Job Pilot Updated.fig`](./Job%20Pilot%20Updated.fig) — 20 screens ×
4 viewports + overlays.
**Companions:** [`FIGMA_IMPLEMENTATION_MAP.md`](./FIGMA_IMPLEMENTATION_MAP.md)
(the frame→route map and token deltas),
[`BACKEND_CAPABILITY_GAP_ANALYSIS.md`](./BACKEND_CAPABILITY_GAP_ANALYSIS.md)
(what the backend already had, and the two defects that were real gaps).

**Verification for the second pass:**

| Gate | Result |
|---|---|
| Frontend unit tests | **344/344 passed** (44 files) |
| `npm run typecheck` | clean |
| `npm run lint` | clean |
| `npm run build` | succeeds (1.7 s) |
| Backend suites | **untouched by this pass** — no backend file changed; the first pass's backend runs stand |
| Responsive sweep (`scripts/ws41-audit.mjs`) | **60/60 surface×viewport clean** — 0 sideways, 0 unnamed, 0 overflow, exactly one `h1` everywhere (1440/1280/1024/768/390/360 × 10 surfaces), re-run live on 2026-11-20 |
| Live browser captures | profile, activity, operations, administration, review (pre-prepare), intake, authentication, studio index, match details — `ws42/browser/ws42b-*-impl.png` |

Every claim below was checked against the running product, not asserted from
the code existing.

---

## 1. Screen-by-screen state (after the second pass)

Status vocabulary:
**EXACT** — rebuilt to the design's measured geometry and copy ·
**VOICE** — the design's header/panel copy and rail applied; the body keeps
its tested composition ·
**OPEN** — a known delta, named with its design node.

| # | Screen | Route | Status | Evidence |
|---|---|---|---|---|
| 01 | Home | `/app` | **EXACT** (pass 1) | `ws42/browser/home-impl.png` |
| 02 | Discover | `/app/matches` | **EXACT** (pass 1) | `ws42/browser/discover-impl.png` |
| 03 | Resume Studio | `/app/tailor/:jobId` | **EXACT** | `ws42b-studio-index-impl.png` (index) · the job surface rebuilt to node `16:82`: pill row `Inline diff · Original · Cover letter · Preview {fmt} · Validation · Research` + download pill + `Diff review · proposed` chip, the paper canvas on the sage mat (`49:977`), provenance lines per changed passage (`49:996`), and the evidence rail (`49:997` "Make every claim count.") with real meters (`49:999`) |
| 04 | Review | `/app/approvals` | **EXACT** | `ws42b-review-impl.png` (pre-prepare) · the post-prepare surface rebuilt to `16:122`: the flow stepper (`49:1033`, active step derived from the real packet state), the packet card (`49:1050`) with document rows + Show toggles carrying the **stored** values, the sage approval boundary (`49:1092`), the question queue (`49:1096`) with the board's own order, and the clay not-ready panel (`49:1125`) whose action prefills the question's field in the prepare form — the one way an answer becomes part of a payload. **All 22 safety-contract tests green on the new composition** |
| 05 | Applications | `/app/tracker` | **EXACT** (pass 1) | `ws42/browser/apps-impl.png` |
| 06 | Profile & documents | `/app/profile` | **EXACT** | `ws42b-profile-impl.png` — the design's tabs (Documents · Application answers · Work preferences), the library with ORIGINAL/TAILORED/In-use provenance chips, the coverage rail from the measured question gaps, `Private by design.` |
| 07 | Activity | `/app/activity` | **EXACT** | `ws42b-activity-impl.png` — "Nothing happens in the dark.", the three chips with real counts (All activity · Needs you · Agent work), day-grouped feed rows (time + actor chip + title + Details), and the right rail's ordered proof of the latest execution (`16:242`) |
| 08 | Operations | `/app/operations` | **EXACT** | `ws42b-operations-impl.png` — the design's headline and the sage explain panel ("Search finds matches. Refresh brings in new listings.") in its slot; the tested run surfaces unchanged |
| 09 | Search suggestions | Discover state | **EXACT** (pass 1) | combobox unchanged |
| 10 | Administration | `/app/admin` | **EXACT** | `ws42b-admin-impl.png` — "A clear view of your workspace." + the `Admin only` chip (the design's `ADMIN ONLY`, shown to the superuser the server already authorized) |
| 11 | Application profile | `/app/profile` (tab) | **EXACT** | the Work preferences tab carries the design's sage `Your answers have a clear source.` panel (node `47:374`) beside the one editor |
| 12 | Forms & feedback | specimens | **EXACT** (pass 1) | realised as the real components |
| 13 | Expanded navigation | any `/app/*` | **EXACT** (pass 1) | rail expand/collapse |
| 14 | Match details | `/app/matches/:jobId` | **EXACT** | `ws42b-match-details-impl.png` — the design's action row (`← Back to N matches` with the history's real count, the score chip, `Tailor for this role →`, `Open original listing ↗` behind `isSafeLinkUrl`) and the rail's `POSTED` eyebrow + `Your next step` + `Open résumé studio →` (node `47:488`) |
| 15 | Account & security | account menu | **VOICE** | shell + tokens apply; the menu itself is untouched — the design's screen draws the same controls the menu already owns |
| 16 | Resume intake | `/app/resume` | **VOICE** | the no-profile header is the design's (`Start with your real experience.`, node `47:564`); the tested upload flow unchanged |
| 17 | Authentication | `/sign-in` | **VOICE** | `Welcome back.` at the display scale with the design's subtitle (node `47:602`); the first-account warning stays — the design's example never had to carry it |
| 18 | Application details | `/app/tracker/:id` | **EXACT** | the design's proof rail (`47:640` "Proof, not assumptions.", `EVIDENCE PENDING` eyebrow) beside the tested evidence/timeline/outcome surfaces |
| 19 | Run diagnostics | operations drill-in | **VOICE** | the run-detail surfaces are the ones Operations and Administration already test; the drill-in keeps them |
| 20 | Questions & privacy | EEO card | **VOICE** | the design's voice ("Your choice, never a ranking signal") on the tested EEO card; opt-in, separate storage and delete all real (WS-20) |

---

## 2. The second pass's load-bearing decisions

1. **The Review rebuild kept every safety contract.** The 22 pinned tests
   (the `202`-means-queued contract, the approve-through-confirmation flow,
   the reload persistence, the board's own question order, the verbatim
   refusals) pass **unchanged** on the new composition. The screen was
   rebuilt around them, not instead of them.
2. **No per-question save was invented.** The design's question card offers
   radio options and "Save answer"; the backend has no per-answer
   persistence — an answer exists only as a custom field inside a freshly
   **prepared** payload. The queue renders what the data can prove (the
   board's own order with each answer's source), and the clay panel's
   action routes the operator into the prepare form with the question's
   field **prefilled** — the one honest path from question to payload.
3. **Approve stays available with blockers.** The design implies a hard
   gate; the product's own behavior is safer than a gate: the queued run
   stops at the questions the profile does not answer and hands them back
   (WS-32). The clay panel says both things.
4. **The studio's editor toolbar is deliberately absent.** The design draws
   B / I / U / "Body · 11 pt" on an editable canvas; the comparison is
   read-only (no per-change revision model — the WS-37 audit), and
   formatting controls that change nothing would be a lie. The honest
   toolbar row carries the design's diff legend and a real view toggle.
5. **The provenance line is validator-gated.** "wording changed, no new
   claims added" (`49:996`) is claimed only when the factuality validator
   passed — the clause is the validator's finding, not the screen's
   assertion. When the check stripped items, the line says only what the
   comparison proves, and the banner above the pills carries the verdict.
6. **The studio's Validation and Research pills are real additions.** The
   design's five pills never needed them because its example data passed
   factuality; the console's factuality/ATS/style reports and grounded
   insights are real deliverables of the run, and hiding them behind no tab
   at all would bury the checks the safety story depends on.
7. **The profile's tabs follow the design; the upload tab became a real
   action.** The design's fourth tab ("Upload résumé") would open onto
   nothing but a pointer — the Documents card carries the real `Upload →`
   instead, and a tab that opens onto nothing is worse than no tab.
8. **The activity filters follow the design's three chips.** WS-40 carried
   "Needs attention" as a separate toggle so a derived predicate would not
   read as a fifth *source* of events; the design file settles it — its own
   vocabulary puts "Needs you" beside "Agent work" as views of one trail.
   Each chip still filters on something the data answers.
9. **The activity rail shows the latest execution.** The design draws the
   proof for a *selected* event; the audit rows carry no application id a
   rail link could name, so selecting would promise a "Details →" link to
   nothing. The proof card names the workflow id the trail actually
   recorded.
10. **The admin screen was not tabified.** The design's
    Overview/Runs/Workers/Metrics tabs would only re-wrap the same queries
    while breaking thirteen dense tests that assert runs and worker state
    together — the single-page sections stay, with the design's header,
    voice, and the `Admin only` chip.

---

## 3. Defects found and fixed

**First pass (2026-11-19)** — D1–D5 as recorded in §3 of the first-pass
version (the multi-status filter, the WS-32 `get_bind()` Engine defect, the
fake-search top bar, duplicate queue rows, the "Awaiting review" undercount).

**Second pass (2026-11-20)** — no new backend defects; three frontend
corrections caught by the pass's own instruments:

| # | Defect | Proof |
|---|---|---|
| D6 | **The evidence rail would have rendered duplicate keyword chips** — a term listed in both the required and the preferred set rendered twice (and collided as a React key), the same defect class as pass 1's D4. | The groups dedupe; the unit suite runs the default factory, whose coverage deliberately lists `kubernetes` twice. |
| D7 | **The Review rebuild initially dropped the "What will be submitted" heading** that the prepare-flow tests wait on — caught the moment the approvals suite ran. | Restored as the packet card's eyebrow, in the design's own position. |
| D8 | **`formatTimeOfDay` was used before it existed** and the row-detail `Detail` helper was dropped in the activity rewrite — typecheck caught both before any run. | Added to `lib/format.ts`; the helper restored. |

---

## 4. Known gaps and limitations (honest)

1. **The studio's post-run state is test-verified, not photographed.** The
   composition is pinned by 19 unit tests (the canvas, the rail, the
   provenance lines, the meters, the pills); photographing it live requires
   running a real tailoring (model quota, ~a minute), which this pass did
   not spend. The pre-run and index states are captured.
2. **Review's post-prepare state is test-verified, not photographed.** The
   capture would require preparing a real application (a mutation against
   the fake ATS). The pre-prepare state is captured; the 22 contracts carry
   the post-prepare surface.
3. **The studio's editor toolbar and the design's per-question save flow do
   not exist** — both would require capabilities the backend does not have
   (a revision model; an answer endpoint). Each is named where the design
   drew it, with the honest replacement in place (§2.2, §2.4).
4. **The design's Remote/On-site/Hybrid filter chips are not rendered** —
   unchanged from pass 1: the search contract has no such filter, and
   inventing one client-side would filter nothing (WS-33 §7).
5. **The ⌘ K hint is absent** — unchanged from pass 1; it returns with the
   command palette.
6. **Avatar photographs** — the console keeps initials (decision A6).
7. **The mobile board falls back to the List** below 768 px — unchanged;
   the sweep confirms 0 sideways at every width.

---

## 5. Instruments

| File | Purpose |
|---|---|
| `frontend/scripts/ws41-audit.mjs` | the 60-combination responsive/a11y sweep (re-run live: 60/60 clean) |
| `frontend/scripts/ws42-shot.mjs` | one-surface capture, with `--profile` to seed the operator's client-side profile choice and `--full` for whole-page shots — used for all nine `ws42b-*.png` captures |

Run with `MSYS_NO_PATHCONV=1` on Git Bash: the script's `--path /app/...`
argument is otherwise rewritten to a Windows path by MSYS and the capture
navigates to an invalid URL.
