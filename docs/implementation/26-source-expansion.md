# WS-26 · Source Expansion — Verified Boards, Cross-Source Dedup, Source Ordering & Tier-A ATS Adapters

Status: **Plan only — the expansion is not built. WS-26b (§11) delivered** · Milestone: **M5** · Depends on: WS-23 (corpus correctness — field completeness and the `job_boards` registry, done 2026-11-11), WS-24 (search performance — done 2026-11-12), WS-18 (durable queue for staggered sync) · Live-verified: every slug and endpoint cited below was probed live on 2026-11-09/10 (read-only GETs); see the research reference notes · **Delivered in §11 (WS-26b): `scripts/verify_sources.py` and the dedup-docstring correction. Not built: Phases 2–6 — cross-source dedup, proposals, honest source ordering, the robots-aware crawl policy, and every tier-A adapter**

> The corpus is correct but **narrow**: four sources — Greenhouse (13
> boards), Lever (4 companies), Ashby (10 orgs), Remotive — **8,558
> listings** as of the WS-23 live refresh (2026-11-10; it was 6,696
> before), all from boards an operator typed into an env list. The
> research pass over
> public ATS endpoints (2026-11-09) found **28,178 keyless boards** across a
> dozen providers — BambooHR 5,168, Greenhouse 5,011, Workable 4,807, Ashby
> 3,216, Personio 2,360, Lever 1,633, Recruitee 1,448 — and a set of
> measured traps: a Greenhouse token is **not** the company name
> (`sourcegraph` 404s, `sourcegraph91` answers), a dead BambooHR tenant
> answers **200 with HTML**, Workday's API silently repeats page one past
> offset 2,000, and SmartRecruiters' robots.txt allows its API only to
> `LinkedInBot`.
>
> The expansion rule, decided in the research review: **the operator
> curates the boards; the system may only propose them** (SRS P188). This
> workstream adds the machinery that makes curation scalable — a verifier,
> a health-aware registry, cross-source dedup, honest source ordering —
> and then **one** new provider at a time, smallest-first, with Workday
> last. It refuses LinkedIn/Indeed/Glassdoor, paid Apify actors, and
> Common Crawl auto-enrolment, permanently.

---

## 1. Phase 0 — The audit (measured against the working tree, 2026-11-10)

| Capability | Existing implementation | Gap | Change |
|---|---|---|---|
| Board storage | `job_boards` table (`src/db/boards.py`, migration `d2e3f4a5b6c7`) with per-board health; env lists are the seed; adapters read the registry with env fallback | Registry exists but **nothing proposes new boards**; enrolment is still hand-editing `.env` | Phase 3 |
| Board verification | Ad hoc, live, in-session (the WS-23/24 slugs were probed by hand) | **No repeatable check** that a board still answers and its payload still parses — a provider can rename a field and every parser silently returns nulls | Phase 1 (`scripts/verify_sources.py`) |
| Dedup | `src/jobs/deduplicate.py` — key includes `job.source`, so dedup is **per-source only**; the registry docstring claims cross-source dedup it does not perform | The same posting on Greenhouse *and* Ashby is stored twice, and the two rows can rank differently | Phase 2 |
| Source ordering | `search_planner.py` fans out to all sources concurrently; no notion of cost | A 20/page, 2,000-offset Workday board and a one-request Greenhouse board cost the same slot in the refresh | Phase 4 |
| Crawl policy | Per-host pacing (`JOB_SOURCE_MIN_INTERVAL=1.0`), per-host circuit breaker, one backoff schedule honouring `Retry-After` up to a cap (`src/jobs/http_client.py`); **no robots.txt check** | A provider that asks for a crawl delay (Jibe: 5 s) or forbids the path (SuccessFactors `Disallow: /`, SmartRecruiters API-except-LinkedInBot) is not distinguished from one that allows | Phase 5 |
| Liveness / ghost jobs | `src/jobs/spam.py` screens ingested listings (token stuffing, link farming) | No probe for "the apply control disappeared" / expired posting; no board-level liveness signal | Phase 5 (adjacent) |
| New ATS adapters | 4 adapters registered (`src/jobs/registry.py:26-31`); LinkedIn stub deliberately unregistered | BambooHR / Workable / Workday / etc. unimplemented; **SRS FR-2.1 says "four public APIs" and must be amended before any adapter is added** | Phase 6 |
| Verified slugs | `.env.example` already carries the live-verified set (brave, sourcegraph91; shieldai, angellist, contentsquare; linear, cursor, elevenlabs, ramp, clerk, vanta, close, render — the corrections from live probing: close/render are Ashby, hotjar's board is contentsquare, vanta/postman/dbtlabs 404 on Greenhouse) | Done as part of WS-23; recorded here so WS-26 does not re-litigate | — |

**The ordering rule (from the research review):** complete fields on the
existing adapters **before** adding any source. The blend uses a fixed
denominator (`src/matching/scores.py`), so a new adapter that fills
`seniority`/`remote_policy`/`currency` would outrank an identical-fit
existing job for the wrong reason. WS-23 Phase 3 is the precondition.

---

## 2. Phase 1 — `scripts/verify_sources.py` (the highest-leverage artifact)

Port of `danielhagever/job-board-apis`'s `verify.py` (MIT, 359 lines,
stdlib only): one assertion per known endpoint, 1 s between calls,
`PASS`/`FAIL`/`SKIP`, exit 1 on failure — runnable standalone **and** from
CI, so a board that changed a field name fails loudly instead of parsing to
nulls silently.

1. **The harness**: stdlib `urllib.request` + `json` + `re` only (no project
   imports, so it runs in a clean venv and in CI before the app is
   installed). For each registered board (`ats`, `slug`): the exact request,
   the assertions (status 200, body parses as JSON — the BambooHR dead-tenant
   trap — at least one job record, the expected id shape), a 1 s sleep.
2. **The registry as input**: the script reads the `job_boards` table (or the
   env seed on a fresh checkout), not a second hardcoded list — one source of
   truth.
3. **CI wiring**: a GitHub Actions job (the project's CI already splits on
   the `browser` marker; this is a `not browser` job) that runs the script
   weekly and on every PR that touches `src/jobs/`. Transient DNS failures
   get one retry with a clear SKIP, not a FAIL.
4. **Output**: a markdown report (board, PASS/FAIL, listings count, first
   failure) suitable for a readme table.

**Gate:** `python scripts/verify_sources.py` exits 0 against the live
registry and exits 1 when a mocked board returns HTML or a renamed field.

---

## 3. Phase 2 — Cross-source dedup (before any new adapter)

The ever-jobs idea, ported as pure Python in `src/jobs/deduplicate.py`:

1. **Exact cross-source key**: `sha256(normalize(company) | normalize(title) |
   normalize(location))` — the same posting on two providers collapses to one
   row, keeping the first-seen source's id and merging `extra_metadata`.
2. **Fuzzy clustering (optional, behind a flag)**: MinHash over title+company
   tokens with union-find, merging only when locations are compatible — for
   near-duplicates ("Senior Backend Engineer" vs "Sr. Backend Engineer").
3. **Precedence rule**: when two sources disagree on a field, the value from
   the source with the higher field-completeness score wins (WS-23 Phase 3
   makes that score exist); ties keep the first-seen.
4. The per-source keys stay as the **identity** (canonical id is
   `{source}:{source_job_id}`) — the cross-source key is a *merge* key, not a
   replacement, so a source's own rows never collide with each other.

**Gate:** the same posting fetched from two mocked sources persists as one
row; a test reproduces the duplicate before the fix; the registry docstring
("deduplicates across sources") becomes true.

---

## 4. Phase 3 — Proposals, not enrolment (the registry becomes the UI surface)

The product decision stands: **the operator curates the boards**. What changes
is that the system can *propose*:

1. A discovery helper (a script, not a runtime service) that sniffs
   careers pages / uses prebuilt board lists to produce a **proposed**
   `ats:slug` list — written to a review file or a `proposed` flag in
   `job_boards`, never `enabled`.
2. The admin console's board view (the WS-23 Phase 5 surface) lists proposed
   boards with their verify status from Phase 1; the operator enables with
   one action, which flips `enabled` in the registry.
3. New boards enter disabled-by-default until their first `verify_sources`
   PASS.

**Gate:** no code path enables a board without an operator action; the
proposal list is visible but inert until then.

---

## 5. Phase 4 — Honest source ordering and staggered sync

1. **Cost-aware ordering**: each ATS gets a declared cost class (one
   request = cheap: Greenhouse light list, Lever, Ashby, Remotive; per-page
   = medium: BambooHR, Workable; paginated with a hard ceiling = expensive:
   Workday 20/page repeating past 2,000, Oracle/Phenom dead past 10,000,
   Eightfold fixed at 10). The refresh runs smallest-first, so a big board's
   cost never starves the cheap ones; **Workday last**.
2. **Two-mode sync with staggering** (the ever-hust idea, reimplemented on
   the WS-18 queue): full sync per source on a slow schedule + keyword sync
   on a rotating term, one queue at concurrency 1 so the two never overlap.
   The WS-18 durable queue/leases already provide the machinery.
3. **Paging ceilings are declared per adapter** and the adapter stops at the
   ceiling instead of re-reading page one forever (the Workday
   offset>2,000 repeat is silent data corruption, not just wasted requests).

**Gate:** a refresh report shows per-source cost and order; a mocked
Workday adapter stops at its declared ceiling; the queue never runs full
and keyword for the same source concurrently.

---

## 6. Phase 5 — Crawl-policy maturation and liveness signals

1. **robots.txt**: before a new host is enrolled, fetch its robots.txt once
   and record the verdict in the registry. Refusals are permanent: SmartRecruiters
   (API allowed only to `LinkedInBot`), SuccessFactors (`Disallow: /`).
   A requested crawl delay (Jibe: 5 s) becomes the host's
   `min_interval`. This is policy, not politeness — it settles the legal
   questions with the provider's own file.
2. **Adaptive cooling**: on 429/503, honour `Retry-After` but if the delay
   exceeds 60 s, cool the host (open its circuit) instead of sleeping —
   the existing breaker in `src/jobs/http_client.py` gains this rule.
3. **Liveness probes**: a board whose apply control disappears or whose
   postings all 404 is marked unhealthy in the registry (Phase 3 surface),
   and its rows are protected from eviction by the WS-23 source-scoped rule.
4. **Ghost-job signals**: extend `src/jobs/spam.py` with the ever-jobs
   signals (dead apply link, bot challenge on the apply page) — deterministic,
   explainable from the listing alone.

**Gate:** a mocked 429 with `Retry-After: 3600` opens the circuit; a
robots-disallowed host is never fetched; a board whose postings 404 is
marked unhealthy and its rows survive eviction.

---

## 7. Phase 6 — One new provider at a time (tier-A order)

Each adapter follows the existing contract (`JobSource` / `DeltaJobSource`,
`src/jobs/contracts.py`), goes through `guarded_get` (SSRF guard, size cap,
breaker, pacing), records board health via `src/jobs/board_health.py`, fills
**all** the WS-23 fields (seniority, remote_policy, salary/currency,
experience, skills) — an adapter that leaves fields empty re-introduces the
ranking bias this workstream exists to avoid — and is enrolled only after:

1. its boards pass `verify_sources.py` live;
2. its paging ceiling is declared and tested;
3. its robots verdict is recorded;
4. the SRS FR-2.1 amendment (Phase 7) is in place.

**Order**: BambooHR (5,168 boards, one list endpoint + `/careers/{id}/detail`
for posted date and pay; the dead-tenant-returns-HTML trap asserted in
tests) → Workable (4,807 boards, widget API with `details=true`, top-level
`name` is the employer) → Recruitee/Personio/Breezy (smaller, JSON/XML,
straightforward) → **Workday last** (720k of 1.46M postings but big-enterprise,
paginated, ceilinged; POST `wday/cxs` only).

**Permanently refused**: LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google
Jobs (ToS/ban risk — AGENTS.md and the ever-jobs README agree); paid Apify
actors; Common Crawl auto-enrolment (discovery is proposal-only, Phase 3);
Playwright as an ingest dependency (browser automation is the WS-08
application layer, never the fetch layer).

**Gate:** each adapter lands with unit tests over recorded payloads + one
live verify pass; the registry grows by exactly one provider per phase.

---

## 8. Phase 7 — The docs contract

- **SRS FR-2.1** ("listings come from four public APIs") is amended to name
  the actual registered set; the contradiction flagged in the research
  review is closed before the first new adapter merges.
- `00-OVERVIEW.md` gains WS-23…26 rows; the README's API/source table is
  updated (enforced by `tests/test_docs_accuracy.py`); `.env.example` board
  comments stay the seed documentation (`tests/test_env_docs.py`).
- Every new env var (per-ATS board lists for the new providers, crawl-delay
  overrides) is documented with its code default.

---

## 9. Acceptance

| Check | Test |
|---|---|
| `verify_sources.py` passes live and fails on a renamed field / HTML body | `tests/test_verify_sources.py` + a live run |
| Cross-source dedup collapses a duplicate across two mocked sources | `tests/test_ws26_dedup.py` (repro first) |
| Fuzzy MinHash merge fires only on compatible locations | `tests/test_ws26_dedup.py` |
| No board becomes `enabled` without an operator action | `tests/test_ws26_registry.py` |
| Refresh order is smallest-first, Workday last; ceilings stop pagination | `tests/test_ws26_ordering.py` |
| 429 with `Retry-After > 60s` opens the circuit | `tests/test_ws26_ordering.py` |
| robots-disallowed host is never fetched | `tests/test_ws26_ordering.py` |
| Each new adapter fills the WS-23 field set | `tests/test_ws26_adapters.py` |
| SRS FR-2.1, README, overview rows updated | `tests/test_docs_accuracy.py` |
| The whole suite is green | `pytest` |
| Lint is clean | `ruff check src tests scripts` |

---

## 10. Out of scope

- **LinkedIn / Indeed / Glassdoor / ZipRecruiter / Google Jobs.** Permanent.
- **Paid actors and services** (Apify and similar). The project uses
  documented, key-less public APIs only.
- **Common Crawl or any automatic enrolment.** Discovery produces proposals;
  a human enables.
- **Scraping HTML career pages for listings.** If a provider publishes no
  public API, it is not a source.
- **A second runtime** (running ever-jobs' TypeScript engine alongside the
  Python backend). Ideas are ported, not imported.
- **Raising `MAX_CORPUS_LISTINGS` past 50,000.** WS-24 re-measures first.
- **Playwright in the ingest path.** Browser automation stays in the
  application layer (WS-08) with its domain controls.

---

## 11. Follow-up phase (WS-26b) — The verifier, and the overclaim

WS-26 is plan-only. This phase starts it where the leverage is highest and
fixes a docstring that currently claims something the code does not do.

### 11.1 — `scripts/verify_sources.py`

The port of `danielhagever/job-board-apis`'s `verify.py` (MIT, 359 lines,
stdlib only). **It does not exist yet** — the repo has `verify_ws06.py`
through `verify_ws22.py`, but no source verifier.

The shape, following the repo's own verifier convention:

- stdlib `urllib.request` + `json` only, so it runs in a clean venv and in
  CI before the app is installed;
- reads the **board registry** (or the env seed on a fresh checkout), not
  a second hardcoded list;
- per board: the exact request, then the assertions — status 200, the body
  parses as JSON (the BambooHR dead-tenant trap answers 200 with HTML), at
  least one job record, the expected id shape;
- 1 s between calls, one retry on a transient DNS failure reported as
  `SKIP` rather than `FAIL`;
- `PASS` / `FAIL` / `SKIP` lines and a non-zero exit on any `FAIL`;
- a markdown report suitable for a table.

**Why it matters.** Nothing currently proves that a board has not renamed
a field. A provider renaming `employmentType` makes every parser return
nulls silently — which is exactly the failure that produced the 0% field
population this whole workstream set out to fix.

### 11.2 — Fix the dedup overclaim

`src/jobs/registry.py:1-8` says `search_all` *"deduplicates across
sources"*. It does not: `src/jobs/deduplicate.py` keys include
`job.source`, so dedup is **per-source only**. The docstring is wrong and
should say what the code does, with a pointer to the cross-source work
(Phase 2 / WS-23b §12.3).

A docstring that overclaims is worse than a missing one: it is the kind of
statement a future reader relies on instead of reading the code.

### 11.3 — Acceptance

| Check | Test |
|---|---|
| The verifier passes against a mocked healthy board | `tests/test_ws26b_verify.py` |
| It fails on a board that returns HTML with a 200 | `tests/test_ws26b_verify.py` |
| It fails on a renamed field | `tests/test_ws26b_verify.py` |
| A transient DNS failure is a SKIP, not a FAIL | `tests/test_ws26b_verify.py` |
| The registry docstring states what the code does | reviewed |
