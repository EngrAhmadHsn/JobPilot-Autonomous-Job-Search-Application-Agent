# WS-09 · Evaluation Harness

Status: **Not started** · Milestone: **M4** · Depends on: [02](02-job-discovery.md), [03](03-matching-engine.md), [04](04-pipeline-and-api.md), [05](05-tailoring-and-research.md) · Blocks: honest "autonomous" claims (plan §7: *"Do not claim the system is autonomous without measurable evaluation"*)

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

- [ ] `python scripts/run_eval.py` (offline) produces a complete report with every metric populated and the dataset hash; a second run yields **identical** numbers.
- [ ] `--check` fails when a metric drops below threshold (tested by temporarily lowering a threshold).
- [ ] Metrics are computed only by `src/evaluation/metrics.py` (no metric logic buried in scripts).
- [ ] No PII in the repo beyond the already-present fixtures; golden resumes carry redacted identities.

## Tests

- `tests/test_metrics.py` — each metric against hand-computed expected values (ndcg on a tiny known ranking, F1 edge cases, dedup P/R).
- `tests/test_eval_runner.py` — offline run over the golden set: report file created, JSON schema, determinism (two runs byte-equal except timestamps), `--check` regression behavior.

## New dependencies

None.
