# WS-01 · Data Foundation

Status: **Done** (2026-10-11) · Milestone: **M1** · Depends on: nothing · Blocks: 02, 03, 04, 06, 07

## Goal

Turn the ad-hoc data layer into a production-grade foundation: versioned schema migrations,
a complete settings surface for everything the later workstreams need, and the missing
application-shell wiring (CORS middleware, DB session dependency). No business-logic changes.

## Current state

- `src/config/settings.py` — plain-class settings loaded from `.env` via python-dotenv. Missing every setting the new workstreams need (sources, policy, embedding, evidence dir).
- `src/db/session.py` — `create_engine(settings.database_url)` with default `sqlite:///./app.db`; `SessionLocal` exists but there is no FastAPI dependency and no per-request lifecycle.
- `src/db/jobs.py` (`JobDB`), `src/db/evidence.py` (`ApplicationEvidence`) — the only two ORM models. Tables exist in `app.db` but were created ad hoc: **alembic is a declared dependency (`alembic>=1.16.0`) with zero migrations**.
- `src/main.py` — includes `health` + `applications` routers; `settings.cors_origins` is parsed but `CORSMiddleware` is **never added**.
- `src/db/base.py` — `Base = declarative_base()` equivalent; nothing else.

## Concrete tasks

### 1. Alembic initialization

- Run `alembic init migrations` at repo root.
- `alembic.ini`: `script_location = migrations`; **do not** put the DB URL in the file — read it from settings.
- `migrations/env.py`:
  - import `src.db.base.Base` and set `target_metadata = Base.metadata`;
  - build the URL from `src.config.settings.get_settings().database_url` for both online and offline modes;
  - ensure `src.db.jobs`, `src.db.evidence` (and later model modules) are imported so autogenerate sees them.
- Generate the initial revision: `alembic revision --autogenerate -m "initial schema"` covering `jobs` and `application_evidence` exactly as the current models define them.
- Keep `Base.metadata.create_all()` **for the test suite only** (fast tmp-file SQLite); Alembic is authoritative everywhere else.

### 2. Per-workstream migration policy

Each later workstream adds **its own** revision(s) rather than one big-bang schema:

| Workstream | Tables it adds |
|---|---|
| 04 | `candidate_profiles`, `job_matches` |
| 05 | `tailored_resumes` |
| 06 | `approval_requests`, `audit_events` |
| 07 | `applications`, `application_events` |

This keeps reviews small and makes rollback per feature possible.

### 3. Settings additions (`src/config/settings.py`)

```python
# Job sources (02)
self.greenhouse_boards = [b.strip() for b in os.getenv("GREENHOUSE_BOARDS", "").split(",") if b.strip()]
self.lever_companies  = [c.strip() for c in os.getenv("LEVER_COMPANIES", "").split(",") if c.strip()]
self.job_source_timeout = float(os.getenv("JOB_SOURCE_TIMEOUT", "15"))
self.job_source_min_interval = float(os.getenv("JOB_SOURCE_MIN_INTERVAL", "1.0"))  # seconds/host

# Matching / embeddings (03)
self.embedding_model = os.getenv("EMBEDDING_MODEL", "gemini-embedding-2")
self.embedding_dimensionality = int(os.getenv("EMBEDDING_DIMENSIONALITY", "768"))
self.chroma_dir = os.getenv("CHROMA_DIR", "./data/chroma")

# Submission policy (06)
self.submission_policy = os.getenv("SUBMISSION_POLICY", "REQUIRE_APPROVAL")
self.allowed_domains = [d.strip() for d in os.getenv("ALLOWED_DOMAINS", "greenhouse.io,lever.co,workday.com,ashbyhq.com,smartrecruiters.com,icims.com").split(",") if d.strip()]

# Evidence / data locations (05, 06, 08)
self.data_dir = os.getenv("DATA_DIR", "./data")
self.evidence_dir = os.getenv("EVIDENCE_DIR", "./data/evidence")
self.resume_upload_dir = os.getenv("RESUME_UPLOAD_DIR", "./data/resumes")
```

- Also derive `data/evidence`, `data/resumes`, `data/chroma` lazily via a small `ensure_dir()` helper called by the owning module (not at import time).
- `.env.example` updates themselves are workstream 11, but add the variables here as they land.

### 4. CORS middleware (`src/main.py`)

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)
```

Note: `settings.cors_origins` already exists and is currently unused — this closes that gap. No wildcard origins in production (`APP_ENV=production` must assert `cors_origins != ["*"]` at startup).

### 5. DB session as a FastAPI dependency (`src/db/session.py`)

```python
def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

Routers then use `db: Session = Depends(get_db)` instead of opening sessions inline (the existing inline `SessionLocal()` use inside `submit_node` stays — it is deliberately non-blocking fallback logic, documented in 06).

### 6. Data directories in `.gitignore`

`data/` (SQLite dev DB already at root stays until 01 lands; after that point `DATABASE_URL` at `sqlite:///./data/app.db` so all state lives under one gitignored tree).

## Acceptance criteria

- [ ] `alembic upgrade head` on a fresh SQLite file creates `jobs` + `application_evidence`; `alembic downgrade base` removes them.
- [ ] `alembic upgrade head` succeeds against a PostgreSQL URL (CI or local container); JSON columns render as portable `JSON` in both dialects.
- [ ] `curl -i http://localhost:8000/health` shows `access-control-allow-origin` for an origin in `CORS_ORIGINS`, and no CORS header for a foreign origin.
- [ ] All existing 68 tests still pass; test suite does not require network or a running Postgres.
- [ ] Startup fails fast (clear error) when `APP_ENV=production` and `CORS_ORIGINS` is unset/`*`.

## Tests

- `tests/test_migrations.py` — run `alembic upgrade head` / `downgrade base` against a tmp SQLite path (subprocess or `alembic.command` API); assert tables exist via inspector.
- `tests/test_health.py` (extend) — assert CORS headers present/absent.
- `tests/test_settings.py` (new) — new settings parse defaults correctly; comma-split lists handle empty strings.

## New dependencies

None.
