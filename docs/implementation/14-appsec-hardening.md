# WS-14 · AppSec Hardening — multi-user security

Status: **Specification + Phase A0 done (2026-10-21)** · Milestone: **M3 → M5** · Depends on: WS-12 (runtime attack-surface hardening) · Blocks: any deployment to real users

> **A note on the number.** This workstream was drafted as **WS-13**, and
> a concurrent session claimed WS-13 for the operator console
> ([13-frontend.md](13-frontend.md), which lifts the "no frontend in this
> iteration" rule). Two workstreams cannot both be WS-13, so this one is
> **WS-14** and the file is `14-appsec-hardening.md`. The scope, the
> phases and the threat model are exactly as first drafted.

> **This document supersedes the single-user framing of WS-14.** The first
> draft of this workstream was written for a single-operator deployment:
> the API had no authentication, but the *caller was the operator*, so the
> absence of auth was a hardening gap rather than an architectural one.
> That assumption no longer holds — the project is heading for a real
> multi-user web application, and under that assumption the gaps WS-12
> closed are the *easy* ones.

## The change in the threat model

**Before (WS-12's assumption):** the caller is the operator. One trusted
principal. The threats were hostile *web content* (a job board, a listing,
a page the browser visits) and *resource exhaustion*.

**After:** the caller is an **untrusted third party on the same
deployment**. A user may be curious about another user's applications, may
be running a script, may be malicious. The web content threats remain,
and the new ones are the ones that a single-operator design never had to
answer.

| ID | Threat | Consequence in this codebase today |
|---|---|---|
| **T1** | **Horizontal escalation (IDOR)** — read another user's data by changing an id | **Live.** `GET /api/applications/{application_id}` did `db.get(ApplicationDB, application_id)` with no ownership check. Same for `/api/resumes/{profile_id}`, `/api/tailored/{id}`, `/api/profiles/{id}/matches`, the approval endpoints, and the two artifact-download endpoints. **A0 has closed the shape of this** (see below); **A2 flips the behaviour**. |
| **T2** | **Vertical escalation** — act as another user, or perform a forbidden action | **Live.** The approver identity is a **request-body field** (`req: ApprovalDecisionRequest` on `POST /api/applications/{id}/approve`). Anyone can approve an application *as anyone*. |
| **T3** | **Existence oracle** — 403 vs 404 reveals that a resource exists | Live wherever a "not yours" answer would differ from "does not exist". A0 makes the accessors answer "not found" for both. |
| **T4** | **Cross-tenant file read** — evidence, uploads, tailored DOCX | Live. Files are under a flat `data/` with predictable names, and the owner is not recorded on the file or in the path. **The artifact-download endpoints are the sharpest instance**: `GET /api/tailored/{id}/download` and `GET /api/applications/{id}/evidence/{filename}` serve the rendered resume and the evidence screenshots, and both read their row directly. A0 has moved them onto the scoped accessors; **Phase B** gives the files themselves a per-user location. |
| **T5** | **Agent run bleed** — one user's profile / browser session / agent state entering another's context | Not yet possible (one user). Becomes possible the moment a run is not bound to a verified principal. |
| **T6** | **Credential confusion** — user credentials mixed with platform secrets | Latent. The platform's LLM key and browser secrets are server-side (correct); nothing yet forces the separation or tests it. |
| **T7** | **Tenant starvation** — one user burns the shared LLM / embedding budget | **Live.** WS-12's embedding budget and the Gemini daily quota are **platform-wide**. A noisy tenant starves the others. |
| **T8** | **Repudiation / audit forgery** — deny an action, or forge another user's audit rows | **Live.** `record_audit` stores `resource` and `actor` **raw** and `sanitize_metadata` does not strip newlines — a newline forges audit rows. `actor` is a free string, so it is not a principal. A0 has given the audit rows an owner; **Phase C** makes the actor a principal and strips the control characters. |
| **T9** | **Incomplete deletion** — residue after "delete my account" | Latent, and it grows: nothing is ever purged today (SEC-15). |

**The pivot:** T1 and T2 are not hardening items. They are the difference
between a tool and a multi-tenant service, and they change the data model.

## The architecture decision: authorization lives in the data layer

The single most consequential choice in this workstream, and the one that
makes T1 mechanically impossible rather than merely unlikely.

**A route-level check is not a control.** There are **11 direct
user-scoped table reads** spread across 4 route files today
(`src/api/routes/{tracking,applications,resumes,tailoring,jobs}.py`).
A check written per route is a check that one of them will miss, and a
miss is an IDOR. The check must live where the data is fetched, so that
"forgetting it" is not possible.

### The rules

- **R1 — A user-scoped table is never queried directly from a route.**
  Every access goes through an accessor in `src/db/access.py` that takes
  a `UserScope` and filters by owner. A test greps the route sources for
  direct queries of the user-scoped tables and fails if it finds one.
- **R2 — The scope comes from the verified session, never from the
  request.** No `user_id` in a body, header, query or path is ever
  trusted. The authenticated principal is the only source.
- **R3 — A foreign resource is `404`, not `403`.** The response for
  "not yours" must be **byte-identical** to the response for "does not
  exist", or the API becomes an existence oracle (T3).
- **R4 — Ownership is a column, not a convention.** Every user-scoped
  table gets a `NOT NULL`, indexed `owner_id`. There is no "the route
  remembered to check" state.
- **R5 — The job corpus stays shared.** `jobs` is public board data and
  is the one table that *should* be shared — it is what makes the
  matching worth running. Everything derived from a person is not.
- **R6 — Preparation and submission are separate permissions.** "May
  prepare an application" and "may execute it" are distinct grants, and
  the actor rule that a human outcome is set by a human becomes *the
  authenticated principal*, not a body field.
- **R7 — Files are owned by a principal, and the client never names a
  path.** See Phase B.

### The data model

One new table, one new column per user-scoped table.

```
users                       (new)
  id, email, hashed_password, is_active, is_superuser,
  is_verified, created_at, updated_at

candidate_profiles          + owner_id        (currently: id, name, email, ...)
job_matches                 + owner_id
tailored_resumes            + owner_id
applications                + owner_id
application_events          + owner_id
application_evidence        + owner_id
approval_requests           + owner_id
audit_events                + owner_id  (+ actor_kind, actor_id — a principal, not a string)
```

`jobs` is unchanged. The `jobs` corpus is shared; the *person* is not.

### AC-ISO — the cross-cutting acceptance criterion

Tenant isolation is not a phase; it is a property of the system that
every phase must preserve. It is stated as four mechanical checks, so it
can be **tested** rather than asserted:

> **AC-ISO.** For every user-scoped table and every endpoint that reaches it:
>
> 1. the table has a `NOT NULL`, indexed `owner_id`;
> 2. no route module contains a direct query of that table (enforced by a
>    test that greps the route sources);
> 3. a two-user test asserts that user A's resource id yields **404** for
>    user B and **200** for user A, for **every** endpoint;
> 4. the response body for "not yours" is byte-identical to the response
>    for "does not exist".

Check 2 is what stops the control from decaying. Check 4 is what stops
the fix from creating a new oracle.

## Authentication: the choice and why

The brief is to use an established identity solution rather than invent
one, with secure cookies for the browser and CSRF protection.

**Backend: `fastapi-users`.** It is the most-used FastAPI identity
library and it covers exactly the account lifecycle this workstream
names — registration, verified email, password reset, password change,
session revocation — without hand-rolling any of it. Passwords are
hashed with a memory-hard KDF (argon2); the API key and the browser
automation secrets stay server-side and are never in a user's reach.

**Transport: both, one identity.** A **cookie** (HttpOnly, `SameSite=Lax`,
CSRF double-submit) for the browser, and a **bearer token** for the CLI
and the repo's own scripts. The repo has scripts that call the API over
HTTP (`scripts/verify_ws06.py`, `scripts/refresh_jobs.py`), and
cookie-only would break them; bearer-only would be wrong for a browser.
`fastapi-users` supports both transports against one user store.

**Not a managed IdP in v1.** Clerk/Auth0/Supabase would give a nicer
frontend story, but they add a third party to the data path, a cost, and
a network dependency to a demo that must run offline. The IdP swap is a
provider change in `fastapi-users`, so the door stays open — it is
documented as the v2 path, not foreclosed.

**Not hand-rolled JWT.** A hand-rolled token scheme is how subtle
verification bugs get in.

**The frontend today is a scaffold.** `frontend/` is a Vite/React shell
with shadcn/ui components and **no API calls at all** — so there is no
existing client to migrate, and a small typed API client is needed
regardless. The auth transport decision is therefore not constrained by
the current frontend.

## Execution plan

**WS-14 is a re-architecture, not a hardening pass.** The phases are
ordered by **dependency**, not by severity: the ownership spine (A0)
must land before identity (A1), because identity without ownership has
nothing to enforce against, and enforcement (A2) must land before the
account lifecycle (A3).

| Phase | Work | Depends on |
|---|---|---|
| **A0** | **The ownership spine.** `users` table, `owner_id` on 8 tables, the Alembic migration + backfill, `src/db/access.py` scoped accessors, the `UserScope` type, the two-user test matrix. | — |
| **A1** | **Identity.** `fastapi-users` wiring, registration/login/logout, password hashing, cookie **and** bearer transports, CSRF, the `users` row's lifecycle fields. | A0 |
| **A2** | **Enforcement.** Every route moves to the scoped accessors; the 11 direct `db.get(...)` calls are removed; the approver identity comes from the session, not the body (T2); the `404`-not-`403` rule (T3). | A1 |
| **A3** | **Account lifecycle.** Password change, email change, session revocation (all sessions / one), account deletion request, and the `users` soft-delete. | A2 |
| **B** | **Filesystem permissions and per-user storage.** The `data/users/{user_id}/…` layout; the client stops naming paths (R7); per-user private storage and access rules. | A0 |
| **C** | **Auditable actor identity and user-scoped events.** `actor` becomes a principal (`actor_kind` + `actor_id`); `audit_events.owner_id`; log-injection protection (strip control characters from every string that reaches the audit store). | A2 |
| **D** | **Per-user retention, account deletion, complete purge.** Age-based purge per store; the deletion cascade (profile, tailored, applications, evidence, files, caches); the audit rows are **anonymized, not deleted** (non-repudiation needs them). | A3, B, C |
| **E** | **CI, security tests, dependency hygiene, migration checks.** GitHub Actions running pytest + ruff + `pip-audit`; a migration check (upgrade head from a clean DB, and the downgrade path); the two-user isolation suite **in CI** — an isolation control that is not in CI is a control that decays. | A2 |
| **F** | **Production configuration, deployment guidance, documentation.** Fail-fast production rules; the bind/TLS guidance; the `.env` and `data/` ACLs; the runbook; the README rewrite (its security section is currently stale and self-contradictory). | A0 |
| **G** | **AI-provider privacy, SSRF, tracing, encryption, multi-tenant threat review.** The shared embedding cache holds **candidate query vectors** (verified — `candidate_query_text()` embeds the profile's name, title, skills and summary, and the vector lands in the shared `embedding_cache.sqlite`); tenant starvation of the shared quota (T7); vector inversion; prompt isolation; SSRF pinning; encryption at rest. | A2, B |

### The findings that Phase G must resolve (verified, not speculative)

- **The shared embedding cache holds candidate data.** `candidate_query_text(profile)`
  produces `"Engineer | Skills: Python. | Backend engineer focused on Python services."`,
  which is embedded; the text is the cache **key** (a SHA-256) and the
  **vector** is stored in the shared `embedding_cache.sqlite` alongside
  every other user's job texts. A cache hit on an identical profile
  reveals that another tenant submitted the same text, and the stored
  vectors are invertible in principle.
- **The quota is platform-wide.** WS-12's `MAX_EMBED_PER_REFRESH` and
  the Gemini daily quota are shared, so one tenant can starve the rest
  (T7). Per-tenant accounting is the fix.
- **`jobs` is genuinely shared** — the Chroma corpus holds job vectors
  only, no candidate data. That is the correct design and should be
  stated rather than assumed.

## Acceptance criteria

**Cross-cutting (AC-ISO)** — see above; it must hold after every phase.

**A0** — every user-scoped table has an indexed `NOT NULL owner_id`; the
migration upgrades and downgrades; the backfill assigns the existing
rows to a single `legacy` owner without losing a row; the two-user
matrix exists for every endpoint.

**A1** — a password is never stored or logged in the clear; a session is
issued on login and revoked on logout; a bearer token and a cookie
resolve to the same principal; a request without a credential is
refused; CSRF is enforced on the cookie transport.

**A2** — no route module contains a direct query of a user-scoped table;
the approver identity is the authenticated principal, and a body-supplied
approver is ignored; a foreign resource returns 404 with a byte-identical
body to a missing one; an unauthenticated request to any protected
endpoint is refused.

**A3** — a user can change their password and revoke their sessions; a
deleted account can no longer authenticate and no longer resolve its
resources.

**B** — the client cannot name a file path; every file written is under
the authenticated user's directory; a user cannot read another user's
file by id.

**C** — `actor` is a principal; a newline in a user-supplied field cannot
forge an audit row; every audit row is scoped to its owner and is
readable only by them (and by the platform's own audit view).

**D** — an age-based purge removes the expired rows and files; a deletion
cascade removes every artefact of the account except the anonymized
audit rows; the purge is idempotent and auditable.

**E** — CI runs the suite, the linter, the audit and the migration
check on every push; the two-user matrix is part of CI.

**F** — production refuses to start with an unsafe configuration
(unset `API_KEY`, `APP_DEBUG=true`, a wildcard CORS origin, a missing
`SUBMISSION_POLICY`); the README's security section is accurate; the
runbook contains no development server.

**G** — the shared caches are either per-tenant or proven not to carry
candidate data; the quota is accounted per tenant; the multi-tenant
threat review is written up in `docs/SECURITY.md`.

## Tests

- `tests/test_auth.py` — registration, login, logout, password hashing,
  both transports, CSRF, session revocation.
- `tests/test_isolation.py` — **the two-user matrix**: for every
  endpoint, user A's resource id yields 404 for user B. Plus the
  byte-identical-response check, and the direct-query grep (check 2 of
  AC-ISO).
- `tests/test_audit_identity.py` — actor as a principal, log-injection
  protection, owner-scoped audit reads.
- `tests/test_retention.py` — the purge cascade, idempotence, and the
  anonymized-audit-rows exception.
- `tests/test_permissions_matrix.py` — prepare and submit are distinct
  grants; a user cannot execute another user's prepared application.

## Evaluation (the FYP contribution)

Tenant isolation becomes a **measured** property, not a claim. The WS-09
harness gains a security metric family:

| Metric | Target | Meaning |
|---|---|---|
| `security.unauthenticated_access_rate` | 0 | protected endpoints reachable without a credential |
| `security.cross_user_isolation_violations` | 0 | cross-user accesses that succeeded |
| `security.authorization_coverage` | 1.0 | fraction of user-scoped endpoints with an isolation test |
| `security.audit_attribution_rate` | 1.0 | actions with a resolvable principal |

These join the existing families — nDCG@10, factuality agreement, form
completion rate, human-intervention rate — so the FYP's security
contribution is reported next to its functional one, in the same report,
against the same gate.

## New dependencies

| Package | Why |
|---|---|
| `fastapi-users[sqlalchemy]` | the identity stack: users table, password hashing, session handling, both transports, the account lifecycle |
| `argon2-cffi` | the memory-hard password KDF (a `fastapi-users` extra) |

Both are justified: the alternative is hand-rolling an authentication
protocol, which the brief explicitly rules out. Everything else stays
hand-rolled per the workspace rule.

## Out of scope, and honest limits

- **A managed IdP** (Clerk / Auth0 / Supabase) is v2. The provider seam
  exists; the migration is a configuration change.
- **E-mail verification delivery.** The flow is implemented and the token
  is issued; actually sending mail needs an SMTP provider and is a
  deployment concern, not a security one.
- **Per-tenant encryption keys.** Phase G assesses the shared stores; a
  key-management design is a larger piece of work.
- **Rate limiting per tenant** rather than per client address — WS-12's
  limiter keys on the transport peer, which is the same for every user
  behind one proxy. This becomes a real gap the moment the deployment is
  multi-user, and it belongs with T7 in Phase G.

## Status

Specification written 2026-10-21. **Phase A0 (the ownership spine) is
done** — see the record below. Execution continues at **A1** (identity).

### Phase A0 — the ownership spine (done 2026-10-21)

**Delivered.**

- `src/db/users.py` — the `UserDB` principal, shaped to the schema
  `fastapi-users` expects so A1 adopts it as the identity backend
  without a second migration. The password is stored only as a hash, and
  the column is named `hashed_password` so no reader can mistake it for
  a plaintext field.
- `owner_id` on all eight user-scoped tables — `NOT NULL`, indexed, with
  a server default of the legacy owner. The default is the **fail-closed**
  direction: a write that forgets its owner becomes owned by nobody
  real, so the row is invisible rather than leaked.
- `migrations/versions/f6a7b8c9d0e1_ws13_users_and_ownership.py` —
  creates `users`, inserts the inactive `legacy` account, and adds the
  owner column to the eight tables. The **default is the backfill**, so
  the migration is one statement per table and needs no batch mode —
  which is also what keeps it renderable in Alembic's offline `--sql`
  mode (batch mode needs table reflection, and reflection needs a live
  connection). Verified: upgrade, backfill, downgrade, and the
  re-upgrade all preserve the pre-WS-14 rows.
- `src/db/access.py` — the `UserScope` and the scoped accessors. Every
  accessor filters by owner; a superuser scope is the one deliberate
  exception (the platform's audit view). A resource that exists but
  belongs to somebody else is **not found**, not "forbidden".
- `src/api/scope.py` — `current_scope()`, the single dependency every
  route takes its scope from. **A2 changes this one function's body**
  and every route becomes tenant-scoped. That is the whole point of the
  split: the shape lands first, the behaviour flips second, and the flip
  is one function.
- The routes now read user-scoped rows through the accessors. The
  accessor names deliberately match the route names, so the routes
  import the module as a namespace (`access.get_application(...)`) to
  keep both.
- `src/db/evidence.py` — the evidence model is renamed
  `ApplicationEvidenceDB` (the database layer names its models after
  their tables) with `ApplicationEvidence` kept as an alias.

**The control is now mechanically enforced.** `tests/test_tenant_isolation.py`
carries the two-user matrix — 17 tests — including the two checks that
stop it decaying:

- **check 2** — a test that greps the route sources for a direct query
  of a user-scoped table and fails if one appears. It found **five**
  real bypasses when it was written (the profile-facts lookup, the match
  history, the status update, and the two artifact-download endpoints);
  all five are now on the accessors.
- **check 4** — the "not yours" and "does not exist" answers must be
  the *same thing*, not merely equal in value, so the API never becomes
  an existence oracle.

**The whole suite is green at 1061 passed** with the migration, the
accessors, the routes and the matrix in place.

**What A0 does *not* claim.** The routes still act as the **legacy**
scope, so the behaviour is still single-tenant: the owner filter is
present and exercised, but the scope that carries it does not yet come
from an identity. A0 is the spine and the shape; **A2 is the flip**.
Until then, the honest statement is that the *mechanism* for isolation
exists and is tested, and the *identity* it is keyed on does not.

**Two notes for the next phase.**

- The `owner_id` server default is permanent by design. It is the
  fail-closed net, and dropping it later would need a table recreate on
  SQLite — so the decision is taken now, while it is cheap.
- The `LEGACY_OWNER_ID` literal is now at the write paths. **A2 must
  replace every one of them with the request's scope**, and the
  equivalent of check 2 should be extended to catch a `LEGACY_OWNER_ID`
  appearing in a route module.
