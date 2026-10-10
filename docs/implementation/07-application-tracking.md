# WS-07 · Application Tracking Lifecycle

Status: **Not started** · Milestone: **M3** · Depends on: [01](01-data-foundation.md), [06](06-security-preconditions.md) · Blocks: M5 pilot, [09](09-evaluation.md) (intervention-rate metrics)

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

- [ ] A full fake-ATS run produces an `Application` row traversing
      `PREPARED → AWAITING_APPROVAL → SUBMITTED → VERIFIED` with one `ApplicationEvent` per
      transition plus `evidence_recorded`, queryable via the API after restart.
- [ ] Illegal transitions are rejected (unit matrix over `ALLOWED_TRANSITIONS`).
- [ ] Agent cannot set `OFFER`/`INTERVIEW` (actor enforcement test).
- [ ] Evidence rows are linked to applications (no more orphan `job_url`-only records).
- [ ] Event history is append-only: no code path updates or deletes `application_events`.

## Tests

- `tests/test_tracking.py` — transition legality matrix, actor enforcement, event append ordering, timestamps.
- `tests/test_tracking_api.py` — list/filter/detail/PATCH; 404s; illegal PATCH → 409.
- `tests/test_application_workflow.py` (extend) — DB rows asserted after prepare/approve/submit/verify (complements existing in-memory state assertions).

## New dependencies

None.
