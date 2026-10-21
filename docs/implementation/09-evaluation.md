# WS-09 · Evaluation Harness

Status: **Done (2026-10-21)** · Milestone: **M4** · Depends on: [02](02-job-discovery.md), [03](03-matching-engine.md), [04](04-pipeline-and-api.md), [05](05-tailoring-and-research.md), [07](07-application-tracking.md), [08](08-browser-automation.md) · Blocks: honest "autonomous" claims (plan §7: *"Do not claim the system is autonomous without measurable evaluation"*)

> **Part 1 (the original five phases) is complete. Part 2 closes the gaps
> Part 1 left open** — the system-level metrics that were blocked on
> WS-07, the browser-automation and matching metric families the plan's
> §7 list names, and the `--live` mode, which labelled its report "live"
> while serving canned data. See **Part 2 — Detailed specification**,
> **Part 3 — Execution plan** and **Part 4 — Implementation notes**
> below.

## Execution plan (added 2026-10-21 — implementation of WS-09)

Phases, in dependency order (each phase: implement → unit tests → full offline
suite → reproducible runner output):

1. **Phase A — Golden datasets (`tests/evaluation/golden/`).** Four synthetic
   resumes (two DOCX, two TXT) with hand-labeled expected extractions
   (`expected_profiles.json`), ~25 normalized listings (`jobs.jsonl`) carrying
   graded relevance labels per profile plus annotated duplicate groups
   (`dup_of`), six (profile, job) tailoring pairs with human-labeled
   *acceptable* facts, and canned LLM drafts (`llm/`) so the offline run is
   deterministic and free. **Identities are synthetic** — the real resume is
   only used redacted, so the repo carries no new personal data.
2. **Phase B — Metrics (`src/evaluation/metrics.py`).** Pure functions only
   (`metric(golden, produced) -> float | dict`): extraction field accuracy,
   skills set-F1, per-entry precision, dedup precision/recall, nDCG@10 and
   precision@5 over graded labels, tailoring factuality agreement, ATS
   coverage delta. No metric logic lives in the runner.
3. **Phase C — Runner (`scripts/run_eval.py`).** `--offline` (canned
   generations, default) and `--live` (real Gemini; the report states which
   mode produced it). Per golden profile: parse → search over a fixture
   `JobSource` → dedup → rank → tailor → ATS → metrics. Writes
   `docs/evaluations/report-YYYY-MM-DD.{md,json}` including the dataset
   sha256 (reproducibility) and `--check` compares against
   `src/evaluation/thresholds.json`, exiting non-zero on a regression.
4. **Phase D — Thresholds + tests.** `src/evaluation/thresholds.json` with
   minimum acceptable values, `tests/test_metrics.py` (each metric against a
   hand-computed expectation) and `tests/test_eval_runner.py` (report written,
   determinism, `--check` regression behavior).
5. **Phase E — Verification.** Two offline runs must produce identical
   numbers; `--check` must fail on a lowered threshold; doc status updated;
   commit.

**Why this workstream now:** FU-5 ("degraded-mode neutral inflation" — the
observed flat ties at the neutral 70) was explicitly deferred to WS-09's
nDCG harness rather than hand-tuned. The harness gives that decision a
measurement instead of an opinion.


## Goal

Implement plan Phase 13 / §7: golden datasets + reproducible metrics for extraction, dedup,
ranking, tailoring factuality, and ATS coverage, with a one-command report. The project gets
real numbers it can put in `docs/evaluations/` and defend.

## Current state

- Nothing. No datasets, no metrics, no runner, no reports. The only quantitative signal today is "68 tests pass".
- Building blocks that make evaluation cheap already exist: deterministic parser, deterministic factuality validator, deterministic ATS analyzer (WS-05), `generate` injection points everywhere the LLM is used.

## Concrete tasks

### 1. Golden datasets — `tests/evaluation/golden/`

- **Resumes**: 4 synthetic DOCX/TXT resumes (`golden/resumes/`) with hand-labeled expected extractions in `expected_profiles.json` (name, email, skills set, experience count, education entries, preferences where stated). Plus the real resume fixture used for the live-verification, **PII-redacted** (fake name/email/phone), so the repo carries no personal data beyond what's already there.
- **Jobs**: ~25 normalized listings (`golden/jobs.jsonl`) with per-candidate relevance labels (`relevant` / `partial` / `irrelevant`) against the golden profiles, and duplicate groups annotated (`dup_of` field) for dedup metrics.
- **Tailoring pairs**: for 6 (profile, job) pairs, a human-labeled set of *acceptable* tailored facts; the factuality validator's verdicts are compared against these labels.

### 2. Metrics — `src/evaluation/metrics.py`

| Area | Metric | Definition |
|---|---|---|
| Extraction | field accuracy | exact-match per scalar field; set-F1 for skills; per-entry precision for experience/education |
| Dedup | precision / recall | over annotated duplicate groups after `deduplicate()` |
| Ranking | nDCG@10, precision@5 | graded labels (relevant=2, partial=1) over `overall_score` ordering |
| Tailoring | factuality agreement | validator verdicts vs human labels (accuracy + violation recall) |
| ATS | coverage delta | `AtsReport.keyword_coverage` before/after tailoring |
| System | human intervention rate, success rate | from `ApplicationEventDB` (WS-07) — reported once M4 tracking data exists |

All pure functions: `metric(golden, produced) -> float | dict`.

### 3. Runner — `scripts/run_eval.py`

- Modes: `--offline` (default; fake LLM responses canned in `golden/llm/` so runs are deterministic and free) and `--live` (uses real Gemini; report flags which mode produced it).
- Pipeline per golden profile: parse → (search against a fixture `JobSource` over golden jobs) → dedup → rank → tailor (canned generation) → ATS.
- Writes:
  - `docs/evaluations/report-YYYY-MM-DD.md` — table of every metric, run config (model ids, dataset version hash), and a short interpretation section (human-written in the first instance);
  - `docs/evaluations/report-YYYY-MM-DD.json` — machine-readable numbers.
- Dataset version: sha256 of the golden directory recorded in the report (reproducibility).

### 4. Regression thresholds

`src/evaluation/thresholds.json` — minimum acceptable values (set after first baseline run, then raised): e.g. extraction field accuracy ≥ 0.95, skills set-F1 ≥ 0.85, dedup precision ≥ 0.98, tailoring factuality agreement ≥ 0.9. `scripts/run_eval.py --check` exits non-zero on regression → CI-able gate.

## Acceptance criteria

- [x] `python scripts/run_eval.py` (offline) produces a complete report with every metric populated and the dataset hash; a second run yields **identical** numbers.
- [x] `--check` fails when a metric drops below threshold (tested by temporarily lowering a threshold).
- [x] Metrics are computed only by `src/evaluation/metrics.py` (no metric logic buried in scripts).
- [x] No PII in the repo beyond the already-present fixtures; golden resumes carry redacted identities.

## Tests

- `tests/test_metrics.py` — each metric against hand-computed expected values (ndcg on a tiny known ranking, F1 edge cases, dedup P/R).
- `tests/test_eval_runner.py` — offline run over the golden set: report file created, JSON schema, determinism (two runs byte-equal except timestamps), `--check` regression behavior.

## New dependencies

None.

## Implementation notes (2026-10-21 — implemented, measured, reproducible)

Suite: **609 passing** (was 553), ruff clean. Delivered:

- `src/evaluation/metrics.py` — the pure metric functions (field accuracy,
  set-F1, per-entry precision/recall, dedup P/R/F1, nDCG@10, precision@5,
  factuality agreement + violation recall, ATS coverage delta). No metric
  logic exists anywhere else.
- `src/evaluation/harness.py` — loads the golden set and runs the pipeline
  over it (parse → dedup → rank → tailor → ATS), producing the data the
  metrics consume. The offline run serves every model call from the canned
  drafts and holds the semantic channel constant with a deterministic lexical
  stand-in, so a run is free and provider-independent.
- `scripts/run_eval.py` — the one-command runner (`--offline` default,
  `--live` for the real LLM/provider, `--check` for the regression gate).
  Writes `docs/evaluations/report-<date>.md` and `.json`, both carrying the
  dataset sha256.
- `src/evaluation/thresholds.json` — the minimum acceptable values the
  `--check` gate enforces.
- Golden set in `tests/evaluation/golden/`: 4 synthetic resumes (2 DOCX, 2
  TXT) with hand-labelled extractions, 25 listings with graded labels and 5
  annotated duplicate listings, 6 tailoring pairs with human-labelled
  acceptable facts, and 6 canned LLM drafts (two carrying a deliberate
  violation). Generated by `scripts/make_golden_resumes.py` /
  `scripts/make_golden_jobs.py` so the dataset is reproducible. **All
  identities are synthetic** — no real candidate data was added.

**Baseline measured (offline, dataset hash `8777fc3e…`):**

| Metric | Value | Threshold |
|---|---|---|
| extraction field accuracy | 1.000 | ≥ 0.95 |
| extraction skills set-F1 | 1.000 | ≥ 0.85 |
| dedup precision / recall | 1.000 / 1.000 | ≥ 0.98 / 0.90 |
| ranking nDCG@10 | 0.754 | ≥ 0.60 |
| ranking precision@5 | 0.400 | ≥ 0.40 |
| tailoring factuality agreement | 1.000 | ≥ 0.90 |
| tailoring violation recall | 1.000 | ≥ 0.90 |
| ATS coverage delta (tailoring) | +0.111 | ≥ 0 |

**FU-5 decided with data (this harness was its decision point).** The ranking
is measured twice over the same corpus — with the semantic channel and in
degraded mode (no semantics, the engine redistributes the weight and
skill-less listings fall back to the neutral score):

| Profile | nDCG@10 | nDCG@10 degraded | Semantic delta |
|---|---|---|---|
| alex_rivera_backend | 0.6896 | 0.6848 | +0.0047 |
| mina_chen_ml | 0.7656 | 0.7508 | +0.0148 |
| sam_okoye_data | 0.7521 | 0.7339 | +0.0182 |
| lena_fischer_frontend | 0.8077 | 0.8077 | +0.0000 |
| **mean** | **0.7537** | **0.7443** | **+0.0094** |

**Conclusion:** the neutral inflation is worth ~1% of nDCG@10 on this set —
an order of magnitude less than the flat-tie symptom suggested, and
precision@5 is unchanged. So FU-5's candidate fixes (capping the neutral
contribution, weighting by evidence availability) are **not justified**:
they would add a hand-tuned constant for a ~1% effect. The real cause of the
observed live flat ties was the corpus having no vectors at all — which the
FU-7 local-provider migration removed (the store-only search now reports
`degraded=false` over 5,854 listings). FU-5 is therefore **closed as
"no change needed"**, with the measurement kept so the claim can be re-checked
when the golden set grows. Caveat, stated plainly: the golden set is 25
listings with a lexical semantic stand-in, so the absolute numbers are
indicative of the pipeline's layers, not a production-scale ranking claim.

**A design flaw the harness exposed (in the metric, not the validator):** the
first version of the factuality metric matched expected violations against
the validator's *message text*, and scored 0.5 — because the skill violation
message ("Removed 1 skill(s) not present in profile") does not name the
removed skill (the detail lives in the structured ``removed_skills`` list).
Matching the question the metric actually asks ("did the validator catch
*this* fact?") means matching the structured fields, so the metric now
accepts a match in either the text or the structured removal lists and is
independent of wording. *Suggestion for the WS-06 owner (not applied here —
that file was being edited in parallel):* naming the removed skills inside
the violation message would make the report readable on its own; the metric
does not depend on it.

**Not done (deliberately, out of scope here):** the system-level metrics
(human intervention rate, submission success rate) need the WS-07
application-tracking tables, which are not implemented yet; the harness
reports the areas it can measure today and names the missing one.
*(Superseded by Part 2 below: WS-07 landed the same day, and the
system-level metrics are now built and measured.)*

---

# Part 2 — Detailed specification (added 2026-10-21 — system, browser and §7 coverage)

## S0. Scope, invariants, non-goals

**Goal.** Extend the WS-09 harness so that it measures the whole system
rather than four of its stages, and so that every number in the report is
traceable to the code that produced it.

**Invariants (binding).**

| # | Invariant | Enforced by |
|---|---|---|
| I1 | Metric logic lives in `src/evaluation/metrics.py` and nowhere else | the acceptance test in `tests/test_metrics.py` greps the tree |
| I2 | Every metric is a **pure function** `metric(golden, produced) -> float \| dict` — no I/O, no clock, no model call | unit tests call them with plain data |
| I3 | The **offline** run is deterministic: two runs produce byte-identical numbers | `tests/test_eval_runner.py` (existing) |
| I4 | The report states **which mode produced it**, and the mode is not a label for something that did not happen | Phase F: the live path must actually call the provider, or the run fails |
| I5 | A metric that cannot be computed is **absent**, never zero and never guessed | the report's `unavailable` section lists what could not be measured and why |
| I6 | No fabricated outcomes. A system-level number is computed from real `ApplicationEventDB` rows, never asserted | Phase G reads the DB |
| I7 | Every golden artifact is synthetic or redacted; no new personal data enters the repo | Phase H's redaction check |
| I8 | Golden-set changes are **reproducible from a script**, not hand-edited | `scripts/make_golden_*.py` remain the only writers |

**Non-goals.**

- Not a production-telemetry product. The system metrics are measured over a
  **golden scenario set**, not over live traffic.
- Not a model leaderboard. `--live` measures *our pipeline* against the real
  provider; it does not compare providers.
- Not a replacement for the WS-06/07/08 live-verification scripts. Those
  prove the system works; this proves the numbers are right.
- No new runtime dependency. `pytest`/`ruff` are already declared.

## S1. What is missing, exactly

The plan's §7 metric list, mapped to what exists today:

| Plan §7 area | Plan §7 metric | Part 1 | Part 2 |
|---|---|---|---|
| Job discovery | precision@k | `ranking.precision_at_5` ✅ | — |
| Job discovery | **recall@k** | ❌ | Phase I |
| Job discovery | **duplicate rate** | implied by dedup P/R, not stated | Phase I |
| Job matching | ranking quality | `ranking.ndcg_at_10` ✅ | — |
| Job matching | **false positive rate** | ❌ | Phase I |
| Job matching | **false negative rate** | ❌ | Phase I |
| Resume tailoring | factual consistency | `tailoring.factuality_agreement` ✅ | — |
| Resume tailoring | **job relevance** | ❌ | Phase I |
| Resume tailoring | **hallucination rate** | ❌ | Phase I |
| Browser automation | **form completion success rate** | ❌ | Phase H |
| Browser automation | **navigation failure rate** | ❌ | Phase H |
| Browser automation | **verification success rate** | ❌ | Phase H |
| Application system | **successful applications** | ❌ | Phase G |
| Application system | **failed applications** | ❌ | Phase G |
| Application system | **human intervention rate** | ❌ | Phase G |
| Application system | **incorrect submissions** | ❌ | Phase G |

Plus the two defects named at the top of this document: `--live` does not
go live (Phase F), and the missing system/browser families (Phases G, H).

## S2. Phase F — the live mode must actually go live

**The defect.** `harness.run_offline(dataset, live=True)` sets
`results["mode"] = "live"` and nothing else. `run_pair()` always serves
`dataset.llm_drafts`; `run_profile()` always uses `lexical_semantic_scores`.
The `--live` report is the offline report with a different label.

**The fix.** The `live` flag must change *what runs*:

- **Tailoring.** In live mode the harness calls the **real** LLM through the
  same `tailor_resume(profile, job, generate=...)` seam the product uses, so
  the prompt, the schema and the factuality validator are the production
  ones. The golden `llm/` drafts are used **only** in offline mode.
- **The semantic channel.** In live mode the harness uses the **real**
  embedding provider over the golden listings, via the production text
  contract (`ChromaVectorStore.document_text` / `candidate_query_text` and
  `build_embedding_fn()`), so the ranking numbers come from the same
  embedding space production uses. The lexical stand-in stays offline-only.
- **The report names the providers.** `results["providers"]` records
  `llm.provider`, `llm.model`, `embeddings.provider` and the mode, so a
  reader can see which system produced the numbers.
- **The live run is not bit-reproducible.** That is the point of a live run,
  and the report must say so rather than promise determinism it cannot
  deliver. `--check` in live mode compares against thresholds but the
  determinism test applies to offline only.

**Live-mode semantics for the two tailoring metrics.** The golden
`expected_violations` labels describe the *canned* drafts. A live draft is
different text, so agreement against those labels is meaningless. In live
mode the harness therefore reports the **pipeline's own** factuality
behaviour — how often the live draft needed stripping, and how much was
stripped — instead of agreement against the canned labels. The report says
which of the two it is showing.

**Files.** `src/evaluation/harness.py` (provider selection + the
`providers` block), `src/evaluation/semantics.py` (new: the real semantic
channel over the golden corpus), `scripts/run_eval.py` (surface the
providers, keep `--check` honest per mode).

**Naming.** `harness.run_offline(dataset, live=...)` is a misnomer once the
flag is real. The entry point becomes `harness.run_evaluation(dataset,
mode="offline"|"live")`; `run_offline` is kept as a thin alias so the
existing tests and the docs keep working.

## S3. Phase G — system-level metrics from the tracking tables

**Source of truth.** The `applications` and `application_events` tables
(WS-07). The metrics are computed from the rows the workflow actually
wrote — not asserted, not hand-counted (I6).

**The scenario set.** A golden file of application *scenarios*:
`tests/evaluation/golden/scenarios.jsonl`, one scenario per line, each
naming a fake-ATS variant and the expected lifecycle. The harness runs
each scenario through the **real** workflow — the real graph, the real
approval gate, the real tracker — against a real (temporary) SQLite
database, then reads the rows back and computes the metrics.

That is the key property: the metric measures the system, and the golden
file supplies only the *inputs* and the *expectations*.

**The metrics** (all pure, in `metrics.py`):

| Metric | Definition |
|---|---|
| `system.successful_applications` | share of tracked applications that reached `verified` |
| `system.failed_applications` | share that reached a terminal non-verified state (`rejected`) |
| `system.human_intervention_rate` | share of runs where a human actor was required — an approval decision, or a human-set terminal outcome |
| `system.incorrect_submission_rate` | share of runs that reached `submitted` but never `verified` (a submission claimed but not confirmed) |
| `system.lifecycle_fidelity` | share of runs whose recorded event sequence matches the scenario's expected sequence exactly |

**The scenario set** must cover every branch the workflow can take, so the
rates are meaningful rather than flattering:

| Scenario | Exercises |
|---|---|
| `basic` | the happy path → `verified` |
| `multipage` | a multi-page wizard → `verified` |
| `widgets` | select/checkbox/radio controls → `verified` |
| `unknown` | an ungrounded question → `needs_human`, no submission |
| `captcha` | a challenge → `blocked_human_review`, no submission |
| `validation` | a server-rejected form → `form_error` |
| `rejected` | a human rejection at the gate → `rejected`, human actor |
| `human_outcome` | a human setting `interview`/`offer` after verification |

`human_intervention_rate` is then a *measured* property of the scenario
mix, not a constant: the mix has 5 auto-completing runs and 3 that need a
human.

**No browser in the metric path.** The scenarios need the real browser to
produce the ATS's behaviour, so this phase is **live-verified**, not
unit-tested end to end. The unit tests cover the metric functions against
hand-computed expectations and cover the *tracker* against a scripted
session; the live script proves the whole chain.

## S4. Phase H — browser-automation metrics

The browser metrics come from the same scenario runs, read out of the
evidence and status columns the adapter already writes:

| Metric | Definition |
|---|---|
| `browser.form_completion_rate` | share of form pages the agent filled and submitted without a pause |
| `browser.navigation_failure_rate` | share of runs that stopped on `unsafe_navigation` |
| `browser.verification_success_rate` | share of submissions that reached `verified` |

These are the plan §7 "Browser automation" group. They are measured over
the same scenario set as Phase G, so the report has one coherent run.

**A second golden artifact.** The scenarios need the fake-ATS page
*structure* (the controls a page asks for) to build the form plan. WS-08
recorded the contract as a **live-page** contract rather than saved
snapshots (deviation D14: a saved copy of the markup "would have been a
second copy of the fake ATS's markup, free to drift"). Part 2 keeps that
decision: the golden scenario file stores the **scenario names and
expectations**, not a copy of the pages. The pages stay the single source
of truth, served live.

## S5. Phase I — the remaining §7 metric families

Four metric families, all over data the harness already produces, all pure
functions in `metrics.py`:

| Metric | Definition | Grading convention |
|---|---|---|
| `ranking.recall_at_10` | share of *relevant* listings (grade ≥ 1) that appear in the top 10 | the same graded labels the golden set already carries |
| `dedup.duplicate_rate` | share of the raw corpus that was a duplicate — the corpus-level view, complementing dedup precision/recall | the `dup_of` annotation the golden set already carries |
| `matching.false_positive_rate` | share of the top-10 that are *not* relevant (grade 0) | a documented, stated threshold on `overall_score` — see below |
| `matching.false_negative_rate` | share of the *relevant* listings that did **not** make the top 10 | the same |
| `tailoring.job_relevance` | share of the job's required skills that appear in the tailored resume | the job's `required_skills` vs. the tailored content |
| `tailoring.hallucination_rate` | share of the tailored claims that the factuality validator had to strip | the validator's own `removed_*` lists |

**The matching threshold must be stated, not tuned.** The engine has no
decision threshold today — it produces a score. For FPR/FNR the harness
needs one. The threshold is a **declared constant in the harness**
(`MATCH_DECISION_THRESHOLD`), documented in the report, and the report
prints the score distribution so a reader can see how sensitive the numbers
are to it. It is **not** fitted to the golden set: it is set to the
engine's own documented neutral score (70) — the score the engine itself
treats as "no signal" — so "predicted relevant" means "scored above the
neutral line", and the numbers are conservative by construction.

**FPR/FNR need a labelled binary decision.** "Relevant" is
`grade >= 1` on the golden labels (grade 2 relevant, 1 partial). The
ranking threshold and the relevance threshold are different things and
the report names both.

## S6. Phase J — the report, the thresholds, the gate

**The report gains three sections** and one honesty section:

- `system` — the Phase G metrics.
- `browser` — the Phase H metrics.
- `providers` — which LLM and which embedding provider produced the run.
- `unavailable` — what could not be measured and why (I5). Empty in a
  healthy run; populated (rather than silently zeroed) when a family is
  not applicable to the mode.

**The thresholds file** gains an entry per new metric, set at the measured
baseline and then raised. A metric with no threshold is not gated, and the
report says so — an ungated metric must not look like a passing one.

**`--check` becomes per-mode.** The offline thresholds gate the offline
run. The live run is checked against the same numeric thresholds but its
numbers are not reproducible, so the gate reports the comparison and does
**not** fail the build on a live-only run (CI runs offline). The report
says which gate applied.

## S7. The test matrix

| Module | What it proves | Browser? | Network? |
|---|---|---|---|
| `tests/test_metrics.py` (extended) | every new metric against a hand-computed expectation; edge cases (empty input, no positives, no negatives) | no | no |
| `tests/test_eval_runner.py` (extended) | the offline run still populates every metric and is byte-identical across runs; the report names its providers; `--check` fails on a lowered threshold | no | no |
| `tests/test_eval_systems.py` (new) | the system metrics over a scripted tracker session: a run that reaches `verified`, one that stops at `needs_human`, one a human rejects; and the metric functions over those rows | no | no |
| `tests/test_eval_scenarios.py` (new) | the golden scenario file is well-formed: every scenario names a real fake-ATS variant, every expectation is reachable | no | no |
| `scripts/verify_ws09.py` (new) | the **whole chain live**: the real workflow against the real fake ATS in Chromium, the real tracking tables, the system + browser metrics computed from the rows, and the report written | **yes** | no (localhost) |

**Live verification must not be a rubber stamp.** The script asserts the
*values* it computes against the expectations, not merely that a run
happened: e.g. the `basic` scenario's application row must be `verified`
with exactly the expected event sequence, and the human-intervention rate
must equal the ratio the scenario mix implies.

## S8. Risks

| Risk | Mitigation |
|---|---|
| The live path needs a Gemini key; a machine without one cannot run `--live` | the runner **fails closed** with a clear message and exits non-zero; it never falls back to canned data under a "live" label (I4) |
| Live tailoring output varies run to run, so live numbers are not comparable across runs | the report states the mode and marks live numbers as non-reproducible; the deterministic gate is offline |
| A browser-based metric phase could make the suite slow and flaky | the browser work lives in the **live script**, not in the unit suite; the unit suite only exercises the metric functions and the tracker |
| The scenario mix decides the intervention rate, so the metric could be read as a production statistic | the report prints the scenario mix next to the rate, and the metric is named `..._rate_over_scenarios` where a reader could misread it |
| The matching threshold is a judgement call | it is a declared constant equal to the engine's own neutral score, printed in the report, with the score distribution beside it |
| A new golden file could carry personal data | the scenarios are synthetic (the existing fake-ATS fixtures already use `Ada Lovelace` / `ada@example.com`); a redaction check runs over the new file |

---

# Part 3 — Execution plan (added 2026-10-21 — Part 2)

Phases in dependency order. Each phase: implement → its own tests → the
full offline suite → `ruff check` → (where the phase claims a live
outcome) the live script. Nothing is committed until the phase's tests
are green.

- **Phase F — The live mode goes live.** `src/evaluation/semantics.py`
  (the real semantic channel over the golden corpus, via the production
  text contract), the live branch in `src/evaluation/harness.py`
  (the real LLM through the production `tailor_resume` seam, the real
  embedding provider, the `providers` block, the live-mode tailoring
  semantics), `harness.run_evaluation(dataset, mode=...)` with
  `run_offline` kept as an alias, and `scripts/run_eval.py` surfacing
  the providers. **Gate:** offline numbers are unchanged and still
  byte-identical; the live path calls the injected provider (a fake in
  the tests, the real one in the live script); the runner fails closed
  when a live provider is unavailable.

- **Phase G — System-level metrics.** The golden scenario set
  (`tests/evaluation/golden/scenarios.jsonl` + the expectations), the
  scenario runner in `src/evaluation/systems.py` (drives the **real**
  workflow against a real temporary SQLite database and reads the rows
  back), the pure metrics in `src/evaluation/metrics.py`
  (`system.successful_applications`, `system.failed_applications`,
  `system.human_intervention_rate`, `system.incorrect_submission_rate`,
  `system.lifecycle_fidelity`), and the `system` report section.
  **Gate:** the metrics over a scripted tracker session match
  hand-computed expectations; the live script proves them over the real
  workflow.

- **Phase H — Browser-automation metrics.** The `browser` metrics in
  `metrics.py` (`browser.form_completion_rate`,
  `browser.navigation_failure_rate`, `browser.verification_success_rate`),
  computed from the same scenario runs' evidence and status columns, plus
  the `browser` report section. **Gate:** the metrics over the recorded
  runs match the hand-computed expectations; the live script proves them.

- **Phase I — The remaining §7 families.** `ranking.recall_at_10`,
  `dedup.duplicate_rate`, `matching.false_positive_rate`,
  `matching.false_negative_rate`, `tailoring.job_relevance`,
  `tailoring.hallucination_rate` — pure functions in `metrics.py`, fed by
  the existing golden corpus, with the declared matching threshold and the
  score distribution printed in the report. **Gate:** every new metric
  matches a hand-computed expectation; the offline report populates them
  all.

- **Phase J — The report, the thresholds, the gate, the docs.** The
  `unavailable` section, the per-mode `--check`, the threshold entries,
  the regenerated baseline report, the `00-OVERVIEW.md` status and
  feature-gap table, and this document's own status. **Gate:** the full
  suite green, `ruff` clean, `--check` passes offline and fails on a
  lowered threshold, and the regenerated report is reproducible.

- **Phase K — Live verification.** `scripts/verify_ws09.py`: the real
  workflow against the real fake ATS in Chromium, the real tracking
  tables, the system + browser metrics computed from the rows and
  asserted against the expectations, and the report written. **Gate:**
  the script exits non-zero on any failed check, and every number it
  prints is one the offline harness can also produce from the same
  scenarios.

**The commit boundary.** Per the repo's convention (discrete per-file
commits, tests travelling with their feature, docs separate), Part 2 lands
as its own set of commits. Per the standing instruction, **pushing remains
a separate, explicit step** and is not performed here.

**Deliberately not in Part 2.** A model leaderboard; production telemetry;
a comparison of embedding providers; any change to the *runtime* behaviour
of the product (Part 2 is measurement only — the one exception is the
harness's own live path, which changes no product code).

---

# Part 4 — Implementation notes (added 2026-10-21 — Part 2 executed)

Suite: **840 passing** (was 799), ruff clean. Delivered:

## Phase F — the live mode goes live

- `src/evaluation/semantics.py` (new) — `RealSemanticChannel`, the **real**
  semantic channel over the golden corpus. It reuses the production text
  contract (`ChromaVectorStore.document_text`, `candidate_query_text`,
  `build_query_text` / `build_document_text`) and the production cosine
  (`src/rag/chroma_store.py`), so a live score is directly comparable to
  a production one. A dimension mismatch or a short vector **raises** —
  it is never a silent zero.
- `src/evaluation/harness.py` — `run_evaluation(dataset, mode=...)` is the
  entry point; `run_offline` is kept as an alias. The mode now changes
  *what runs*: live mode calls the **real** LLM through the production
  `tailor_resume` seam (no canned draft) and the **real** embedding
  provider (no lexical stand-in). The report carries a `providers` block
  naming the LLM and the embedding provider, and a `reproducible` flag
  that is `false` for a live run — because it is.
- `src/evaluation/metrics.py` — `live_factuality_scores`, the live-mode
  tailoring metric. The hand labels describe the *canned* drafts, so
  agreement against them is meaningless for a live draft; the live run
  measures the pipeline's own factuality behaviour instead (how often a
  live draft needed stripping, and how much was stripped).
- `scripts/run_eval.py` — the live path **fails closed**: a provider that
  cannot be reached exits non-zero with the error, rather than quietly
  serving the canned data under a "live" heading.

**Measured.** The live path produces genuinely different numbers from the
offline one: the per-profile false-negative rate moves from 0.7722
(offline, lexical stand-in) to 0.6667 (live, real embeddings). The
report names the providers in both cases.

## Phase G — system-level metrics (the §7 "Application system" group)

- `src/evaluation/systems.py` (new) — the pure metrics:
  `successful_applications`, `failed_applications`, `paused_for_human`,
  `human_outcome_applications`, `human_intervention_rate`,
  `human_outcome_rate`, `incorrect_submission_rate`, `verification_rate`,
  `lifecycle_fidelity`. Every run falls in **exactly one** bucket, so the
  buckets sum to the run count (asserted).
- `src/evaluation/scenarios.py` (new) — the golden scenario set
  (`tests/evaluation/golden/scenarios.jsonl`) and its reader. The file
  names a fake-ATS variant and the lifecycle the run is expected to
  produce; it holds **no copy of the fake ATS's markup** (the WS-08
  decision, D14).
- `src/evaluation/runner.py` (new) — drives the **real** workflow (the
  real graph, the real approval gate, the real WS-07 tracker) against
  the fake ATS, then reads the tracking rows back out of the database.
  The metrics are computed from those rows, so the numbers describe the
  system rather than an expectation about it.
- `tests/evaluation/golden/scenarios.jsonl` — eight scenarios covering
  every branch: three that complete on their own (`/basic`,
  `/multipage`, `/widgets`), three that pause for a human (`/unknown`,
  `/captcha`, `/validation`), one a human declines at the gate
  (`rejected`), and one where a human records the outcome after a
  confirmed submission (`human_outcome`).

**The human-intervention rate is defined as "the run stopped for a
human"**, not "a human was present". The approval gate is mandatory in
this design, so the latter would be 1.0 for every run and would measure
nothing. What is worth measuring is how often the agent could *not*
finish on its own: 3 of 8 (0.375).

## Phase H — browser-automation metrics (the §7 "Browser automation" group)

- `src/evaluation/browser.py` (new) — `form_completion_rate`,
  `navigation_failure_rate`, `verification_success_rate`, and the status
  distribution, computed from the status the adapter returned.

## Phase I — the remaining §7 families

- `ranking.recall_at_10` — the counterpart to precision@5: of the
  relevant listings, how many the ranking showed.
- `relevance.duplicate_rate` — the corpus-level view, complementing the
  deduplicator's own precision and recall.
- `ranking.false_positive_rate` / `ranking.false_negative_rate` — the
  match decision's error rates. The engine produces a score, not a
  decision, so the **threshold is declared, not fitted**: it is the
  engine's own documented neutral score (70), and the report prints it.
  The measured false-negative rate is high (0.7722) because the golden
  corpus's scores sit below the neutral line — a real finding about the
  corpus and the threshold, not a defect in the metric.
- `relevance.job_relevance` — the share of the job's required skills the
  tailored resume carries.
- `relevance.hallucination_rate` — the share of the tailored claims the
  factuality validator had to strip (0.0606 on the golden set).

## Phase J — the report, the thresholds, the gate

- `src/evaluation/thresholds.json` — restructured into `min` and `max`
  sections (a rate like the false-positive rate is good when it is
  **low**), plus a `system` section for the metrics the live script
  produces. A metric the run did not measure is **skipped, never
  silently passed**.
- The report gains a **"Not measured in this run"** section naming the
  families a run could not measure and why. The system and browser
  metrics need a browser and a live database, so they are produced by
  `scripts/verify_ws09.py`; the offline report says so rather than
  leaving the reader to assume they were measured.

## Phase K — live verification

`scripts/verify_ws09.py` — **26/26 checks passed**: the real workflow
against the real fake ATS in Chromium, with a real database, and the
system and browser metrics computed from the rows the workflow actually
wrote. The script asserts the **values**, not merely that a run
happened: every scenario's final status and event sequence, the
aggregate rates against the rates the scenario mix implies, and every
run landing in exactly one bucket.

### Three defects the live run found (all fixed)

The live verification earned its place: it found three real problems
that the unit suite could not, because all three need a real database
and a real browser.

1. **A failed evidence write silently cancelled the tracking writes**
   (`src/graph/nodes.py`). The submit node wrote the evidence row and
   then, on failure, **returned** — skipping the `SUBMITTED` transition
   and the `evidence_recorded` event entirely. The function's own
   docstring says "the evidence write and the tracking writes are
   independent: neither can cost the other", but the code did exactly
   that: a missing evidence table left the application claiming it had
   **never been submitted**, which is an audit trail that under-reports
   what the agent did. Fixed: the evidence failure is now recorded as
   such (`evidence_stored: false`) and the lifecycle is still written.
   Regression test: `tests/test_application_workflow.py`.
2. **The scenario runner double-recorded the rejection.** It wrote an
   `approval_rejected` event *and* a transition carrying the same event
   type, so the event log showed two rejections. The API's reject route
   records the decision as the transition's own event; the runner now
   does the same.
3. **The evaluation's own database was missing tables.**
   `Base.metadata.create_all` only creates the tables whose model
   modules have been *imported*, so the harness's database silently
   lacked the evidence and approval tables. Fixed by importing every
   model module, as the migrations do.

### A metric definition the live run forced a correction on

The first draft of the system metrics counted "a human was present"
as the human-intervention rate. The live run showed why that is
worthless: the approval gate is mandatory, so every run has a human in
it, and the rate would be 1.0 — a constant wearing a measurement's
clothes. The metric now counts the runs that **stopped** for a human
(3 of 8), and the runs whose terminal outcome a human set are counted
separately, so the two are never confused and every run falls in
exactly one bucket.

## The measured baseline (offline, dataset hash `6ddec277c3f2…`)

| Metric | Value | Threshold |
|---|---|---|
| extraction field accuracy | 1.0000 | ≥ 0.95 |
| extraction skills set-F1 | 1.0000 | ≥ 0.85 |
| dedup precision / recall | 1.0000 / 1.0000 | ≥ 0.98 / ≥ 0.90 |
| ranking nDCG@10 | 0.7537 | ≥ 0.60 |
| ranking precision@5 | 0.4000 | ≥ 0.40 |
| ranking recall@10 | 0.6458 | ≥ 0.50 |
| ranking false-positive rate | 0.0000 | ≤ 0.35 |
| ranking false-negative rate | 0.7722 | ≤ 0.85 |
| tailoring factuality agreement | 1.0000 | ≥ 0.90 |
| tailoring violation recall | 1.0000 | ≥ 0.90 |
| relevance duplicate rate | 0.2000 | — |
| relevance job relevance | 1.0000 | ≥ 0.90 |
| relevance hallucination rate | 0.0606 | ≤ 0.10 |
| ATS coverage delta | +0.1111 | ≥ 0 |

**The system and browser metrics (live, `scripts/verify_ws09.py`):**

| Metric | Value | Threshold |
|---|---|---|
| system successful rate | 0.3750 | ≥ 0.30 |
| system human intervention rate | 0.3750 | ≤ 0.50 |
| system human outcome rate | 0.1250 | — |
| system incorrect submission rate | 0.0000 | ≤ 0.00 |
| system verification rate | 1.0000 | ≥ 1.00 |
| system lifecycle fidelity | 1.0000 | ≥ 1.00 |
| browser form completion rate | 0.3750 | ≥ 0.30 |
| browser navigation failure rate | 0.0000 | ≤ 0.00 |
| browser verification success rate | 1.0000 | ≥ 1.00 |

## What is still not measured

- **No live LLM run is part of the gate.** The live mode exists and was
  measured by hand, but the CI gate is the offline run: a live run is
  not reproducible and depends on a quota, so it cannot be a gate.
- **The system and browser metrics are not in the offline report.** They
  need a browser and a live database, so they live in the live script's
  report; the offline report names them as not measured.
- **The golden set is still 25 listings over 4 profiles.** The
  false-negative rate is high because the corpus's scores sit below the
  declared decision threshold; a larger, more varied corpus would say
  more about the threshold's placement.
- **The matching decision threshold is a declared constant, not a tuned
  one.** It is the engine's neutral score (70), chosen so the number is
  conservative by construction. A production deployment would want the
  threshold set where the business wants it, and the report prints it so
  the number is never mistaken for a property of the engine.

