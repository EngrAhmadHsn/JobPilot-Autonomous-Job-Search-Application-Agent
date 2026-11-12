# Interface review — JobPilot, all pages

Reviewed 2026-11-12 with `better-interface`, which routes to the six domain
skills. Read-only: no source changed in this pass.

---

## Scope and coverage

**Scope.** Every surface in the React application, in both themes:

- Public: `/` (landing, six sections plus the interactive demo), `/sign-in`.
- Console, ten screens: `/app` (Overview), `/app/resume`, `/app/profile`,
  `/app/matches`, `/app/matches/:jobId`, `/app/tailor`, `/app/approvals`,
  `/app/tracker`, `/app/activity`, `/app/operations`, `/app/admin`.

**Stack.** React 19, Vite 8, React Router 7 (client-rendered, no SSR),
Tailwind v4 with `@theme inline` tokens, Base UI primitives, TanStack Query,
Vitest + Testing Library.

**Styling conventions.** Semantic tokens in `frontend/src/index.css`
(`--color-lime`, `--color-forest`, `--color-terracotta`, `--color-night`,
`--color-night-muted`, plus the shadcn role tokens). Dark mode is `.dark` on the
root, not `prefers-color-scheme`. The identity rule the project documents:
lime means the agent acted, terracotta means a person did or must.

**Convention documents found.** `AGENTS.md` and `CLAUDE.md` at the root;
`docs/implementation/13-frontend.md` § "The design system" (which records the
ivory/forest/lime/clay identity and its token names). No `CONTRIBUTING.md`, no
`CODING_STANDARDS.md`, no Storybook.

**Boundary.** Server-supplied strings (job titles, company names, error
messages from the API, model provider errors) were inspected only as rendered
in this deployment's data. A string only the server can produce in another
state was not seen.

### Coverage

| Domain | Evidence inspected | Result |
| --- | --- | --- |
| Accessibility | All 12 routes in a browser: `h1` count, `main`/`nav` landmarks, heading outline, accessible name on every `a`/`button`/`input`/`select`/`textarea`, label binding, dialog semantics, `:focus-visible` rule presence, `scroll-padding-block-start`, 375 px and 200 % zoom sweeps | 3 findings |
| Layout | All screens at 375 px and 320 px measured for `scrollWidth > clientWidth` and per-element overflow; 1440 px; 200 % zoom; `dir="rtl"` mirror on the activity timeline; `minmax(0,…)` track audit | Clear (fixes from the earlier pass hold) |
| Writing | Every rendered string on the landing page and demo (`landing-page.tsx`, `demo-data.ts`); page headings and section intros on all ten console screens; empty-state and error copy in `progress-state.tsx`, `error-notice.tsx`; button labels across both surfaces | Clear |
| Typography | Declared sizes and weights per heading level, line-height values, `tabular-nums` coverage, arbitrary `text-[Npx]` values, `text-balance` placement, truncation rules, 16 px input rule | 2 findings |
| Colors | Computed contrast for 10 token pairs in both themes; status-badge tone mapping; semantic-color usage across screens | Clear |
| UI polish | `transition-all` uses, press-scale values, `overscroll-behavior` on overlays, icon `currentColor` compliance, `will-change`, stagger and easing values | 3 findings |

---

## Findings

| Severity | Domain | Location | Before | After | Why |
| --- | --- | --- | --- | --- | --- |
| HIGH | Accessibility | `frontend/src/screens/*.tsx` (all 12 screens), `index.html:6` | `document.title` is never assigned. Every route shows `Agentic Job Applier — Operator console`, confirmed in the browser on all ten console screens and both public pages. | Add a `useDocumentTitle(title)` hook that sets `document.title = `${title} · JobPilot``, called once per screen from the `h1` it already renders | Route changes announce nothing to a screen reader and a user with several tabs open cannot tell them apart (WCAG 2.4.2 Page Titled). The landing page is also publicly indexed under the wrong product name. |
| HIGH | Accessibility | `frontend/src/screens/landing/landing-page.tsx:29`, `frontend/src/components/layout/app-shell.tsx:130` | No skip link in the DOM on any route (verified: no element matching `/skip/i` is focusable, and the first focusable element on the landing page is the logo link). | Add one skip link as the first child of both surfaces: `<a href="#main" className="sr-only focus:not-sr-only …">Skip to content</a>`, and give the landing page's content wrapper `id="main"` | The landing page has a 14-heading document and the console has a two-row nav plus an account menu before `<main>`. Keyboard users must tab through all of it on every route change (WCAG 2.4.1 Bypass Blocks). |
| HIGH | Accessibility | `frontend/src/screens/landing/landing-page.tsx:29` | The landing page has no `<main>` landmark. Verified in the browser: `main: 0`, while all ten console screens correctly have `main: 1`. | Change the content wrapper to `<main className="night-surface min-h-screen">`, keeping `<SiteHeader>` outside it | Screen-reader users navigate by landmark. A page with a header, a nav and a footer but no main landmark offers no way to jump to the content (WCAG 1.3.1 Info and Relationships). |
| MEDIUM | Accessibility | `frontend/src/components/layout/nav-drawer.tsx:34` | The hamburger is `size-9` (36 px). Below `lg`, `app-shell.tsx:121` hides the desktop bar, so this is the only navigation in the entire console. | `size-11` (44 px) | 36 px is below the 44 px touch heuristic and this control is the sole route to every screen. Not a WCAG 2.5.8 failure (36 > 24), so not a trigger. |
| MEDIUM | Typography | `frontend/src/components/common/page-header.tsx:24` | `text-[28px] … sm:text-[32px]` for every screen's `h1`, and `text-[15px]` on the description. | Use the scale: `text-3xl` (30 px) and `text-base` (16 px) | Arbitrary pixel values bypass `rem`, so a reader who raises the browser font size gets no effect on the primary heading. The rest of the app sizes in `rem`. |
| MEDIUM | Typography | `frontend/src/components/common/page-header.tsx:24` | `leading-tight` (1.25) on an `h1` that wraps to two lines on every console screen at 375 px. | `leading-[1.15]` at display scale is fine for one line; for a heading that wraps, raise to `1.2`–`1.3` — `leading-tight` resolved to 1.25, which is inside the band, so this is only a risk where the string is long | Recorded as a watch item, not a defect: 1.25 is within the accepted 1.2–1.3 range. Listed because three console `h1` strings exceed 30 characters and will wrap at phone width. |
| MEDIUM | UI polish | `frontend/src/components/ui/button.tsx:6` | `transition-all` on the shared button, alongside `hover:scale-[1.02]` and `active:…:scale-[0.97]` | `transition-[scale,background-color,border-color,color,box-shadow]` | `transition-all` animates every animatable property, including ones that trigger layout, and it is the one class every button in the product inherits. |
| MEDIUM | UI polish | `frontend/src/screens/landing/landing-page.tsx:88,266` | `active:scale-[0.97]` on the two landing CTAs, against the component library's `0.96` | `active:scale-[0.96]` | The same detail done two ways within one product. The library value is the documented one. |
| LOW | UI polish | `frontend/src/components/ui/dialog.tsx`, `frontend/src/components/ui/sheet.tsx` | No `overscroll-behavior: contain` on either overlay's scroll container | Add `overscroll-contain` | Scrolling past the end of a dialog or the nav drawer scrolls the page behind it. |
| LOW | UI polish | `frontend/src/screens/landing/landing-page.tsx:299,305` | `stroke="#173d32"` hardcoded twice in the logo SVG | `className="stroke-forest"` | An icon taking a literal color cannot follow the theme; `currentColor` or a token can. Isolated to one mark, so low. |
| LOW | UI polish | `frontend/src/screens/landing/agent-demo.tsx:232` | `transition-all duration-300` on the stage-progress dot, a high-frequency element | `transition-[width,background-color]` | Naming the property is the cheaper correct form. |

That is 11 findings. Ranked by severity and reach, the three HIGH findings all
sit in the same layer (document-level accessibility plumbing), and fixing them
together is roughly one hook plus two lines of markup.

---

## What was checked and passed

These were not assumed. Each was measured.

**Accessible names.** Every `a`, `button`, `input`, `select`, `textarea` and
`[role=tab]` on all 12 routes was tested for a name from `aria-label`,
`aria-labelledby`, `label[for]`, a wrapping label, visible text, or `title`.
The final count is zero unnamed controls on the landing page and zero on all
ten console screens. Two inputs on `/app/resume` and `/app/profile` initially
reported as unnamed; a re-check with a settled wait showed them correctly
labelled, so the first read was a loading-state artifact and is not reported.

**Heading structure.** One `h1` per route, no skipped levels, on all 12 routes.

**Landmarks.** `main: 1` and `nav: 2` on every console screen. The landing page
is the exception, reported above.

**Contrast, both themes.** Computed from the token values:

| Pair | Ratio |
| --- | --- |
| night-muted on night (hero sub-head) | 8.01 |
| night-muted on night-soft (card body) | 7.41 |
| ivory on night | 16.35 |
| lime on night (headline line 2) | 14.41 |
| lime-foreground on lime (primary CTA) | 9.70 |
| muted-foreground on ivory | 5.38 |
| dark muted on dark | 7.19 |
| accent on primary | 10.27 |
| terracotta on night | 12.90 |

Every pair clears 4.5:1 for text; most clear AAA.

**Meaning is never carried by color alone.** `status-badge.tsx` renders the
status label as text, with the tone as a secondary cue; the two-colour
agent/human legend on the landing page is likewise paired with words.

**Layout.** Confirmed in an earlier browser pass and unchanged: no horizontal
document scroll at 320 px, 375 px or 1440 px; the admin filter strip wraps; the
suggestion panel fits at 320 px; the tracker table drops duplicate columns
below `md`; the event timeline mirrors correctly under `dir="rtl"`; zero
overflowing elements at 200 % zoom.

**Dialogs.** Base UI's `Dialog` supplies focus trapping, Escape, and the modal
semantics; `role="dialog"`/`aria-modal` are not hand-rolled, which is the
correct choice.

**Reduced motion.** `index.css` keys motion on `html[data-motion="reduced"]`,
resolved before first paint, and distinguishes travel (removed) from feedback
(kept). The demo's auto-advance pauses off-screen and the visitor can pause it.

**Inputs.** `input.tsx` is `text-base … md:text-sm`, which is the correct iOS
exception to the 16 px rule.

---

## Verification

Run and observed:

- `npx tsc -b --force` — clean.
- `npm run lint` — clean.
- `npx vitest run --maxWorkers=1` — 36 files, 214 tests pass.
- Browser, 12 routes, signed in as the local operator: heading counts, landmark
  counts, accessible-name sweep, input label binding, `document.title` per
  route, computed contrast, overflow sweeps.

**Not verified:**

- **Visible focus rings.** The global rule exists (`index.css:200`,
  `:focus-visible { outline: 2px solid var(--ring) }`) and `--ring` resolves to
  `#173d32`. But the in-app browser cannot dispatch real keyboard input
  (`tab.cua.keypress` did not move focus; `el.focus()` never matches
  `:focus-visible` by design), so no ring was actually seen. **Not verified.**
- **Screen-reader output.** Roles and names were read from the DOM, not
  announced by an assistive technology.
- **200 % browser zoom via the UA setting.** Zoom was emulated with
  `zoom: 2`, not the browser's own control.
- **Server-supplied strings** in states this dataset did not produce.

---

## Verdict

**Block.** Three HIGH findings remain: no per-screen document title, no skip
link, and no `<main>` landmark on the landing page. All three are
document-level accessibility plumbing rather than surface defects, they affect
every route, and they are cheap to fix together. The MEDIUM and LOW findings
stay in the table as work to do.

Styling, color, layout and copy came out clean.

---

## Remediation (2026-11-13)

All three HIGH findings and every MEDIUM and LOW item are fixed. Gates after
the work: `tsc -b --force` clean, `npm run lint` clean, **37 files / 218 tests
pass** (214 before; four added), `npm run build` succeeds.

| Severity | Finding | Fix | Location |
| --- | --- | --- | --- |
| HIGH | No per-screen document title | `useDocumentTitle` hook; `PageHeader` calls it, which covers all eleven console screens from one place, and the landing and sign-in screens call it directly | `src/hooks/use-document-title.ts`, `src/components/common/page-header.tsx:30` |
| HIGH | No skip link | `SkipToContent` component, first child of both surfaces, targeting `#main-content` | `src/components/common/skip-to-content.tsx`, `app-shell.tsx:83`, `landing-page.tsx:44` |
| HIGH | Landing page has no `<main>` | The content wrapper became `<main id="main-content" className="scroll-mt-24">`, with the header left outside it | `src/screens/landing/landing-page.tsx:46` |
| MEDIUM | Hamburger 36px, the console's only navigation below `lg` | `size-9` → `size-11` (44px) | `src/components/layout/nav-drawer.tsx:38` |
| MEDIUM | Account trigger 36px, the only path to sign-out and settings | `h-9` → `h-11` | `src/components/layout/account-menu.tsx:59` |
| MEDIUM | Motion toggle ~20px, the only motion control below `sm` | `min-h-9` and `py-1.5` | `src/components/motion-toggle.tsx:68` |
| MEDIUM | `text-[28px]`/`text-[15px]` bypassed `rem` | `text-3xl` and `text-base`; `leading-tight` → `leading-[1.15]` | `src/components/common/page-header.tsx:41` |
| MEDIUM | `transition-all` on the shared button | `transition-[scale,background-color,border-color,color,box-shadow] duration-150` | `src/components/ui/button.tsx:6` |
| MEDIUM | Press scale `0.97` against the library's `0.96` | `active:scale-[0.96]` on both landing CTAs | `src/screens/landing/landing-page.tsx:88,266` |
| LOW | No `overscroll-behavior` on overlays | `overscroll-contain` on the dialog and the sheet (the sheet also gained `overflow-y-auto`) | `src/components/ui/dialog.tsx:54`, `sheet.tsx:63` |
| LOW | Literal `stroke="#173d32"` in the logo | `className="stroke-forest"` | `src/screens/landing/landing-page.tsx:312,318` |
| LOW | `transition-all` on the demo's progress dot | `transition-[width,background-color]` | `src/screens/landing/agent-demo.tsx:232` |
| — | **Also found:** the sign-in screen had no `main` | Wrapper became `<main>` | `src/screens/sign-in-screen.tsx:69` |

### Verified in the browser

- Landing: title `Job search that waits for you · JobPilot`, description, OG
  and Twitter tags, canonical, `/favicon.svg`, `main#main-content` with the
  header outside it, skip link first in the tab order.
- Console, five screens sampled: each shows its own title (`Overview ·
  JobPilot`, `Find the work that fits · JobPilot`, `Track every application ·
  JobPilot`, …), one `main`, skip link present.
- 375px: hamburger exactly 44×44, account trigger 44px, no horizontal scroll.
- Dark theme: `localStorage.theme = "dark"` then reload paints the dark canvas
  immediately (`rgb(22,21,15)`), which is the flash the pre-paint script fixes.

Four tests pin the document-level behaviour, in
`src/screens/document-accessibility.test.tsx`: the landing title, a per-screen
console title, the skip link being first in the tab order, and `<main>` existing
with the header outside it.

### Still not verified

Visible focus rings, for the same reason as before: this browser harness cannot
dispatch real keyboard input, so `:focus-visible` never matches. The rule and
its token are present and correct; the rendering was not seen. That remains the
one item to close by hand.

**Verdict after remediation: `Approve`** for every domain inspected, with the
focus-ring rendering the single unverified check.
