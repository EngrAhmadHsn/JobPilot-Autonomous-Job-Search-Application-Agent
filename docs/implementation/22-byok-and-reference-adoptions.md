# WS-22 · Bring-your-own model key, prompt PII masking, résumé style policy & sponsor verification

Status: **Done (2026-11-08)** · Milestone: **M5** · Depends on: WS-10 (LLM client), WS-13/14 (console, multi-user), WS-17/19 (console experience), WS-18 (durable execution), WS-20/21 (matching, application profile)

> Two source documents drive this workstream:
>
> 1. `docs/reference_comparisons/00_COMPARATIVE_SYNTHESIS.md` — the
>    seven-reference comparison and its "High-Value Ideas to Integrate" list.
> 2. `docs/implementation/00-OVERVIEW.md` — the roadmap this workstream now
>    extends.
>
> The work is split in two halves:
>
> - **Bring your own key (BYOK)** — a user may register *their own* LLM
>   provider key. When one is stored, every model call that user's requests
>   make runs on **their** key, their quota and their bill; the platform key
>   is only a fallback when the deployment mode allows it.
> - **The reference ideas that survive triage** — a two-way PII mask in front
>   of every prompt that carries candidate data, a deterministic
>   anti-AI-jargon résumé style policy, verified visa-sponsorship lookup from
>   official government registers, and gap-diagnosis chips in the console.
>
> Several reference ideas are **deliberately rejected** and several are
> **explicitly pending** — §1 records each one with its reason, so the next
> session does not silently revive a rejected idea or re-litigate a decision.
> ChatOps integrations (Slack, Telegram, Lark/Feishu), the MCP server and
> Typst PDF rendering stay **pending** by instruction (§11).

---

## 1. The reference ideas, and what happens to each

The synthesis lists eleven ideas; the seven reference documents add several
more. Every one is dispositioned here.

| # | Idea (source) | Disposition | Why |
|---|---|---|---|
| 1 | **Fail-closed CDP port guard** (JobHunter AI `engine_guard.py`) | **Recorded, no code** | The runtime has **no CDP attach path**: `grep -rn "connect_over_cdp\|remote-debugging" src/` finds nothing. Playwright launches its own browser and every run gets a fresh context (SEC-07). A guard for a path that cannot run would be untested code. The rule is recorded in §7.4: *if a CDP attach is ever added, it must verify the PID and the profile owner and fail closed.* |
| 2 | **Stealth Playwright args / Patchright** (AutoJob) | **Rejected on policy** | `AGENTS.md` and `docs/SECURITY.md` forbid bypassing anti-bot controls; suppressing `navigator.webdriver` and CDP fingerprints *is* detection evasion. The project's answer to a challenge is a `blocked_human_review` stop (SEC-09), not camouflage. |
| 3 | **Humanized typing / smooth scroll** (Auto_job_applier_linkedIn) | **Rejected on policy** | Same reason as #2: it is detection evasion by another name. It also makes runs slower and less deterministic. |
| 4 | **Two-way PII redaction layer** (auto-apply-bot `anonimizacao.ts`) | **Adopted** — Phase B3 | The tailoring path is the one place candidate identity reaches a third-party model. Masking it before the prompt and restoring it after the answer is a pure privacy gain with no loss of function (the résumé schema never contains the candidate's own name). |
| 5 | **Official visa-sponsorship registers** (JobOps) | **Adopted, adapted** — Phase B5 | USCIS H-1B Data Hub and the UK Home Office sponsor register are *facts*. The reference's "elevate verified / demote unverified" is **not** adopted: absence from a partial register is not evidence against a company, and folding it into the score would present an opinion as a measurement. WS-22 **verifies and informs** — a badge, a note, a queryable status — and changes no score. |
| 6 | **Direct ATS JSON endpoints** (JobOps) | **Already holds** | Greenhouse, Ashby, Lever and Remotive adapters already call the boards' JSON APIs directly (`src/jobs/*_adapter.py`), HTTP before browser. Workday's CXS API is per-tenant (`<tenant>.myworkdayjobs.com`) and there is no public tenant directory; inventing one is fabrication. Recorded in §11. |
| 7 | **Anti-AI jargon + strong-verb policy** (JobHunter AI) | **Adopted** — Phase B4 | Deterministic, offline, and it addresses a real quality problem: generated résumés that read like every other generated résumé. A ban list in the prompt **and** a deterministic report on the answer. |
| 8 | **Skill match / gap badges** (AutoApplyMax) | **Adopted** — Phase B6 | Matched/missing requirements already flow to the console but render as comma-joined prose; chips make the gap diagnosable at a glance. |
| 9 | **Typst resume PDF** (JobOps) | **Pending** (§11) | PDF export is FR-1.8, planned and unimplemented. Typst is a native binary toolchain; adopting it is a deployment dependency decision of its own, not a phase of this workstream. |
| 10 | **Standalone MCP server** (JobGPT) | **Pending** (§11) | An integration surface; per instruction, integrations stay pending. |
| 11 | **ChatOps notifications + approval cards** (auto-apply-bot, JobHunter AI) | **Pending** (§11) | Slack / Telegram / Lark — per instruction, pending. |
| 12 | **Form answer cache** (auto-apply-bot `buscarRespostaCache`) | **Already holds, differently** | WS-20's question taxonomy + the application profile is the deterministic answer source; WS-08's answer rule fills a field only from profile facts. Caching model-generated answers would reintroduce the non-determinism WS-20 removed. |
| 13 | **Token/cost ledger** (auto-apply-bot `token-tracker.ts`) | **Already holds** | WS-10 writes a usage row per call (counts only); WS-14 attributes spend per tenant. §2.8 adds the *whose key* dimension. |
| 14 | **Decision audit stream / SSE to the console** (AutoJob) | **Already holds, honestly** | WS-17 chose polling over streaming and WS-19 added per-run progress; the audit trail is the decision stream. Not re-opened. |
| 15 | **Stuck-form watchdog** (AutoApplyMax, 2-minute abort) | **Already holds in substance** | Every Playwright action carries a timeout, the form walker fails the run on a non-advancing wizard, and the evidence (screenshot + trace + action log) is captured for the failed run. |
| 16 | **Single-call application analytics** (JobGPT `get_application_stats`) | **Already holds** | `GET /api/admin/overview` (WS-17) and the tracker endpoints provide the aggregates; the console Overview is the consumer. |

Everything the triage *adopts* is specified below as phases B1–B6.

---

## 2. Phase B1 — the credential store and client resolution

### 2.1 The model

One credential **per user** (the principal), not per profile: a key belongs to
the person who pays for it. The row carries provider, model, optional
`base_url`, the **encrypted** key, a display hint, and timestamps.

New table `llm_credentials` (`src/db/byok.py`), owner-scoped like every other
user table — added to the isolation matrix (`tests/test_tenant_isolation.py`)
and reachable **only** through `src/db/access.py`.

### 2.2 Encryption at rest

The key is encrypted with **Fernet** (AES-128-CBC + HMAC-SHA256, from the
`cryptography` package) under a key derived per deployment:

1. `BYOK_ENCRYPTION_KEY` — an explicit urlsafe-base64 32-byte key, when set;
2. otherwise **HKDF-SHA256 over `AUTH_SECRET`** (the deployment already has
   one in production);
3. otherwise, **development only**, a generated key file
   `data/secrets/byok.key` (0600 where the platform supports it).

A production deployment that enables BYOK without (1) or (2) **refuses to
start** — the same fail-fast rule the identity settings follow. The tradeoff
of (3) is stated honestly in the module docstring: a local key file protects
against database exfiltration, not against a host-level attacker.

### 2.3 The deployment mode

`BYOK_MODE`:

- `optional` (default) — a stored user key is used; otherwise the platform
  key;
- `required` — the platform key is **never** used for user requests; a user
  without a credential gets a clear, actionable error;
- `disabled` — the routes report the feature as unavailable; writes are
  refused (`403`).

### 2.4 Resolution and its failure rule

`resolve_client()` (in `src/llm/credentials.py`) is what the two generation
call sites (`src/resume/tailor.py`, `src/research/engine.py`) now call instead
of `get_client()`:

1. no tenant (script, worker, CLI) → the platform client, unchanged;
2. mode `disabled`, or no stored credential → the platform client;
3. a stored credential → a client built from **it**, cached per
   `(owner_id, updated_at)` so a rotation takes effect on the next call, with
   its own rate-limit bucket and its own circuit breaker
   (`llm:byok:<owner>`) — one user's failing key must not open the breaker
   for the platform key or for another user.

**A user's key that fails does not fall back to the platform key.** That
would spend the platform's quota on the user's misconfiguration and hide the
problem. The error names the fix ("your stored model key was rejected — update
it in Profile → Model credentials").

### 2.5 The secrets

- The key is never returned by any route (the status carries a hint: the last
  four characters).
- It is never written to the audit trail, a log line, or an exception
  message; the store's audit rows carry `provider`, `model` and `hint` only.
- The status read is served from the store, never from a shadow copy.

### 2.6 The API

`src/api/routes/llm_credentials.py` (prefix `/api/llm/credentials`):

| Route | Purpose |
|---|---|
| `GET /api/llm/credentials` | Status: mode, availability, whether the platform key is configured, the stored credential (masked) |
| `PUT /api/llm/credentials` | Insert or replace the caller's credential (validated; never echoed) |
| `DELETE /api/llm/credentials` | Remove the caller's credential |
| `POST /api/llm/credentials/test` | One bounded call with the **stored** credential, to prove it works |

The `test` route is concurrency-gated and rate-limited like the other
expensive endpoints, and it spends the *user's* quota — which is why setting a
key does not silently test it.

### 2.7 The console

A **Model credentials** card on the Profile screen
(`frontend/src/components/profile/model-credentials-card.tsx`), following the
Work Preferences card's pattern: status line, provider select, model input,
base URL (openai-compatible only), password-style key input, Save / Remove /
Test buttons, inline errors. The key input is cleared after a successful save
and never re-rendered.

### 2.8 Usage accounting

`GenerationUsage` gains a `credential` field (`platform` | `byok`) so the
audit row says **whose** key the call spent. Nothing else changes: counts
only, never content.

---

## 3. Phase B2 — the docs contract

The new routes are added to the README API table and the new environment
variables to `.env.example` — the machine-checked contract
(`tests/test_docs_accuracy.py`, `tests/test_env_docs.py`) makes both
mandatory, which is the point.

---

## 4. Phase B3 — the PII mask (`src/security/pii.py`)

### 4.1 The gap

`_profile_for_prompt` (tailor) drops the candidate's `email`, `phone` and
`website` from the profile JSON, but the candidate's **name**, and any
identity-shaped string in the job text (recruiter emails, phone numbers,
tracking URLs), still reach the provider.

### 4.2 The design

A deterministic, offline vault:

- `PiiVault.for_profile(profile)` builds tokens from the candidate's identity
  fields: `[[NAME]]`, `[[EMAIL_1]]`, `[[PHONE_1]]`, `[[LINK_1]]`… (the
  candidate's known values), plus a per-text sweep for any *other*
  email/phone/URL found in the prompt inputs (`for_text`).
- `vault.mask(text)` replaces them; `vault.restore_text(text)` and
  `vault.restore_model(model)` put the real values back **exactly**.
- A token that does not survive the model verbatim cannot be restored; the
  residue is **stripped** (the sentence is dropped) and reported as a
  factuality violation — never left in the output as a placeholder, never
  guessed at.
- The vault is per call, holds no secrets of its own, and is never persisted.

### 4.3 Wiring

In `src/resume/tailor.py`: mask the profile JSON, the requirements block and
the insights block; restore the generated object before factuality validation
(so the validator sees real values, e.g. company names). `research/engine.py`
sends no candidate data and is unchanged.

### 4.4 The proof

A test captures the prompt with a fake generator and asserts that **no** name,
email, phone or URL from the profile/job appears in it, and that the returned
bullets carry the real values again. This is the test that makes the claim
"the provider never sees the candidate's identity" true rather than aspirational.

---

## 5. Phase B4 — the résumé style policy (`src/resume/style.py`)

### 5.1 The design

Deterministic, offline analysis of generated prose:

- **banned phrases** — the AI-jargon blacklist ("leverage", "synergy",
  "seamlessly", "cutting-edge", "results-driven", "passionate about", …),
  each with a plain-language suggestion;
- **weak phrases** — "responsible for", "helped with", "worked on" — with a
  strong-verb suggestion;
- **quantification** — the share of bullets that carry a number, because a
  bullet without a measure is a claim.

`analyze_style(text) -> StyleReport` returns findings (phrase, category,
snippet, suggestion) and the quantified ratio. It is the same family as the
factuality validator: it reports, it does not silently rewrite.

### 5.2 Where it acts

1. **In the prompt** — the ban list is injected into the tailoring system
   rules from the module's own constant, so the prompt and the checker can
   never drift apart.
2. **On the answer** — `TailoringResult` gains `style: StyleReport`; the
   `POST /api/tailor` response carries it; the console shows the findings
   next to the factuality report.

---

## 6. Phase B5 — verified sponsorship registers

### 6.1 The data

Two official sources, imported by an operator (never fetched at request time):

- **USCIS H-1B Employer Data Hub** yearly export (`h1b_datahubexport-<year>.csv`)
  — employer, fiscal year, approvals, denials;
- **UK Home Office Register of licensed sponsors** — organisation name, town,
  route (Skilled Worker / Temporary Worker).

`scripts/import_visa_sponsors.py` loads either file into the shared
`visa_sponsors` table (`src/db/sponsors.py`): normalized name, raw name,
source, country, year, approvals, denials. Rows are replaced per
(source, year) so a re-import is idempotent.

### 6.2 The lookup

`src/matching/sponsors.py`:

- `normalize_company(name)` — deterministic: lowercase, punctuation removed,
  legal suffixes dropped (inc, llc, ltd, plc, gmbh, bv, ag, sa, oy, ab …),
  whitespace collapsed;
- `lookup(session, company_name) -> SponsorVerdict` with status
  `verified` | `not_found` | `no_data`;
- the note is **always about the register, never about the company**:
  "Listed in the USCIS H-1B Employer Data Hub (FY2024: 132 approvals)" or
  "No entry found in the imported sponsorship registers" — the second only
  when at least one register is loaded (`no_data` otherwise).

### 6.3 Where it surfaces

- `POST /api/jobs/search` and `GET /api/profiles/{id}/matches` enrich each
  match with `sponsor_status` + `sponsor_note` (two new optional fields on
  `JobMatchResult`); the enrichment is an API-layer lookup against shared
  reference data, so it is always fresh and needs no column on `job_matches`;
- the console shows a badge: green "Verified sponsor" or neutral "No
  sponsorship record";
- an explicit non-goal: **no score change and no silent filtering** (§1 #5).

---

## 7. Phase B6 — the console gap diagnosis

### 7.1 Chips

A small `MatchGapChips` component renders matched requirements (forest/green),
missing requirements (terracotta/red) and the sponsor badge, used by the job
detail screen and the match cards. It replaces the comma-joined prose with
the same data, and it renders **nothing** when both lists are empty (a chip
row that says "nothing known" is noise).

### 7.2 The routes table

Unchanged by this phase; the README rows are added with B1/B2.

### 7.3 Tests

Component tests for the chips and the credentials card; the existing
`console-navigation.test.ts` guarantees no route was missed.

### 7.4 The recorded CDP rule

Not implemented (there is no attach path), recorded here and in
`docs/implementation/08-browser-automation.md`: **any future CDP attach must
verify the PID and the browser profile it is attaching to and fail closed on
any mismatch** (the JobHunter AI `engine_guard.py` lesson).

---

## 8. Cross-cutting

- **Migrations**: one Alembic revision for `llm_credentials` and
  `visa_sponsors` (both additive; the CI migration check applies it to a
  fresh database).
- **Isolation matrix**: `LlmCredentialDB` joins the owned-models list; a
  cross-user read of a credential is a 404, and a test proves user A's key is
  never used for user B's call.
- **Redaction**: the audit metadata for a credential write carries `provider`,
  `model` and `hint` — no key-shaped value and no key-shaped *name* (the
  redaction filter drops metadata keys matching `key|token|secret|credential`).
- **Rate limits / admission**: the credential routes sit behind the existing
  body cap; `POST .../test` also takes the expensive-endpoint gate.
- **No new runtime dependency beyond `cryptography`** (already installed
  transitively; declared now because WS-22 imports it — the WS-11 lesson).

## 9. Verification plan

`scripts/verify_ws22.py` — live, against a real uvicorn, a real database and a
local fake chat-completions server:

1. register a user; `GET /api/llm/credentials` reports mode and no credential;
2. `PUT` a credential pointing at the local fake provider; the stored row is
   **not** the plaintext key (read the DB directly);
3. `POST /api/llm/credentials/test` succeeds and the fake server saw the
   **user's** key, not the platform's;
4. `POST /api/tailor` runs on the user's key; the captured prompt contains no
   candidate name/email/phone; the response carries a `style` report;
5. import a small sponsor fixture; a search for a known company returns
   `sponsor_status=verified` with a register-scoped note;
6. a second user sees their own status only (no leak of user 1's hint);
7. ChatOps / MCP routes do not exist (404) — the pending list is real.

## 10. Results

**Status: done (2026-11-08).** What was built, and what the verification found.

### The live run — 27/27 checks (`scripts/verify_ws22.py`)

Against a real uvicorn, a real migrated database and a local fake
chat-completions server, with a throwaway data directory:

- the migration adds `llm_credentials`, `visa_sponsors` and
  `tailored_resumes.style`;
- the credential read starts empty and never carries a key field; storing one
  returns a mask; the row in SQLite is a Fernet token, not the key;
- exercising the credential works **and the fake provider received the user's
  key**, not the platform's;
- a tailoring run succeeds on the user's credential, the captured prompt
  contains no candidate identity (checked against the uploaded résumé's own
  name, plus e-mail/phone/URL shapes) and carries `[[NAME]]` instead, and the
  answer's placeholder comes back as the real name;
- the style report is delivered and counts the quantified bullets;
- the imported USCIS fixture verifies a registered employer with its counts
  ("Listed in the USCIS H-1B Employer Data Hub (FY2024, 75 approvals, 3
  denials)"), an unregistered employer is a register-scoped miss, and the
  persisted match score is unchanged at 71.0;
- the Slack, Telegram and MCP surfaces answer 404 — the pending list is real.

### Two defects the verification found (both pre-existing, both fixed)

1. **The scope dependency never published its tenant to a sync route.**
   `current_scope` was a **sync** dependency, and FastAPI runs a sync
   dependency in a worker thread under a *copy* of the context — so its
   `ContextVar.set` was discarded, and the route body (and every call under
   it) read `current_tenant() == None`. The visible symptom in this
   workstream: BYOK silently fell back to the **platform** key, which the
   capture server proved by showing the platform token. The same hole meant
   WS-14's per-tenant embedding spend was attributed to the platform. Fixed
   by making the dependency `async` (it then runs on the request's own task),
   and pinned by `tests/test_ws22_byok_api.py::TestTheTenantPublication`,
   which mounts the real dependency on a probe app with a sync route.
2. **The `openai-compatible` provider dropped the prompt on structured
   calls.** `build_request` replaced the message content with the JSON-schema
   instruction instead of prefixing it — so a structured call asked the model
   for a JSON object and never said what it was about. The existing test
   asserted the schema and "JSON" were present, never that the caller's
   prompt survived; that assertion is now there. (The provider is not
   experimental any more either: users bring their own OpenAI-compatible
   endpoints, so its failures are user-visible.)

### Tests

- backend: `tests/test_ws22_byok.py` (46), `test_ws22_byok_api.py` (17),
  `test_ws22_pii.py` (12), `test_ws22_style.py` (9), `test_ws22_sponsors.py`
  (19) — plus the sharpened append-only rule in `tests/test_tracking.py`
  (with a proof that the sharpened rule still catches real event mutations),
  the migration expectations in `tests/test_migrations.py`, the new
  variables in `tests/test_env_docs.py` and the four routes in the README
  table (`tests/test_docs_accuracy.py`).
- frontend: `model-credentials-card.test.tsx` (8) and
  `match-gap-chips.test.tsx` (7).
- the full suites, measured on 2026-11-08:
  - **backend**: 1,598 selected (`pytest -q -m "not browser"`, serial, 7:20)
    → **1,592 passed** and the **6 documented Remotive DNS flakes**
    (`socket.gaierror` in the SSRF guard — see `AGENTS.md`; they are
    environmental and were not touched);
  - **frontend**: **205 tests in 33 files** (`npx vitest run
    --maxWorkers=1`) and `tsc -b --noEmit` clean;
  - **`ruff check src tests scripts`** clean;
  - **e2e**: 5/5 against the production build (`npm run build && npm run
    preview` on 4173) and a private-port backend running this code — the
    smoke journey, plus keyboard, account-menu and drawer checks. One
    adjustment was needed and is part of this workstream: with the model
    provider **stalling** (TCP reachable, the API call hanging) the API's
    retry budget is ~190 s, so the smoke test's 180 s wait for
    "tailored **or** model unavailable" failed one step before the API
    answered. The wait is now 260 s and the test timeout 420 s.

### Notes for the next session

- **`npm test` can exhaust the Node heap on this machine** when vitest fans
  out; `npx vitest run --maxWorkers=1` is the reliable invocation (205 tests
  in 33 files, ~2.5 minutes). A partial "20 passed (33)" from the fanned-out
  run is worker memory pressure, not a red suite.
- The console's `api:types` generation needs no running server: dumping
  `app.openapi()` to `frontend/node_modules/.cache/openapi.json` and running
  `openapi-typescript` over it produces the same file. **Do not run
  `prettier --write` on the result** — the committed `schema.ts` is the
  generator's own layout (4-space indent, no semicolons), and Prettier
  rewrites the whole file (≈10 k lines) for a 300-line change.
- The e2e's preview server **binds `localhost` (IPv6) only**: setting
  `E2E_BASE_URL=http://127.0.0.1:4173` makes Playwright's readiness poll fail
  with a 180 s webServer timeout that looks like a build failure.

## 11. Pending, explicitly

| Item | State | What it would take |
|---|---|---|
| ChatOps (Slack, Telegram, Lark/Feishu) notifications and approval cards | **Pending** | An outbound webhook client with a domain allowlist, an interactive-approval token bound to the approval row, and a delivery-failure audit path. Deferred by instruction; the approval flow (WS-06) and the run events (WS-18) already produce the payloads it would send. |
| Standalone MCP server | **Pending** | A separate package (stdio + HTTP transports) wrapping the existing API; needs its own auth story (a scoped token per client) before it can be exposed. Deferred by instruction. |
| Typst PDF rendering | **Pending** | The DOCX renderer stays the deliverable; a PDF path means either a native toolchain (Typst) or an HTML→PDF render through the already-installed Chromium. FR-1.8 stays Planned. |
| Workday CXS adapter | **Pending** | Requires a per-tenant host list; no public directory exists. Recorded, not invented. |

## 12. Acceptance criteria

1. A user can store, replace, test and delete their own provider key; no
   route, log line or audit row ever carries the key; the database column is
   encrypted.
2. With a stored key, that user's tailoring and research calls run on **their**
   credential (proven live against a capture server); without one, the
   platform key is used when the mode allows, and the mode `required` fails
   with an actionable message.
3. Rotation takes effect without a restart; a failing user key never opens the
   platform breaker and never spends the platform key.
4. Captured prompts carry no candidate name, email, phone or URL, and the
   answer is restored exactly; an unrestorable token is stripped and reported.
5. `POST /api/tailor` returns a style report; the prompt carries the ban list.
6. A job whose employer appears in an imported register reports
   `sponsor_status=verified`; no register loaded reports `no_data`; the score
   is unchanged in every case.
7. The README table, `.env.example`, the isolation matrix and the migration
   check are all green.
8. The full backend suite (serial), the frontend suite (`vitest run`), the
   production build and the e2e suite pass; `scripts/verify_ws22.py` passes
   end to end.