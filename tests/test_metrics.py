"""Tests for the WS-09 evaluation metrics (src/evaluation/metrics.py).

Every metric is checked against a hand-computed expectation, so a change in
the metric code cannot silently move the numbers the report shows.
"""

from __future__ import annotations

import math

import pytest

from src.evaluation import metrics

# --------------------------------------------------------------- extraction


def test_field_accuracy_counts_exact_matches():
    expected = {"name": "Alex Rivera", "email": "a@b.test", "title": "Engineer"}
    produced = {"name": "Alex Rivera", "email": "a@b.test", "title": "Designer"}
    assert metrics.field_accuracy(expected, produced, ["name", "email", "title"]) == pytest.approx(
        2 / 3
    )


def test_field_accuracy_is_case_and_space_insensitive():
    expected = {"name": "Alex Rivera"}
    produced = {"name": "  alex rivera "}
    assert metrics.field_accuracy(expected, produced, ["name"]) == 1.0


def test_field_accuracy_with_no_fields_is_perfect():
    assert metrics.field_accuracy({}, {}, []) == 1.0


def test_set_f1_edge_cases():
    assert metrics.set_f1([], []) == 1.0
    assert metrics.set_f1([], ["Python"]) == 0.0
    assert metrics.set_f1(["Python"], []) == 0.0
    assert metrics.set_f1(["Python"], ["python"]) == 1.0
    # one of two expected, one of two produced -> precision .5 recall .5 F1 .5
    assert metrics.set_f1(["Python", "Go"], ["Python", "Rust"]) == pytest.approx(0.5)


def test_entry_scores_counts_matched_entries():
    expected = [{"title": "Backend Engineer", "company": "Acme Corp"}]
    produced = [
        {"title": "Backend Engineer", "company": "Acme Corp"},
        {"title": "Data Analyst", "company": "Other"},
    ]
    scores = metrics.entry_scores(expected, produced, ("title", "company"))
    assert scores["matched"] == 1
    assert scores["precision"] == pytest.approx(0.5)
    assert scores["recall"] == pytest.approx(1.0)


def test_entry_scores_requires_every_key_to_match():
    expected = [{"title": "Backend Engineer", "company": "Acme Corp"}]
    produced = [{"title": "Backend Engineer", "company": "Different"}]
    scores = metrics.entry_scores(expected, produced, ("title", "company"))
    assert scores["matched"] == 0
    assert scores["precision"] == 0.0


# ------------------------------------------------------------------- dedup


def test_dedup_scores_perfect_case():
    scores = metrics.dedup_scores(kept_ids={"a", "b"}, removed_ids={"c"}, duplicate_of={"c": "a"})
    assert scores["true_positive"] == 1
    assert scores["false_positive"] == 0
    assert scores["false_negative"] == 0
    assert scores["precision"] == 1.0
    assert scores["recall"] == 1.0


def test_dedup_scores_counts_kept_duplicate_as_miss():
    scores = metrics.dedup_scores(
        kept_ids={"a", "b", "c"}, removed_ids={"d"}, duplicate_of={"d": "a", "c": "b"}
    )
    assert scores["true_positive"] == 1
    assert scores["false_negative"] == 1
    assert scores["precision"] == 1.0
    assert scores["recall"] == pytest.approx(0.5)


def test_dedup_scores_counts_wrong_removal_as_false_positive():
    scores = metrics.dedup_scores(kept_ids={"a"}, removed_ids={"b"}, duplicate_of={"c": "a"})
    assert scores["false_positive"] == 1
    assert scores["precision"] == 0.0


# ----------------------------------------------------------------- ranking


def test_ndcg_perfect_ordering_is_one():
    labels = {"a": 2, "b": 1, "c": 0}
    assert metrics.ndcg_at_k(["a", "b", "c"], labels, k=3) == pytest.approx(1.0)


def test_ndcg_swapped_ordering_matches_hand_computation():
    labels = {"a": 2, "b": 1, "c": 0}
    ranked = ["b", "a", "c"]
    dcg = 1 / math.log2(2) + 3 / math.log2(3)
    idcg = 3 / math.log2(2) + 1 / math.log2(3)
    assert metrics.ndcg_at_k(ranked, labels, k=3) == pytest.approx(dcg / idcg, abs=1e-6)
    assert metrics.ndcg_at_k(ranked, labels, k=3) < 1.0


def test_ndcg_zero_when_no_relevant_items():
    assert metrics.ndcg_at_k(["a", "b"], {"a": 0, "b": 0}, k=2) == 0.0


def test_precision_at_k_counts_only_relevant():
    labels = {"a": 2, "b": 1, "c": 0, "d": 2, "e": 0}
    assert metrics.precision_at_k(["a", "b", "c", "d", "e"], labels, k=5) == pytest.approx(0.4)
    # with min_grade=1 the partial counts as a hit
    assert metrics.precision_at_k(["a", "b", "c", "d", "e"], labels, k=5, min_grade=1) == 0.6


def test_precision_at_k_respects_k():
    labels = {"a": 2, "b": 2}
    assert metrics.precision_at_k(["a", "b"], labels, k=1) == 1.0


def test_mean_of_empty_is_zero():
    assert metrics.mean([]) == 0.0
    assert metrics.mean([1.0, 3.0]) == pytest.approx(2.0)


# --------------------------------------------------------------- tailoring


def test_factuality_scores_agreement_and_violation_recall():
    expected = [
        {"expected_passed": True, "expected_violations": []},
        {"expected_passed": False, "expected_violations": ["Rust"]},
    ]
    produced = [
        {"passed": True, "violations": []},
        {"passed": False, "violations": ["Removed skills not present in profile: Rust"]},
    ]
    scores = metrics.factuality_scores(expected, produced)
    assert scores["agreement"] == 1.0
    assert scores["violation_recall"] == 1.0


def test_factuality_scores_penalise_disagreement():
    expected = [{"expected_passed": True, "expected_violations": []}]
    produced = [{"passed": False, "violations": ["Removed something"]}]
    scores = metrics.factuality_scores(expected, produced)
    assert scores["agreement"] == 0.0


def test_factuality_scores_violation_miss_lowers_recall():
    expected = [{"expected_passed": False, "expected_violations": ["Rust"]}]
    produced = [{"passed": False, "violations": ["Removed something else"]}]
    scores = metrics.factuality_scores(expected, produced)
    assert scores["violation_recall"] == 0.0


def test_factuality_scores_match_structured_removals():
    """The metric asks "did the validator catch this fact?", so a labelled
    violation matches the structured removal lists even when the violation
    text does not name it."""
    expected = [{"expected_passed": False, "expected_violations": ["Rust"]}]
    produced = [
        {
            "passed": False,
            "violations": ["Removed 1 skill(s) not present in profile"],
            "removed_skills": ["Rust"],
        }
    ]
    scores = metrics.factuality_scores(expected, produced)
    assert scores["violation_recall"] == 1.0


# --------------------------------------------------------------------- ATS


def test_coverage_delta_is_after_minus_before():
    assert metrics.coverage_delta(0.25, 0.5) == pytest.approx(0.25)
    assert metrics.coverage_delta(0.5, 0.25) == pytest.approx(-0.25)
