# WS-07 · Application Tracking Lifecycle

Status: **Done** (2026-10-21) · Milestone: **M3** · Depends on: [01](01-data-foundation.md), [06](06-security-preconditions.md) · Blocks: M5 pilot, [09](09-evaluation.md) (intervention-rate metrics)

## Goal

Implement plan §27 / Phase 12: a durable application lifecycle with every transition recorded
as an event — the tracking half of "verify → track" that today exists only as an evidence row.

## Current state

- `ApplicationEvidence` (`src/db/evidence.py`) records submissions — good, stays.
- **No `Application` entity**: nothing persists *which* job/candidate/resume-version an
  evidence row belongs to beyond a free-form `job_url`; no status machine
  (`DISCOVERED → … → VERIFIED`), no `ApplicationEvent` history, no tracking API.
- The workflow (`src/graph/nodes.py`) updates only in-memory state; a restart loses everything
  except evidence rows.

## Concrete tasks

### 1. Models + migration

`src/db/applications.py` (new; Alembic revision per WS-01 policy):

```python
class ApplicationDB(Base):
    __tablename__ = "applications"
    id: str            # uuid4 hex, PK
    profile_id: str    # FK candidate_profiles
    job_id: str        # FK jobs (normalized listing id)
    workflow_id: str   # index
    status: str        # ApplicationStatus value, index
    tailored_resume_id: str | None   # set when M2 tailoring is wired in
    submitted_at: datetime | None
    verified_at: datetime | None
    application_url: str | None
    notes: str | None
    created_at / updated_at

class ApplicationEventDB(Base):
    __tablename__ = "application_events"
    id: int (PK, autoincrement — append-only ordering)
    application_id: str (FK, index)
    event_type: str    # status_transition | evidence_recorded | approval_granted | ...
    actor: str         # "agent" | "human:<who>" | "system"
    from_status / to_status: str | None
    metadata: JSON (sanitized via src/security/audit.sanitize_metadata)
    recorded_at: datetime
```

### 2. Status machine — `src/applications/tracking.py`

```python
class ApplicationStatus(str, Enum):
    DISCOVERED, MATCHED, SHORTLISTED, PREPARED, AWAITING_APPROVAL,
    SUBMITTED, VERIFIED, REJECTED, INTERVIEW, OFFER, WITHDRAWN

ALLOWED_TRANSITIONS = {
    DISCOVERED: {MATCHED, REJECTED},
    MATCHED: {SHORTLISTED, DISCOVERED},
    SHORTLISTED: {PREPARED, MATCHED},
    PREPARED: {AWAITING_APPROVAL, SHORTLISTED},
    AWAITING_APPROVAL: {SUBMITTED, REJECTED, PREPARED},   # REJECTED = declined at gate
    SUBMITTED: {VERIFIED, AWAITING_APPROVAL},             # back = verification failed
    VERIFIED: {INTERVIEW, OFFER, REJECTED, WITHDRAWN},    # human-outcome driven
    INTERVIEW: {OFFER, REJECTED, WITHDRAWN},
    ...
}

def transition(app: ApplicationDB, to: ApplicationStatus, *, actor: str,
               db: Session, metadata: dict | None = None) -> ApplicationDB
    # illegal move -> IllegalTransitionError; legal move -> update row + append
    # ApplicationEvent + record_audit(action="application.transition")
```

Terminal-outcome statuses (`INTERVIEW`, `OFFER`, `REJECTED`, `WITHDRAWN`) are only settable by
a human actor — the agent never invents outcomes (project rule: never fabricate outcomes).

### 3. Workflow wiring

- `prepare_node` (extend `src/graph/nodes.py`): create/transition `Application` to `PREPARED` → `AWAITING_APPROVAL` when the approval request is created.
- `submit_node`: → `SUBMITTED` (+ `submitted_at`), and attach the created `ApplicationEvidence.id` as an event.
- `verify_node`: → `VERIFIED` (+ `verified_at`) on success; on failure → back to `AWAITING_APPROVAL` with `event_type="verification_failed"` metadata carrying the failure reason.
- Rejection at the gate (WS-06 approve/reject): → `REJECTED` with `actor="human:<approver>"`.
- `job_id` comes from the normalized listing (WS-04 persistence); where the submit API is called with a raw URL (fake-ATS tests), a `JobListing` stub row is created with `source="manual"` so the FK always resolves.

### 4. Tracking API — `src/api/routes/tracking.py`

- `GET /api/applications` — list with status filter + pagination.
- `GET /api/applications/{id}` — detail incl. full event history (ordered by id).
- `PATCH /api/applications/{id}/status` `{status, actor, notes?}` — human outcome updates (`INTERVIEW`/`OFFER`/`REJECTED`/`WITHDRAWN`); server rejects illegal transitions and non-human-actor claims on terminal outcomes.

## Acceptance criteria

- [x] A full fake-ATS run produces an `Application` row traversing
      `PREPARED → AWAITING_APPROVAL → SUBMITTED → VERIFIED` with one `ApplicationEvent` per
      transition plus `evidence_recorded`, queryable via the API after restart.
- [x] Illegal transitions are rejected (unit matrix over `ALLOWED_TRANSITIONS`).
- [x] Agent cannot set `OFFER`/`INTERVIEW` (actor enforcement test).
- [x] Evidence rows are linked to applications (no more orphan `job_url`-only records).
- [x] Event history is append-only: no code path updates or deletes `application_events`.

## Tests

- `tests/test_tracking.py` — transition legality matrix, actor enforcement, event append ordering, timestamps.
- `tests/test_tracking_api.py` — list/filter/detail/PATCH; 404s; illegal PATCH → 409.
- `tests/test_application_workflow.py` (extend) — DB rows asserted after prepare/approve/submit/verify (complements existing in-memory state assertions).

## New dependencies

None.

---

# Part 2 — Detailed specification (added 2026-10-21)

## S0. Scope, invariants, non-goals

**Goal.** Give the agent a *durable* application lifecycle: one row per
application, one append-only event per state change, and a read/annotate API —
so that "which job, which candidate, which resume version, what happened, who
did it" survives a restart and is queryable.

### Invariants (binding)

| # | Invariant | Enforced by |
|---|---|---|
| I1 | Every state change writes **exactly one** `application_events` row, with `from_status`, `to_status` and an `actor`. | `transition()` in `src/applications/tracking.py` |
| I2 | `application_events` is **append-only**: no code path updates or deletes a row. | no update/delete helper exists; proven by a source-level test (Phase G) |
| I3 | A **human outcome** (`INTERVIEW`, `OFFER`, `REJECTED`, `WITHDRAWN`) may only be set by a human actor. The agent never invents an outcome. | `ActorNotPermittedError` in `transition()`; the API refuses a non-human actor with 403 |
| I4 | An illegal transition changes **nothing**: no row mutation, no event, no audit entry. | `IllegalTransitionError` raised before any write |
| I5 | Event metadata is sanitized like every other audit payload (no secrets, masked PII, truncated strings). | `src.security.redaction.sanitize_metadata` |
| I6 | A failed submission is never recorded as `SUBMITTED`; a failed verification is never recorded as `VERIFIED`. | the nodes only transition on the *successful* branch; a failure is an event, not a state |
| I7 | The history of an application is ordered by the event id (append order), never by a mutable timestamp. | autoincrement `id` primary key on `application_events` |
| I8 | The agent does **not** fabricate history: a state that never happened is never written. | the application is created directly in `PREPARED`; `DISCOVERED`/`MATCHED`/`SHORTLISTED` are reachable in the machine but not walked today (see D3) |

### Non-goals

- **No** tracking of applications that were never prepared. The row is created
  by the prepare step, which is the first moment the agent acts on a job.
- **No** outcome prediction, scoring or ranking of applications.
- **No** automatic outcome detection. `INTERVIEW`/`OFFER`/`REJECTED`/`WITHDRAWN`
  are recorded by a human; the agent never infers them from a page.
- **No** auth. The API trusts the caller the same way the WS-06 approval API
  does (an `approver` string). The actor format is the *record* of who acted,
  not an authentication mechanism — stated plainly here so it is not
  mistaken for one later.
- **No** deletion endpoint. An application and its history are not deletable
  through the API; SEC-15 (retention) is still open (see Part 5).

## S1. Data model — `src/db/applications.py` (new)

Two tables. JSON columns are portable `sa.JSON()` (SQLite and PostgreSQL),
matching the WS-01/WS-04/WS-05/WS-06 convention.

### `applications` — one row per application

| Column | Type | Notes |
|---|---|---|
| `id` | `String` PK | `uuid4().hex[:12]` — the same id shape as profiles/tailoring/approvals |
| `profile_id` | `String` nullable, indexed | the candidate profile this application belongs to; **nullable** (see D2) |
| `job_id` | `String` indexed | the normalized listing id (always resolves — see S1.2) |
| `workflow_id` | `String` indexed | the application-workflow id this application belongs to |
| `approval_id` | `String` nullable, indexed | the WS-06 approval request that gates it |
| `adapter_name` | `String` | the adapter that prepared it (`fake-ats-playwright`, ...) |
| `job_url` | `String` | the posting the application targets |
| `job_title`, `company_name` | `String` | denormalized for a readable list/detail without a join |
| `status` | `String` indexed | an `ApplicationStatus` value |
| `tailored_resume_id` | `String` nullable | the WS-05 tailoring this application used |
| `submitted_at` | `DateTime` nullable | set on the transition into `SUBMITTED` |
| `verified_at` | `DateTime` nullable | set on the transition into `VERIFIED` |
| `application_url` | `String` nullable | the URL the submission landed on (from the evidence) |
| `notes` | `String` nullable | a free-text note set by a human through the API |
| `created_at`, `updated_at` | `DateTime` | `updated_at` moves on every state change |

### `application_events` — the append-only history

| Column | Type | Notes |
|---|---|---|
| `id` | `Integer` PK, autoincrement | **the ordering** (I7) |
| `application_id` | `String` indexed | the application this event belongs to |
| `event_type` | `String` indexed | see S1.1 |
| `actor` | `String` indexed | `agent` \| `system` \| `human:<who>` (see S2.2) |
| `from_status`, `to_status` | `String` nullable | the state change (both `None` for a pure event) |
| `metadata` | `JSON` nullable | sanitized (I5) |
| `recorded_at` | `DateTime` indexed | when it was written |

`metadata` is a reserved attribute name on SQLAlchemy declarative classes, so
the attribute is `extra_metadata` mapped to the column `metadata` — the same
pattern as `src.db.jobs` and `src.db.evidence`.

### S1.1 Event types

| `event_type` | When | State change? |
|---|---|---|
| `application_created` | the application row is created | yes (`None` → `PREPARED`) |
| `status_transition` | the default for any other state change | yes |
| `approval_granted` | a human approved the request (WS-06 `/approve`) | no — the application stays `AWAITING_APPROVAL` until the agent submits |
| `approval_rejected` | a human declined at the gate (WS-06 `/reject`) | yes (`AWAITING_APPROVAL` → `REJECTED`) |
| `evidence_recorded` | the submission's evidence row was written | no |
| `verification_failed` | the submission was not verified | yes (`SUBMITTED` → `AWAITING_APPROVAL`) |

**One state change produces exactly one event row** (I1). `approval_rejected`
and `verification_failed` are *specializations* of a transition, not extra
rows: the event type describes what happened, and the row still carries
`from_status`/`to_status`. The `status_transition` type is used for every
other move.

### S1.2 The `job_id` always resolves

`job_id` points at a row of the `jobs` table (created by WS-04). The prepare
API is called with a **raw URL** that may have no stored listing behind it, so
`ensure_job_row()` resolves it:

1. look for an existing `JobDB` row with `application_url == job_url` → use its
   id;
2. otherwise create a **stub** listing: `id = "manual:" + sha256(job_url)[:16]`,
   `source = "manual"`, `title`/`company` from the request, `application_url`
   = the job URL.

The stub id is derived from the URL, so preparing the same posting twice
resolves to the same job row instead of creating a second one. The stub is a
*listing placeholder*, not a claim that the job exists on a board: it records
the URL the agent acted on. The `jobs` table is unchanged by this workstream —
no new migration for it.

### S1.3 Evidence linkage — `src/db/evidence.py`

`ApplicationEvidence` gains a nullable, indexed `application_id` column. The
evidence row written by the submit node now names the application it belongs
to, so an evidence row is no longer an orphan identified only by a free-form
`job_url` (acceptance criterion 4). Existing rows keep `NULL` — the column is
additive and nullable, so the WS-06 evidence history stays readable.

## S2. The status machine — `src/applications/tracking.py` (new)

### S2.1 The statuses and the transition matrix

```python
class ApplicationStatus(str, Enum):
    DISCOVERED = "discovered"
    MATCHED = "matched"
    SHORTLISTED = "shortlisted"
    PREPARED = "prepared"
    AWAITING_APPROVAL = "awaiting_approval"
    SUBMITTED = "submitted"
    VERIFIED = "verified"
    REJECTED = "rejected"
    INTERVIEW = "interview"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"
```

`ALLOWED_TRANSITIONS` (the matrix from the Part 1 brief, completed for every
status — the brief left the tail as "..."):

| From | To |
|---|---|
| `DISCOVERED` | `MATCHED`, `REJECTED` |
| `MATCHED` | `SHORTLISTED`, `DISCOVERED` |
| `SHORTLISTED` | `PREPARED`, `MATCHED` |
| `PREPARED` | `AWAITING_APPROVAL`, `SHORTLISTED` |
| `AWAITING_APPROVAL` | `SUBMITTED`, `REJECTED`, `PREPARED` |
| `SUBMITTED` | `VERIFIED`, `AWAITING_APPROVAL` |
| `VERIFIED` | `INTERVIEW`, `OFFER`, `REJECTED`, `WITHDRAWN` |
| `INTERVIEW` | `OFFER`, `REJECTED`, `WITHDRAWN` |
| `OFFER` | `REJECTED`, `WITHDRAWN` |
| `REJECTED` | — (terminal) |
| `WITHDRAWN` | — (terminal) |

A self-transition is **not** a transition: `X → X` is illegal everywhere. The
matrix is the single source of truth — the API, the graph and the tests all
read it, so the rules cannot drift apart.

### S2.2 Actors

```python
AGENT_ACTOR = "agent"
SYSTEM_ACTOR = "system"
HUMAN_ACTOR_PREFIX = "human:"
```

- `is_human_actor(actor)` → the actor starts with `human:` and names someone.
- `human_actor(name)` → normalizes a free-form operator name into
  `human:<name>` (idempotent). Used at the **human** boundaries: the WS-06
  approve/reject routes and the tracking PATCH.
- The agent's own actor is the literal `agent`; the platform's is `system`.
  Neither can be confused with a human identity.

**I3 — human outcomes.** `HUMAN_OUTCOME_STATUSES = {INTERVIEW, OFFER,
REJECTED, WITHDRAWN}`. A transition into one of them requires a human actor;
otherwise `ActorNotPermittedError`. The agent physically cannot record an
outcome it did not observe.

**Why the `human:` prefix matters.** The actor string is the *record* of who
acted. Without a reserved prefix, `actor="agent"` and `actor="ada"` would be
indistinguishable, and I3 would be unenforceable. The prefix makes the
distinction explicit and machine-checkable.

### S2.3 `transition()`

```python
def transition(
    app: ApplicationDB,
    to: ApplicationStatus,
    *,
    actor: str,
    db: Session,
    metadata: dict | None = None,
    event_type: str = EVENT_STATUS_TRANSITION,
) -> ApplicationDB
```

Order of operations (I4 — nothing is written when the move is illegal):

1. validate the actor: `to` in `HUMAN_OUTCOME_STATUSES` and not a human actor
   → `ActorNotPermittedError`;
2. validate the move: `to` not in `ALLOWED_TRANSITIONS[current]` →
   `IllegalTransitionError`;
3. mutate the row: `status`, `updated_at`, plus `submitted_at` (into
   `SUBMITTED`) / `verified_at` (into `VERIFIED`) / `application_url` (passed
   in metadata) ;
4. append the event row (I1, I2, I5);
5. `record_audit("application.transition", ...)` with the same session;
6. `db.commit()`.

Errors:

| Error | Base | Meaning |
|---|---|---|
| `TrackingError` | `Exception` | base of the two below |
| `IllegalTransitionError` | `TrackingError` | the move is not in the matrix |
| `ActorNotPermittedError` | `TrackingError` | a non-human actor tried to set a human outcome |

### S2.4 `record_event()`

```python
def record_event(db, application_id, event_type, *, actor, from_status=None, to_status=None, metadata=None) -> ApplicationEventDB
```

The append-only write used for the events that are *not* state changes
(`approval_granted`, `evidence_recorded`). It never touches the application
row.

## S3. Graph and executor wiring

### S3.1 State — `src/graph/state.py`

`ApplicationWorkflowState` gains `application_id: str | None = None` — the
tracking row this run belongs to. It is a plain string, so the state stays
serializable for the LangGraph checkpointer (a `Session` would not be).

### S3.2 Nodes — `src/graph/nodes.py`

The nodes receive an optional `session`. When it is `None` the node behaves
exactly as it does today (no tracking writes) — the graph stays usable in
tests that have no database, and the WS-06 behaviour is unchanged.

**`submit_node`**
1. the existing permission check (unchanged);
2. `adapter.submit(...)` → `result`;
3. **tracking**: if the submission **succeeded** and an application row was
   found → `transition(app, SUBMITTED, actor="agent")` (sets `submitted_at`).
   If the submission **failed** → the application stays where it is and an
   `evidence_recorded`/failure event records what happened. A failed
   submission is never `SUBMITTED` (I6);
4. the evidence row is written with `application_id` set (S1.3). The evidence
   write keeps its "never blocks the submission" behaviour; it now uses the
   injected session when there is one, and falls back to `SessionLocal()`
   otherwise (the WS-06 documented fallback);
5. `record_event(..., EVENT_EVIDENCE_RECORDED, actor="agent",
   metadata={"evidence_id": ..., "status": ...})`.

**`verify_node`**
1. the existing permission check (unchanged);
2. `adapter.verify(...)` → `verified_result`; the existing evidence-existence
   downgrade (SEC-14) is unchanged;
3. **tracking**: on success → `transition(app, VERIFIED, actor="agent")`
   (sets `verified_at`); on failure → `transition(app, AWAITING_APPROVAL,
   actor="agent", event_type=EVENT_VERIFICATION_FAILED, metadata={"reason":
   ...})` — the move back is legal (`SUBMITTED → AWAITING_APPROVAL`) and the
   failure reason travels with it.

**Lookup.** The nodes find the application by `state.application_id`, then by
`state.approval_id`, then by `state.workflow_id`. If no application row
exists (the graph was run outside the API), the nodes simply do not write
tracking rows — no error, no fabricated row.

### S3.3 Executor — `src/graph/executor.py`

`execute_approved()` gains an optional `session: Session | None = None` and
passes it to `build_application_workflow(adapter, session=session)`. When it
is `None`, the graph behaves as today.

### S3.4 The prepare / approve / reject routes — `src/api/routes/applications.py`

**`POST /api/applications/prepare`**
1. the allowlist check, the adapter selection and the payload build are
   unchanged;
2. the approval request row is written (unchanged);
3. **tracking**: the application row is created in `PREPARED`
   (`application_created` event), then
   `transition(app, AWAITING_APPROVAL, actor="agent")`. The application is
   created *already prepared* — the system never matched or shortlisted
   anything, so those states are not written (I8, D3);
4. the response gains `application_id`.

**`POST /api/applications/{approval_id}/approve`**
1. the decision is recorded on the approval row (unchanged);
2. **tracking**: `record_event(..., EVENT_APPROVAL_GRANTED, actor=human_actor(req.approver),
   metadata={"reason": ...})` — the decision is an event, not a state change
   (the application is still `AWAITING_APPROVAL` until the agent submits);
3. the execution runs with the request-scoped session, so the submit/verify
   transitions land in the same transaction as everything else.

**`POST /api/applications/{approval_id}/reject`**
1. the decision is recorded on the approval row (unchanged);
2. **tracking**: `transition(app, REJECTED, actor=human_actor(req.approver),
   event_type=EVENT_APPROVAL_REJECTED, metadata={"reason": ...})` — a decline
   at the gate is a human outcome, so the actor is a human identity.

**Route shape change.** `GET /api/applications/{approval_id}` (the WS-06
approval-status endpoint) moves to `GET /api/applications/approvals/{approval_id}`,
because `GET /api/applications/{id}` is now the **tracking** detail (the
Part 1 brief's §4). Two different resources cannot share one path shape; the
approval record keeps its own path, and `scripts/verify_ws06.py` and
`tests/test_submit_api.py` are updated accordingly (D1).

## S4. Tracking API — `src/api/routes/tracking.py` (new)

Router prefix `/api/applications`, registered **after** the WS-06 router.

### `GET /api/applications` — list

Query parameters: `status` (repeatable — `?status=submitted&status=verified`),
`profile_id`, `limit` (default 50, max 200), `offset` (default 0).

Response: `{"items": [...], "total": N, "limit": L, "offset": O}`.

An unknown `status` value → **400** (not 422 — the value is a domain value,
not a schema violation). Ordering: `created_at DESC, id DESC` (newest first).

### `GET /api/applications/{application_id}` — detail

The application row plus its **full event history**, ordered by event id
(I7). Unknown id → **404**.

### `PATCH /api/applications/{application_id}/status` — human outcome

Body: `{"status": "interview", "actor": "human:ada", "notes": "..."}`.

| Situation | Response |
|---|---|
| unknown application | 404 |
| unknown `status` value | 400 |
| illegal transition | **409** |
| a human outcome with a non-human actor | **403** |
| legal | 200 + the updated application (with its history) |

The `notes` are stored on the row. The endpoint never invents a transition: the
matrix decides.

## S5. The audit trail

Two new actions in `src/security/audit.py`:

| Action | When |
|---|---|
| `application.transition` | every state change (the `from`/`to` pair and the reason) |
| `application.event` | every non-transition event |

Both are written with the same session as the state change, so the audit
trail and the event log cannot disagree about what happened.

## S6. Test matrix (all offline, no network)

| File | Covers |
|---|---|
| `tests/test_tracking.py` (new) | the transition matrix (every legal and every illegal pair), the actor rule (the agent cannot set a human outcome; a human can), `transition()` side effects (row, event, audit, timestamps), `record_event()`, the append-only shape, the job resolution (existing row, stub row, idempotence), the event ordering |
| `tests/test_tracking_api.py` (new) | the list (filter, pagination, total, ordering), the detail (history included and ordered), the PATCH (legal, illegal → 409, non-human actor on a human outcome → 403, unknown id → 404, unknown status → 400), the 404 paths |
| `tests/test_application_workflow.py` (extended) | the DB rows after prepare/approve/submit/verify: the `Application` row, one event per transition, `evidence_recorded`, the evidence row carrying `application_id` |
| `tests/test_approval_flow.py` (extended) | the approve/reject transitions with a human actor; the agent actor refused for a human outcome |
| `tests/test_submit_api.py` (extended) | the moved approval endpoint; the `application_id` in the prepare response; the tracking detail over HTTP |
| `tests/test_migrations.py` (extended) | the `applications` + `application_events` columns and indexes at head, the reversible downgrade, the portable JSON on SQLite and PostgreSQL, the new `application_evidence.application_id` |
| `tests/test_audit.py` (extended) | the two new actions appear in the trail |
| `tests/test_tracking_append_only.py` (new, or a case in `test_tracking.py`) | the source-level proof that no code path updates or deletes an `application_events` row |

---

# Part 3 — Execution plan (added 2026-10-21)

## S7. Execution plan (phases A–H)

Each phase: implement → its own tests → the full offline suite → `ruff check`.
Nothing is committed until the phase's tests are green.

- **Phase A — Models + migration.** `src/db/applications.py`; the
  `application_id` column on `ApplicationEvidence`; the Alembic revision
  (`applications`, `application_events`, the evidence column); the
  `migrations/env.py` import. Tests: `tests/test_migrations.py` (extended).
  *Gate:* the revision upgrades and downgrades cleanly on SQLite and renders
  portable DDL for PostgreSQL; the new tables have the documented columns and
  indexes.
- **Phase B — The status machine.** `src/applications/tracking.py`: the
  statuses, the matrix, the actors, the errors, `transition()`,
  `record_event()`, `find_application()`, `ensure_job_row()`,
  `create_application()`. Tests: `tests/test_tracking.py`.
  *Gate:* the full legal/illegal matrix behaves; the agent cannot set a human
  outcome; an illegal move writes nothing.
- **Phase C — Audit wiring.** The two new actions in `src/security/audit.py`.
  Tests: `tests/test_audit.py` (extended).
  *Gate:* every transition and every event appears in the audit trail with a
  sanitized payload.
- **Phase D — Graph + executor.** `src/graph/state.py` (`application_id`),
  `src/graph/nodes.py` (submit/verify transitions + the evidence link),
  `src/graph/application_workflow.py` (`session` seam),
  `src/graph/executor.py` (`session` parameter). Tests:
  `tests/test_application_workflow.py` (extended).
  *Gate:* a full run leaves an `Application` in `VERIFIED` with one event per
  transition; a failed submission leaves it in `AWAITING_APPROVAL`; the graph
  still works with no database at all.
- **Phase E — The application routes.** `src/api/routes/applications.py`:
  prepare creates the application, approve records the decision, reject
  transitions to `REJECTED`; the approval-status route moves to
  `/api/applications/approvals/{id}`. Tests: `tests/test_submit_api.py`,
  `tests/test_approval_flow.py` (extended).
  *Gate:* the prepare response carries an `application_id`; the decline is
  attributed to a human; the moved endpoint still answers.
- **Phase F — The tracking API.** `src/api/routes/tracking.py`; the router
  registration in `src/main.py`. Tests: `tests/test_tracking_api.py`.
  *Gate:* the list filters and paginates; the detail returns the ordered
  history; an illegal PATCH is 409; a non-human actor on a human outcome is
  403.
- **Phase G — Append-only proof + evidence linkage + docs.** The source-level
  append-only test; the evidence-linkage test; the `00-OVERVIEW.md` status
  and feature-gap table; this document's status part.
  *Gate:* the full suite green offline; `ruff check` clean; the append-only
  test fails if anyone adds an update/delete of an event.
- **Phase H — Live verification.** `scripts/verify_ws07.py`: a real HTTP
  server, a real prepare → approve → submit → verify against the local fake
  ATS, the database inspected directly, and a **restart** of the server to
  prove the history survives.
  *Gate:* every check prints PASS and the script exits 0.

**Ordering rationale.** A before B (the machine writes to the tables). B
before C (the audit action names describe the events). C before D (the nodes
write audit events as they transition). D before E (the routes create the
application the nodes then advance). E before F (the tracking API serves the
rows the routes create). G after F (the append-only proof covers the whole
tracking surface). H is last because it asserts the finished behaviour over
real HTTP.

**Risk register for this workstream**

| Risk | Mitigation |
|---|---|
| The tracking writes break the submission path | every tracking write is wrapped so a tracking failure is logged, never raised — a missing history must not cost a submission (the same rule the evidence write already follows) |
| The two `/api/applications/{id}` resources collide | the approval status route moves to `/api/applications/approvals/{id}`; the WS-06 script and tests are updated in the same phase |
| A second session in the nodes sees a stale row | the nodes use the **injected** request-scoped session; the `SessionLocal()` fallback is only used when no session was injected (and it is documented as the WS-06 fallback) |
| The agent fabricates an outcome | the actor rule refuses a non-human actor for every human outcome, and the agent's own actor is the literal `agent` |
| A crash between the state change and the event | both are written in one session and one commit — the event and the row cannot disagree |
| The event log grows without bound | SEC-15 (retention) is still open; it is recorded in the follow-ups, not silently solved here |
| A `Session` inside the LangGraph state breaks checkpointing | the session is passed as a graph-builder argument, never stored in the state; only the `application_id` string travels in the state |

---

# Part 4 — Deviations from the Part 1 brief (recorded for audit)

## S8. Deviations from the Part 1 brief (recorded for audit)

| # | Brief says | Implemented as | Why |
|---|---|---|---|
| D1 | `GET /api/applications/{id}` is the tracking detail | it is — and the WS-06 approval-status endpoint moved to `GET /api/applications/approvals/{id}` | two resources cannot share one path shape; the approval record keeps a path of its own and the WS-06 script/tests move with it |
| D2 | `profile_id` is a foreign key to `candidate_profiles` | it is a **nullable**, indexed column, and the prepare request gains an optional `profile_id` and `tailored_resume_id` | the prepare flow has no profile today; a non-null FK would make the tracked application un-creatable for every existing caller. Linking becomes possible the moment the caller knows the profile |
| D3 | the application starts at `DISCOVERED` and walks `MATCHED`/`SHORTLISTED`/`PREPARED` | the application is **created** in `PREPARED`; the earlier states stay in the matrix for a future workstream that really records them | the system never matched or shortlisted anything in this flow — writing those states would fabricate history (I8) |
| D4 | the tables carry foreign keys | the columns are indexed, and no `ForeignKey` constraint is declared | the repo convention (`approval_requests`, `audit_events`, `job_matches`, `tailored_resumes` all avoid FKs): a tracking record must outlive the rows it refers to. The `job_id` still **always resolves** — a stub listing row is created when the URL has none (S1.2) |
| D5 | `transition()` takes the row and a session | it does — and the brief's `metadata` argument is `metadata: dict \| None` | as specified |
| D6 | the API takes `{status, actor, notes?}` | it does; the `actor` for a **human outcome** must be an explicit `human:<who>` identity | the brief also requires the server to "reject non-human-actor claims on terminal outcomes". Accepting a free-form name and normalizing it would make that check unreachable; the explicit form is the record of a human act |
| D7 | the WS-06 `POST /reject` records `REJECTED` with `actor="human:<approver>"` | it does; the free-form `approver` string is normalized to `human:<name>` at that boundary | the WS-06 request body carries a plain name, and the tracking actor format is explicit |
| D8 | the submit node attaches the created `ApplicationEvidence.id` as an event | it does, as an `evidence_recorded` event carrying the evidence id, the status and the artifact paths | as specified, with the paths included so the event is useful on its own |
| D9 | the verify node's failure moves back to `AWAITING_APPROVAL` with `event_type="verification_failed"` | it does — as the *one* event of that state change (`from_status`/`to_status` set), not as an extra row beside a generic transition | "one event per transition" (the acceptance criterion) and "the failure is an event" (the brief) are both satisfied without a redundant pair of rows |
| D10 | the tracking API lives in `src/api/routes/tracking.py` with the `/api/applications` prefix | it does | as specified |
| D11 | the `application_url` travels in the transition's `metadata` | `transition()` takes it as an explicit keyword argument | digging a column value out of a free-form metadata dict is exactly the kind of implicit contract that breaks silently |
| D12 | — | the WS-06 evidence row's `metadata` column was found to be **always NULL** and is now fixed | the submit node passed `metadata=` to a model whose attribute is `extra_metadata` (the column is `metadata`). SQLAlchemy's declarative constructor accepts it because `hasattr(cls, "metadata")` is true — `Base.metadata` is the registry — so the value was set on the instance and silently never persisted. The row was written; its metadata was lost. Fixed to `extra_metadata=`, with a regression test |
| D13 | — | the audit and evidence models are imported at **module** level, not inside the functions that use them | the lazy import meant the model was not registered on `Base.metadata` when `create_all()` ran, so the `audit_events` and `application_evidence` tables were missing from the test databases. The symptom was silent: the evidence write failed, was swallowed by the "never block the submission" rule, and the row was never written. A latent defect in WS-06, found and fixed here |
| D14 | — | the tracking lookup is isolated from the evidence write | they are independent concerns: a missing `applications` table must not cost a submission its evidence. The lookup has its own error handling, and the evidence write has its own |

---

# Part 5 — Implementation status (2026-10-21)

Suite: **711 passing** (baseline at the start of the workstream: 635), offline,
`ruff check` clean over `src/ tests/ migrations/ scripts/`. New: 76 tests across
3 new test modules plus extensions to 4 existing ones. Live-verified with a
real HTTP server, a real Chromium browser and a real database:
**21/21 checks** in `scripts/verify_ws07.py`.

## What was built

| Area | Files | What it does |
|---|---|---|
| The lifecycle | `src/db/applications.py` | The `applications` row (status, timestamps, the job/profile/tailoring it belongs to) and the `application_events` log (append-only, ordered by its autoincrement id) |
| The status machine | `src/applications/tracking.py` | The eleven statuses, the transition matrix, the actor rule, `transition()` and `record_event()`. The matrix is the only authority; the actor rule refuses a human outcome to a non-human actor |
| Job resolution | `src/applications/tracking.py` | `ensure_job_row()` — a tracked application always points at a real `jobs` row; a stub listing is created for a URL that has none, with an id derived from the URL so the same posting resolves to the same row |
| Graph wiring | `src/graph/nodes.py`, `src/graph/state.py`, `src/graph/application_workflow.py`, `src/graph/executor.py` | `submit_node` moves the application to `SUBMITTED` and records the evidence; `verify_node` moves it to `VERIFIED`, or back to `AWAITING_APPROVAL` with the failure reason. The session is a graph-builder argument, never part of the (serializable) state |
| The application routes | `src/api/routes/applications.py` | Prepare creates the tracked application; approve records the decision and executes with the request-scoped session; reject moves the application to `REJECTED` with a human actor |
| The tracking API | `src/api/routes/tracking.py` | `GET /api/applications` (filter + pagination), `GET /api/applications/{id}` (with the full ordered history), `PATCH /api/applications/{id}/status` (human outcomes) |
| The audit trail | `src/security/audit.py` | Two new actions: `application.transition` and `application.event` |

## Live verification (2026-10-21, real HTTP + real Chromium + real database)

`scripts/verify_ws07.py` serves a local fake ATS, migrates a throwaway
database, starts the API with uvicorn, and runs the flow. **21/21 checks
passed**:

| Check | Result |
|---|---|
| prepare records an approval request | `awaiting_approval` |
| prepare creates a tracked application | `application_id` returned |
| the application awaits the approval | `awaiting_approval` in the row |
| the application points at a real listing row | `manual:815f7a2d414191f3` |
| the approved application is submitted and verified | `verified`, in Chromium |
| the submission and verification timestamps are set | both present |
| one event per state change, in order | `prepared → awaiting_approval → submitted → verified` |
| the event ids are ordered | `[1, 2, 3, 4, 5, 6]` |
| the decision and the evidence are recorded | `approval_granted`, `evidence_recorded` |
| the evidence row is linked to the application | 1 linked row |
| no evidence row is left unlinked | 0 orphans |
| the audit trail recorded the transitions | 6 audit rows |
| the application is listed | `total=1` |
| the status filter works | `total=1` |
| the detail carries the ordered history | 6 events |
| the agent cannot record a human outcome | 403 |
| an illegal transition is refused | 409 |
| a human records the interview | 200, `interview` |
| the outcome is attributed to the human | `human:operator` |
| **the history survives a restart of the server** | `interview`, 7 events |

## Acceptance criteria (as delivered)

- [x] A full fake-ATS run produces an `Application` row traversing
      `PREPARED → AWAITING_APPROVAL → SUBMITTED → VERIFIED` with one
      `ApplicationEvent` per transition plus `evidence_recorded`, queryable via
      the API after restart. *(Live-verified: 21/21.)*
- [x] Illegal transitions are rejected (the full legal/illegal matrix is
      exercised in `tests/test_tracking.py`).
- [x] The agent cannot set `OFFER`/`INTERVIEW` (the actor enforcement test;
      and the live run shows a 403 for `actor="agent"`).
- [x] Evidence rows are linked to applications (the `application_id` column;
      the live run shows 0 orphans).
- [x] Event history is append-only: no code path updates or deletes
      `application_events` (proved by a source-level AST test over `src/`).

## Test matrix (as delivered)

| File | Tests | Covers |
|---|---|---|
| `tests/test_tracking.py` (new) | 40 | the actor model, the whole legal/illegal transition matrix, the actor rule, the effects of a transition, the event log and its ordering, the job resolution, the lookups, and the append-only source proof |
| `tests/test_tracking_api.py` (new) | 24 | the list (filter, several values, pagination, bounds), the detail with its ordered history, and the PATCH (legal, illegal → 409, non-human actor → 403, unknown status → 400, a refused update changing nothing) |
| `tests/test_application_workflow.py` (extended) | +10 | the DB rows after submit/verify: the state change, one event per move, the linked evidence row, the evidence metadata, the failed paths, and a run with no database at all |
| `tests/test_submit_api.py` (extended) | +6 | the tracked application over HTTP: the `application_id`, the job row, the whole lifecycle, the linked evidence, the rejection, and the moved approval endpoint |
| `tests/test_migrations.py` (extended) | +0 (extended) | the `applications` and `application_events` columns and indexes, the reversible downgrade, the portable JSON on SQLite and PostgreSQL, the new `application_evidence.application_id` |

## Follow-ups left for later workstreams

- **SEC-15 (retention)**: the application rows, their events and the evidence
  artifacts are kept until the operator deletes them. There is no deletion
  endpoint, and none is planned without a retention policy.
- **The pre-application states** (`DISCOVERED`, `MATCHED`, `SHORTLISTED`) are in
  the matrix but never written: nothing in the system records a match or a
  shortlist today. The states become reachable when WS-08/WS-09 record them
  for real — writing them now would fabricate history.
- **No outcome detection**: `INTERVIEW`, `OFFER`, `REJECTED` and `WITHDRAWN`
  are recorded by a human through the API. Nothing infers them from a page,
  and the agent has no way to set them.
- **The WS-09 intervention-rate metrics** can now be computed: the tracking
  tables carry the submission and the outcome, so the rate at which a
  submitted application led to an interview is a query.
