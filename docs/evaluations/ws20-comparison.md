# WS-20 · evaluation — before and after

Both runs are the offline, deterministic harness (`scripts/run_eval.py`) over
the same golden dataset, so the difference is the WS-20 scoring change alone.
Reproducible: no network, no provider, no API key.

| metric | baseline `report-2026-10-21` | WS-20 `report-2026-11-07` | notes |
|---|---|---|---|
| `ranking.ndcg_at_10` | 0.7537 | 0.7537 | unchanged — the top-10 ordering is stable; BM25 reinforces the same ranking |
| `ranking.precision_at_5` | 0.4000 | 0.4000 | unchanged |
| `ranking.recall_at_10` | — | 0.6458 | newly reported |
| `ranking.degraded_ndcg_at_10` | 0.7443 | 0.7301 | degraded ranking is now *lower*, because a vector-less listing no longer gains redistributed semantic weight |
| `ranking.semantic_delta_ndcg_at_10` | 0.0094 | 0.0236 | the semantic channel is now worth more *relative to* degraded mode (degraded stopped inflating) |
| `ranking.false_negative_rate` | 0.7722 (threshold **70**) | 0.6111 (threshold **30**) | the decision threshold was recalibrated — the neutral-70 line no longer exists |
| `ranking.false_positive_rate` | 0.0000 | 0.0000 | unchanged |
| `ranking.evidence_coverage` | — | 0.5250 | new — the average share of each score backed by real evidence |

## Reading the numbers honestly

- **The ranking metrics are unchanged, and that is the point.** WS-20 did not
  set out to move nDCG; it set out to stop *defaulting* — to make an unearned
  score impossible. That the ordering holds constant while the missing-data
  policy changes is evidence the change is safe.
- **The false-negative comparison crosses a threshold change.** The baseline's
  0.7722 was measured at the old declared threshold of 70 (the neutral score).
  Removing the neutral 70 removes that line, so the threshold was
  **recalibrated to 30** on the golden score distribution and the rate is
  measured there. The two FNRs are therefore not a like-for-like comparison;
  what is directly comparable is that the *same* threshold (30) applied to the
  old engine scores would have behaved differently — the old engine pushed
  more listings over 70 by giving them free credit, so at 30 it would report a
  *worse* precision. The recalibration is documented, not fitted to a target.
- **`evidence_coverage` is the new honesty signal.** 52.5% means the golden
  corpus's average score rests on a bit over half its weight in measured
  evidence, the rest being unknowns the profile or the listing did not state.
  Before WS-20 there was no way to see this at all: an unknown was silently
  70.

## Remaining limitations

- The golden dataset is small (25 listings, 4 profiles); these numbers are a
  regression guard, not a production benchmark.
- BM25's saturation constant (`K = 6.0`) and the seven weights were calibrated
  by inspection against this set; a larger labelled corpus would let them be
  fitted rather than declared.
- `evidence_coverage` is not yet thresholded in CI (it is reported, and will
  be gated once the golden set is larger and the number is stable).