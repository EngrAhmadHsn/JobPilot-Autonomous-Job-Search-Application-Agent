"""WS-21 before/after comparison: the numbers behind docs/evaluations/ws21-comparison.md.

Before: the pre-WS-21 harness (a git worktree at ``1c41e60``) run over the
same extended golden dataset; its ranked ids were dumped by the worktree's
own harness. After: ``docs/evaluations/ws21-report.json``.

To reproduce the before side, recreate the worktree and run the harness with
the main environment's Python, then dump ``run_profile(...)["ranked_ids"]``
into ``<dir>/out/rankings.json`` (the stored report does not carry them)::

    git worktree add <dir> 1c41e60
    env/Scripts/python.exe <dir>/scripts/run_eval.py \\
        --golden-dir tests/evaluation/golden --out-dir <dir>/out

Then run this script from the repo root, optionally passing ``<dir>/out``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.evaluation.harness import load_dataset
from src.matching.roles import (
    BAND_WEAK,
    classify_job_role,
    compatibility,
    resolve_candidate_targets,
)
from src.resume.parser import parse_resume

DEFAULT_BEFORE_DIR = Path(r"C:\Users\AHMAD\zcode-ws21-before\out")
BEFORE_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BEFORE_DIR
AFTER_REPORT = REPO / "docs" / "evaluations" / "ws21-report.json"


def role_maps(dataset, profile_key: str):
    profile = parse_resume(str(dataset.root / dataset.expected_profiles[profile_key]["file"]))
    targets = resolve_candidate_targets(profile)
    mismatched: dict[str, bool] = {}
    uncertain: dict[str, bool] = {}
    for job in dataset.listings:
        classification = classify_job_role(job)
        uncertain[job.id] = classification.family is None or classification.ambiguous
        mismatched[job.id] = bool(
            targets.families
            and classification.family is not None
            and max(compatibility(family, classification.family) for family in targets.families)
            <= BAND_WEAK
        )
    return mismatched, uncertain


def rate(ranked: list[str], flags: dict[str, bool], k: int = 10) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    return round(sum(1 for job_id in top if flags.get(job_id, False)) / len(top), 4)


def main() -> None:
    dataset = load_dataset(REPO / "tests" / "evaluation" / "golden")
    before_rankings = json.loads((BEFORE_DIR / "rankings.json").read_text(encoding="utf-8"))
    before_report = json.loads((BEFORE_DIR / "report-2026-11-07.json").read_text(encoding="utf-8"))
    after_report = json.loads(AFTER_REPORT.read_text(encoding="utf-8"))

    print("profile                   mismatch@10 before->after  uncertain@10 before->after")
    before_mismatch, after_mismatch = [], []
    for profile in after_report["profiles"]:
        key = profile["profile"]
        mismatched, uncertain = role_maps(dataset, key)
        b_m = rate(before_rankings[key], mismatched)
        b_u = rate(before_rankings[key], uncertain)
        a_m = profile["ranking"]["role_mismatch_at_10"]
        a_u = profile["ranking"]["role_uncertain_at_10"]
        before_mismatch.append(b_m)
        after_mismatch.append(a_m)
        print(f"{key:26} {b_m:.2f} -> {a_m:.2f}           {b_u:.2f} -> {a_u:.2f}")
    mean_b = sum(before_mismatch) / len(before_mismatch)
    mean_a = sum(after_mismatch) / len(after_mismatch)
    print(f"mean mismatch@10: {mean_b:.4f} -> {mean_a:.4f}")

    keys = (
        "ndcg_at_10",
        "precision_at_5",
        "recall_at_10",
        "false_positive_rate",
        "false_negative_rate",
        "degraded_ndcg_at_10",
        "semantic_delta_ndcg_at_10",
    )
    print("\naggregate                         before -> after")
    for key in keys:
        print(
            f"{key:28} {before_report['metrics']['ranking'][key]:.4f} -> "
            f"{after_report['metrics']['ranking'][key]:.4f}"
        )
    for key in ("role_mismatch_at_10", "role_uncertain_at_10"):
        print(f"{key:28} (n/a) -> {after_report['metrics']['ranking'][key]:.4f}")

    print("\nhard negatives in the frontend candidate's top-10 (before):")
    by_id = {job.id: job for job in dataset.listings}
    for rank, job_id in enumerate(before_rankings["lena_fischer_frontend"][:10], 1):
        classification = classify_job_role(by_id[job_id])
        if classification.family in {"hardware_physical_design", "sales", "data_analytics"}:
            print(f"  rank {rank}: {job_id} ({classification.family})")


if __name__ == "__main__":
    main()
