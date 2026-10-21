"""Tests for the WS-09 evaluation runner (scripts/run_eval.py + harness).

The runner must be reproducible: two offline runs over the same dataset have
to produce identical numbers, and the report must record the dataset hash so
a number can be traced back to the data that produced it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "evaluation" / "golden"
RUNNER = REPO_ROOT / "scripts" / "run_eval.py"

sys.path.insert(0, str(REPO_ROOT))

from src.evaluation.harness import dataset_hash, load_dataset, run_offline


@pytest.fixture(scope="module")
def results() -> dict:
    return run_offline(load_dataset(GOLDEN_DIR))


def test_offline_run_populates_every_metric(results: dict) -> None:
    metrics = results["metrics"]
    assert set(metrics) == {
        "extraction",
        "dedup",
        "ranking",
        "tailoring",
        "ats",
        "relevance",
    }
    for section in metrics.values():
        for value in section.values():
            if isinstance(value, (int, float)):
                assert value is not None
    assert results["mode"] == "offline"
    assert results["dataset"]["profiles"] == 4
    assert results["dataset"]["jobs"] == 25
    assert results["dataset"]["tailoring_pairs"] == 6


def test_the_offline_run_names_the_stand_ins_it_used(results: dict) -> None:
    """A report must say what produced it. The offline run serves canned
    drafts and a lexical stand-in, and says so."""
    providers = results["providers"]
    assert providers["llm"]["provider"] == "canned-drafts"
    assert providers["embeddings"]["provider"] == "lexical-standin"
    assert results["reproducible"] is True


def test_the_offline_run_is_reproducible(results: dict) -> None:
    assert results["reproducible"] is True


def test_dataset_hash_is_stable_and_documented(results: dict) -> None:
    assert results["dataset"]["hash"] == dataset_hash(GOLDEN_DIR)
    assert len(results["dataset"]["hash"]) == 64


def test_two_runs_produce_identical_numbers() -> None:
    first = run_offline(load_dataset(GOLDEN_DIR))
    second = run_offline(load_dataset(GOLDEN_DIR))
    assert first["metrics"] == second["metrics"]
    assert first["profiles"] == second["profiles"]
    assert first["pairs"] == second["pairs"]


def test_extraction_is_exact_on_the_golden_set(results: dict) -> None:
    """The parser must reproduce the hand-labelled extractions."""
    extraction = results["metrics"]["extraction"]
    assert extraction["field_accuracy"] == 1.0
    assert extraction["skills_f1"] == 1.0
    assert extraction["experience_precision"] == 1.0
    assert extraction["education_precision"] == 1.0


def test_dedup_collapses_the_annotated_duplicate_groups(results: dict) -> None:
    dedup = results["metrics"]["dedup"]
    assert dedup["true_positive"] == 5  # 5 duplicate listings in the golden set
    assert dedup["false_positive"] == 0
    assert dedup["precision"] == 1.0
    assert dedup["recall"] == 1.0


def test_factuality_agreement_with_the_human_labels(results: dict) -> None:
    tailoring = results["metrics"]["tailoring"]
    assert tailoring["agreement"] == 1.0
    assert tailoring["violation_recall"] == 1.0


def test_runner_writes_both_report_files(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--out-dir",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    reports = list(tmp_path.glob("report-*.md"))
    payloads = list(tmp_path.glob("report-*.json"))
    assert len(reports) == 1 and len(payloads) == 1

    payload = json.loads(payloads[0].read_text(encoding="utf-8"))
    assert payload["mode"] == "offline"
    assert payload["dataset"]["hash"] == dataset_hash(GOLDEN_DIR)
    assert "metrics" in payload
    assert "dataset hash" in reports[0].read_text(encoding="utf-8").lower()


def test_check_passes_against_the_shipped_thresholds(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--check", "--out-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_fails_when_a_threshold_is_lowered(tmp_path: Path, monkeypatch) -> None:
    """A regression must be visible: lowering one threshold below the measured
    value makes --check exit non-zero."""
    thresholds_path = REPO_ROOT / "src" / "evaluation" / "thresholds.json"
    original = thresholds_path.read_text(encoding="utf-8")
    payload = json.loads(original)
    payload["min"]["extraction.field_accuracy"] = 1.01  # unreachable on purpose
    thresholds_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--check", "--out-dir", str(tmp_path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        assert result.returncode == 1
        assert "threshold failures" in result.stdout
    finally:
        thresholds_path.write_text(original, encoding="utf-8")


def test_check_fails_when_a_maximum_threshold_is_exceeded(tmp_path: Path) -> None:
    """A rate that is good when it is *low* is gated the same way."""
    thresholds_path = REPO_ROOT / "src" / "evaluation" / "thresholds.json"
    original = thresholds_path.read_text(encoding="utf-8")
    payload = json.loads(original)
    # A bound the measured rate (0.0) cannot satisfy, so the gate must
    # fail. It is deliberately *not* -1.0: that value is the gate's
    # "no constraint" sentinel (a rate is never <= -1.0, so a bound of
    # -1.0 would make every run fail rather than express a real limit).
    payload["max"]["ranking.false_positive_rate"] = -0.5
    thresholds_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--check", "--out-dir", str(tmp_path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        assert result.returncode == 1
        assert "threshold failures" in result.stdout
    finally:
        thresholds_path.write_text(original, encoding="utf-8")


def test_the_report_says_which_families_it_could_not_measure(tmp_path: Path) -> None:
    """A family the run did not measure must be named, not left to be
    assumed measured."""
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--out-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(next(tmp_path.glob("report-*.json")).read_text(encoding="utf-8"))
    assert "system" in payload["unavailable"]
    assert "browser" in payload["unavailable"]
    report = next(tmp_path.glob("report-*.md")).read_text(encoding="utf-8")
    assert "Not measured in this run" in report
