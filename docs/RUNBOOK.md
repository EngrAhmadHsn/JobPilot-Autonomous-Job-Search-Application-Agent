# The operator runbook

How to run, check and maintain a deployment of the Agentic Job
Application Agent.

**There is no development server in this document.** A development
server (`uvicorn --reload`, `APP_DEBUG=true`) is for a laptop; a
deployment runs behind a TLS-terminating reverse proxy, with the
configuration the code refuses to start without.

The names below are the ones the code uses. The full variable list is
in [`.env.example`](../.env.example), and every one of them is
machine-checked against the code by `tests/test_env_docs.py`.

---

## 1. What a deployment is

```text
                    ┌──────────────────────────┐
   browser ───────► │  reverse proxy (TLS)     │
                    │  nginx / caddy / …       │
                    └────────────┬─────────────┘
                                 │  http://127.0.0.1:8000
                    ┌────────────▼─────────────┐
                    │  uvicorn (the API)        │
                    │  --host 127.0.0.1        │
                    │  --port 8000             │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  data/ (SQLite, evidence, │
                    │  uploads, vectors, mail)  │
                    └──────────────────────────┘
```

Three things follow from that shape, and they are the ones to get
right:

1. **The API binds to the loopback.** The proxy is the only thing that
   talks to it, and the proxy is the only thing that terminates TLS.
   `AUTH_COOKIE_SECURE` is on, so a session cookie never crosses a
   plain-HTTP hop.
2. **`data/` is private.** It holds the resumes, the rendered DOCX
   files, the evidence screenshots, the vector store and the token
   mailbox. It is readable by the service account and by nobody else.
3. **`.env` is private.** It holds the identity secret and the provider
   keys. It is not in the repository, and it is not world-readable.

---

## 2. The first deployment

### 2.1 The environment file

```bash
cp .env.example .env
python -c "import secrets; print('AUTH_SECRET=' + secrets.token_urlsafe(48))"
```

Put the generated value in `.env`, and set at least:

| Variable | Why |
|---|---|
| `APP_ENV=production` | turns on the fail-fast rules |
| `CORS_ORIGINS` | the exact origins the console is served from — no wildcard |
| `AUTH_SECRET` | signs the password-reset and verification tokens (32+ characters) |
| `SUBMISSION_POLICY=REQUIRE_APPROVAL` | the decision that an application needs a human |
| `DATA_DIR` | where the private data lives |

Then lock the file down:

```bash
chmod 600 .env
chmod 700 data
```

### 2.2 The install

```bash
python -m venv env
env/Scripts/pip install -e .          # Windows
pip install -e .                       # elsewhere
python -m playwright install chromium
```

### 2.3 The migrations

```bash
python scripts/verify_migrations.py    # proves the chain applies and reverses
alembic upgrade head
```

Run the check **before** the upgrade. A migration that does not apply
is discovered here rather than during the deployment.

### 2.4 The first account

The API has no anonymous access. The first account registers through
`POST /api/auth/register`, and — unless `AUTH_CLAIM_LEGACY=false` — it
**claims the rows that pre-date the identity work**, so an existing
corpus reaches the operator's own account instead of being orphaned.

The claim is a one-time transfer: the second registration claims
nothing.

---

## 3. Running it

### 3.1 The API

```bash
uvicorn src.main:app --host 127.0.0.1 --port 8000 --workers 4
```

Behind a supervisor (systemd, a container's entrypoint, a process
manager). **No `--reload`**: the reloader is a development convenience
and a development convenience in production is a second, unsupervised
copy of the process.

### 3.2 The console

The console is a Vite/React application in `frontend/`. It is a static
bundle in production:

```bash
cd frontend && npm ci && npm run build
```

Serve the bundle from the same origin as the API, or from a second
origin listed in `CORS_ORIGINS`. The console keeps **no token in
JavaScript**: the session is an `HttpOnly` cookie, so a script that
gets injected cannot read it.

### 3.3 The proxy

```nginx
server {
    listen 443 ssl http2;
    server_name app.example.com;

    ssl_certificate     /etc/letsencrypt/live/app.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.example.com/privkey.pem;

    # The browser is told to speak HTTPS only.
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**`X-Forwarded-For` matters.** The API's rate limiter keys on the
transport peer, and without the forwarding header every request arrives
from the proxy — one bucket for the whole internet. The limiter is
configured to trust the proxy's address.

---

## 4. The daily work

### 4.1 Refreshing the corpus

```bash
python scripts/refresh_jobs.py
```

The refresh is bounded on purpose: a single board may not dictate the
size of the corpus, and the embedding spend is capped so a flood of fake
listings cannot spend the provider's whole daily quota.

### 4.2 The retention purge

```bash
python scripts/purge_expired.py --expired        # what is past its window
python scripts/purge_expired.py --deactivated    # the accounts that asked to go
python scripts/purge_expired.py --user <id>      # one account, now
python scripts/purge_expired.py --expired --dry-run
```

The purge is **idempotent** — running it twice changes nothing the
second time — so it is safe on a schedule and safe to retry after a
crash. Run it daily:

```cron
17 4 * * * cd /srv/agentic-job-applier && env/Scripts/python scripts/purge_expired.py --expired >> /var/log/purge.log 2>&1
```

The audit rows of a purged account are **anonymized, not deleted**. The
record of what happened survives; the identity does not.

### 4.3 The evaluation

```bash
python scripts/run_eval.py
```

The report covers ranking, factuality, the ATS score, the application
lifecycle and the browser metrics, against the thresholds in
`src/evaluation/thresholds.json`.

---

## 5. When something goes wrong

### 5.1 The API refuses to start

The message says which rule was broken. The rules are in
`src/config/settings.py`:

| Message | What to do |
|---|---|
| `APP_ENV=production requires an explicit CORS_ORIGINS` | list the origins the console is served from |
| `...forbids wildcard CORS origins` | remove the `*` |
| `...requires an explicit AUTH_SECRET` | generate one (see §2.1) |
| `AUTH_SECRET must be at least 32 characters` | generate a longer one |
| `...requires a Secure session cookie` | remove `AUTH_COOKIE_SECURE=false` |
| `...requires an explicit SUBMISSION_POLICY` | set it to `REQUIRE_APPROVAL` |
| `APP_ENV=production forbids APP_DEBUG=true` | unset it |
| `EMBEDDING_PROVIDER=gemini requires LLM_API_KEY` | set the key, or use the local provider |

### 5.2 A user cannot log in

1. Is the account active? A deletion request deactivates it at once
   (`GET /api/auth/me` returns 401 for a deactivated account).
2. Do they have a session? `GET /api/auth/sessions` lists the live
   sessions — and a password change ends every session but the one it
   was made from.
3. Is the console sending the CSRF header? The cookie transport
   refuses an unsafe request without `X-CSRF-Token`, and the answer is
   a 403 saying so.
4. Is the account verified, and does the deployment require it?
   `AUTH_REQUIRE_VERIFIED=true` refuses a login for an unverified
   account. The verification token is in the token mailbox
   (`data/outbound/`).

### 5.3 The audit trail says something odd

```bash
sqlite3 data/app.db "SELECT recorded_at, action, actor_kind, actor_id, resource, outcome
                     FROM audit_events ORDER BY id DESC LIMIT 50;"
```

The actor is a **principal**: `actor_kind` is `user`, `agent` or
`system`, and `actor_id` is the account id or the adapter's name. The
`actor` column is the human-readable label, derived from the two.

A control character in a stored string is impossible: every string that
reaches the store is stripped of the C0 range, so a newline cannot
forge a row.

### 5.4 A request is refused with a 429

The API's rate limiter keys on the transport peer. Behind a proxy, that
is the proxy — so check that `X-Forwarded-For` is set. The response
carries `Retry-After` and `X-RateLimit-Remaining`.

---

## 6. The checks to run before a release

```bash
ruff check src tests scripts          # the linter
pytest tests -q                       # the whole suite
python scripts/verify_migrations.py   # the migration chain
python scripts/audit_dependencies.py  # the dependency audit
```

All four run in CI on every push. The isolation matrix is part of the
suite, so a release that breaks tenant isolation does not go green.
