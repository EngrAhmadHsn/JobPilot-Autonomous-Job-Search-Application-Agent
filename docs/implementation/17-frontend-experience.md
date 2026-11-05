# WS-17 — Product Experience, Visual Identity & Frontend Evolution

**Status:** in progress
**Depends on:** WS-13 (the operator console), WS-14 (multi-user identity + authorization)
**Scope:** the public marketing site, the authenticated workspace, the administrator
console, user-facing observability, and one coherent motion system — all in
`/frontend`.

---

## 0. Phase 0 — the audit (what actually exists)

Findings from reading the repository, not from its documentation.

**Frontend.** React 19 + TypeScript + Vite 8 + Tailwind 4 + Base UI/shadcn 4 +
React Router 7 + TanStack Query 5 + Zod 4, tested with Vitest + MSW and
Playwright. A single route tree (`src/routes.tsx`) mounts every screen as a
child of `AppShell` at `/`. Six screens exist: Resume, Matches, Tailor,
Approvals, Tracker, Operations. There is **no public page**: an unauthenticated
visitor gets the sign-in screen at every path (`app-shell.tsx` renders
`SignInScreen` for any `/api/auth/me` error). The design system is real and
deliberate — ivory/paper/forest/lime/terracotta/ink tokens in `src/index.css`,
Bricolage Grotesque over Geist, and the semantic rule **lime = the agent,
terracotta = a human**. Screen transitions already use the View Transitions API
via React Router's `viewTransition` prop.

**Backend.** 39 routes across ten router modules. Relevant to this workstream:

- `GET /api/applications` — a page of tracked applications with a status filter.
- `GET /api/applications/{id}` — one application **with its ordered event log**.
- `GET /api/audit` — the caller's **own** audit rows, newest first: `action`,
  `actor`, `actor_kind`, `actor_id`, `resource`, `outcome`, `workflow_id`,
  `metadata`, `recorded_at`. This is the observability backbone.
- No aggregate, metrics, streaming (SSE/WebSocket), or admin endpoint exists.

The audit vocabulary is fixed and small: actions
`resume.upload`, `job.search`, `match.compute`, `application.{prepare,approve,
reject,submit,verify,transition,event,permission_denied,unsafe_navigation,
blocked_challenge}`, `allowlist.violation`, `llm.usage`, `auth`, `retention`;
outcomes `success`, `blocked`, `denied`, `error`. **Observability must be built
from exactly these strings — nothing else is real.**

**Identity / authorization.** `is_superuser` is a column on `users` and is
returned by `/api/auth/me` (`UserRead` extends fastapi-users' `BaseUser`). A
`UserScope` carries `is_superuser`, and `src/db/access.py::_owned` drops the
owner filter for a superuser scope — the platform's audit view, "the one
deliberate exception". **No route exposes that scope.** So an administrator
console needs a new, explicitly-guarded server surface; a frontend-only admin
flag would violate the WS-14 model.

**The machine-checked contracts that constrain any change:**

- `tests/test_docs_accuracy.py` — the README's API table must equal the running
  OpenAPI surface, **both directions**. A new route without a README row fails.
- `tests/test_tenant_isolation.py` — no route may query a user-scoped table
  directly (it must use `src/db/access.py`), and any route that uses the
  accessors must take `current_scope`.
- `tests/test_env_docs.py` — `.env.example` must equal the runtime's env reads.

**Phase 0b — external references (inspected, not assumed).** Visited in a real
Chromium (script: `frontend/scripts/inspect-refs.mjs`; captures in
`frontend/refs-out/`).

| Reference | Reachable | What was observed |
| --- | --- | --- |
| formless.xyz | yes | Pure-black canvas, two `<canvas>` layers (WebGL/2D), Neue Haas Grotesk, an enormous white grotesk headline, minimal top nav, pill buttons. The colour spill itself is animated and not captured in a static frame. |
| agencly.app | yes | Ivory background with a faint grid; a **mock product window** (`yourcompany.agencly.app`) that auto-cycles and invites "click any module to explore"; scattered floating module chips; centred bold hero. |
| youtube `Fog8WpdTnYU` | title only | "7 Web Design Styles That Make Any Website Look Expensive in 2026". Video body **not retrievable** (no transcript/description body). Not used. |
| youtube `pbhLsV-Dyho` | title only | "6 EASY Tips to 10x Any Site's Design". The six tips are stated in the brief itself and are applied; the video body is not retrievable. |
| facebook `1HhjPLqoRj` | caption only | "How to unslop your designs: 1. Show it a reference… get AI to match or combine the styling". Used as an anti-pattern cue. |
| facebook `1146520814389665` | caption only | "Premium apps aren't faster. They move better. The difference between cheap and premium is mostly in the motion." Used as the motion principle. |

The two Facebook reels and the two YouTube videos could not be watched — only
their titles/captions were obtainable. Their **bodies are not fabricated**;
only what the captions state is applied.

---

## 1. Phase 1 — design direction

Two directions were developed; the second was rejected for a stated reason.

### Direction A — *The dossier, after dark* (selected)

The **console** keeps its identity exactly: an ivory dossier on a desk, lime for
the agent, terracotta for the human, Bricolage over Geist. The **public front**
is the same desk at night: a warm, near-black forest-charcoal canvas
(`--night`, `#0E1A16`), the same ivory type, lime as the *agent's light* and
terracotta as the *human's*. The signature interaction is a pointer-reactive
**light field**: the cursor stirs a slow, lagging bloom of lime and terracotta
across the dark paper, like a hand moving under a lamp — smooth interpolation,
intensity tied (subtly) to pointer velocity, confined to the hero, disabled on
touch and under `prefers-reduced-motion`. The centrepiece is the **interactive
agent demonstration**: a miniature, clearly-labelled JobPilot window a visitor
can drive stage by stage through the real workflow.

*Why it wins:* it satisfies "the landing page can be more immersive and darker
using the existing identity" without inventing a second brand, and the light
field is the product's own metaphor (the agent's lime and the human's clay)
turned into the interaction rather than an unrelated gradient.

### Direction B — *The workbench* (rejected)

A light, product-forward page in the Agencly idiom: ivory page, floating
module chips orbiting a centred hero, a mock console panel. **Rejected:** it
makes the marketing site a copy of the console, drops the immersion the brief
explicitly permits, and leans on floating chips — named in §12 of the brief
("too many floating cards and disconnected UI panels") — as its main device.

### The motion language (applies to both surfaces)

One system, six rules: (1) motion answers an action or explains a transition —
never decorates; (2) transform/opacity only; (3) a single easing family
(`--ease-soft` for entrances, `--ease-inout` for transitions); (4) scroll
reveals fire **once**, on an `IntersectionObserver`, never per-frame; (5) a
continuous render loop runs **only** while the pointer is over the surface that
wants it (the light field), and never at all for touch/reduced-motion; (6)
every important interaction is reachable by keyboard and `prefers-reduced-motion`
turns all of it off.

---

## 2. Phase 2 — architecture and plan

**Route split.** The console moves under `/app`; `/` becomes the public
landing page and `/sign-in` a public route. `AppShell` keeps its identity gate
for `/app/*` only.

| Path | Surface | Auth |
| --- | --- | --- |
| `/` | marketing landing (hero, demo, capabilities, trust, CTA) | public |
| `/sign-in` | sign in / create account | public |
| `/app` | **Overview** (new) — real activity summary | session |
| `/app/resume` … `/app/operations` | the six existing screens | session |
| `/app/activity` | **Agent activity** (new) — the audit feed + run detail | session |
| `/app/admin` | **Administration** (new) — platform overview | superuser |

**New shared components:** `ColorField` (the light field), `useReveal`
(scroll reveal), `AgentWorkflowDemo` + `demo-data` (isolated sample data),
`RunTimeline` + `observability` helpers (group audit rows into runs),
`StatTile`.

**New hooks/utilities:** `useReducedMotion`, `usePointerCapable`.

**New API contracts:**

- `GET /api/audit` — already exists; the console gains a typed client.
- `GET /api/admin/overview` — **new**, superuser-only: platform aggregates
  (accounts, applications by status, audit outcomes by kind, corpus size). The
  route is refused with 403 for a non-superuser and reads across owners through
  a superuser `UserScope` (the accessors' documented exception).

**Security invariants kept:** the session stays an `HttpOnly` cookie; no token
in JS; CSRF header on unsafe requests unchanged; the admin screen renders only
what the server authorized; every aggregate is a real DB count.

**Honest limits recorded up front:** there is **no event streaming** — the
overview and activity screens refetch on an interval and say when data was last
updated; genuine streaming (SSE) is listed as a required backend capability,
not simulated. There is **no fake-ATS-to-real-board capability**, so the
marketing copy advertises only what the code supports (approval-gated
submission to the controlled test target).

---

## 3. Phase 3 — implementation (as built)

### The public surface

| File | What it is |
| --- | --- |
| `screens/landing/landing-page.tsx` | the landing page: header, hero, sections, final CTA, footer |
| `screens/landing/color-field.tsx` | the pointer-reactive light field (canvas 2D) + the static fallback |
| `screens/landing/agent-demo.tsx` | the interactive demonstration (a `tablist` + panel) |
| `screens/landing/demo-data.ts` | the isolated sample data — a fixture, labelled a demo |
| `hooks/use-media-query.ts` | `useReducedMotion`, `usePointerCapable` |
| `hooks/use-reveal.ts` | the one-way scroll reveal (marks descendants, never hides without JS) |

The light field is **canvas 2D**, not WebGL: a handful of additive radial
gradients in the identity's lime and terracotta, eased toward the pointer at
per-bloom depths so the light lags the hand. It starts on the first
`pointermove` and **stops** when the blooms settle and the pointer leaves — an
idle page does zero work per frame. It is off entirely on touch devices and
under `prefers-reduced-motion`, where the section's own static gradient is the
fallback.

The demonstration is seven stages of the real loop (résumé → discovery →
matching → tailoring → preparation → approval → verification) with the real
job sources and tailoring vocabulary. It is keyboard-operable (arrow keys,
`Home`/`End`), it auto-advances only while on screen and not under
reduced-motion, and it pauses the moment a visitor takes over. It never
contacts the API.

### The console

| Path | Change |
| --- | --- |
| `/` | the public landing page (lazy-loaded — the console bundle does not carry it) |
| `/sign-in` | a public route; the shell still renders the form inline for `/app/*` |
| `/app` | **new** — the Overview |
| `/app/activity` | **new** — Agent activity (observability) |
| `/app/admin` | **new** — Administration (superuser only) |
| `/app/{resume,matches,tailor,approvals,tracker,operations}` | the existing screens, re-based under `/app` |

New shared pieces: `components/common/stat-tile.tsx`,
`components/observability/event-timeline.tsx` (`EventList`, `RunTimeline`),
`lib/observability.ts` (the vocabulary *and* the run grouping).

The **Overview** counts its figures from `GET /api/applications` and
`GET /api/audit`; the **Activity** screen shows the audit trail, groups rows
into executions by `workflow_id`, and says in plain words that it refetches on
an interval rather than streaming. Both show when the data was read.

### The administrator surface (a real backend change)

`GET /api/admin/overview` (`src/api/routes/admin.py`) is guarded by
`require_superuser`, which depends on `current_scope` — so a request with no
credential is a 401 and an ordinary account is a **403 before any query runs**.
The scope that reads across owners is built from the session's own
`is_superuser` flag; there is no header, body or path field that can widen it.
The aggregates go through `src.db.access` (`count_owned`, `group_owned`,
`count_distinct_owned`, `count_jobs`, `count_users`) so the route never queries
an owner-scoped table directly — the isolation matrix enforces that. The
console only decides whether it is worth *asking*; the server decides whether
to answer.

### A note on "there is no animation"

**Check the visitor's OS first.** On this machine,
`HKCU\Control Panel\Desktop\WindowMetrics\MinAnimate` is **`0`** — Windows'
"Animation effects" is off, which makes every Chromium browser report
`prefers-reduced-motion: reduce`. That single switch explains every symptom at
once: the light field off, entrances that only fade, no stagger, and a
walkthrough that never advances. **Playwright cannot see it:** it forces
`reducedMotion: 'no-preference'` unless told otherwise, which is why an early
diagnostic wrongly reported `false`.

**The motion control (so the OS is a default, not a verdict).** Windows reports
reduce on plenty of machines for reasons that have nothing to do with the
person using the site, so the product offers its own choice —
`src/lib/motion.ts` and `components/motion-toggle.tsx`:

- **System** (the default) — follow the OS;
- **Full** — play everything, whatever the OS says;
- **Reduced** — no movement, whatever the OS says.

The control is in the **landing header and footer**, and in the **console
account menu**. The effective value is mirrored onto `<html data-motion="…">`
by `initMotion()` **before the first render**, which is what the CSS keys on —
so choosing "Full" restores the light field, the stagger and the walkthrough on
a reduced-motion machine. Verified with
`scripts/verify-motion-control.mjs`: on a `reducedMotion: "reduce"` browser,
`data-motion="reduced"` and the hero staggers fades at 0.08 s / 0.16 s; after
choosing Full, `data-motion="full"`, the canvas repaints and the demo advances.

**What reduced motion still does, by design:** it removes **travel**. Entrances
keep their fade *and their stagger* (a sequence of fades is not movement), the
walkthrough still advances (it is content, with an explicit pause), and the
light field, the shine sweep and view-transition rises are off.

### Six defects the verification found and fixed

1. **The scroll reveal hid its own content.** The hook observed only the
   section wrapper while the cards carried a static `data-reveal="pending"`, so
   the loop, capability and trust cards were permanently invisible — and would
   have been invisible with scripting off, too. The hook now marks each
   descendant itself, and only when an `IntersectionObserver` exists.
2. **The navigation rendered "Overview" twice** (a group heading and the item).
   The first group now has no heading.
3. **Every console screen-to-screen link pointed at the old paths.** Moving the
   console under `/app` left links like `to={`/matches/${id}`}` unchanged, so
   they fell through the catch-all route to the landing page. The unit suite
   missed it — each test asserted what a screen *rendered*, not where its links
   *went*; the **e2e** caught it. All links now carry the `/app` prefix, and
   `src/lib/console-navigation.test.ts` scans the sources mechanically so the
   rule cannot drift again.
4. **The `<meta>` CSP was asking for a directive it cannot have.** The Vite
   plugin injected the **whole** policy — `frame-ancestors` included — into the
   built document, but `frame-ancestors` (like `report-uri` and `sandbox`) is
   defined only for a **header**-delivered policy: in a `<meta>` tag the browser
   drops it and logs an error on every load. So the anti-framing rule the
   document claimed was never in force there. The meta policy now omits the
   directives meta cannot carry; the header keeps the full policy, and the
   `X-Frame-Options: DENY` header covers the rest. The browser console is now
   silent.
5. **The light field's pointer gate excluded touchscreen laptops.** It asked
   `(hover: hover) and (pointer: fine)` — the **primary** input — and on a
   laptop whose primary input is reported as the touch screen the effect
   switched itself off even while the visitor used the trackpad. It now asks
   `(any-hover: hover) and (any-pointer: fine)` ("is a fine pointer available
   at all?"), which is true on a touchscreen laptop and false on a phone. That
   decision is pinned by `src/hooks/use-media-query.test.ts`.
6. **The reduced-motion rule deleted feedback, not just movement.** A blanket
   `transition-duration: 0.01ms` on `*` (plus `animation-duration`) is the lazy
   reading of the preference: it removed the harmless parts — an opacity fade, a
   colour change — along with the harmful ones, so on any machine with Windows'
   "Animation effects" off the whole interface *popped*, and the hero had no
   entrance at all. Reduced motion now removes **travel** (transforms, the
   pointer field, loops, scroll effects) and keeps non-moving feedback: entrances
   fade over 300 ms with no rise, reveals fade at 0.32 s. Measured with
   `scripts/diagnose-reduced-motion.mjs`: `reduced-fade 0.3s`, intermediate
   opacity values present, `travelled: false`.

The hero also now carries a **one-shot entrance** (`.enter-up`, a 420 ms
stagger down the column), so the page reads as alive before any pointer input.
It is not a loop.

### Not done (and not faked)

- **No event streaming.** The activity screen polls and says so; real-time
  needs a server-sent-events endpoint the backend does not have.
- **The administrator screen is unpopulated by default**, because the local
  operator account is not a superuser — the screen correctly shows the 403
  state. Verifying the *populated* state in a browser would need an account
  promoted to superuser (a deliberate, separate step).
- **The brand reads "JobPilot"** on both surfaces; the console previously said
  "CareerPilot". The SDD's captured screenshots (`docs/SDD.docx`) still show the
  old name and are now stale.

## 4. Phase 4 — verification

- `npm run typecheck` — clean
- `npm run lint` — clean
- `npm test` — **117 passed** (84 pre-existing + 33 new)
- `npm run build` — clean; the landing page is a separate lazy chunk
- `npm run e2e` — **4 passed**, including the full workflow (sign up → résumé →
  search → match → tailor → prepare → approve against the fake ATS → verify →
  tracker). This is the run that caught defect 3 above.
- `ruff check src tests scripts` — clean
- `pytest -m "not browser"` — **1282 passed**, 6 failed: the six documented
  Remotive DNS flakes (`SSRFBlockedError` on `remotive.com`), environmental,
  not a regression
- `pytest tests/test_admin_api.py tests/test_docs_accuracy.py tests/test_tenant_isolation.py`
  — 30 passed (the README API table and the isolation matrix both accept the
  new route)
- Real-browser pass (Chromium against the production build on `:4173` and a
  live backend on `:8000`): landing desktop/tablet/mobile, the demo driven by
  click and by keyboard, and the four console screens against the **real**
  corpus (10 tracked applications, 100 audit rows, 29 documents). No page
  errors and no CSP-blocked resources.

