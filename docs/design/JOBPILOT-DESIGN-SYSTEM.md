# JobPilot Design System — the shared contract (WS-33 / WS-UX-01)

**Status:** Complete · **Date:** 2026-11-17
**Authorities:** [`JOBPILOT-UX-01-AUDIT.md`](JOBPILOT-UX-01-AUDIT.md) (evidence),
[`docs/Redesign Image.png`](../Redesign%20Image.png) + [`docs/JobPilot Career
Dashboard.png`](../JobPilot%20Career%20Dashboard.png) (visual direction), master
prompt `docs/JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md` §4 (palette/typography) and
§8C (component strategy).
**Ground truth:** `frontend/src/index.css` and `frontend/src/lib/status.ts`.
Where this document and the code disagree, the code wins and this document must
be corrected — later workstreams may only change tokens **through** this
document, with the contrast numbers re-measured.

---

## 0. Mode and character

The authenticated console is an **Operate** surface (impeccable's term): the
visitor is completing a task — discover, evaluate, prepare, decide, track.
Scanability, consistency and precision outrank expression. The metaphor the
code itself declares is a **dossier on a desk**: an ivory page, paper on it,
ink for text, a lime highlighter for the agent's marks, a warm clay wash for a
human's (`frontend/src/index.css:9-20`). The reference images share that world:
warm ivory canvas, deep forest sidebar, paper cards, hairline warm borders,
restrained elevation, dense but legible content. A premium, calm career-
operations product — not an enterprise admin template, not a neon AI toy
(master prompt §4.1).

Anti-goals carried over from the master prompt (§4.3, §8C): no card-in-card
without structural reason, no glassmorphism, no gradient text, no oversized
decorative match circles or chart heroes, no emoji-as-icons, no decorative
motion.

---

## 1. Token table (reconciled with `frontend/src/index.css`)

Declared in the `@theme inline` block (`index.css:21-100`) and the `:root` /
`.dark` blocks (`index.css:102-173`). Values below are **measured from the
file**, not from the brief. The brief's names are kept; where the brief and the
file differ, the file is the contract and the deviation is recorded.

### 1.1 Brand surfaces and ink (light theme — the default workspace)

| Role | Token (`--color-*` / var) | Value | Declared at | Brief says |
|---|---|---|---|---|
| Canvas | `--background` / `--color-ivory` | `#f7f5ef` | :104, :36 | ivory `#F7F5EF` ✓ |
| Paper/card | `--card` / `--color-paper` | `#fffdf8` | :106, :37 | paper `#FFFDF8` ✓ |
| Brand / primary | `--primary` / `--color-forest` | `#173d32` | :111, :34 | forest `#173D32` ✓ |
| Primary text on forest | `--primary-foreground` | `#f7f5ef` | :112 | — |
| Agent lime | `--color-lime` | `#d9f36a` | :28 | `#D9F36A` ✓ |
| Lime text/ink | `--color-lime-foreground` | `#173d32` | :29 | — |
| Lime wash | `--color-lime-soft` | `#eef9c4` | :30 | (derived; not in brief) |
| Human terracotta | `--color-terracotta` | `#f1d6c8` | :31 | `#F1D6C8` ✓ |
| Terracotta text/ink | `--color-terracotta-foreground` | `#6d3a27` | :32 | — |
| Terracotta wash | `--color-terracotta-soft` | `#faeee6` | :33 | (derived) |
| Sage (forest-soft) | `--color-forest-soft` | `#e6ece8` | :35 | sage `#E6ECE8` ✓ (named `forest-soft` in code) |
| Warm border | `--border` | `#e3ddd0` | :121 | `#E3DDD0` ✓ |
| Ink | `--foreground` / `--color-ink` | `#23211c` | :105, :38 | `#23211C` ✓ |
| Muted text | `--muted-foreground` | `#6a6459` | :117 | `#6A6459` ✓ |
| Muted surface | `--muted` | `#f1ede2` | :116 | (derived) |
| Secondary surface | `--secondary` | `#efeade` | :113 | (derived) |
| Accent wash (hover) | `--accent` | `#e8efea` | :118 | (derived; forest whisper) |
| Destructive | `--destructive` | `#9a3b2c` | :120 | (derived warm red) |
| Input border | `--input` | `#d9d2c2` | :122 | (derived) |
| Focus ring | `--ring` | `#173d32` | :123 | — |
| Radius (base) | `--radius` | `0.75rem` | :129 | rounded-but-controlled ✓ |
| Sidebar surface | `--sidebar` | `#1b3831` (WS-34, in flight at audit time; was `#f2efe6`) | :~132 | — |

**Sidebar update (WS-34, landed during this audit):** WS-34 replaced the warm
paper sidebar tokens with the reference's deep forest — `--sidebar #1b3831`,
`--sidebar-foreground #f2efe6`, `--sidebar-primary #d9f36a`,
`--sidebar-primary-foreground #14261f`, `--sidebar-accent #3a6052`,
`--sidebar-accent-foreground #f2efe6`, plus new `--sidebar-muted #a7bfb4` and
`--sidebar-hover #24443b`. Its measured pairs all pass AA (foreground 11.03,
muted 6.49, active pill 6.14, ring 10.25 — verified independently for this
document). The brand tokens above (§1.1) are unchanged by WS-34.

### 1.2 Night palette (public landing; keep, do not derail)

`--color-night #0e1a16`, `--night-soft #13221c`, `--night-raised #182b23`,
`--night-line #244036`, `--night-muted #9db3a7` (`index.css:49-53`). The dark
**theme** (`.dark`, :140-173) inverts the desk: warm charcoal `#16150f`, lime
becomes the action colour, terracotta stays human. Dark-theme support is wired
(`theme-provider.tsx`, pre-paint inline script) and tested — preserve it; the
default authenticated workspace stays light warm-paper (master prompt §4.2).

### 1.3 Type

| Role | Token | Value | At |
|---|---|---|---|
| Display / headings | `--font-heading`, `--font-display` | `"Bricolage Grotesque Variable", "Geist Variable", sans-serif` | :22-24 |
| Interface / body | `--font-sans` | `"Geist Variable", ui-sans-serif, system-ui, sans-serif` | :25 |
| Mono (ids, paths) | `--font-mono` | `ui-monospace, "SF Mono", Menlo, Consolas, monospace` | :26 |

Both faces ship via `@fontsource-variable/*` (`index.css:4-5`) — local, no CDN.
Rules: display for `PageHeader` titles and card titles
(`font-heading`/`font-display`); body/interface in Geist; tabular numerals for
scores and counts (`tabular-nums`, e.g. `tailor-screen.tsx:263`,
`operations-screen.tsx:255`); reading column ≤68ch (`.console-reading`,
:343-345); long board-supplied tokens wrap with `wrap-anywhere`, not
`break-words` (`matches-screen.tsx:130-144` documents why with a measured
failure). No new fonts without a demonstrated requirement (master prompt §4.3).

### 1.4 Elevation, motion, texture

| Token | Value | At | Use |
|---|---|---|---|
| `--shadow-paper` | `0 1px 2px rgb(35 33 28 / 4%), 0 10px 30px -18px rgb(35 33 28 / 18%)` | :94-95 | resting cards (the reference's soft lift) |
| `--shadow-lift` | `0 2px 4px rgb(35 33 28 / 5%), 0 18px 40px -20px rgb(35 33 28 / 24%)` | :96-97 | hover/raised only (e.g. match cards on hover) |
| `--ease-soft` | `cubic-bezier(0.22, 0.61, 0.36, 1)` | :98 | entrances |
| `--ease-inout` | `cubic-bezier(0.65, 0, 0.35, 1)` | :99 | transitions/exits |
| grain | inline SVG turbulence at 5% opacity | :187 | body texture; `background-attachment: fixed` desktop-only (:224-228) |

Motion rules (already in code, keep): transform/opacity only; entrances
stagger by index at 80 ms (`.enter-up`, :481-496); scroll reveal fires once
(`[data-reveal]`, :523-537); the shine sweep is one pass on hover (:386-415);
view-transition rise 280 ms (:451-471). Reduced motion removes **travel, not
feedback** and keys on `<html data-motion>` set before first render
(:258-324, `lib/motion.ts`) — a System/Full/Reduced user choice exists in the
account menu (`components/motion-toggle.tsx`). New motion must respect
`prefers-reduced-motion` through this same attribute, never a blanket
`transition-duration: 0.01ms` (the anti-pattern §17 fixed once already,
`17-frontend-experience.md:293-302`).

### 1.5 Spacing and layout rhythm (from the code + reference)

- Content container: `max-width: 1120px`, `padding-inline: 1.5rem → 2rem` at
  `md` (`.console-container`, :329-340). The reference's generous page gutter.
- Section rhythm: `space-y-6/8/10` between major sections (every screen);
  card padding `p-6`, rounded `rounded-2xl` cards on `rounded-lg` controls.
- Stat-tile grid: 2-up mobile → 4-up desktop (`sm:grid-cols-2
  lg:grid-cols-4`, `overview-screen.tsx:132`).
- Split layouts: `lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]`
  (`overview-screen.tsx:157`), form + sticky aside
  `lg:grid-cols-[minmax(0,1fr)_320px]` with the sticky offset published as
  `--header-height` (`approvals-screen.tsx:501,666`,
  `use-header-height.ts`).
- Tables: drop columns rather than scroll sideways below `md`
  (`tracker-screen.tsx:180-194` — the pattern for every future table).
- Touch spacing ≥8px between adjacent targets; skeleton screens for async
  reads (ui-ux-pro-max ux domain, queried 2026-11-17; already practiced via
  `MatchListSkeleton`, `CardSkeleton`, `Skeleton`).

---

## 2. Semantic colour rules (invariant)

These four lines are the product's meaning system
(`index.css:9-20`, master prompt §4.1). Every later workstream renders through
them; replacing them requires an explicit design decision and a migration of
all affected states.

1. **Lime = the agent.** Agent-originated work and marks: agent progress line
   (`.agent-progress`, :351-375), tailored documents (`document.kind ===
   "tailored"`, `document-picker.tsx:54-56`), verified/agent tones,
   match-score chips (`score-grid.tsx`).
2. **Terracotta = the human.** Human-originated action/attention: next-action
   cards (`overview-screen.tsx:172`), awaiting-approval tiles, parse warnings
   (`resume-screen.tsx:366-372`), human-outcome framing.
3. **Forest = brand, primary navigation, primary action.** The one colour that
   says "act" (`index.css:110`); buttons, active nav, focus ring, sidebar
   (after WS-34).
4. **Sage/paper/stone = structure and quiet positive support**; terracotta is
   *attention*, **not** error — errors use `--destructive` (a warm red, not
   terracotta).

---

## 3. Status → tone contract (from `lib/status.ts`)

One backend state = one label + one tone + one next-step line, everywhere.
Rendered only through the status badge. Unknown statuses render verbatim in
`neutral` — never hidden, never recoloured. **WS-34 (in flight during this
audit) added a fourth field, `icon` (a Lucide export name), to every
`StatusPresentation`;** the vocabulary, tones and next-step lines below are
unchanged by it, and the icon travels as data so `lib/status.ts` stays free of
React imports.

| Tone | Classes | Contrast (WCAG 2.2, measured) |
|---|---|---|
| `neutral` | `border-border bg-muted text-muted-foreground` | 5.01 (text on muted) |
| `info` | `border-border bg-card text-foreground` | 15.82 |
| `progress` | `border-lime/70 bg-lime-soft text-lime-foreground` | 10.85 |
| `success` | `border-lime/70 bg-lime text-lime-foreground` | 9.70 |
| `warning` | `border-terracotta bg-terracotta-soft text-terracotta-foreground` | 8.07 |
| `danger` | `border-destructive/40 bg-destructive/10 text-destructive` | 5.85 (text on the 10% blend over paper) |

Mapping highlights (full table lives in `status.ts:27-162`): `awaiting_approval`
→ warning ("a human must approve…"); `submitted` → **progress**, labelled
"Submitted, not yet verified" — never success; `verified` → success; approval
`QUEUED` → info, labelled "Accepted and queued" (`status.ts:128-134`); human
outcomes `interview/offer` → success, `withdrawn` → neutral, `rejected` →
danger; `blocked_human_review` → warning ("nothing was bypassed — finish it by
hand").

**Measured AA results (script `.scratch/sdd-ux/contrast.py`, recomputable):**
every status-tone text/background pair passes WCAG 2.2 AA at ≥4.5:1 — worst
pairs: muted-on-secondary 4.89, muted-on-muted 5.01, danger-on-blend 5.85.
Dark theme: all pairs pass (worst muted-on-muted 6.05).

**The one failure (fix through this document):** `text-muted-foreground/80` on
12 px labels blends to **3.55:1** on ivory — AA-fail for normal text. Two live
occurrences on light surfaces: the non-forest branch of the nav group headings
(`components/layout/nav-groups.tsx:343`) and the admin worker-status note
(`screens/admin-screen.tsx:977`). Drop the `/80` (full `--muted-foreground` =
5.38:1 on ivory) or darken the token itself; no other token needs touching.
WS-34's forest sidebar sidesteps it with `--sidebar-muted` (6.49:1).

**Rule for later workstreams:** any *new* text/background combination must be
added to the contrast script before it ships. Alpha-modified text colours
(`text-*/80`) count as their blended result — `forest/70` on the card/60 wash
measures 4.65 (pass); `/80` of muted is the demonstrated failure mode.

---

## 4. Surfaces and elevation rules (from the reference)

1. **One canvas, one paper layer.** The page is ivory; content sits on paper
   cards. A card never sits on a card without a structural reason — inside the
   prepared-payload panel the inner block is a bordered wash
   (`bg-card/60`, `approvals-screen.tsx:132`), not a nested `Card`.
2. **Hairlines over shadows.** Separation is `border-border` (#e3ddd0); shadow
   is the *exception* — resting `--shadow-paper`, interactive lift
   `--shadow-lift` (hover), nothing else. The reference's depth comes from
   light washes (`console-header::before`, :424-440) not drop shadows.
3. **Washes for meaning, not decoration.** `bg-terracotta-soft/60` for human
   attention rows, `bg-forest-soft` for the prepared payload panel, `bg-lime-soft`
   for agent progress — always paired with their `-foreground` ink (contrast
   table above).
4. **Radius scale.** `--radius 0.75rem`; `rounded-lg` controls, `rounded-xl`
   rows/inner blocks, `rounded-2xl` cards, full-round pills for badges/filters
   (`rounded-full`). No radius beyond `rounded-2xl` in the console.
5. **Iconography: Lucide only** (`lucide-react` is the only icon dependency,
   `package.json:31`); stroke ~1.6-1.7 for the large decorative file glyph
   (`resume-screen.tsx:87`), default for inline icons; never emoji
   (§8C). The reference image's emoji (👋) and brand logos must be replaced
   with a Lucide icon and a text monogram respectively (audit §7).
6. **Job-board content is untrusted:** rendered through `PlainText` (no HTML),
   with `isSafeLinkUrl` guarding the single link the board supplies
   (`job-detail-screen.tsx:239-255`). Any new surface that renders board text
   inherits both rules.

---

## 5. Component strategy (master prompt §8C, binding)

- **Foundation stays shadcn/Base UI.** Installed: `@base-ui/react ^1.9.0`,
  shadcn conventions, Tailwind 4 (`package.json:21-38`). Existing primitives in
  `components/ui/**`: accordion, alert-dialog, badge, button, card, dialog,
  dropdown-menu, empty-state, error-state, input, link-button, page-header,
  progress, separator, sheet, skeleton, status-badge, table, tabs, tooltip.
  Extend these before adding any second system; a new dependency needs a
  written reason (master prompt §3.20).
- **Product components compose the primitives** (`components/common/**`,
  `components/observability/**`, `components/profile/**`,
  `components/documents/**`): banner, disclosure, field-list, pagination,
  query-combobox, score-grid + OverallScore, match-gap-chips, stat-tile,
  status-badge, event-timeline, run-progress, document-picker/list, profile
  cards. Reuse them; a redesigned screen that re-implements a badge or a
  banner is a defect.
- **No stock shadcn look:** primitives are styled with the semantic tokens of
  §1 — never the default zinc/slate palette, radius or shadows.
- **Custom components** (resume diff block, match-evidence view, multi-stage
  packet) are justified when a primitive cannot express the composition, but
  their controls must be Base UI/shadcn primitives and they need typed APIs
  and tests (master prompt §8C "When a custom component is justified").
- **Accessibility floor (non-negotiable):** the one focus treatment
  (`index.css:230-235`), pointer-cursor on interactive elements (:246-254),
  labelled inputs, `aria-pressed` toggles, `role="status"` loading frames
  (`routes.tsx:104-118`), status announcements via `StatusExplainer`'s plain
  language, visible focus never suppressed, WCAG 2.2 AA contrast per §3, and
  the reduced-motion contract of §1.4.
- **Responsive floor:** desktop 1440×1000 and 1280×800; mobile 390×844 and
  360×800; one tablet width 768-900 (master prompt §7). No horizontal page
  scroll: wrap-anywhere for long tokens, column-dropping tables, split views
  that become stacked. Drawers/dialogs own their scroll and return focus.

---

## 6. What later workstreams may and may not change

**Through this document only:** any `--*` token value; the tone class table;
the type roles. Changing a token requires re-running the contrast script and
recording the new numbers here.

**Never:** raw hex in components (use the tokens); a second icon system; a
second component library; a "live" label on polling; a status label outside
`lib/status.ts`' vocabulary; a count computed from a partial page presented as
a total; fabricated metrics, logos, or plan names (audit §7 is the
authoritative grounded-vs-illustrative list); deleted tests to go green.

**The screen workstreams** (WS-34 shell, WS-35 Home, WS-36 Discover, WS-37
Resume Studio, WS-38 Review, WS-39 Tracker, WS-40 Profile/Activity/Operations,
WS-41 mobile/a11y) inherit everything above; their screenshots are judged
against `docs/design/baseline/` (29 PNGs: 12 desktop populated, 9 mobile
populated, 8 desktop empty).
