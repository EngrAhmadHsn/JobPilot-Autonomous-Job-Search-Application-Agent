# Running JobPilot locally

Two processes: the **API** and the **console**. Start the API first, then the
console. Commands are for Windows (`cmd`/PowerShell); the repository root is
`E:\Study\Supporting Study\Job Agents\Agentic Job Applier`.

## Terminal 1 — the API

```
cd /d "E:\Study\Supporting Study\Job Agents\Agentic Job Applier"
env\Scripts\python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

- Health check: <http://127.0.0.1:8000/api/health>
- Interactive docs (development only): <http://127.0.0.1:8000/docs>
- The database is `app.db` at the repository root.

## Terminal 2 — the console

```
cd /d "E:\Study\Supporting Study\Job Agents\Agentic Job Applier\frontend"
npm run dev
```

Open <http://localhost:5173>.

| URL | What it is |
| --- | --- |
| `http://localhost:5173/` | the public landing page (no session needed) |
| `http://localhost:5173/sign-in` | sign in / create an account |
| `http://localhost:5173/app` | the console — Overview |
| `http://localhost:5173/app/activity` | agent activity (the audit trail) |
| `http://localhost:5173/app/admin` | administration (administrators only) |

The dev server proxies `/api` to `http://127.0.0.1:8000`, which is why the API
must be running first.

**Login:** `operator@example.com` / `operator-local-password`
(see `DEV_CREDENTIALS.local.md`, which is generated locally and git-ignored).

## The production build (what the e2e suite tests)

```
cd /d "E:\Study\Supporting Study\Job Agents\Agentic Job Applier\frontend"
npm run build
npm run preview
```

Open <http://localhost:4173> — use `localhost`, **not** `127.0.0.1`: the preview
server binds IPv6 localhost only.

## Optional — the controlled submission target

The approval step really fills and submits a form, to a local fake ATS. Start a
third terminal at the repository root:

```
cd /d "E:\Study\Supporting Study\Job Agents\Agentic Job Applier"
env\Scripts\python.exe scripts\serve_fake_ats.py
```

That serves <http://127.0.0.1:8901>. Without it, approval succeeds up to the
submission step and the evidence reports the target as unreachable.

## First run on a fresh checkout

```
cd /d "E:\Study\Supporting Study\Job Agents\Agentic Job Applier"
env\Scripts\python.exe -m alembic upgrade head      # the schema must be current
env\Scripts\python.exe -m pip install -e .          # if the venv is new

cd frontend
npm install
```

## Tests

Python (from the repository root):

```
env\Scripts\python.exe -m pytest -q -m "not browser"
env\Scripts\python.exe -m ruff check src tests scripts
```

Frontend (from `frontend/`):

```
npm run typecheck
npm run lint
npm test
npm run e2e        # needs the API and the fake ATS running
```

## Motion, and why the page can look static

The landing page follows the OS `prefers-reduced-motion` setting by default.
On Windows that setting is "Animation effects"; when it is off, **every**
browser reports reduced motion and the app quiets down (the pointer light field
off, entrances fade instead of rising, the demo walkthrough still advances).

You do not have to change the OS:

- **Landing page:** the **Motion** control in the header (and footer) —
  `System` / `Full` / `Reduced`.
- **Console:** account menu → **Motion**.

`Full` plays everything; `System` follows the OS; `Reduced` stops all movement.
The choice is stored per browser.

`frontend/scripts/diagnose-motion.mjs` and `diagnose-reduced-motion.mjs` report
what the running app is actually doing.

## Remote / alternate API

Set `VITE_API_BASE_URL` (in `frontend/.env.local`) to point the console at a
different API; leave it empty to use the dev proxy.