# WS-09 · Evaluation Harness

Status: **Done (2026-10-21)** · Milestone: **M4** · Depends on: [02](02-job-discovery.md), [03](03-matching-engine.md), [04](04-pipeline-and-api.md), [05](05-tailoring-and-research.md) · Blocks: honest "autonomous" claims (plan §7: *"Do not claim the system is autonomous without measurable evaluation"*)

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
