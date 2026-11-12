# UX gap audit — JobPilot against 22 short-form UX reels

Status: **Audit only — nothing fixed** · Date: 2026-11-12 · Scope: `frontend/` (landing + console)

> This document records a read-only audit. It changes no code. Every finding
> below was verified in the source; measurements marked "measured" come from a
> real `npm run build`, not an estimate.

---

## 1. What the source material said

The 22 links are Facebook reels, which serve a login wall to normal clients.
They were read through `og:title`/`og:description` under a crawler user agent,
so what is recorded here is each video's **stated subject**, not a transcript
of its content. Three of the twenty-two are unrelated (engagement bait, a
prompt-selling caption); the rest reduce to nine themes:

| # | Theme | Reels | What it claims |
|---|-------|-------|----------------|
| 1 | **Skeleton loaders over spinners** | U7, A11, U3 | Loaders inflate LCP; a skeleton that reserves the real layout is both faster and calmer. |
| 2 | **375px is where apps break** | U1, A9 | An app that "fits the laptop" breaks in five specific ways on a phone. |
| 3 | **SEO basics on a shipped site** | A9 | Titles, canonical, broken links, mobile layout — verify, don't assume. |
| 4 | **Dark mode is not inversion** | U5 | A real dark theme re-derives surfaces and desaturates colour; it is not a filter over the light one. |
| 5 | **Six/nine small motions** | A12, A8, U2, A13 | Small, purposeful motion makes a UI feel alive; icons should *move*, not swap. |
| 6 | **Search must feel effortless** | A14 | Five decisions separate a search that feels instant from one that feels broken. |
| 7 | **Grids are the invisible structure** | A10 | Layout quality is mostly the grid underneath it. |
| 8 | **"Looks AI-made" tells** | U6, A2, A5, A3, A4, A7 | Gradients, centred hero, generic cards, emoji, uniform spacing — the tells. |
| 9 | **Five tokens: wireframe → real screen** | U4, U8 | Type, spacing, colour, radius, shadow done as tokens — not per-component. |

---

## 2. Verdict

**The design system is strong; the delivery and the small screens are not.**

Nine of the fourteen audited reels' concerns are already solved better than the
source material asks for — the token system (theme 9) is genuinely complete, the
motion system (theme 5) is more careful than almost anything shipped, contrast
(theme 4's substance) passes everywhere, and the AI-tell problem (theme 8) is
largely absent: **zero** `bg-gradient` utilities and only three `backdrop-blur`.

The gaps cluster in four places:

- **P0 — the landing CTA is a dead end.** "Create your account" goes to
  `/sign-in`, which opens in **sign-in** mode. A first-time visitor is asked for
  a password they don't have.
- **P0 — 375px has one page-breaking overflow plus three unreachable controls.**
- **P1 — the public site has no SEO at all**, and it is a client-rendered shell
  with an 854 kB entry bundle, so crawlers and first-paint both pay for it.
- **P1 — skeletons exist on exactly one screen.** The core insight of the most
  prominent reel is implemented once, on Matches, and nowhere else.

---

## 3. Findings, worst first

### P0-1 · The primary CTA leads to the wrong form

`landing-page.tsx:254` — "Create your account" → `to="/sign-in"`.
`sign-in-screen.tsx:25` — `useState<"sign-in" | "create">("sign-in")`.
The route takes no state and reads no query param (`landing-page.tsx:71,251,332,354`).

A first-time visitor presses the one button written for them and lands on a form
that asks them to sign in to an account they do not have. The escape hatch
("No account yet? Create one") is a 14px underlined text button *below* the
password field. This is the single highest-value conversion defect in the
product.

**Fix:** give the CTA `to="/sign-in" state={{ mode: "create" }}` and have the
screen honour `location.state?.mode`, or route to `/sign-up`. Two lines and a
test.

---

### P0-2 · Genuine horizontal page scroll at 375px

`admin-screen.tsx:399` — `className="inline-flex ..."` on the run-type filter,
with four buttons at `px-3 py-1 text-xs` (`:414-415`): Everything · Refreshes ·
Embeddings · Reconciliations. An `inline-flex` **does not wrap**, and there is
no `overflow-x-auto`. The content box is 327px (`index.css:298-303`: 375 − 2×24)
and the strip is roughly 360–375px. The parent's `flex-wrap` (`:395`) cannot
shrink an inline child, so this pushes the **whole page** sideways. This is the
one layout in the app that fails the 375px test outright.

**Fix:** add `flex-wrap` or `overflow-x-auto` to the strip at `:399`.

---

### P0-3 · Three controls below 44px that are the *only* route to their feature

- `nav-drawer.tsx:34` — hamburger is `size-9` (36px). Below `lg`,
  `app-shell.tsx:121` hides the desktop bar, so this is **the only navigation
  in the entire console**. A miss leaves the user with no way to move between
  screens at all.
- `account-menu.tsx:54` — trigger `h-9` (36px), and it is the only path to
  sign out, the theme switch and the motion control.
- `landing-page.tsx:353` + `motion-toggle.tsx:62` — the footer motion toggle is
  `px-2 py-1 text-[11px]` ≈ 20px, and `landing-page.tsx:330` hides the header
  toggle below `sm`. At 375px this 20px strip is the only motion control on the
  page.

**Fix:** `size-11` (44px) on the first two, `py-2.5` on the third. The nav
hamburger is the one that matters most — it is the whole app's navigation.

---

### P1-1 · No SEO metadata whatsoever

Verified in `frontend/index.html` (all 12 lines) and the built `dist/index.html`:

- **no** `<meta name="description">`
- **no** `og:title` / `og:description` / `og:image` / `twitter:*` → a shared link
  renders as a bare URL with no card
- **no** `<link rel="canonical">`
- **no** `robots.txt`, **no** `sitemap.xml` (`frontend/public/` holds only
  `vite.svg`)
- **one** `<title>` for the whole app — `"Agentic Job Applier — Operator console"`,
  which is also the wrong product name (the product is **JobPilot**) and the
  wrong audience for a landing page
- **favicon is still Vite's default** `vite.svg` (`index.html:5`)
- **no per-screen titles** — no `document.title` assignment anywhere in `src/`

Theme 3 of the source material is exactly this checklist, and the site fails
every line of it. This also means the browser tab for every route in the
console reads "Agentic Job Applier — Operator console", so an operator with
several tabs open cannot tell them apart.

**Fix (in order of value):** a real favicon + `apple-touch-icon`; a
`description` and OG/Twitter block; `robots.txt` + `sitemap.xml`; a tiny
`useDocumentTitle` hook called per screen. The per-screen titles cost about
fifteen lines and fix tab confusion across nine screens.

---

### P1-2 · The entry bundle is 854 kB, and a landing visitor downloads all of it

**Measured** from `npm run build`:

| chunk | raw | gzip |
|---|---|---|
| `index-*.js` | **854.11 kB** | **262.64 kB** |
| `landing-page-*.js` | 33.95 kB | 9.93 kB |
| `index-*.css` | 79.18 kB | 14.85 kB |

Vite warns: *"Some chunks are larger than 500 kB after minification."*

The lazy split on the landing page (`routes.tsx:24-28`, and its comment claims a
marketing visitor "never downloads the console") **does not work as documented**,
because `routes.tsx` eagerly imports all twelve console screens at
`:5-30`. Those imports populate the entry chunk, so `dist/index.html` loads the
854 kB `index-*.js` **before** it can even discover the landing chunk. The
landing page's own 34 kB is on top of that, not instead of it. Also note the
route-level split covers only the landing page: nine console screens share one
chunk.

This is the direct cause of a poor LCP on the landing page — the very metric
reel U7 is about.

**Fix:** convert the twelve `routes.tsx` screen imports to `lazy()` the same way
`LandingPage` already is. That is a mechanical change, already has the
`frame()` helper waiting at `routes.tsx:32`, and should cut the initial payload
by roughly half. Then add `manualChunks` for `react`/`react-dom`/`react-router`.

---

### P1-3 · Skeletons were built for one screen and applied to one screen

`grep Skeleton` across `frontend/src` returns exactly two non-test files:
`skeleton.tsx` and `match-list-skeleton.tsx`. Its only consumer is
`matches-screen.tsx`. Everywhere else the app still renders either a generic
progress card with a live seconds counter or the literal string "Loading…":

| Screen | Current loading UI |
|---|---|
| `matches-screen.tsx:417` | **MatchListSkeleton** ✅ |
| `tracker-screen.tsx:154,290,362` | `ProgressState` ×3 |
| `job-detail-screen.tsx:105` | `ProgressState` |
| `tailor-screen.tsx:592` | `ProgressState` |
| `document-picker.tsx:220,307` | `ProgressState` ×2 |
| `operations-screen.tsx:205` | `ProgressState` |
| `admin-screen.tsx:456` | `ProgressState` |
| `resume-screen.tsx:414` | `"Loading your profile…"` text |
| `profile-screen.tsx:45` | `"Loading…"` text |
| `application-profile-panel.tsx:84` | `"Loading…"` text |
| `work-preferences-card.tsx:84` | `"Loading…"` text |

The skeleton component's own doc comment (`match-list-skeleton.tsx:5-10`) makes
the argument for replacing the elapsed clock — and that argument applies
verbatim to the ten remaining sites.

Be careful about **which** ones to convert: `ProgressState` is *correct* for a
long mutation the user started and can cancel (a tailoring run at ~80s, a
search, a refresh). It is *wrong* for a query that is simply fetching a shape
the page already knows. So the targets are the five text-only sites plus the
three `ProgressState` calls that are really reads:
`job-detail-screen.tsx:105`, `tracker-screen.tsx:362`,
`document-picker.tsx:220,307`.

---

### P1-4 · The theme is applied after first paint, so dark users get a white flash

`index.css:244` and `motion.ts:69-78` both key off `<html>` attributes, and
`main.tsx` deliberately calls `initMotion()` **before** `createRoot` so motion is
correct on the first frame. The theme gets no such treatment:

- `index.html` contains **zero** references to `localStorage` — there is no
  inline pre-paint script.
- `theme-provider.tsx` reads `localStorage` inside `useState` and applies the
  class in a `useEffect`.

A user who chose **dark** therefore paints the **light** ivory canvas first and
switches after hydration — a full-screen white flash on every navigation that
reloads the document. The motion system already demonstrates the correct
pattern in this very repo; the theme just doesn't follow it.

Compounding it: the contrast/palette work for dark mode *is* correct
(`index.css:140-173` re-derives surfaces rather than inverting, which is exactly
what reel U5 asks for), so this is purely a delivery bug, not a design one.

**Fix:** a three-line inline `<script>` in `index.html` that reads the stored
theme and sets `document.documentElement.classList` before the first paint.

---

### P2-1 · Long text is clipped or overflows, with no way to recover it

The safe pattern exists in this repo (`plain-text.tsx:26`, `field-list.tsx:25`,
`error-notice.tsx:48` all use `break-words`) but is not applied consistently:

- `admin-screen.tsx:836-838` — the worker command
  `env\Scripts\python.exe scripts\run_worker.py` sits in a bare `<span
  className="font-mono">`. Backslashes are not break opportunities, the string is
  ~320px, the Card is `overflow-hidden`, and there is no `title`. **The command
  the operator is told to run is silently unreadable on a phone.**
- `matches-screen.tsx:128-140` — job title and `company · location` have no
  `break-words`/`truncate`; `Card` clips them with no ellipsis and no `title`.
- `approvals-screen.tsx:676-680` — the target `job_url` is interpolated into a
  plain `<p>` with no `break-words`, while the *same* URL shown via `FieldList`
  at `:586-589` is safe. The inconsistency is the bug.
- `admin-screen.tsx:514,528` — run id and `last_error` inside a
  `grid grid-cols-2` dialog with no `break-words`; grid items default to
  `min-width: auto`, so a long error string blows the dialog open.

**Fix:** `break-words` on each, or route them through the existing safe
primitives.

---

### P2-2 · The tracker table is 5 non-wrapping columns in a 295px box

`table.tsx:10` correctly wraps tables in `overflow-x-auto`, so there is no page
overflow — but `table.tsx:72,85` put `whitespace-nowrap` on every head and cell,
so no column can collapse. `tracker-screen.tsx:178-212` then places a title,
company, status badge and two formatted timestamps into a 295px card.

The row's only link to the detail screen is column 1 (`:191-198`). To read a
timestamp the user must scroll the table sideways, and the link scrolls out of
view. On the admin table the pinned Actions column (`:632,688`) is ~150px of a
325px viewport, leaving ~180px for six data columns.

**Fix (applied, see §7):** the table now drops its two timestamp columns below
`md` rather than growing wider. Both values are already shown in full on the
record screen the row links to, so nothing is lost — a short view that links
deeper, rather than one long view that shows everything. The Job and Company
cells also wrap now instead of being forced onto one line.

---

### P2-3 · The approval decision sits below the entire form on mobile

> **Corrected 2026-11-12 (see §7).** This finding was **wrong** as first
> written, and the fix suggested here would have violated the layout rules.
> The "Prepare application" button lives in the `<aside>` at
> `approvals-screen.tsx:709-719`, not inside the `<form>`. So the aside is not
> "after a form the user just filled in" — it *is* the form's submit control,
> and on mobile the order reads: form fields → Prepare → decision card. That
> is the correct order. **No reordering is needed.** The button-size half of
> this finding still stands.

`approvals-screen.tsx:665-673` — "Approve and submit", the only irreversible
action in the product, is a default-size `Button`, i.e. **32px** tall. The
largest button in the system is `h-9` (36px), so nothing reaches 44px. That
belongs to hit-area work (`better-accessibility`), not layout.

**Fix:** make this one button `h-11`. Do **not** move the card with `order`
or grid placement — see §7.

---

### P2-4 · `background-attachment: fixed` on the body

`index.css:188`. On mobile Safari and Chrome this is a known repaint cost: the
grain texture is repainted on every scroll frame instead of composited. It
affects every screen, not just the landing page.

**Fix:** scope it to `@media (min-width: 768px)`, or move the grain to a
`position: fixed` pseudo-element (which is composited).

---

### P3-1 · The demo's declared orientation contradicts its layout

`agent-demo.tsx:122-123` sets `aria-orientation="vertical"` on the tablist,
which is `flex ... lg:flex-col` (`:122-141`). At 375px the tabs are actually
laid out **horizontally**, and the row is `overflow-x-auto` with
`shrink-0 whitespace-nowrap` tabs, so most of the seven stages sit off-screen
with no fade or scroll affordance hinting at them.

Arrow keys handle both axes (`:77-80`), so it remains operable — but a screen
reader announces "vertical" while a sighted user scrolls sideways, and a touch
user may never discover stages 5–7.

**Fix:** drop the hardcoded orientation (let it be inferred), and add a fade
mask on the scroll container.

---

### P3-2 · The `d` shortcut has no modifier, so it hijacks the key

`theme-provider.tsx` binds a bare `d` key to toggle the theme. It does guard
`metaKey`/`ctrlKey`/`altKey` and editable targets — but not `shiftKey`, and not
the many single-letter-command conventions (a `v`/`j`/`k`-style keyboard user,
or a future command palette). A bare letter as a global document shortcut will
eventually collide with something; nothing else in the app currently claims
`d`, so this is latent rather than live.

**Fix:** require a modifier (`mod+shift+d`) or drop it — the account menu
already exposes the theme.

---

## 4. What is already better than the source material asks

Worth stating plainly, because the audit is heavily weighted toward gaps:

- **Token system (themes 9 and 4).** `index.css:21-173` is a complete,
  semantic, two-theme token set. Dark mode re-derives every surface
  (`:140-173`) instead of inverting, which is the correct answer to U5.
- **Contrast passes everywhere.** Measured: night-muted/night **8.01**,
  muted/ivory **5.38**, lime/forest **9.70**, ink/ivory **14.75**. All clear
  WCAG AA; most clear AAA.
- **The motion system (theme 5) is the strongest part of the codebase.**
  `index.css:225-293` distinguishes *travel* (removed) from *feedback* (kept),
  keeps the stagger under reduced motion, and offers a three-way
  System/Full/Reduced control on top of the OS setting. That is more
  considered than any of the nine motion reels.
- **AI tells (theme 8) are largely absent.** Zero `bg-gradient` utilities,
  three `backdrop-blur`, a warm non-black dark surface, and a real typographic
  pair (Bricolage Grotesque + Geist). The hero is left-aligned, not centred.
- **The reveal system fails safe.** `use-reveal.ts:7-13` applies the hidden
  state *after* mount and only when `IntersectionObserver` exists, so content
  is never invisible without JS.
- **The color field stops working when idle** (`color-field.tsx:23-27`) and is
  off on touch — no per-frame cost on a phone.

---

## 5. Suggested order of work

| Order | Item | Effort | Why first |
|---|---|---|---|
| 1 | CTA → create mode (P0-1) | ~15 min | Currently loses every new visitor at the door |
| 2 | 375px overflow + three 44px targets (P0-2, P0-3) | ~1 h | The hamburger is the whole console's navigation |
| 3 | Code-split the twelve routes (P1-2) | ~1 h | Halves the initial payload; `frame()` already exists |
| 4 | SEO + per-screen titles + favicon (P1-1) | ~2 h | The "live site" checklist; also fixes tab confusion |
| 5 | Skeletons on the read-only screens (P1-3) | ~2 h | Reuse the component that already exists |
| 6 | Pre-paint theme script (P1-4) | ~20 min | Copy the pattern `main.tsx` already uses for motion |
| 7 | Break-words + tracker cards (P2-1, P2-2) | ~2 h | Data the user cannot read is data they cannot trust |
| 8 | Approval order + button size (P2-3) | ~1 h | The irreversible action should not be the hardest to reach |
| 9 | Grain compositing, demo orientation (P2-4, P3-1) | ~1 h | Polish |

Items 1, 2, 3 and 6 together are roughly half a day and remove every P0 and the
largest P1. None of them touch the backend, the safety model, or the approval
gate — this is all presentation-layer work.

---

## 6. Method and limits

- The 22 reels were read via `og:title`/`og:description` under a crawler UA.
  **No transcript or visual content was available**; the themes in §1 are what
  each video's own caption states, not an analysis of what it shows. A reel's
  advice is therefore taken at face value rather than reconstructed.
- Bundle sizes are measured. Layout, token, contrast and accessibility findings
  are read from source with line references; contrast ratios are computed with
  the WCAG relative-luminance formula.
- Nothing was rendered in a browser during this audit, so no finding depends on
  a claim about runtime rendering that the source does not already state.
- `docs/implementation/13-frontend.md` is the owning workstream document. This
  audit deliberately does not edit it — per the project's spec-then-execute
  convention, a WS-27 document should be written before any of §5 is executed.

---

## 7. Layout pass — what was actually changed (2026-11-12)

A follow-up pass applied the `better-layout` skill's rules to the findings
above. Ten edits, all presentation-layer, in eleven files. Two findings from
§3 were **corrected by that pass** and are marked inline.

### Applied

| Severity | Location | Before | After | Why |
|---|---|---|---|---|
| HIGH | `src/screens/admin-screen.tsx:396` | `inline-flex` filter strip, four labels, ~360 px in a 327 px box | `inline-flex flex-wrap` | The only layout that scrolled the **document** horizontally at 375 px. |
| HIGH | `src/components/common/query-combobox.tsx:106` | `right-0 … min-w-[20rem]` | `end-0 … sm:min-w-[20rem]` | A hard 320 px floor threw its surplus past the leading viewport edge at ≤360 px, and `right-0` did not mirror. |
| HIGH | `src/screens/matches-screen.tsx:127` | `min-w-0` with no wrap | `min-w-0 flex-1`, `break-words` | Job title is the *link*; `Card` clipped it with no ellipsis and no tooltip. |
| HIGH | `src/screens/admin-screen.tsx:846` | worker command in a bare `span` | `<code class="font-mono break-all">` | Backslashes are not break opportunities; the instruction was clipped and unrecoverable on a phone. |
| MEDIUM | `src/index.css:197` | per-section `scroll-mt-20` guesses | one `html { scroll-padding-block-start }` | Anchored targets landed under the sticky header; a new anchor cannot now forget the offset. |
| MEDIUM | `src/screens/tracker-screen.tsx:178` | 5 nowrap columns in 295 px | timestamps `hidden md:table-cell`; Job/Company wrap | The only route into a record scrolled out of view. Detail screen already shows both dates. |
| MEDIUM | `src/screens/landing/agent-demo.tsx:117` | `lg:grid-cols-[240px_1fr]`; hardcoded `aria-orientation="vertical"` | `minmax(0,…)` both tracks; orientation from `matchMedia`; trailing fade | The announced axis contradicted the rendered axis at every width below `lg`; off-screen tabs had no cue. |
| MEDIUM | `src/components/profile/profile-view.tsx:96` | `grid-cols-[10rem_1fr]` | `grid-cols-[minmax(6rem,10rem)_minmax(0,1fr)]` | A fixed 160 px track plus a `1fr` that refuses to shrink. |
| MEDIUM | `src/screens/admin-screen.tsx:514` | `grid-cols-2`; bare `dd`s | `minmax(0,auto) minmax(0,1fr)`; `break-all`/`break-words` | Grid items default to `min-width:auto`, so a long run id or error widened the dialog off-screen. |
| LOW | `src/screens/approvals-screen.tsx:676` | URL in a plain `<p>` | `break-words` | The same URL via `FieldList` was already safe; this copy was not. |
| LOW | `src/components/observability/event-timeline.tsx:56,85` | `border-l`, `pl-*`, `left-*` | `border-s`, `ps-*`, `start-*` | The rail would not mirror under RTL. |
| LOW | `src/components/common/error-notice.tsx:53`, `src/components/observability/run-progress.tsx:283` | `pl-5` | `ps-5` | List markers follow the inline direction. |

### Corrected

- **§3 P2-3 (approvals DOM order)** — **withdrawn.** The "Prepare application"
  button is *in* the aside (`approvals-screen.tsx:709`), not in the form, so
  mobile order is already form → Prepare → decision. The suggested `order-first`
  fix would have been wrong twice over: the layout rules forbid reordering
  against DOM order, and there was nothing to reorder.
- **§3 P2-2 (tracker)** — the recommendation changed from "cards below `md`"
  to "drop the duplicated timestamp columns", which is the cheaper fix that
  the "short view that links deeper" rule points at.

### Verification

- `npx tsc -b --force` — clean.
- `npm run lint` — clean.
- `npx vitest run --maxWorkers=1` — **36 files, 211 tests, all pass.**
- `npm run build` — succeeds; CSS grew 0.67 kB raw / 0.17 kB gzip.
- Compiled output spot-checked for `border-inline-start`,
  `inset-inline-start`, `break-all`, `mask-image`, and the `lg` mask reset.

**Known pre-existing, not caused by this pass:** under the default parallel
worker pool, `approvals-screen.test.tsx` intermittently fails with
*"Test timed out in 5000ms"* (a timeout, not an assertion). It reproduces at
HEAD before these edits, passes in isolation, and passes in every serial run.
`landing-page.tsx` and `error-notice.tsx` were already `prettier --check`
failures at HEAD; they were left alone rather than reformatted as unrelated
churn.

**Not verified:** anything requiring a browser. No supported-width sweep, no
200%/400% zoom check, and no RTL mirror was rendered. The logical-property
conversions are justified by the rules and confirmed in the compiled CSS, but
no mirrored layout was seen. A concurrent session is also editing this
repository (new `profile-screen.tsx` and backend files referencing a WS-27);
its work predates this pass, shares no file with it, and was not touched.

---

## 8. Browser verification (2026-11-12)

Everything in §7 marked "not verified" was then checked in a real browser: the
ZCode in-app browser against the live dev server (`localhost:5173` → FastAPI on
`:8000`), signed in as the local operator so the console screens were reachable.

### Measured, not reasoned

| Claim | How it was measured | Result |
|---|---|---|
| Landing page never scrolls horizontally | `documentElement.scrollWidth` vs `clientWidth` at 320 / 375 / 1440 | **Pass** — `scrollsX: false` at all three |
| Admin filter strip wraps instead of overflowing | `getComputedStyle(group).flexWrap` + each button's `top` | **Pass** — `flexWrap: "wrap"`, 312 px strip in a 360 px box, "Reconciliations" on row 2 |
| Suggestion panel fits at 320 px | `listbox` rect + computed `minWidth` | **Pass** — `minWidth: 0px`, panel 225 px, inside both edges |
| Tracker drops its timestamp columns below `md` | each `<th>`/`<td>` computed `display` at 375 and 1440 | **Pass** — `none` at 375, `table-cell` at 1440; table 281 px with **no** scroll |
| Section anchors clear the sticky header | click `#how` in the header nav, compare heading top to header bottom | **Pass** — `scroll-padding-block-start: 80px`, heading 96 px below the header |
| Demo tablist orientation matches its layout | `aria-orientation` vs computed `flex-direction` | **Pass on load** — `horizontal`/`row` at 375 px, `vertical`/`column` at 1440 px |
| Event timeline mirrors under RTL | dot offset from the `ol` edges, LTR vs `dir="rtl"` | **Pass** — −4 px off the left edge → −4 px off the **right** edge |
| Dark mode is real, not inverted | computed body/card colours with `.dark` | **Pass** — body `rgb(22,21,15)`, card `rgb(30,29,23)` |
| 200 % zoom does not overflow | `zoom: 2`, then the same overflow sweep | **Pass** — 0 overflowing elements, no horizontal scroll |

### The browser found a defect my source review had missed

**`break-words` does not do what its name suggests.** It compiles to
`overflow-wrap: break-word`, which breaks a long word *after* the box has
already sized itself to that word's full width. A `Card` is `overflow-hidden`,
so the text is still clipped — exactly the defect §7 claimed to fix.

Measured on a real match card at 375 px: a 69-character unbreakable title
rendered **425 px wide inside a 311 px card**, `containedInCard: false`. After
switching to Tailwind v4's `wrap-anywhere` (`overflow-wrap: anywhere`, which
*does* affect min-content sizing), the same token wrapped onto 4 lines at
168 px, `containedInCard: true`.

Four sites were corrected: the match title and meta line, the approval URL, the
tracker job link, and the admin dialog's error value. This is the clearest
argument for the browser pass — all four looked correct in review and three of
them would have shipped broken.

### Verified in the browser, and safe

- The admin screen's stat grid is single-column at 375 px (`gridTemplateColumns: 312px`, no overflow).
- The worker command's `break-all` keeps a 45-character Windows path inside a 150 px box.
- No console screen overflowed at 375 px in the five that were sampled before a
  rate limit interrupted the sweep (`/app`, `/app/resume`, `/app/profile`,
  `/app/matches`, `/app/tailor`).

### Still not verified

- **A full nine-screen 375 px sweep.** The first attempt tripped the API's rate
  limiter (429, `Retry-After: 9`) after five screens; the remaining four were
  re-checked individually at desktop width instead.
- **The `aria-orientation` live-resize case.** It is correct on load at both
  widths, but the in-app browser's viewport emulation dispatches **no**
  `resize`/`matchMedia` change events (`resizeEvents: 0` across two resizes), so
  the live-resize path could not be exercised. That is a harness limitation, not
  evidence of a bug — the hook's behaviour on a real resize remains unproven.
- **Screen-reader output.** Roles and attributes were read from the DOM, not
  announced by an AT.

### Note on a pre-existing flake

`approvals-screen.test.tsx` intermittently times out at 5000 ms under the
default parallel worker pool. It reproduces at HEAD, passes alone, and passes
in every serial run — it is worker contention, not a regression. Verified again
after the §7 edits: **36 files / 211 tests pass** with `--maxWorkers=1`.

---

## 9. Landing copy rewrite (2026-11-12)

The whole public page's prose was rewritten with the `humanizer` and
`writing-clearly-and-concisely` skills. Two structural defects were fixed at
the same time, because they were copy problems, not layout ones.

### P0 fixed: the primary CTA opened the wrong form

`landing-page.tsx` said "Create your account" and linked to `/sign-in`, which
always opened in **sign-in** mode. A first-time visitor followed the button
written for them and was asked for a password to an account they did not have.
The only escape was a 14px underlined text button below the password field.

Both hero and closing CTAs now pass `state={{ mode: "create" }}`, and
`sign-in-screen.tsx` reads it. The default stays sign-in, so the header link
and a returning visitor still get the form they want. Three tests pin it: the
create form opens when asked, sign-in remains the default, and `renderApp`
gained `state` support so the location descriptor can be tested the way a
`<Link state>` sets it.

Verified in the browser: clicking "Create your account" lands on a page whose
`h1` is "Create an account" and whose submit button reads "Create the
account"; clicking "Sign in" in the header lands on "Sign in".

### Fixed: two vocabularies for one process

The page described the workflow twice with different words. The demo's tablist
names seven concrete stages (Résumé analysis, Job discovery, Matching and
relevance, Résumé tailoring, Application preparation, Human review and
approval, Submission and verification). The section below it then listed eight
abstract phases (Perceive, Reason, Plan, Act, Observe, Evaluate, Adapt,
Escalate). A visitor had to map one set onto the other, and "Adapt" and
"Escalate" appeared nowhere in the demo at all.

That section now names four things one application passes through (a profile,
ranked matches, a prepared application, a decision then evidence), using the
words the console uses, and the demo above it shows the mechanism for each.

### Copy patterns removed

| Pattern | Example before | After |
|---|---|---|
| Not-X-but-Y contrast | "This is not a tool, it's a mirror" style framing; "Tightened, not invented" | Each label names what happened: "Rephrased from the profile" |
| Abstract phase nouns as headings | "It works the whole process"; "What each screen does" | "What happens to one application"; "What you get" |
| Staging that restates | "Every claim below is a screen you can open. Nothing here is a plan for later." | "Each of these is a screen in the console. Nothing below is a plan for a later release." (one claim, stated once) |
| Dashes as the universal connector | "Sample data, a real interface — nothing here touches your account" | "The interface is the real one and the data is a fixture, so nothing here contacts a job board" |
| Curly quotes in UI | `"Thank you — your application has been received."` | `"Thank you. Your application has been received."` with straight quotes |
| Internal detail exposed as copy | "Walkthrough playing · fades only"; "Walkthrough paused (off screen)" | "Advancing on its own"; "Advancing without motion"; "Paused while off screen" |
| Marketing abstraction | "Matching that explains itself" / "Evidence, or it did not happen" | "Matches you can argue with" / "Evidence, or the word unverified" |

The headline changed from "Your job search runs itself. You still make the
calls." to "JobPilot finds the roles, ranks them, and fills in the forms. You
approve what gets sent." The first version claims the search "runs itself",
which is the one thing the product is careful **not** to claim about
submission; the new one names the three verbs the agent actually performs and
keeps the human decision in the same breath.

### Gates

- `npx tsc -b --force` clean, `npm run lint` clean.
- `npx vitest run --maxWorkers=1`: **36 files, 214 tests pass** (211 before;
  three added for the CTA mode).
- `npm run build` succeeds; the landing chunk shrank from 34.05 kB to 33.33 kB.
- Browser: hero, demo, loop, capabilities and trust sections all render at
  1200px and 375px; zero horizontal overflow and no document scroll at either
  width; all four reveal cards settle to `opacity: 1`.

### Still open

The SEO gap from §3 P1-1 is untouched by this pass: no `description`, no OG
tags, no `robots.txt`, and the document title is still "Agentic Job Applier —
Operator console" rather than JobPilot. Copy is now good enough that a shared
link deserves a card, which makes that gap more visible, not less.

---

## 10. Landing copy compaction (2026-11-12)

Second pass on the same page, with one instruction: too verbose, and stop
telling the visitor which providers we use or how it works internally.

### Implementation detail removed

| Was | Now | Why it was wrong |
|---|---|---|
| "It searches Greenhouse, Lever, Ashby and Remotive" (hero) | "It ranks every opening against it" | Which vendor feeds us is our plumbing. A visitor deciding whether to try the product does not care, and naming four boards dates the page to today's integrations. |
| A `greenhouse` / `lever` / `remotive` pill on every demo row | No badge | Same reason, in the most conspicuous place. The source stays in the fixture because the real system tracks it; the demo no longer shows it. |
| "The score combines keyword overlap with semantic similarity" | "The reasons come from the same signals as the score." | Explains the algorithm rather than the outcome. |
| "A validator then compares every line" | "Checking every line against your profile" | Same, for machinery. |
| "Approving runs the prepared payload against the configured adapter" | "Approve sends it. Reject sends nothing." | `payload` and `adapter` are internal nouns. |
| "converts every posting to one shape, drops duplicates, and screens out listings" | "searches the boards you pick and removes duplicates" | Normalization is invisible to the user and uninteresting. |
| "Candidate profile, personal information" | "Your profile" | A database path in UI copy. |
| `Target: Controlled test target` | removed | A demo does not need to announce its harness. |
| A "Perceive" / "Reason" / "Act" pill above every demo stage | removed | The agent framework's vocabulary, which a visitor should not have to learn. The stage name carries the meaning. |
| "Your session stays on the server" trust card | removed | Correct and important, but it is a security-page fact. Four trust cards became three, and the remaining three are the ones a job seeker actually weighs. |

### Tightened throughout

Every rendered string was shortened to one idea. The four loop steps went from
one sentence each to a phrase ("Your résumé, read into skills, roles and
dates. Nothing added."), and the four capability cards from two sentences to
one ("Every score shows what you match and what you miss."). The hero
paragraph dropped from 47 words to 33 and lost the provider list.

Section intros lost their throat-clearing:
"Pick a stage and look at what the agent produces. The interface is the real
one and the data is a fixture, so nothing here contacts a job board or touches
your account." became "Pick a stage and look at what comes out. Sample data,
nothing submitted." The demo card already carries the full disclaimer in its
own badge, so the intro was saying it twice.

### Verified

Searched the rendered DOM for the three leak categories and found none:
provider names, phase jargon (`Perceive|Reason|Evaluate|Observe`), and
implementation terms (`lexical|semantic similarity|payload|validator|adapter|normaliz|de-duplic|fixture`).
All three returned `false`.

- `npx tsc -b --force` clean, `npm run lint` clean.
- `npx vitest run --maxWorkers=1`: **36 files, 214 tests pass.**
- Landing chunk: 33.33 kB → **30.05 kB** (8.50 kB gzipped).
- Browser at 1200 px: hero, demo, loop, capabilities and trust all read as
  intended; the discovery panel shows roles with no source badges; the four
  loop cards and three trust cards settle correctly.
- Three test assertions were updated to the new copy. They assert the
  product's claims, not its vocabulary, so they moved with it.

---

## 11. Remediation (2026-11-13)

Every open item in this audit is now fixed. Gates: `tsc` clean, `lint` clean,
**37 files / 218 tests pass**, build succeeds.

| Item | State | What was done |
| --- | --- | --- |
| §3 P0-1 CTA opened the wrong form | **Fixed** (earlier pass, §9) | Both CTAs pass `state={{ mode: "create" }}`; the screen reads it. |
| §3 P0-2 page scroll at 375px | **Fixed** (§7) | The admin filter strip wraps. |
| §3 P0-3 controls under 44px | **Fixed** (§7 + this pass) | Hamburger and account trigger are `size-11`/`h-11`; the motion toggle is `min-h-9`. |
| §3 P1-1 no SEO metadata | **Fixed** | `index.html` now carries a description, OG and Twitter tags, a canonical link, `theme-color`, `color-scheme` and `viewport-fit=cover`. A real `favicon.svg` and `apple-touch-icon.svg` replace Vite's, `robots.txt` and `sitemap.xml` exist, and a 1200×630 `og.png` is generated from the product's own tokens by `scripts/render_og_card.py`. |
| §3 P1-2 the 855 kB entry bundle | **Fixed** | All twelve screens are `lazy()` in `routes.tsx`, with a `vendor` chunk for React, React Router and TanStack Query. **The entry chunk fell from 855 kB (263 kB gzip) to 185 kB (61 kB gzip)**: a landing visitor now downloads 185 + 109 vendor + 30 landing instead of the whole console. A source-map-free measurement of the new build: `index-*.js` 185.29 kB, `vendor-*.js` 348.51 kB, `landing-page-*.js` 30.35 kB. |
| §3 P1-3 skeletons on one screen | **Fixed** | `CardSkeleton` and `InlineSkeleton` added; applied to `application-profile-panel`, `work-preferences-card`, `resume-screen`, `profile-screen`, `job-detail-screen` and the tracker's evidence block. `ProgressState` is kept where it is correct: a long run the operator started and can cancel. |
| §3 P1-4 theme applied after paint | **Fixed** | An inline pre-paint script in `index.html` sets the theme class before the first frame, and the CSP carries its SHA-256 hash so the strict policy still allows exactly that one script. The hash is computed from the emitted HTML, so editing the script cannot silently break it. |
| §3 P2-1 clipped text | **Fixed** (§7) | `wrap-anywhere` on the four sites; `break-all` on the worker path. |
| §3 P2-2 tracker table | **Fixed** (§7) | Timestamp columns drop below `md`. |
| §3 P2-3 approval button size | **Open** | "Approve and submit" is still a default-size button. It belongs to hit-area work and the table in §7 records it; it is the one product decision left (a taller primary button in a dense form). |
| §3 P2-4 grain repaint on mobile | **Fixed** | `background-attachment: scroll` on touch, restored to `fixed` only at `min-width: 768px` with a hover-capable pointer. |
| §3 P3-1 demo tab orientation | **Fixed** (§7) | Orientation derived from `matchMedia`; a fade cue marks the scrollable edge. |
| §3 P3-2 bare `d` shortcut | **Fixed** | Now requires `Shift` plus `Ctrl`/`Cmd`, and calls `preventDefault`; the account menu carries the same control. |

### The CSP change is the one worth understanding

Adding the pre-paint theme script meant the strict `script-src 'self'` would
have blocked it. The alternatives were `'unsafe-inline'` (which allows every
inline script, forever) or a hash. `vite.config.ts` now computes a SHA-256 of
each inline script in the emitted document and puts it in `script-src`. The
built policy reads:

```
script-src 'self' 'sha256-lfcGGGCEro09/v3Z7Prepd/ej3G0SDtsCRwHr1DuzXw='
```

so the theme script runs and nothing else inline can. The preview server's
header policy is computed from the source `index.html`, because a header and a
meta policy are intersected by the browser and must agree.
