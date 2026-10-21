"""Run the WS-09 evaluation harness and write a report.

One command, one report:

    python scripts/run_eval.py            # offline, deterministic, free
    python scripts/run_eval.py --live     # real LLM + real embedding provider
    python scripts/run_eval.py --check    # exit non-zero on a metric regression

The report is written to ``docs/evaluations/report-<date>.md`` (human) and
``report-<date>.json`` (machine). The dataset hash is recorded in both, so
a number can always be traced back to the exact dataset that produced it.

**The mode is a fact, not a label.** ``--live`` really calls the configured
LLM and the configured embedding provider; a live run that cannot reach
them fails loudly rather than quietly serving the canned data under a
"live" heading. The report names the providers that produced the run.

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

from src.evaluation.harness import MODE_LIVE, MODE_OFFLINE, load_dataset, run_evaluation

GOLDEN_DIR = REPO_ROOT / "tests" / "evaluation" / "golden"
THRESHOLDS_PATH = REPO_ROOT / "src" / "evaluation" / "thresholds.json"
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "evaluations"


def flatten_metrics(results: dict) -> dict[str, float]:
    """Flatten the nested metric tree into ``name -> value`` for gating.

    The tailoring family differs by mode: offline it scores agreement with
    the hand labels of the canned drafts, live it scores the pipeline's own
    factuality behaviour over the real drafts. Only the names that exist in
    the run that produced the report are returned, so a threshold on a
    metric the run did not measure is skipped rather than silently passed.
    """
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
        # WS-12: this metric was measured and declared as a threshold, but
        # it was missing from the flattened set, so the gate skipped it. A
        # threshold that is never enforced is a threshold that reads as a
        # guarantee and is not one.
        "ranking.recall_at_10": float(metrics["ranking"]["recall_at_10"]),
        "ranking.degraded_ndcg_at_10": float(metrics["ranking"]["degraded_ndcg_at_10"]),
        "ranking.degraded_precision_at_5": float(metrics["ranking"]["degraded_precision_at_5"]),
        "ranking.semantic_delta_ndcg_at_10": float(metrics["ranking"]["semantic_delta_ndcg_at_10"]),
        "ranking.false_positive_rate": float(metrics["ranking"]["false_positive_rate"]),
        "ranking.false_negative_rate": float(metrics["ranking"]["false_negative_rate"]),
        "ats.coverage_delta": float(metrics["ats"]["coverage_delta"]),
        "relevance.duplicate_rate": float(metrics["relevance"]["duplicate_rate"]),
        "relevance.job_relevance": float(metrics["relevance"]["job_relevance"]),
        "relevance.hallucination_rate": float(metrics["relevance"]["hallucination_rate"]),
    }
    tailoring = metrics["tailoring"]
    if "agreement" in tailoring:
        flat["tailoring.factuality_agreement"] = float(tailoring["agreement"])
        flat["tailoring.violation_recall"] = float(tailoring["violation_recall"])
    if "pass_rate" in tailoring:
        flat["tailoring.live_pass_rate"] = float(tailoring["pass_rate"])
        flat["tailoring.live_strip_rate"] = float(tailoring["strip_rate"])
    return flat


#: A **maximum** bound of this value means "no constraint". The metrics
#: that carry a maximum are rates, which live in [0, 1], so a bound below
#: zero can never be satisfied — a rate is never <= -1.0. Treating it as a
#: real bound would make the gate fail every run, which is how a gate
#: stops being read as a guarantee. The way to *disable* a maximum is to
#: say so.
DISABLED_MAX = -1.0


def check_thresholds(results: dict) -> list[tuple[str, float, str]]:
    """The metrics that fall outside their threshold.

    A threshold is a **minimum** or a **maximum**: a rate like the
    false-positive rate is good when it is *low*, and one like the
    extraction accuracy is good when it is *high*. Both are expressed in
    the thresholds file, and a metric the run did not measure is skipped
    rather than silently passed.

    A maximum of :data:`DISABLED_MAX` is read as "no constraint on this
    metric" rather than as a bound no rate could ever meet.
    """
    thresholds = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
    flat = flatten_metrics(results)
    failures: list[tuple[str, float, str]] = []
    for name, minimum in (thresholds.get("min") or {}).items():
        if name not in flat:
            continue
        if flat[name] < float(minimum):
            failures.append((name, flat[name], f"< {float(minimum):.4f}"))
    for name, maximum in (thresholds.get("max") or {}).items():
        if name not in flat:
            continue
        bound = float(maximum)
        if bound <= DISABLED_MAX:
            # Explicitly unconstrained: skip it rather than fail every run.
            continue
        if flat[name] > bound:
            failures.append((name, flat[name], f"> {bound:.4f}"))
    return failures


def render_markdown(results: dict) -> str:
    lines = [
        f"# Evaluation report — {results['dataset']['hash'][:12]}",
        "",
        f"- Mode: **{results['mode']}**",
        f"- Reproducible: **{'yes' if results['reproducible'] else 'no'}**",
        f"- Dataset hash: `{results['dataset']['hash']}`",
        (
            f"- Golden set: {results['dataset']['profiles']} profiles, "
            f"{results['dataset']['jobs']} listings, "
            f"{results['dataset']['tailoring_pairs']} tailoring pairs"
        ),
    ]
    providers = results.get("providers") or {}
    if providers:
        llm = providers.get("llm") or {}
        embeddings = providers.get("embeddings") or {}
        lines.append(
            f"- Providers: LLM `{llm.get('provider')}` / `{llm.get('model')}`, "
            f"embeddings `{embeddings.get('provider')}` / `{embeddings.get('model')}`"
        )
    lines += [
        "",
        "## Metrics",
        "",
        "| Area | Metric | Value |",
        "|---|---|---|",
    ]
    for name, value in flatten_metrics(results).items():
        lines.append(f"| {name.split('.')[0]} | `{name}` | {value:.4f} |")

    unavailable = results.get("unavailable") or {}
    if unavailable:
        lines += [
            "",
            "## Not measured in this run",
            "",
            "| Family | Why |",
            "|---|---|",
        ]
        for family, reason in unavailable.items():
            lines.append(f"| `{family}` | {reason} |")

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
    ]
    if results["mode"] == MODE_OFFLINE:
        lines += [
            "The offline run holds the semantic channel constant (a deterministic lexical",
            "stand-in) and serves every model call from the canned drafts, so the numbers",
            "measure the deterministic layers of the pipeline: extraction, dedup, the hybrid",
            "scorers, factuality stripping, and ATS keyword coverage. Two runs of this mode",
            "produce identical numbers.",
            "",
            "The `--live` mode is a different measurement, not a rerun of this one: it uses",
            "the real LLM and the real embedding provider, so it is not reproducible and its",
            "tailoring numbers describe the pipeline's own factuality behaviour rather than",
            "agreement with the canned drafts' labels. The providers that produced each run",
            "are named in the header, so the two are never confused.",
            "",
        ]
    else:
        lines += [
            "This report was produced by the **live** mode: the tailored drafts came from",
            "the configured LLM and the semantic scores from the configured embedding",
            "provider, both named in the header. Those numbers are **not reproducible** — a",
            "second live run will differ, because a language model does. The deterministic",
            "layers of the pipeline (extraction, dedup, the non-semantic scorers) are still",
            "exact; the tailoring and semantic numbers are a measurement of this provider on",
            "this dataset at this moment, not a property of the code.",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="use the real LLM and the real embedding provider (needs a configured key)",
    )
    parser.add_argument(
        "--check", action="store_true", help="exit non-zero when a metric regresses"
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="where reports are written")
    parser.add_argument("--golden-dir", default=str(GOLDEN_DIR), help="golden dataset directory")
    args = parser.parse_args()

    mode = MODE_LIVE if args.live else MODE_OFFLINE
    dataset = load_dataset(Path(args.golden_dir))
    try:
        results = run_evaluation(dataset, mode=mode)
    except Exception as exc:  # noqa: BLE001 - the run must fail closed, whatever broke
        # A live run that cannot reach its provider must fail loudly. Falling
        # back to the canned data under a "live" heading would be a report
        # that lies about its own provenance.
        print(f"the {mode} evaluation could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    # The system and browser metrics need a browser and a live database, so
    # they are produced by ``scripts/verify_ws09.py``. The report says so
    # rather than leaving the reader to assume they were measured.
    results["unavailable"] = {
        "system": (
            "the application-lifecycle metrics need a browser and a live database; "
            "run scripts/verify_ws09.py"
        ),
        "browser": (
            "the browser-automation metrics need a browser and a live database; "
            "run scripts/verify_ws09.py"
        ),
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).date().isoformat()
    json_path = out_dir / f"report-{stamp}.json"
    md_path = out_dir / f"report-{stamp}.md"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(results), encoding="utf-8")

    print(f"dataset hash : {results['dataset']['hash']}")
    print(f"mode         : {results['mode']}")
    providers = results.get("providers") or {}
    if providers:
        llm = providers.get("llm") or {}
        embeddings = providers.get("embeddings") or {}
        print(f"llm          : {llm.get('provider')} / {llm.get('model')}")
        print(f"embeddings   : {embeddings.get('provider')} / {embeddings.get('model')}")
    for name, value in flatten_metrics(results).items():
        print(f"  {name:<38} {value:.4f}")
    print(f"\nreport written:\n  {md_path}\n  {json_path}")

    if args.check:
        failures = check_thresholds(results)
        if failures:
            print("\nthreshold failures:")
            for name, value, bound in failures:
                # The third element is the *rendered* bound ("> 0.3500"), not
                # a number, so it is printed as-is. Formatting it with a
                # float spec raised a ValueError and crashed the gate with
                # a traceback — the one moment the gate must not crash is
                # the moment it has something to report.
                print(f"  {name}: {value:.4f} {bound}")
            return 1
        print("\nall metrics meet their thresholds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
