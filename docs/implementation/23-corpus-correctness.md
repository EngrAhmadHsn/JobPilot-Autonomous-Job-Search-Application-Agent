# WS-23 · Corpus Correctness, Field Completeness & Source Health

Status: **Done (2026-11-11)** — Phases 0–6 plus the WS-23b follow-up in §12 · Milestone: **M5** · Depends on: WS-02 (boards), WS-12 (limits), WS-15 (corpus cap), WS-18 (durable queue), WS-20 (matching) · Live-verified: against the local corpus and live board endpoints · **Deviations in §11, follow-up in §12 (WS-23b)**. Phase 6's expiry signal landed in WS-23b (the age bound, `first_seen_at`, the approval-gate liveness check), and §11.1's unfinished field is finished by ingest-time mining. **Still open and deferred:** §11.3 (cross-source dedup — now owned by WS-26 Phase 2) and §11.4 (the operator role-family allowlist, not needed inside the 50,000 cap)

> The corpus is not too small. It is **wrong**.
>
> Measured on the live local database (`app.db`, 6,696 listings, 6,696 Chroma
> vectors) on 2026-11-09: **1,696 listings (25.3%) belong to boards the
> system can no longer fetch**, and every one of them has a NULL
> `last_seen_at`. The cause is a single configuration value. The
> `MAX_RESPONSE_BYTES` cap of 8 MiB is below the size of three live boards
> — `anthropic` (9.83 MiB), `databricks` (9.58 MiB) and `ashby/openai`
> (13.58 MiB) — so each of those boards raises `SourceError`, the adapter
> logs it as "board unavailable", and **the whole board disappears without
> an error the operator would notice**.
>
> Worse, the eviction policy then selects exactly those rows for deletion.
> SQLite sorts NULLs first in `ORDER BY last_seen_at ASC`, so the rows that
> failed to refresh are the **first** candidates for eviction — 45.4% of
> the corpus is currently queued in that order, and the first 5,000
> candidates include **all 1,069 Ashby rows and 3,864 Greenhouse rows**.
>
> This workstream fixes the corpus. It does not expand it.

---

## 1. Phase 0 — The defect matrix (measured, 2026-11-09)

Every row is a measured fact about the running system, not an inference.

| # | Defect | Evidence | Impact |
|---|---|---|---|
| **C1** | `MAX_RESPONSE_BYTES` (8 MiB) is below the size of 3 live boards | `anthropic` 9.83 MiB, `databricks` 9.58 MiB, `ashby/openai` 13.58 MiB (live GETs) | **1,696 rows (25.3%) unreachable.** The board is dropped whole; the log says "unavailable" |
| **C2** | Eviction orders by `last_seen_at ASC`, and SQLite sorts NULL first | `src/db/jobs.py:194-201`; preview of the first 5,000 candidates: greenhouse 3,864, ashby 1,069 (100%), lever 45, remotive 21 | The policy selects **the rows that failed to refresh**. 45.4% of the corpus is queued |
| **C3** | The `last_seen_at` migration has no backfill | `migrations/versions/c3d4e5f6a7b8_ws15_job_last_seen.py:41-42` — `add_column` + index only | 3,042 rows carry a NULL that predates the column |
| **C4** | A source's failure ages out that source's rows | Eviction is global; there is no per-source health | If Greenhouse 403s, its 5,255 rows age out together and are deleted |
| **C5** | No per-board registry, only three env lists | `src/config/settings.py:100-106` | No board health, no per-board policy, cannot scale past a few dozen boards |
| **C6** | `seniority`, `experience_requirements`, `currency` are **never** written | 0/6,696 rows non-null (measured) | The `seniority` component (weight 0.08) is always `JOB_REQUIREMENT_MISSING` → 0 |
| **C7** | `preferred_skills` is never non-empty | 0 rows (measured) | The skill component's half-weight preferred channel is dead |
| **C8** | `remote_policy` is set for Ashby + Remotive only | greenhouse 0/5,255, lever 0/350 (measured) | The location component (weight 0.09) takes the `else: value = 40.0` branch (`src/matching/engine.py:359`) for **78.5%** of the corpus — a *measured* 40, not an unknown |
| **C9** | `employment_type` is 0% for Greenhouse | greenhouse 0/5,255 (measured) | The preference component (weight 0.08) is unknown for 78.5% of the corpus |
| **C10** | `salary` is 0.19% (13 rows, Remotive only) | measured | The preference component's salary half is dead |
| **C11** | The Greenhouse adapter matches a metadata key named `"employmentType"` | `src/jobs/greenhouse_adapter.py:71-89` | **No board in the registry uses that name.** Across 11 boards / 4,406 jobs the key appears **0 times**. The real keys are per-board (`Employee Type`, `Position open to remote`, `Workplace Type`, `Location Type`, `Job Posting Location`) |
| **C12** | The refresh path fetches a whole board with `?content=true` | `src/jobs/greenhouse_adapter.py:178-199` (single-pass, empty query) | One oversized board kills the whole board. O(all jobs) requests per refresh |
| **C13** | No expiry signal | No `first_seen_at`, no status column, no closed-job detection; `posted_at` spans 2026-06-23 → 2026-11-07 | A June posting closed in July still ranks. **This is the most likely first M5 pilot failure** |
| **C14** | Remotive's query parameters are inert | Live: `?search=`, `?limit=`, `?category=`, `?company_name=` all return **byte-identical** bodies (204,646 B). The endpoint serves a static file | `src/jobs/remotive_adapter.py` claims *"Remotive filters server-side via the `search` parameter"* — it does not. Every query returns the whole board |
| **C15** | `jobs` rows are not referenced by any FK | `PRAGMA foreign_key_list` empty for `applications`, `job_matches`, `approval_requests` | The `manual:` stub row has a NULL `last_seen_at`, so it is **evicted first** — and 39 `applications` rows reference it |

### The field-population table that drives Phase 2

Measured on all 6,696 rows, **per source**:

| Source | rows | `remote_policy` | `employment_type` | `salary` | `seniority` | `experience_req` |
|---|---|---|---|---|---|---|
| greenhouse | 5,255 | **0.0%** | **0.0%** | 0.0% | 0.0% | 0.0% |
| ashby | 1,069 | 68.6% | 100.0% | 0.0% | 0.0% | 0.0% |
| lever | 350 | **0.0%** | 100.0% | 0.0% | 0.0% | 0.0% |
| remotive | 21 | 100.0% | 100.0% | 61.9% | 0.0% | 0.0% |
| manual | 1 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

**The ranking bias is now measurable, not theoretical.** A Greenhouse row and
an Ashby row describing the same job score differently *because the adapters
differ*, not because the jobs differ. That is the trap: adding a new,
field-rich adapter before fixing the existing ones would make the new
source look better than it is.

---

## 2. Phase 1 — The two configuration changes (the acute fix)

**1a. `MAX_RESPONSE_BYTES` 8 MiB → 16 MiB.**

Measured board sizes at the time of writing:

| Board | Size | 8 MiB | 16 MiB |
|---|---|---|---|
| greenhouse/anthropic | 9.83 MiB | **dropped** | ok |
| greenhouse/databricks | 9.58 MiB | **dropped** | ok |
| ashby/openai | 13.58 MiB | **dropped** | ok |
| greenhouse/cloudflare | 7.87 MiB | ok (200 KB of headroom) | ok |

16 MiB clears every board in the current registry with headroom. It is
still a bounded value, and the response-size assertion
(`src/jobs/http_client.py:185-208`) stays exactly where it is: the cap
grows, the control does not move.

**1b. The embedded-document length 8,000 → 16,000 characters.**

`MAX_DESCRIPTION_CHARS = 8_000` in `src/rag/chroma_store.py:52` truncates
the description before it is embedded. The local model is EmbeddingGemma-2
with an **8,192-token** input limit — 8,192 *tokens* is roughly 32,000
characters of English prose, so the 8,000-character cap was the binding
constraint by a factor of four, not the model.

The contract cap (`max_description_chars`, default 20,000) is separate and
stays: the contract protects the **stored** description, the store cap
protects the **embedded** text. 16,000 is the embedded length.

**Consequence — the embedding space changes.** A longer embedded document
produces a different vector for the same listing, so every stored vector
becomes stale. This is a version-locked space (`VectorStoreMismatch`), and
the migration is: bump the cap, then re-embed the corpus through the normal
`scripts/embed_store_gaps.py` path, which computes the content hash and
rewrites only what changed.

**Gate:** `anthropic`, `databricks` and `ashby/openai` fetch successfully;
the 1,696 orphaned rows are re-seen and their `last_seen_at` is no longer
NULL.

---

## 3. Phase 2 — Eviction correctness

### 2a. Exclude never-seen rows from eviction (the acute half)

Two rules, both applied to the candidate query:

1. **Never evict a row whose `last_seen_at` is NULL.** A NULL means *"we
   have no evidence this listing is live"* — that is an argument for
   **investigating**, not for deleting. Today it is an argument for
   deleting first.
2. **Never evict a row belonging to a source that is currently failing.**

Rule 1 alone ends the current mass-deletion risk immediately, because
45.4% of the corpus has a NULL and would otherwise be the first 5,000
candidates.

### 2b. Source-scoped eviction (the policy half)

A board that starts returning 403 must not age out its own coverage. The
eviction candidate set becomes:

```
ORDER BY last_seen_at ASC
  WHERE last_seen_at IS NOT NULL
    AND source NOT IN (sources currently failing)
```

A source is "currently failing" when its board health row records a
consecutive-failure streak above the threshold **and** the breaker for its
host is open. Both conditions, so a single transient blip does not protect
a dead source forever (the breaker recovers; the streak resets on success).

### 2c. The backfill

A migration backfills `last_seen_at` for the rows that predate the
column. The backfill value must be **honest**: the row was last seen at
some point before the column existed, and the only evidence of that is the
row's own `posted_at` or the migration time. The migration uses the
migration timestamp — which is the conservative choice, because it makes
those rows *recently seen* and therefore **not** immediate eviction
candidates, while the delta refresh in Phase 4 re-sees them properly.

### 2d. Preserve referenced rows

A row referenced by an `applications` row must not be evicted. There is no
FK (C15), so the guard is explicit: the eviction excludes any `job_id`
that appears in `applications`, `job_matches` or `approval_requests`.

**Gate (reproducing test first, as agreed):** a test that fills the corpus
past the cap with one source failing, runs a refresh, and asserts that
the failing source's rows are **still present** while a healthy source's
stale rows are evicted. The test fails against the current code.

---

## 4. Phase 3 — Field completeness on the existing adapters

The premise of this phase: **the data is already in the payload.** Phase 1
of the audit found that the Greenhouse metadata keys are **per-board**,
not standardized (C11), and that the metadata is present in the
**light-list** response — the one the refresh already fetches.

Measured metadata keys per board (live, light list):

| Board | Keys present |
|---|---|
| airbnb | `Workplace Type` (205/205), `Is this job part of ACC?` |
| block | **`Position open to remote` (200/200)**, **`Employee Type` (200/200)** |
| anthropic | `Location Type` (677/677) |
| cloudflare | `Job Posting Location` (465/465) |
| asana | `Careers Page: Location`, `Careers Page: Team` |
| databricks | `Company Assignment`, `Career Page Posting Category` |
| coinbase | `Team`, `Careersite Department (for job postings)` |
| gitlab | `Quota Coverage Type` |
| adyen, figma, stripe | *(none)* |

### 3a. A per-board metadata mapping table

A declarative table, in the project, mapping a board token to the metadata
key that carries each concept. This is a **policy file**, not code, because
the keys differ per board and change without notice.

```
board            remote_policy_key            employment_type_key
airbnb           Workplace Type               -
block            Position open to remote     Employee Type
anthropic        Location Type                -
cloudflare       Job Posting Location         -
```

The resolution is: try the board's configured key → fall back to a small
set of **alias** keys observed across boards → else leave the field
**honestly unknown**. A global lookup of one key name is what produced
C11, and it must not be repeated.

### 3b. `seniority` — a deterministic classifier

`seniority` is 0/6,696 and carries weight 0.08. It is derived, not
fetched: a deterministic title classifier (intern / junior / mid / senior /
staff / principal / lead / director / head / vp / cto), implemented in
Python with a regex ladder and an `lru_cache`. No model reasoning — the
architecture rule is that business logic lives in code.

The classifier must be **conservative**: an unrecognized title leaves the
field NULL rather than guessing "mid". A wrong seniority is worse than an
unknown one, because the unknown is visible in `evidence_coverage`.

### 3c. `experience_requirements`

Greenhouse publishes an `employment` enum on some boards (live:
`employment_required`, `employment_optional` on dropbox/lyft) and an
`education` enum (`education_required`, `education_optional`). These map
to `experience_requirements` / `education_requirements` directly.

When the board does not publish them, the field is mined from the
description by the existing `src/matching/experience.py` machinery — but
the mined value is stored on the row, so the matching layer reads a field
instead of re-mining per search. That removes `required_years` (9.5 s of
the 32.6 s artifact rebuild) from the per-search path.

### 3d. `salary` and `currency`

- **Greenhouse**: `?pay_transparency=true` → `pay_input_ranges[]` with
  `min_cents`, `max_cents`, `currency_type`, `title`, `blurb`. Live:
  dropbox publishes ranges; stripe, lyft and block return `[]`. This is
  board-specific and sparse — **a board that does not publish pay is not a
  failure**, it is a fact about the board.
- **Lever**: `salaryRange{min, max, currency, interval}` and
  `salaryDescription` — both currently unused.
- **Ashby**: `includeCompensation=true` →
  `compensation.compensationTiers[].components[]` with `minValue`,
  `maxValue`, `currencyCode`, `interval` — currently unused.
- **Remotive**: a free-text string (`"$25k - $35k"`, `"$50-$75 /hour"`,
  `"$35,3k- $52k"` — note the European decimal comma). It is parsed
  tolerantly into `salary` + `currency`, and the raw string is retained in
  `extra_metadata`.

`currency` becomes fillable for the first time.

### 3e. The `location` fallback must stop asserting 40

`src/matching/engine.py:359` returns `value = 40.0` when the policy is
unknown. Under a fixed denominator that is a **measured** PARTIAL_MATCH,
not an unknown — so a fully-remote Greenhouse job is penalised 5.4 points
against an identical remote Ashby job.

The fix has two halves:
1. **Populate** the field (3a) so the true value is known.
2. When the field is **still** unknown, report `JOB_REQUIREMENT_MISSING`
   (value 0, weight kept) instead of asserting 40. This is the honest
   reading of "the listing states no location or work mode" — and it is
   what the existing `evidence_coverage` metric is for.

Note the effect: after this change a Greenhouse row with no remote signal
scores *lower* than today (0 instead of 40 for the location component).
That is correct. Today the flat 40 is a hidden subsidy for sparse rows;
after the fix, `evidence_coverage` shows the truth and the console can
surface it.

### 3f. Lever `workplaceType`

Live Lever data has a top-level `workplaceType` field with values
`hybrid` / `onsite` / `remote` / `unspecified` — currently unused. It maps
directly to `remote_policy` and is **authoritative**, better than inferring
from the description text.

### 3g. Lever `lists[]`

`lists[]` is where the requirements bullets live — `{text: "Skill Set:",
content: "<li>3+ years of…</li><li>…</li>"}`, a bare `<li>` sequence with
no wrapping `<ul>`. This is the **best structured requirements source of
the four providers** and is currently discarded. It feeds
`preferred_skills` (C7) and `required_skills`.

**Gate:** `seniority`, `experience_requirements`, `currency` and
`preferred_skills` are non-zero across the corpus; `remote_policy` and
`employment_type` cover Greenhouse and Lever; the location component no
longer asserts a value it did not measure.

---

## 5. Phase 4 — A delta refresh on `updated_at`

**The 8 MiB cliff disappears if the refresh stops fetching whole boards.**

Greenhouse's light list (`?content=false`) carries `updated_at` per job and
is small: every board in the registry is between 91 KB and 792 KB — an
order of magnitude below the cap. The refresh becomes:

1. Fetch the **light list** for each board (never over the cap).
2. Compare each job's `updated_at` against the stored value.
3. Fetch the **detail** (`?content=true`) only for jobs whose
   `updated_at` changed, or that have no vector yet.
4. Leave every other job untouched — it is unchanged by the board's own
   account.

This turns the refresh from **O(all jobs)** requests into **O(changed
jobs)** — which is what actually dissolves the 1-second pacing problem,
more effectively than any title filter. A board of 919 jobs that changed
3 postings costs 4 requests, not 1.

**It is also more correct** than a title filter: a title filter can
silently drop a job whose *description* changed but whose title did not,
and on the refresh path (empty query) it has nothing to filter on at all.

A second consequence: the `updated_at` value must be **stored**, so the
delta can be computed. It goes into `extra_metadata` (the existing
catch-all) rather than a new column, because it is a source-specific
detail, not a first-class matching field.

**Gate:** a refresh against a board with one changed job issues one
content request, not N.

---

## 6. Phase 5 — The `job_boards` registry

A table, shared (not owner-scoped, like `jobs`):

| Column | Purpose |
|---|---|
| `id` | `"{ats}:{slug}"` — the same identity the canonical job ids use |
| `ats` | `greenhouse` / `lever` / `ashby` / `remotive` |
| `slug` | The board token |
| `company_name` | Display name |
| `enabled` | Whether the refresh watches it |
| `last_ok_at` | The last successful fetch |
| `last_error` | The last failure message (sanitized) |
| `consecutive_failures` | The streak |
| `listings_seen` | The last count |
| `first_seen_at` | When it entered the registry |

The three env lists (`GREENHOUSE_BOARDS`, `LEVER_COMPANIES`,
`ASHBY_ORGS`) become the **seed**, not the storage. The env vars stay
readable so an operator can still bootstrap, and the registry takes over
from there.

This table is what makes Phase 2b (source-scoped eviction) and Phase 7
(health in the console) possible. It is also the precondition for
watching more than a few dozen boards: an env list cannot record health.

**Gate:** the refresh reads the registry; the env lists still seed it; a
board's health is visible in the admin surface.

---

## 7. Phase 6 — Expiry, so the pilot cannot apply to a dead job

**This is the most likely first M5 failure.** A June posting closed in July
is still in the corpus, still has a vector, still ranks, and still has a
perfectly valid application URL.

Three layers, in order of cost:

1. **Admission age.** A listing whose `posted_at` is older than
   `MAX_JOB_AGE_DAYS` (default 90) is not admitted. This is free — it
   uses a field the adapters already populate. It also keeps the corpus
   inside the embedding budget.
2. **A `first_seen_at` column.** The corpus cannot currently distinguish
   "seen for three months" from "seen once". It needs the column to
   compute an age for rows whose `posted_at` is missing (Remotive, Lever
   edge cases).
3. **Liveness re-fetch before approval** — Phase 4 of WS-25. A job that
   has closed must not be submitted to. This is the layer that actually
   protects the application, and it belongs in the approval path, not the
   ingest path.

**Gate:** a listing older than the age limit is not admitted; the corpus
can report its own age distribution.

---

## 8. Phase 7 — Remotive's dead query parameters

C14: every Remotive query parameter is inert — the endpoint serves a
static file and ignores `search`, `limit`, `category` and `company_name`.
The adapter's docstring claims server-side filtering, and its search
returns the whole board every time.

The fix is client-side filtering, matching the pattern the other three
adapters already use. Two consequences:

- The `search` filter must actually filter, or a query for "react" returns
  every Remotive job.
- Remotive's live catalog is **12 listings** (204,646 B), down from the
  thousands the board historically held. Its weight in the corpus (21
  rows, 0.3%) is accurate. Remotive is not a scale source; it is a
  remote-first supplement.

Also: Remotive's terms ask for **no more than about 4 fetches a day** and
require **credit and a link back**. The refresh schedule must respect
that, and the console must carry the attribution.

**Gate:** a Remotive query returns only the matching listings; the
adapter's docstring matches reality.

---

## 9. Acceptance

| Check | Command |
|---|---|
| Eviction never deletes a failing source's rows | `tests/test_ws23_corpus.py` |
| A never-seen row is never evicted | `tests/test_ws23_corpus.py` |
| A referenced row is never evicted | `tests/test_ws23_corpus.py` |
| The board registry seeds from the env lists | `tests/test_ws23_corpus.py` |
| The delta refresh fetches only changed jobs | `tests/test_ws23_corpus.py` |
| The location component reports unknown instead of asserting 40 | `tests/test_ws23_corpus.py` |
| Remotive filters client-side | `tests/test_ws23_corpus.py` |
| The three formerly-dropped boards fetch | `tests/test_ws23_corpus.py` (mocked) + a live run |
| The whole suite is green | `pytest` |
| Lint is clean | `ruff check src tests scripts` |

---

## 10. What the live run measured

A live refresh on 2026-11-10/11, against the 29 boards in the registry.

**Before** (measured 2026-11-09, before this workstream):

| | Value |
|---|---|
| Listings | 6,696 |
| Listings with **no** sighting | 3,042 (45.4%) |
| Boards that could not be fetched | 3 (anthropic, databricks, ashby/openai) |
| `remote_policy` populated | 754 (11.3%) |
| `employment_type` populated | 1,440 (21.5%) |
| `salary` populated | 13 (0.2%) |
| `currency` populated | **0** |
| `seniority` populated | **0** |

**After** the live refresh:

| | Value |
|---|---|
| Listings | **8,558** |
| Listings with no sighting | **0** |
| Boards that failed | **0 of 29** |
| `remote_policy` populated | **3,270 (38%)** |
| `employment_type` populated | **3,073 (36%)** |
| `salary` populated | **3,268 (38%)** |
| `currency` populated | **3,255 (38%)** |
| `seniority` populated | **4,275 (50%)** |

The three dead boards came back on their own: anthropic (675),
databricks (914) and ashby/openai (830) are now in the corpus with
their listings, and the eviction no longer selects the rows that fail.

**The delta refresh, measured against a live board** (brave, 10 jobs):

| Pass | Listings fetched | Requests |
|---|---|---|
| Nothing known | 10 | 11 |
| Everything known and unchanged | **0** | **1** |
| One job changed | **1** | 2 |

---

## 11. Deviations — what this workstream did **not** finish

Recorded rather than left implicit.

### 11.1 `experience_requirements` is still 0% (Phase 3c, partly)

The boards publish `employment_required` / `employment_optional` enums on
only **some** of them (live: dropbox, lyft and block publish them; most do
not). Where the board publishes nothing, the value is mined from the
description — but **the mined value is not written back to the row**, so
the column stays NULL and the experience component still mines the
description at search time (~1.4 ms per listing).

**What remains.** Mine the value at ingest and store it, so the matching
layer reads a field instead of re-mining. That also removes
`required_years` from the artifacts rebuild (WS-24, 9.5 s of the 32.56 s).

### 11.2 The corpus has no expiry signal (Phase 6, not started)

A listing whose `posted_at` is older than an age limit is still admitted,
and a posting that closed months ago is still in the corpus, still has a
vector, and still ranks. There is no `first_seen_at` column and no
closed-job detection.

**What remains.** An admission age bound using the `posted_at` the
adapters already populate (free — it uses a field that is already there),
a `first_seen_at` column for the rows whose `posted_at` is missing, and
the liveness re-fetch at the approval gate (WS-25, §7a.2 — the check
exists but is not wired).

### 11.3 The cross-source merge is **not** done

`src/jobs/deduplicate.py` still keys on `(source, source_job_id)`, so the
same posting on Greenhouse and on Ashby is **two rows**. The field
completion makes this more visible, not less: two rows for one job now
carry *different* field values, so they can rank differently. WS-26 Phase
2 owns this.

### 11.4 The operator role-family allowlist is **not** built

The corpus is shared, so per-user filtering at ingest is impossible; the
operator-level allowlist described in Phase 6 is not implemented. The
corpus is currently 8,558 listings — well inside the 50,000 cap — so it
is not yet needed, but it is the mechanism that would keep the corpus
inside the embedding budget as the board count grows.

---

## 10. Out of scope

- **New adapters.** WS-26, and only after this workstream is done.
- **A larger corpus.** `MAX_CORPUS_LISTINGS` stays at 50,000 until WS-24
  has re-measured what the search path can serve.
- **Automatic company discovery.** The operator curates the boards
  (SRS P188). WS-26 may *propose* boards; it may not enrol them.
- **Scraping.** Every endpoint in this workstream is a documented,
  key-less public API.

---

## 12. Follow-up phase (WS-23b) — The unfinished field, the missing expiry, and the untested registry

§11 lists what this workstream did not finish. This phase finishes it.

### 12.1 — Mine `experience_requirements` at ingest (finishes 3c)

The column is 0% populated. The boards publish
`employment_required` / `employment_optional` on only some of them, so
the value has to be mined from the description — but the **mining already
exists** (`src/matching/experience.required_years`), it is simply not
written back to the row.

**The change.** In the persist path (`merge_jobs`), when the listing
carries no `experience_requirements`, run the existing extractor once and
store the result. It is the same function the search calls per listing
today, moved from read time to write time.

**What it buys, beyond the field.** `required_years` is 9.5 s of the
32.56 s artifacts rebuild (WS-24) — the most expensive per-listing item.
Storing it means the rebuild reads a column instead of re-mining, so this
is also a WS-24 win.

**A caveat worth stating.** The mined value is an *inference*, not a
board statement. It must be recorded as such — the existing
`JOB_REQUIREMENT_MISSING` vs measured distinction in the score states is
the place to keep that honest: a mined bar is weaker evidence than a
published one, and the explanation should say which it is.

### 12.2 — An expiry signal (finishes Phase 6)

The corpus has no age bound: a posting from June closed in July is still
admitted, still ranked, and still has a valid application URL.

1. **Admission age.** A listing whose `posted_at` is older than a
   configurable `MAX_JOB_AGE_DAYS` (default 120) is not admitted. This is
   free — `posted_at` is already populated by all four adapters — and it
   keeps the corpus inside the embedding budget.
2. **`first_seen_at`.** A column, so the corpus can tell "seen for three
   months" from "seen once", and can compute an age for the rows whose
   `posted_at` is missing (Remotive, some Lever postings).
3. **The approval-gate liveness check** (WS-25b §9.2) is the layer that
   actually protects a submission. Admission age protects the *corpus*.

### 12.3 — Cross-source dedup (finishes 11.3)

`src/jobs/deduplicate.py` keys on `(kind, source, value)`, so the same
posting on Greenhouse and Ashby is two rows — and after the field
completion those two rows can carry different field values and rank
differently. This is WS-26 Phase 2's work; it is listed here because it
is this workstream's measured consequence.

### 12.4 — Test the board registry (finishes the coverage hole)

`src/db/boards.py` and `src/jobs/board_health.py` have **zero direct test
coverage** (verified: no test file references `BoardDB`, `list_boards`,
`record_board_success`, `record_board_failure` or `registry_slugs`). The
source-scoped eviction depends on this layer, so an untested health
record is an unverified guarantee.

`tests/test_ws23b_boards.py` covers: the registry seeds from the env
lists and is additive; a success resets the streak and records the
listings count; a failure increments it and sanitizes the error;
`registry_slugs` returns enabled boards only; and an empty registry makes
the adapters fall back to the env list.

### 12.5 — Acceptance

| Check | Test |
|---|---|
| Mined experience is written at ingest | `tests/test_ws23b_fields.py` |
| A washed-out listing is not admitted past the age bound | `tests/test_ws23b_fields.py` |
| `first_seen_at` is set on first sight and not moved | `tests/test_ws23b_fields.py` |
| The registry seeds additively and never overwrites health | `tests/test_ws23b_boards.py` |
| A success resets the failure streak | `tests/test_ws23b_boards.py` |
| A failure increments it and sanitizes the message | `tests/test_ws23b_boards.py` |
| `registry_slugs` returns enabled boards only | `tests/test_ws23b_boards.py` |
| An empty registry falls back to the env list | `tests/test_ws23b_boards.py` |

---

## 13. Corrections to a later review

A subsequent review of this workstream stated three things about the
working tree that are **not** true of the code as it stands. They are
recorded here so the record is accurate, with the command that settles
each one.

### 13.1 "The 16k cap never binds — the embedder still truncates at 8,000"

**False.** Both caps are 16,000, and the provider's is the one that
applies on the write path:

```
src/llm/embeddings.py:100   MAX_TEXT_CHARS = 16_000
src/rag/chroma_store.py:68  MAX_DESCRIPTION_CHARS = 16_000
```

Proven at runtime, not by reading:

```
FastembedEmbedding.MAX_TEXT_CHARS = 16000
GeminiEmbedding.MAX_TEXT_CHARS    = 16000
truncate(10000 chars) -> 10000      # under the cap: untouched
truncate(20000 chars) -> 16000      # over the cap: cut at 16k, not 8k
```

The review's claim was true of the state **before** the fix — the
provider cap was 8,000 and the store's 16,000 never bound. The fix
changed both, and the measurement above is the proof.

### 13.2 "`00-OVERVIEW.md` has no WS-23…26 rows"

**False.** All four rows exist (`grep -c` returns 4):

| WS | Row |
|---|---|
| 23 | corpus correctness — the field population 0%/11%/0.2% → 50%/38%/38% |
| 24 | search performance — 68× scan, the refresh penalty removed |
| 25 | provider depth — the form schema and liveness verified live |
| 26 | source expansion — planned, depends on WS-23 |

### 13.3 "The test files have 17 / 8 / 14 tests"

**Partly wrong.** Those are the `def test_` counts, which undercount the
**parametrized** cases. Pytest collects:

```
tests/test_ws23_corpus.py            17 defs
tests/test_ws24_search_perf.py        8 defs
tests/test_ws25_approval_expiry.py   14 defs
                                     ---
46 tests collected
```

The 46 is the number the suite runs; `test_the_free_text_salary_is_parsed`
alone expands to eight cases.

### 13.4 What the review got **right**, and this workstream now acts on

- **The board registry had no test coverage** — corrected by §12.4
  (`tests/test_ws23b_boards.py`).
- **`greenhouse_forms` / `fetch_form_schema` / `check_job_is_live` have no
  callers** — corrected by WS-25b §9.1 and §9.2.
- **`scripts/verify_sources.py` does not exist** — corrected by WS-26b
  §11.1.
- **`registry.py`'s "deduplicates across sources" overclaims** —
  corrected by WS-26b §11.2.
- **The questions measurement does not exist in any form** — corrected by
  WS-25b §9.3, which is scoped from the probe measurement in §7a.3.
- **Nothing is committed** — still true, and deliberate: the workstream
  model in this repo commits as discrete per-file commits at the end.

---

## 14. WS-23b — what was delivered (2026-11-11)

### 14.1 The unfinished field is finished

`experience_requirements` was 0% populated. The **mining** existed; it
ran at read time. It now runs once at write time and is stored in a
**separate** column:

```
jobs.required_years   -- what the system inferred from the description
jobs.experience_requirements  -- what the BOARD stated (usually nothing)
```

Separate on purpose: collapsing them would make an inference
indistinguishable from a published fact, which is the distinction the
score states exist to preserve.

**Backfilled live: 0% → 21.2% (1,817 of 8,558 rows)** in 23 s. The other
79% state no bar, which is the honest answer — `None`, not a fabricated
zero.

It also removes `required_years` from the artifacts rebuild (9.5 s of the
32.56 s), because the rebuild now reads a column.

### 14.2 The age bound

`MAX_JOB_AGE_DAYS` (default 120) drops a listing whose `posted_at` is
older than the bound, at admission, **before** the other caps — so a
washed-out listing does not consume a live one's per-source slot or
embedding budget.

Two deliberate non-drops:

* a listing with **no** `posted_at` is kept — an absent date is not
  evidence of an old listing (Remotive and some Lever postings);
* an **unparsable** date is kept — refusing on a date nobody can read
  would be a guess.

`MAX_JOB_AGE_DAYS=0` disables the bound.

### 14.3 `first_seen_at`

A column, so the corpus can tell "seen for three months" from "seen
once". `session.merge` writes every column, so the merge looks up the
existing row's first sighting and carries it forward — without that, the
column would say "first seen now" on every refresh, which is the same as
not having it. Two tests pin it: a re-sighting does not move it, and a
content change does not either.

### 14.4 The registry is tested

`tests/test_ws23b_boards.py` (13 tests) covers the layer that had **zero
coverage**: additive seeding that never overwrites health, a success
resetting the streak, a failure sanitizing its message, the enabled
filter, the per-provider read, and the env fallback for a fresh
checkout. The sanitizer test was checked to be able to **fail** — the
raw text does contain a newline and is longer than the 500-char bound.
