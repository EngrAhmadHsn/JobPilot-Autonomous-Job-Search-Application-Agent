# The operator console

Two surfaces in one package for the **Agentic Job Applier**:

- a **public landing page** at `/` — explains the product and lets a visitor
  drive an interactive demonstration of the agent's working loop (sample data;
  it never calls the API) — plus `/sign-in`;
- the **operator console** at `/app` — upload a résumé, browse the ranked
  matches, tailor a résumé for a job, prepare an application, **approve or
  reject it**, track every application's history, and watch the agent's own
  activity (Overview, Activity, and an Administration screen for a superuser).

It is a separate package beside the backend, not part of the runtime. The
backend is the source of truth; the console is a thin, honest projection of
what the API returned. The design and the API contract are in
[`docs/implementation/13-frontend.md`](../docs/implementation/13-frontend.md);
the landing page, observability and administration are in
[`docs/implementation/17-frontend-experience.md`](../docs/implementation/17-frontend-experience.md).

## Running it

```bash
npm install
npm run dev      # http://localhost:5173
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so the browser makes
a same-origin request. The API has to be running:

```bash
# in the repository root
env\\Scripts\\python.exe -m uvicorn src.main:app --port 8000
```

Set `VITE_API_BASE_URL` to point the console at another API (leave it empty
for the proxy). There is no secret here: the console holds no credential of
any kind, and nothing in this package may ever hold a key. The session lives
in an `HttpOnly` cookie the browser attaches on its own, and the only token
the console can read is the CSRF token, which grants nothing without that
cookie beside it.

## The scripts

| Script                | What it does                                                              |
| --------------------- | ------------------------------------------------------------------------- |
| `npm run dev`         | the dev server (Vite)                                                     |
| `npm run build`       | the production build (typecheck, then bundle)                             |
| `npm run typecheck`   | `tsc` over the app, the tooling and the e2e tests                         |
| `npm run lint`        | ESLint, including the rule that forbids `dangerouslySetInnerHTML`         |
| `npm run format`      | Prettier                                                                  |
| `npm test`            | the Vitest suite (the client, the screens, the error handling)            |
| `npm run coverage`    | the same, with a coverage report                                          |
| `npm run api:types`   | regenerate `src/lib/api/schema.ts` from the running API's `/openapi.json` |
| `npm run e2e`         | the Playwright smoke path against the real backend and the fake ATS       |
| `npm run e2e:install` | install the Chromium build Playwright needs                               |

## The look

The console is a **dossier on a desk**: an ivory page (`#F7F5EF`), a sheet of
paper on it (`#FFFDF8`), ink for the text (`#23211C`), a forest green for the
one action (`#173D32`), a lime highlighter for the marks the **agent** makes
(`#D9F36A` — match scores, the progress bar) and a warm clay for the marks a
**human** makes (`#F1D6C8` — the current profile, a recorded outcome).

That last rule is the one that carries the meaning: if a mark is lime, the
agent did it; if it is clay, a person did. It is kept across the landing page
too, where the same lime and clay are the light the pointer stirs on a warm,
near-black forest canvas (`--night`, `#0E1A16`) — the same desk, after dark.

The tokens live in `src/index.css`, and the shadcn components inherit them,
so the whole kit changed with one file. The display face is Bricolage
Grotesque, the body face is Geist, the content column is 1120 px, and the
motion is 150–200 ms that answers an action (`prefers-reduced-motion` turns
it off). The one continuous effect — the landing page's pointer-reactive
light field — runs only while the pointer is over it, and never on touch or
under reduced motion.

## The rules this package keeps

- **Backend text is data.** Every string the API returns — a job description,
  a tailored bullet, a confirmation message — is rendered as plain text. The
  ESLint config forbids `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`
  and `insertAdjacentHTML`, so the rule is enforced by the toolchain.
- **No optimistic UI.** A status is shown only after the API returned it. The
  approve, reject, status, search, tailor and refresh calls never update the
  screen before the server answers.
- **A human actor.** The Tracker records a human outcome as `human:<name>` and
  offers only the four statuses a human may set. It never sends an agent or
  system actor.
- **No silent failures.** 400, 404, 409, 413, 422, 429 (with its
  `Retry-After`), 503, a dead network and a client-side timeout each have
  their own message.
- **No secret.** The only configuration is the API base URL. The session is
  an `HttpOnly` cookie; the console never holds a token, and it sends the
  CSRF token as a header on every unsafe request (WS-15).

## Layout

```text
src/
  api/          the fetch wrapper, the typed endpoints, the generated schema
  components/   the shared components (the error surface, the status badge, ...)
  hooks/        the elapsed-time, motion and reveal hooks
  lib/          the status + observability vocabulary, the profile store, the safe accessors
  screens/      the public landing page and the console screens
  test/         the MSW server, the payload factories, the render helpers
scripts/        the reference inspection and browser verification passes
e2e/            the Playwright smoke path
```
