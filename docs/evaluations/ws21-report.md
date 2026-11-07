# Evaluation report — 021aa3f6d56a

- Mode: **offline**
- Reproducible: **yes**
- Dataset hash: `021aa3f6d56a1b63a4d68be4b7cbc1733a008c59c62d113d37e46fe8e1868db8`
- Golden set: 5 profiles, 29 listings, 6 tailoring pairs
- Providers: LLM `canned-drafts` / `none`, embeddings `lexical-standin` / `none`

## Metrics

| Area | Metric | Value |
|---|---|---|
| extraction | `extraction.field_accuracy` | 1.0000 |
| extraction | `extraction.skills_f1` | 1.0000 |
| extraction | `extraction.summary_coverage` | 1.0000 |
| extraction | `extraction.experience_precision` | 1.0000 |
| extraction | `extraction.experience_recall` | 1.0000 |
| extraction | `extraction.education_precision` | 1.0000 |
| extraction | `extraction.education_recall` | 1.0000 |
| dedup | `dedup.precision` | 1.0000 |
| dedup | `dedup.recall` | 1.0000 |
| dedup | `dedup.f1` | 1.0000 |
| ranking | `ranking.ndcg_at_10` | 0.8240 |
| ranking | `ranking.precision_at_5` | 0.4000 |
| ranking | `ranking.recall_at_10` | 0.7333 |
| ranking | `ranking.degraded_ndcg_at_10` | 0.8253 |
| ranking | `ranking.degraded_precision_at_5` | 0.4400 |
| ranking | `ranking.semantic_delta_ndcg_at_10` | -0.0013 |
| ranking | `ranking.false_positive_rate` | 0.0000 |
| ranking | `ranking.false_negative_rate` | 0.3533 |
| ranking | `ranking.role_mismatch_at_10` | 0.2800 |
| ranking | `ranking.role_uncertain_at_10` | 0.2800 |
| ats | `ats.coverage_delta` | 0.1111 |
| relevance | `relevance.duplicate_rate` | 0.1724 |
| relevance | `relevance.job_relevance` | 1.0000 |
| relevance | `relevance.hallucination_rate` | 0.0606 |
| tailoring | `tailoring.factuality_agreement` | 1.0000 |
| tailoring | `tailoring.violation_recall` | 1.0000 |

## Not measured in this run

| Family | Why |
|---|---|
| `system` | the application-lifecycle metrics need a browser and a live database; run scripts/verify_ws09.py |
| `browser` | the browser-automation metrics need a browser and a live database; run scripts/verify_ws09.py |

## Per-profile ranking

| Profile | nDCG@10 | Precision@5 | nDCG@10 degraded | Semantic delta | Role mismatch@10 |
|---|---|---|---|---|---|
| alex_rivera_backend | 0.7180 | 0.2000 | 0.7180 | +0.0000 | 0.0000 |
| mina_chen_ml | 0.7658 | 0.4000 | 0.7724 | -0.0065 | 0.3000 |
| sam_okoye_data | 0.8287 | 0.6000 | 0.8287 | +0.0000 | 0.3000 |
| lena_fischer_frontend | 0.8077 | 0.4000 | 0.8077 | +0.0000 | 0.0000 |
| kai_nakamura_hardware | 1.0000 | 0.4000 | 1.0000 | +0.0000 | 0.8000 |

## Tailoring pairs

| Profile | Job | Factuality | ATS score |
|---|---|---|---|
| alex_rivera_backend | golden:job-001 | passed | 100.0 |
| alex_rivera_backend | golden:job-002 | stripped: Removed 1 skill(s) not present in profile | 71.7 |
| mina_chen_ml | golden:job-003 | passed | 92.5 |
| mina_chen_ml | golden:job-004 | stripped: Removed experience for unknown company 'Globex' | 83.5 |
| sam_okoye_data | golden:job-005 | passed | 92.5 |
| lena_fischer_frontend | golden:job-007 | passed | 81.8 |

## Interpretation

The offline run holds the semantic channel constant (a deterministic lexical
stand-in) and serves every model call from the canned drafts, so the numbers
measure the deterministic layers of the pipeline: extraction, dedup, the hybrid
scorers, factuality stripping, and ATS keyword coverage. Two runs of this mode
produce identical numbers.

The `--live` mode is a different measurement, not a rerun of this one: it uses
the real LLM and the real embedding provider, so it is not reproducible and its
tailoring numbers describe the pipeline's own factuality behaviour rather than
agreement with the canned drafts' labels. The providers that produced each run
are named in the header, so the two are never confused.
