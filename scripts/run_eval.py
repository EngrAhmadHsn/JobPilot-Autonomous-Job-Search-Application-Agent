"""Run the WS-09 evaluation harness and write a report.

One command, one report:

    python scripts/run_eval.py            # offline, deterministic, free
    python scripts/run_eval.py --live     # real LLM + real embedding provider
    python scripts/run_eval.py --check    # exit non-zero on a metric regression

The report is written to ``docs/evaluations/report-<date>.md`` (human) and
``report-<date>.json`` (machine). The dataset hash is recorded in both, so a
number can always be traced back to the exact dataset that produced it.

All metric logic lives in ``src/evaluation/metrics.py``; this script only
wires the harness to the filesystem and the threshold gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.evaluation.harness import load_dataset, run_offline

GOLDEN_DIR = REPO_ROOT / "tests" / "evaluation" / "golden"
THRESHOLDS_PATH = REPO_ROOT / "src" / "evaluation" / "thresholds.json"
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "evaluations"


def flatten_metrics(results: dict) -> dict[str, float]:
    """Flatten the nested metric tree into ``name -> value`` for gating."""
    metrics = results["metrics"]
    flat: dict[str, float] = {
        "extraction.field_accuracy": float(metrics["extraction"]["field_accuracy"]),
        "extraction.skills_f1": float(metrics["extraction"]["skills_f1"]),
        "extraction.summary_coverage": float(metrics["extraction"]["summary_coverage"]),
        "extraction.experience_precision": float(metrics["extraction"]["experience_precision"]),
        "extraction.experience_recall": float(metrics["extraction"]["experience_recall"]),
        "extraction.education_precision": float(metrics["extraction"]["education_precision"]),
        "extraction.education_recall": float(metrics["extraction"]["education_recall"]),
        "dedup.precision": float(metrics["dedup"]["precision"]),
        "dedup.recall": float(metrics["dedup"]["recall"]),
        "dedup.f1": float(metrics["dedup"]["f1"]),
        "ranking.ndcg_at_10": float(metrics["ranking"]["ndcg_at_10"]),
        "ranking.precision_at_5": float(metrics["ranking"]["precision_at_5"]),
        "ranking.degraded_ndcg_at_10": float(metrics["ranking"]["degraded_ndcg_at_10"]),
        "ranking.degraded_precision_at_5": float(metrics["ranking"]["degraded_precision_at_5"]),
        "ranking.semantic_delta_ndcg_at_10": float(metrics["ranking"]["semantic_delta_ndcg_at_10"]),
        "tailoring.factuality_agreement": float(metrics["tailoring"]["agreement"]),
        "tailoring.violation_recall": float(metrics["tailoring"]["violation_recall"]),
        "ats.coverage_delta": float(metrics["ats"]["coverage_delta"]),
    }
    return flat


def check_thresholds(results: dict) -> list[tuple[str, float, float]]:
    """Return the metrics that fall below their threshold."""
    thresholds = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
    flat = flatten_metrics(results)
    failures: list[tuple[str, float, float]] = []
    for name, minimum in thresholds.items():
        if name not in flat:
            continue
        if flat[name] < float(minimum):
            failures.append((name, flat[name], float(minimum)))
    return failures


def render_markdown(results: dict) -> str:
    lines = [
        f"# Evaluation report — {results['dataset']['hash'][:12]}",
        "",
        f"- Mode: **{results['mode']}**",
        f"- Dataset hash: `{results['dataset']['hash']}`",
        (
            f"- Golden set: {results['dataset']['profiles']} profiles, "
            f"{results['dataset']['jobs']} listings, "
            f"{results['dataset']['tailoring_pairs']} tailoring pairs"
        ),
        "",
        "## Metrics",
        "",
        "| Area | Metric | Value |",
        "|---|---|---|",
    ]
    for name, value in flatten_metrics(results).items():
        lines.append(f"| {name.split('.')[0]} | `{name}` | {value:.4f} |")

    lines += [
        "",
        "## Per-profile ranking",
        "",
        "| Profile | nDCG@10 | Precision@5 | nDCG@10 degraded | Semantic delta |",
        "|---|---|---|---|---|",
    ]
    for profile in results["profiles"]:
        lines.append(
            f"| {profile['profile']} | {profile['ranking']['ndcg_at_10']:.4f} | "
            f"{profile['ranking']['precision_at_5']:.4f} | "
            f"{profile['ranking']['degraded_ndcg_at_10']:.4f} | "
            f"{profile['ranking']['semantic_delta_ndcg_at_10']:+.4f} |"
        )

    lines += [
        "",
        "## Tailoring pairs",
        "",
        "| Profile | Job | Factuality | ATS score |",
        "|---|---|---|---|",
    ]
    for pair in results["pairs"]:
        lines.append(
            f"| {pair['profile']} | {pair['job']} | "
            f"{'passed' if pair['passed'] else 'stripped: ' + ', '.join(pair['violations'])} | "
            f"{pair['ats_score']:.1f} |"
        )

    lines += [
        "",
        "## Interpretation",
        "",
        "The offline run holds the semantic channel constant (a deterministic lexical",
        "stand-in) and serves every model call from the canned drafts, so the numbers",
        "measure the deterministic layers of the pipeline: extraction, dedup, the hybrid",
        "scorers, factuality stripping, and ATS keyword coverage. The `--live` mode",
        "re-runs the same dataset through the real LLM and embedding provider; the mode",
        "and dataset hash are recorded with every report so the two are never confused.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="use the real LLM (needs a configured key)"
    )
    parser.add_argument(
        "--check", action="store_true", help="exit non-zero when a metric regresses"
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="where reports are written")
    parser.add_argument("--golden-dir", default=str(GOLDEN_DIR), help="golden dataset directory")
    args = parser.parse_args()

    dataset = load_dataset(Path(args.golden_dir))
    results = run_offline(dataset, live=args.live)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).date().isoformat()
    json_path = out_dir / f"report-{stamp}.json"
    md_path = out_dir / f"report-{stamp}.md"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(results), encoding="utf-8")

    print(f"dataset hash : {results['dataset']['hash']}")
    print(f"mode         : {results['mode']}")
    for name, value in flatten_metrics(results).items():
        print(f"  {name:<38} {value:.4f}")
    print(f"\nreport written:\n  {md_path}\n  {json_path}")

    if args.check:
        failures = check_thresholds(results)
        if failures:
            print("\nthreshold failures:")
            for name, value, minimum in failures:
                print(f"  {name}: {value:.4f} < {minimum:.4f}")
            return 1
        print("\nall metrics meet their thresholds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
