# WS-25 · Provider Depth, the Application Form Schema & Approval Expiry

Status: **Done (2026-11-11)** — Phases 1–5 plus the WS-25b wiring in §9/§10 · Milestone: **M5** · Depends on: WS-06 (approval), WS-08 (browser automation), WS-20 (matching), WS-23 (corpus correctness) · **Deviations in §7a, follow-up in §9 (WS-25b)**. The §7a gaps are closed: §7a.1's form schema is wired into prepare (`_build_form_plans`), §7a.2's liveness check is wired into approve (`_job_liveness`), and §7a.3's questions measurement is built (75 `form_questions` rows behind `GET /api/profiles/{id}/question-gaps`). **Still open:** the console does not call that endpoint yet, so the measured field order is not what the profile screen renders

> Two of the four providers publish far more than the adapters were
> reading, and one of the project's core safety guarantees — *a human
> approves before anything is submitted* — had no clock on it.
>
> This workstream reads the rest of the provider APIs, uses Greenhouse's
> published **application form schema** to show the operator the exact
> form, checks that a job is still **open** before it is applied to, and
> gives an approval an **expiry**.

---

## 1. Phase 0 — What the providers publish and what the adapters read

Measured against the live APIs on 2026-11-09/10, per provider. "Read" means
the field reaches the normalized `JobListing` today.

| Concept | Greenhouse | Lever | Ashby | Remotive |
|---|---|---|---|---|
| Company name | `company_name` | **none** (slug only) | **none** (slug only) | `company_name` |
| Description plain | **none** | `descriptionPlain` | `descriptionPlain` | **none** (HTML) |
| Location | `location.name` | `categories.location` + `allLocations[]` | `location` + `secondaryLocations[]` + `address` | `candidate_required_location` |
| **Remote policy** | **none** | **`workplaceType`** | `workplaceType` + `isRemote` | always remote |
| Employment type | `metadata[]` (per-board keys) | `categories.commitment` | `employmentType` | `job_type` |
| **Salary** | **`pay_input_ranges[]`** | **`salaryRange`** | **`compensation`** | free-text `salary` |
| Requirements bullets | in `content` | **`lists[]`** | in `descriptionHtml` | in `description` |
| Department / team | `departments[]`, `offices[]` | `categories.team` | `department`, `team` | `category` |
| Posted date | `updated_at`, `first_published` | `createdAt` (ms) | `publishedAt` | `publication_date` |
| **Form schema** | **`?questions=true`** | none | none (authenticated only) | none |
| Pagination | none | `limit`/`skip` | none | none (params inert) |

The three bolded rows are the WS-23 field completion; the form schema is
this workstream.

### The query parameters that do not exist

Measured by probing each endpoint with a set of parameter names and
comparing the response bytes:

* **Greenhouse**: only `content` and `pay_transparency` change the
  response. `questions=true` is **not** a list parameter (it works on
  the *detail* endpoint); `departments`, `offices` and `updated_at` are
  not parameters at all; unknown parameters are silently ignored.
* **Ashby**: only `includeCompensation=true` changes the response.
  Eleven other plausible names (`includeBenefits`, `includeLocations`,
  `includeQuestions`, `includeCustomFields`, `includeBranding`,
  `includeJobUrl`, `includeAllAdapters`, `includeApplicationForm`,
  `includeForm`, `includeCustomFields`) returned **byte-identical**
  bodies.
* **Remotive**: **every** parameter is inert. The endpoint serves a
  static JSON file; `search`, `limit`, `category` and `company_name`
  all return the same 204,646 bytes. The adapter's docstring claimed
  server-side filtering — it did not have any.

The Ashby parameters that sound right but do nothing are the reason the
adapter's "no single-job endpoint" note matters: a 401 on
`/posting-api/job-board/{org}/{id}` is a blanket rejection of the path
form, and `?jobId=` is ignored (it returns the whole board).

---

## 2. Phase 1 — The application form schema

**Greenhouse is the only one of the four that publishes its application
form over a public, key-less endpoint:**

```
GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}?questions=true
```

Verified live against stripe, anthropic and databricks on 2026-11-10:
stripe's first job carries **16 questions, 3 location questions and 3
compliance questions**.

The response adds four keys to the ordinary job detail:

```json
{
  "questions": [
    {"description": null, "label": "First Name", "required": true,
     "fields": [{"name": "first_name", "type": "input_text", "values": []}]},
    {"description": null, "label": "Resume/CV", "required": true,
     "fields": [{"name": "resume", "type": "input_file", "values": []},
                {"name": "resume_text", "type": "textarea", "values": []}]},
    {"description": null, "label": "Please select the country where you currently reside.\n",
     "required": true,
     "fields": [{"name": "question_69650990", "type": "multi_value_single_select",
                 "values": [{"label": "Germany", "value": "1"}]}]}
  ],
  "location_questions": [
    {"label": "Latitude",  "required": true, "fields": [{"name": "latitude",  "type": "input_hidden", "values": []}]},
    {"label": "Longitude", "required": true, "fields": [{"name": "longitude", "type": "input_hidden", "values": []}]},
    {"label": "Location",  "required": true, "fields": [{"name": "location",  "type": "input_text",   "values": []}]}
  ],
  "compliance": [
    {"type": "eeoc", "description": "<p>…</p>",
     "questions": [{"required": false, "label": "VeteranStatus",
                    "fields": [{"name": "veteran_status", "type": "multi_value_single_select",
                                "values": [{"label": "I don't wish to answer", "value": "3"}]}]}]}
  ],
  "demographic_questions": null,
  "data_compliance": [
    {"type": "gdpr", "requires_consent": false, "requires_processing_consent": false,
     "requires_retention_consent": false, "retention_period": null,
     "demographic_data_consent_applies": false}
  ]
}
```

Two details that a naive parser gets wrong, both measured:

* the option `value` is a **string** ("3", "2", "1"), while the
  documentation's example shows integers — a caller that assumes
  integers silently fails to match the board's own value;
* a multi-select field name carries a trailing `[]`
  (`question_69650991[]`), which is the multipart bracket convention
  and matters for the POST encoding.

### The three rules the schema buys

**1. Consent and demographic questions are never answered by the agent.**
They arrive in their own blocks (`compliance`, `demographic_questions`),
and `data_compliance` states whether GDPR consent is required. Ticking a
consent box on the candidate's behalf is an assertion the agent cannot
make, and the demographic questions are voluntary by design. They are
surfaced to the human at approval time and nothing else.

**2. Location needs the coordinates.** Greenhouse documents that
`location`, `latitude` and `longitude` must **all** be sent — if the
coordinates are omitted, the location is ignored entirely — and
`country_short_name` is strongly recommended. The schema names the
fields, so the prepare step can detect that the form wants a geocode
and say so, rather than silently sending an address that the board will
discard.

**3. A custom, required, unanswerable question stops the flow.** With
the schema, the prepare step can classify every question against the
existing taxonomy (`src/applications/questions.py`) and route the ones
it cannot answer to `blocked_human_review` — the status the fake-ATS
adapter already uses — instead of discovering the gap at submission
time.

**What it does not do:** the schema describes the form; it does not
answer it. The taxonomy decides what the agent may answer, and the
answer comes from the profile's grounded facts. The schema's job is to
make the form **visible** before a human approves it.

---

## 3. Phase 2 — The closed-job check

A job must be live and published to accept applications, so re-fetching
the job just before the approval **is** the liveness check. It costs one
request and it is the layer that actually protects the submission.

`GreenhouseAdapter.check_job_is_live(job_url)` returns `(is_live, reason)`:

* **404** → "the job is no longer published";
* a past `application_deadline` → "the application deadline passed";
* anything else → "the job is published and accepting applications".

Verified live on 2026-11-10: a real stripe job reports live; a
non-existent id reports "no longer published (404)".

The deadline is parsed as ISO-8601. A deadline that **cannot** be
parsed is not treated as passed — refusing to apply on a date nobody
can read would be a guess.

Why this matters more than a corpus-level expiry: the corpus has no
expiry signal (WS-23, Phase 6), so a posting that closed months ago is
still in it, still has a vector, and still ranks. The check at the
approval gate is the one that stops the application.

---

## 4. Phase 3 — The approval expiry

`ApprovalStatus` was `PENDING / APPROVED / REJECTED / EXECUTED /
FAILED`. There was no `EXPIRED` state and no expiry timestamp, so an
approval granted on Monday would still authorize a submission on
Friday — against a résumé tailored with Monday's profile, for a job that
may have closed in between.

Two columns close that (`e3f4a5b6c7d8`):

* **`expires_at`** — when the approval stops being valid. Past it, the
  request is **expired**: not *rejected* (a human said no) and not
  *pending* (nobody said anything). A decision was made, and it is no
  longer valid.
* **`profile_version`** — the digest of the profile facts the payload
  was built from. An approval is bound to the profile it was approved
  against; if the candidate edits their profile afterwards, the
  approval no longer matches what it authorized.

Two properties of the window:

* It is measured from **creation**, not from approval. A request that
  sat pending for six days gets one day when it is finally approved,
  not a fresh week — the decision was made about a payload that is six
  days old.
* The TTL is configurable (`APPROVAL_TTL_HOURS`, default 168). A bad
  value falls back to the default rather than failing the request.

An approval with **no** expiry is never expired. The column is nullable
because a row created before this workstream has none, and refusing to
execute it on that basis would strand every existing approval.

The approve route now writes the `expired` state, records the refusal in
the audit trail, and answers `409`.

---

## 5. Phase 4 — The board registry

The three environment lists say *which* boards to watch. They cannot say
whether a board is **healthy**, and that is what the corpus needs.

`job_boards` (migration `d2e3f4a5b6c7`) is a **shared** table — like
`jobs`, not owner-scoped — carrying the board's identity, its display
name, whether it is enabled, its last success, its last error, its
consecutive-failure streak and how many listings it contributed.

The env lists become the **seed**; the adapters read the registry and
fall back to the env list when the registry is empty (so a fresh
checkout still works). Seeding is additive, so a restart never
overwrites the registry's own health.

The registry is what makes the WS-23 **source-scoped eviction** possible:
a board that is failing is excluded from eviction while it is failing.

---

## 6. Phase 5 — The verified boards

Every slug was verified live on 2026-11-10: the endpoint answered 200,
the payload parsed, and the jobs belonged to the named company. A slug
that does not resolve is a dead board, not a warning.

**Greenhouse** — `brave` (10 jobs), `sourcegraph91` (7).

**Lever** — `shieldai` (662), `angellist` (32), `contentsquare` (28).

**Ashby** — `linear` (32), `cursor` (120), `elevenlabs` (136), `ramp`
(169), `clerk` (2), `vanta` (80), `close` (6), `render` (35).

The requested list needed four corrections, and the corrections are the
interesting part:

* **`sourcegraph` is not a Greenhouse board.** The token 404s; the real
  board is **`sourcegraph91`**. A board token is not the company name.
* **`figma` is on Greenhouse, not Lever.** Its Lever board 404s.
* **`close` and `render` are on Ashby, not Lever.** Their Lever boards
  404.
* **`hotjar` no longer exists as a board.** Hotjar was acquired by
  Contentsquare; its postings live on the **`contentsquare`** Lever
  board.
* **`vanta`, `postman` and `dbtlabs` are not on Greenhouse.** Vanta is
  on Ashby; Postman publishes no board at all; dbt Labs' careers page
  links to **fivetran's** Greenhouse board, not its own.

The Remotive company targets (Doist, Buffer, DuckDuckGo, Ghost) are not
Remotive candidates: Remotive is a general remote-job aggregator whose
live catalogue holds **12 listings**, and none of the four companies
appears in it.

---

## 7. Acceptance

| Check | Test |
|---|---|
| An approval carries an expiry | `tests/test_ws25_approval_expiry.py` |
| The window is measured from creation | `tests/test_ws25_approval_expiry.py` |
| An expired approval is not executable | `tests/test_ws25_approval_expiry.py` |
| An approval without an expiry still works | `tests/test_ws25_approval_expiry.py` |
| The profile version moves when the facts move | `tests/test_ws25_approval_expiry.py` |
| The form schema is read from the payload | `tests/test_ws25_approval_expiry.py` |
| Consent questions are never answered | `tests/test_ws25_approval_expiry.py` |
| The location questions are recognized | `tests/test_ws25_approval_expiry.py` |
| A multi-select option value is a string | `tests/test_ws25_approval_expiry.py` |
| A Greenhouse job URL is parsed safely | `tests/test_ws25_approval_expiry.py` |
| A past deadline means the job is not live | `tests/test_ws25_approval_expiry.py` |
| The whole suite is green | `pytest` |
| Lint is clean | `ruff check src tests scripts` |

---

## 7a. Deviations — what this workstream did **not** finish

Recorded rather than left implicit. Each item names what exists, what is
missing, and why.

### 7a.1 The form schema is a **library**, not yet a **feature**

`src/applications/greenhouse_forms.py` parses the schema and
`GreenhouseAdapter.fetch_form_schema` fetches it — both verified live
against stripe, anthropic and databricks (2026-11-10). But **neither is
called from the application flow**. `POST /api/applications/prepare` still
builds the payload from the fixed field map, and no route returns a form
schema to the console.

The consequence is precise: the schema is **readable but not surfaced**.
The three rules in §2 are implemented in the parser
(`FormQuestion.needs_consent`, `FormQuestion.is_location`) but nothing
consumes them yet, so a custom required question still does **not** stop
the flow with `blocked_human_review`.

**Why it stopped here.** The prepare path is a security boundary: it
validates the target domain, selects the adapter, builds the payload and
persists the approval row. Adding a live network fetch to it changes its
failure modes (a board that is slow or down would slow or fail a
*prepare*), and the route has no timeout story of its own. Doing that
properly is the same work as the M5 pilot's liveness check being called
from the approval route — which is the natural place for it, and is not
yet wired either.

**What remains.** Wire `fetch_form_schema` into the prepare step behind
the same timeout the rest of the outbound HTTP uses; classify each
question through `src/applications/questions.py`; return the per-question
plan in the prepare response so the console can show it; and route an
unanswerable required question to `blocked_human_review`.

### 7a.2 The closed-job check is a **library**, not yet a **gate**

`GreenhouseAdapter.check_job_is_live` works and was verified live (a real
stripe job reports live; a non-existent id reports 404). It is **not
called from the approve route**, so a closed job is still not blocked at
the point of submission.

The corpus has no expiry signal either (WS-23, Phase 6 — also not
finished), so a posting closed months ago is still in the corpus, still
ranked, and still has a valid application URL.

**What remains.** Call the check in the approve route, alongside the
WS-25 approval-expiry check, and treat a dead job as a `409` that
requires a fresh prepare.

### 7a.3 The "top asked questions" measurement is **not** built

The schema is a source of **real** question labels — the board's own
words for what it asks — and the project currently asks the user for a
**guessed** set of fields (`src/resume/application_profile.py`:
`seniority_level`, `current_title`, `legally_authorized`,
`requires_sponsorship`, `citizenship_status`, `expected_currency`,
`notice_period_days`, …). Nothing measures which of those the boards
actually ask, and nothing measures what the boards ask that the profile
does **not** cover.

**The measurement was taken** (2026-11-11, 12 live Greenhouse boards, 12
jobs each): **310 distinct question labels**, 1,455 question occurrences.
The distribution:

| Label | Seen | Taxonomy category | Covered? |
|---|---|---|---|
| First Name | 142 | `unknown` | **no** |
| Last Name | 142 | `unknown` | **no** |
| Email | 142 | `email` | yes |
| Phone | 142 | `phone` | yes |
| Resume/CV | 142 | `unknown` | **no** |
| Cover Letter | 118 | `unknown` | **no** |
| Location | 99 | `location` | yes |
| LinkedIn Profile | 93 | `linkedin_url` | yes |
| Gender | 83 | `eeo_gender` | yes — never autofill |
| VeteranStatus | 72 | `unknown` | **no** |
| Race | 72 | `eeo_race` | yes — never autofill |
| How did you hear about this job? | 40 | `unknown` | **no** |
| Preferred First Name | 39 | `unknown` | **no** |
| Website | 24 | `portfolio_url` | yes |
| Additional Information | 21 | `unknown` | **no** |
| Who is your current or previous employer? | 12 | `unknown` | **no** |
| What is your current or previous job title? | 12 | `unknown` | **no** |
| Please select the country where you currently reside. | 12 | `country` | yes |
| Are you authorized to work in the location(s) … | 12 | `work_authorization` | yes |
| Will you require … to sponsor you for a work permit … | 12 | `visa_sponsorship` | yes |

**10 of the 22 most-asked labels are unclassified, covering 740 of 1,455
occurrences (51%).** The five biggest gaps are `First Name`, `Last Name`,
`Resume/CV`, `Cover Letter` and `VeteranStatus`.

Two of the gaps are **structural, not a taxonomy gap**:

* `First Name` / `Last Name` — the profile has a name, but the taxonomy
  classifies "First Name" as `unknown` because the rule looks for
  "full name" / "legal name" / "candidate name". A one-word title split
  is a real form question and needs its own answer source.
* `Resume/CV` / `Cover Letter` — the taxonomy has `RESUME` and
  `COVER_LETTER` categories, but the labels do not match the patterns
  (`"Resume/CV"` is not matched by a "resume" pattern that requires a
  word boundary, and `"Cover Letter"` is not matched at all). These are
  the two highest-frequency questions after the name fields.

`VeteranStatus` is a third: it is an EEO question (never autofill) but
the taxonomy does not recognise it, so it would currently be
`unknown` rather than `eeo_veteran` — the wrong *reason* to leave it to a
human, though the same outcome.

**What remains.** A `form_questions` observation table (board, label,
field name, type, required, seen-at, count); a sweep that records the
schema of the boards the operator watches; taxonomy rules for the
unclassified labels above (and for the `First Name` / `Last Name`
answer source); and an endpoint that returns the most-asked questions
**the profile does not currently answer**, so the console asks for those
first instead of a guessed list.

This is the highest-value thing left in this workstream, and it is the
one that would change what the user is actually asked. **It was built
in §10 (WS-25b)** — the store, the sweep script and the gap endpoint
all exist, and the taxonomy gaps it exposed are fixed.

### 7a.4 The other providers' schemas are **not** available

Lever exposes none (its `eeo[...]` and `surveysResponses[...]` structures
are undocumented and only obtainable by scraping the hosted form's HTML);
Ashby's form definition is behind an authenticated API
(`POST /jobPosting.info` → `results.applicationFormDefinition`). So the
"top asked questions" measurement covers **Greenhouse boards only** until
another provider publishes a key-less schema.

### 7a.5 `experience_requirements` is still 0%

WS-23, Phase 3c is partly unfinished: the boards publish
`employment_required` / `employment_optional` on only some of them, and
the value mined from the description is **not** written back to the row.
The experience component therefore still mines the description at search
time, at ~1.4 ms per listing.

---

## 8. Out of scope

- **A real submission.** `GreenhouseAdapter.submit` still refuses: a
  real Greenhouse submission needs an API key (Basic Auth), and the
  permission registry refuses the call before it arrives. This
  workstream reads the board's public API; it does not submit.
- **The browser form walk for a real board.** The form *schema* is
  read; filling the hosted form is WS-08's browser layer and the M5
  pilot's job.
- **The other providers' form schemas.** Lever exposes none (its
  hosted form's `eeo[...]` and `surveysResponses[...]` structures are
  undocumented and only obtainable by scraping the HTML), and Ashby's
  form definition is behind an authenticated API
  (`POST /jobPosting.info` → `results.applicationFormDefinition`).

---

## 9. Follow-up phase (WS-25b) — Wire the two libraries, and measure the questions

§7a lists three things this workstream built but did not connect. This is
the follow-up that connects them. It is the difference between *"the
schema is readable"* and *"the operator sees the real form"*.

### 9.1 — Wire the form schema into prepare

`GreenhouseAdapter.fetch_form_schema` and
`src/applications/greenhouse_forms.build_form_schema` have **zero callers
outside their own modules** (verified: `grep -rn fetch_form_schema src/`
returns only the definition). The prepare route builds the payload from
the fixed field map and shows the operator a summary of *our* fields, not
the board's form.

**The change.** In `POST /api/applications/prepare`, after the adapter is
selected and before the approval row is persisted:

1. If the adapter exposes `fetch_form_schema`, fetch it — **bounded by the
   same timeout the rest of the outbound HTTP uses** (`job_source_timeout`,
   default 15 s), and **fail soft**: a board that is slow or down must not
   fail a *prepare*. A missing schema degrades to the current behaviour.
2. Classify every question through `src/applications/questions.py`.
3. Build a per-question plan: `answerable` (the profile has a grounded
   fact), `needs_human` (required, and the profile does not answer it),
   `never_autofill` (consent / EEO), `unknown` (not recognized).
4. Persist the plan in the approval row, and return it in the prepare
   response so the console can render the real form.
5. If a **required** question is unanswerable and is not
   `never_autofill`, set the approval's state to `blocked_human_review` —
   the status the fake-ATS adapter already uses. The flow stops with a
   reason the operator can act on, instead of discovering the gap at
   submission.

**Why the timeout and the fail-soft matter.** The prepare route is a
security boundary that currently makes **no network call**. Adding one
changes its failure modes, and the honest way to add it is to make the
call bounded, optional, and never able to turn a prepare into a failure.

**Acceptance.** A mocked board with a custom required question produces
`blocked_human_review` naming that question. A board that times out
produces a normal prepare with the schema absent, and says so.

### 9.2 — Wire the liveness check into approve

`check_job_is_live` is also uncalled. The approve route already has the
WS-25 expiry gate (`_expire_if_stale`); the liveness check belongs beside
it:

1. Before the approval is executed, re-fetch the job.
2. A 404, or a past `application_deadline`, means the job is gone: answer
   `409` with the reason, and record the refusal in the audit trail — the
   same shape as the expiry refusal.
3. A board that cannot be reached is **not** a dead job: a transport
   failure degrades to "cannot verify", which the operator sees, rather
   than silently blocking every approval during an outage.

That last distinction is the whole point. The corpus has no expiry signal
(WS-23 §11.2), so this is the only check that stops an application to a
posting closed months ago — and it must not become a way to block all
approvals whenever a board is flaky.

### 9.3 — Measure the questions the boards actually ask

The profile currently asks the user a **guessed** set of fields
(`src/resume/application_profile.py`). The boards' own schemas state what
they actually ask. The measurement was taken as a probe (§7a.3) and
showed **310 distinct labels across 12 boards, with 10 of the 22
most-asked labels unclassified — 51% of occurrences**. This phase makes
that a stored, repeatable measurement instead of a one-off probe.

**The store.** A `form_questions` table (migration `f4a5b6c7d8e9`), shared
like `jobs` and `job_boards` — the questions are a property of the boards,
not of a user:

| Column | Purpose |
|---|---|
| `id` | `"{ats}:{board}:{normalized_label}"` |
| `ats`, `board` | Which board asked it |
| `label` | The board's own wording, verbatim |
| `field_name` | `first_name`, `question_69650990`, … |
| `field_type` | `input_text`, `multi_value_single_select`, … |
| `required` | As the board marks it |
| `block` | `questions` / `location_questions` / `compliance` / `demographic_questions` |
| `category` | The taxonomy verdict at record time |
| `first_seen_at`, `last_seen_at`, `times_seen` | Accumulated observation |

**The sweep.** `scripts/measure_form_questions.py` walks the boards in the
registry, fetches each job's schema (bounded, paced, and **respecting the
same per-host rate limit as the refresh**), and upserts the observations.
It is an operator command, not part of the nightly refresh: it costs one
request per job, so it runs deliberately.

**The read.** `GET /api/profiles/{profile_id}/question-gaps` returns the
questions ranked by frequency, **excluding the ones the profile already
answers** and labelling the rest:

```json
{ "questions": [
    { "label": "Cover Letter", "times_seen": 118, "required": false,
      "category": "unknown", "coverage": "unclassified" },
    { "label": "VeteranStatus", "times_seen": 72, "required": false,
      "category": "unknown", "coverage": "should_be_eeo" }
] }
```

**The taxonomy work this exposes.** Two of the biggest gaps are
*structural*, not oversights, and they need fixing before the read is
useful:

* `First Name` / `Last Name` (142 each) — the taxonomy looks for "full
  name" / "legal name"; a split name has no answer source in the profile.
* `Resume/CV` (142) and `Cover Letter` (118) — the `RESUME` and
  `COVER_LETTER` categories exist but their patterns do not match these
  labels.
* `VeteranStatus` (72) — an EEO question the taxonomy does not recognize,
  so it is `unknown` rather than `eeo_veteran`. Same outcome (left to a
  human), wrong reason.

**The console.** The profile screen's question list is ordered by the
measured frequency instead of the guessed order, and each entry says why
it is being asked ("asked by 118 of the boards you watch"). A question
the profile cannot answer and the boards never ask is **not** shown.

### 9.4 — Acceptance

| Check | Test |
|---|---|
| A required custom question blocks the prepare with a named reason | `tests/test_ws25b_prepare_gate.py` |
| A board that times out does not fail the prepare | `tests/test_ws25b_prepare_gate.py` |
| A gone job blocks the approval with 409 + an audit row | `tests/test_ws25b_approve_gate.py` |
| An unreachable board does not block the approval | `tests/test_ws25b_approve_gate.py` |
| A consent question is never answered, and is surfaced | `tests/test_ws25b_prepare_gate.py` |
| The measurement upserts and accumulates `times_seen` | `tests/test_ws25b_questions.py` |
| The gap read excludes what the profile already answers | `tests/test_ws25b_questions.py` |
| The taxonomy classifies the ten measured gaps | `tests/test_ws25b_questions.py` |
| The whole suite is green | `pytest` |

### 9.5 — Out of scope

- **Lever and Ashby form schemas.** Neither publishes one (§7a.4), so the
  measurement covers Greenhouse boards only.
- **Auto-answering the questions.** The measurement changes *what the user
  is asked*; it does not let the agent answer more.

---

## 10. WS-25b — what was delivered (2026-11-11)

### 10.1 The form schema is wired into prepare

`POST /api/applications/prepare` now reads the board's **own** form and
returns a per-question plan in its response:

```json
{
  "status": "blocked_human_review",
  "form_questions": [
    {"label": "Email", "verdict": "answerable", "answer_from": "email", "required": true},
    {"label": "Why do you want this role?", "verdict": "needs_human", "required": true},
    {"label": "VeteranStatus", "verdict": "never_autofill", "required": false}
  ],
  "blocking_questions": ["Why do you want this role?"]
}
```

Four verdicts, and the distinctions are the point:

| Verdict | Meaning | Blocks? |
|---|---|---|
| `answerable` | a grounded profile fact answers it | no |
| `needds_human` | **required** and the profile does not answer it | **yes** |
| `never_autofill` | consent / EEO / attestation | **no** — the human answers it |
| `optional_unanswered` | unanswerable, and the form does not require it | no |

`never_autofill` is not a blocker on purpose: a consent question is the
approver's to answer, so its presence must not stop the flow. But it is
also not overridable by supplying the fact — a test asserts that a
`veteran_status` value in the facts does **not** make the question
answerable, because the prohibition is on the *question*.

**Fail-soft, bounded.** The route made no network call before this. A
board that times out, answers with nothing, or publishes no schema
(six of the seven providers) degrades to the fixed field map. A test
injects a `TimeoutError` and asserts the prepare still returns.

### 10.2 The liveness check is wired into approve

The approve route now re-fetches the job beside the expiry gate, and the
distinction it draws is the whole design:

| Board says | Outcome |
|---|---|
| 404 | **409** — the job is gone |
| deadline passed | **409** |
| live | proceed |
| **could not be reached** | **proceed** — an outage is not a closed job |

Without that last row, a flaky board would become a way to block every
approval. The check is Greenhouse-only (the other providers publish no
liveness endpoint), and a provider with no check proceeds rather than
blocking.

### 10.3 The measured questions

`src/db/form_questions.py` (migration `f4a5b6c7d8e9`) stores the
questions the boards actually ask; `scripts/measure_form_questions.py`
populates it; `GET /api/profiles/{profile_id}/question-gaps` reads the
gaps ranked by frequency.

**The measurement, run live against 3 boards / 18 jobs:**

| | Before this workstream | After |
|---|---|---|
| Labels measured | 0 (a one-off probe in a chat log) | **347 occurrences stored** |
| Most-asked labels unclassified | **10 of 22 (51% of occurrences)** | **2** |

The taxonomy fixes are in `src/applications/questions.py`:

| Label | Was | Now |
|---|---|---|
| `First Name` | `unknown` | `candidate_first_name` |
| `Last Name` | `unknown` | `candidate_last_name` |
| `Resume/CV` | `unknown` | `resume` |
| `Cover Letter` | `unknown` | `cover_letter` |
| `VeteranStatus` | `unknown` | **`eeo_veteran` (never autofill)** |
| `Preferred First Name` | `unknown` | `candidate_first_name` |
| `Latitude` / `Longitude` | `unknown` | `location_latitude` / `location_longitude` |

`VeteranStatus` is the instructive one: before, it was `unknown`, which
*also* left it to a human — but for the wrong **reason**. The console
could not tell "we must not answer this" from "we do not know what this
is", and those mean different things to an operator.

`First Name` / `Last Name` needed new **categories**, not just patterns:
the profile stores one `name`, so a split has to happen in the answer,
and `CATEGORY_FACT_KEYS` now points both at the stored full name.

### 10.4 What remains

The gaps the measurement reports are now real, and they are the honest
to-do list:

* `Latitude` / `Longitude` are `not_in_profile` — the profile has a
  location string and no coordinates, and Greenhouse ignores `location`
  without them.
* `First Name` / `Last Name` classify correctly but read
  `not_in_profile` for a profile whose name field the fact map does not
  yet populate.
* The **console** still renders the guessed field order. The endpoint
  exists; the profile screen has not been changed to call it.
