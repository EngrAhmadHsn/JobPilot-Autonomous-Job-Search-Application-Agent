"""Tests for the WS-09 Part 2 metrics.

Every metric is checked against a hand-computed expectation, so a change
in the metric code cannot silently move the numbers the report shows.
"""

from __future__ import annotations

import pytest

from src.evaluation import metrics
from src.evaluation.browser import browser_scores
from src.evaluation.systems import system_scores

# --------------------------------------------------------------- discovery


def test_recall_at_k_counts_the_relevant_listings_shown():
    labels = {"a": 2, "b": 2, "c": 1, "d": 0}
    # By default only the grade-2 listings count as relevant, so both of
    # them are in the top two and the recall is complete.
    assert metrics.recall_at_k(["a", "b", "d"], labels, k=2) == 1.0


def test_recall_at_k_can_count_the_partial_listings_as_relevant():
    labels = {"a": 2, "b": 2, "c": 1, "d": 0}
    # With the partial grade included, three listings are relevant and
    # only two of them are in the top two.
    assert metrics.recall_at_k(
        ["a", "b", "d"], labels, k=2, min_grade=metrics.GRADE_PARTIAL
    ) == pytest.approx(2 / 3)


def test_recall_at_k_with_nothing_relevant_is_perfect():
    assert metrics.recall_at_k(["a"], {"a": 0}, k=1) == 1.0


def test_recall_at_k_ignores_relevant_listings_below_the_slice():
    labels = {"a": 2, "b": 2}
    assert metrics.recall_at_k(["a", "x", "y", "b"], labels, k=1) == pytest.approx(0.5)


def test_duplicate_rate_is_the_corpus_share():
    assert metrics.duplicate_rate(25, 5) == pytest.approx(0.2)
    assert metrics.duplicate_rate(0, 0) == 0.0


# ---------------------------------------------------------------- matching


def test_matching_error_rates_count_the_confusion():
    labels = {"a": 2, "b": 2, "c": 0, "d": 0}
    # "a" and "b" are relevant and predicted; "c" is irrelevant but
    # predicted; "d" is irrelevant and not predicted.
    scores = {"a": 90.0, "b": 80.0, "c": 75.0, "d": 10.0}
    result = metrics.matching_error_rates(["a", "b", "c", "d"], labels, scores, 70.0)
    assert result["true_positive"] == 2
    assert result["false_positive"] == 1
    assert result["true_negative"] == 1
    assert result["false_negative"] == 0
    assert result["false_positive_rate"] == pytest.approx(0.5)
    assert result["false_negative_rate"] == 0.0


def test_matching_error_rates_catch_a_missed_relevant_listing():
    labels = {"a": 2, "b": 2}
    scores = {"a": 90.0, "b": 10.0}
    result = metrics.matching_error_rates(["a", "b"], labels, scores, 70.0)
    assert result["false_negative"] == 1
    assert result["false_negative_rate"] == pytest.approx(0.5)


def test_matching_error_rates_are_zero_without_a_population():
    result = metrics.matching_error_rates([], {}, {}, 70.0)
    assert result["false_positive_rate"] == 0.0
    assert result["false_negative_rate"] == 0.0


# --------------------------------------------------------------- tailoring


def test_job_relevance_counts_the_required_skills_carried():
    assert metrics.job_relevance(["Python", "Docker"], ["Python", "Go"]) == pytest.approx(0.5)
    assert metrics.job_relevance(["Python", "Docker"], ["Python", "Docker"]) == 1.0


def test_job_relevance_finds_a_skill_mentioned_only_in_the_text():
    assert metrics.job_relevance(["Kubernetes"], [], "ran a Kubernetes cluster") == 1.0


def test_job_relevance_with_no_required_skills_is_perfect():
    assert metrics.job_relevance([], ["Python"]) == 1.0


def test_hallucination_rate_is_the_stripped_share():
    assert metrics.hallucination_rate(10, 2) == pytest.approx(0.2)
    assert metrics.hallucination_rate(10, 0) == 0.0
    assert metrics.hallucination_rate(0, 0) == 0.0


def test_live_factuality_scores_measure_the_pipeline_own_behaviour():
    produced = [
        {"passed": True, "violations": [], "removed_skills": []},
        {
            "passed": False,
            "violations": ["Removed 1 skill(s) not present in profile"],
            "removed_skills": ["Rust"],
        },
    ]
    scores = metrics.live_factuality_scores(produced)
    assert scores["pairs"] == 2
    assert scores["passed"] == 1
    assert scores["pass_rate"] == pytest.approx(0.5)
    assert scores["stripped_pairs"] == 1
    assert scores["strip_rate"] == pytest.approx(0.5)
    assert scores["stripped_claims"] == 1


# ------------------------------------------------------------------ system


def _run(status: str, events: list[dict], run_id: str = "r1") -> dict:
    return {"id": run_id, "status": status, "events": events}


def test_system_scores_count_a_verified_run():
    runs = [
        _run(
            "verified",
            [
                {"event_type": "application_created", "actor": "agent", "to_status": "prepared"},
                {
                    "event_type": "status_transition",
                    "actor": "agent",
                    "to_status": "awaiting_approval",
                },
                {
                    "event_type": "status_transition",
                    "actor": "agent",
                    "to_status": "submitted",
                },
                {
                    "event_type": "status_transition",
                    "actor": "agent",
                    "to_status": "verified",
                },
            ],
        )
    ]
    scores = system_scores(runs)
    assert scores["runs"] == 1
    assert scores["successful_applications"] == 1
    assert scores["successful_rate"] == 1.0
    assert scores["failed_applications"] == 0
    assert scores["human_intervention_rate"] == 0.0
    assert scores["incorrect_submission_rate"] == 0.0
    assert scores["verification_rate"] == 1.0


def test_system_scores_count_a_run_that_stopped_for_a_human():
    runs = [
        _run(
            "awaiting_approval",
            [
                {"event_type": "application_created", "actor": "agent", "to_status": "prepared"},
                {
                    "event_type": "status_transition",
                    "actor": "agent",
                    "to_status": "awaiting_approval",
                },
            ],
        )
    ]
    scores = system_scores(runs)
    assert scores["successful_applications"] == 0
    assert scores["paused_for_human"] == 1
    assert scores["human_intervention_rate"] == 1.0
    assert scores["submitted"] == 0


def test_system_scores_count_a_rejected_run_as_a_failure():
    runs = [_run("rejected", [{"event_type": "status_transition", "actor": "human:ada"}])]
    scores = system_scores(runs)
    assert scores["failed_applications"] == 1
    assert scores["failed_rate"] == 1.0


def test_system_scores_count_a_human_outcome_separately():
    """A human setting the outcome after a confirmed submission is neither a
    success of the agent nor a failure — it is a human outcome."""
    runs = [
        _run(
            "interview",
            [
                {"event_type": "status_transition", "actor": "agent", "to_status": "submitted"},
                {"event_type": "status_transition", "actor": "agent", "to_status": "verified"},
                {"event_type": "status_transition", "actor": "human:ada", "to_status": "interview"},
            ],
        )
    ]
    scores = system_scores(runs)
    assert scores["successful_applications"] == 0
    assert scores["failed_applications"] == 0
    assert scores["paused_for_human"] == 0
    assert scores["human_outcome_applications"] == 1
    assert scores["human_outcome_rate"] == 1.0
    # The submission still happened and was confirmed.
    assert scores["submitted"] == 1
    assert scores["verified"] == 1


def test_every_run_falls_in_exactly_one_bucket():
    runs = [
        _run("verified", [{"event_type": "status_transition", "to_status": "verified"}]),
        _run("rejected", [{"event_type": "status_transition", "to_status": "rejected"}]),
        _run("awaiting_approval", [{"event_type": "status_transition"}]),
        _run("interview", [{"event_type": "status_transition", "to_status": "interview"}]),
    ]
    scores = system_scores(runs)
    assert (
        scores["successful_applications"]
        + scores["failed_applications"]
        + scores["paused_for_human"]
        + scores["human_outcome_applications"]
        == scores["runs"]
    )


def test_system_scores_count_an_unconfirmed_submission_as_incorrect():
    runs = [
        _run(
            "awaiting_approval",
            [
                {"event_type": "status_transition", "actor": "agent", "to_status": "submitted"},
                {
                    "event_type": "verification_failed",
                    "actor": "agent",
                    "to_status": "awaiting_approval",
                },
            ],
        )
    ]
    scores = system_scores(runs)
    assert scores["submitted"] == 1
    assert scores["verified"] == 0
    assert scores["incorrect_submission_rate"] == 1.0
    assert scores["verification_rate"] == 0.0


def test_system_scores_compare_the_lifecycle_against_the_expectation():
    runs = [
        _run(
            "verified",
            [
                {"event_type": "application_created", "actor": "agent", "to_status": "prepared"},
                {
                    "event_type": "status_transition",
                    "actor": "agent",
                    "to_status": "awaiting_approval",
                },
            ],
        )
    ]
    expected = {"r1": ["application_created", "status_transition"]}
    scores = system_scores(runs, expected)
    assert scores["lifecycle_fidelity"] == 1.0
    assert scores["lifecycle_checked"] == 1

    wrong = {"r1": ["application_created", "evidence_recorded"]}
    assert system_scores(runs, wrong)["lifecycle_fidelity"] == 0.0


def test_system_scores_with_no_runs_are_all_zero():
    scores = system_scores([])
    assert scores["runs"] == 0
    assert scores["successful_rate"] == 0.0
    assert scores["human_intervention_rate"] == 0.0


# ------------------------------------------------------------------ browser


def test_browser_scores_count_a_completed_form():
    runs = [{"id": "a", "status": "verified"}]
    scores = browser_scores(runs)
    assert scores["form_completion_rate"] == 1.0
    assert scores["navigation_failure_rate"] == 0.0
    assert scores["verification_success_rate"] == 1.0


def test_browser_scores_count_a_navigation_failure():
    runs = [{"id": "a", "status": "unsafe_navigation"}]
    scores = browser_scores(runs)
    assert scores["form_completion_rate"] == 0.0
    assert scores["navigation_failure_rate"] == 1.0


def test_browser_scores_count_a_paused_run_as_neither_completion_nor_failure():
    runs = [{"id": "a", "status": "needs_human"}]
    scores = browser_scores(runs)
    assert scores["form_completion_rate"] == 0.0
    assert scores["navigation_failure_rate"] == 0.0
    assert scores["paused_for_human"] == 1


def test_browser_scores_count_an_unconfirmed_submission():
    runs = [{"id": "a", "status": "verification_failed"}]
    scores = browser_scores(runs)
    assert scores["submitted"] == 1
    assert scores["verified"] == 0
    assert scores["verification_success_rate"] == 0.0


def test_browser_scores_report_the_status_distribution():
    runs = [{"id": "a", "status": "verified"}, {"id": "b", "status": "needs_human"}]
    scores = browser_scores(runs)
    assert scores["status_distribution"] == {"verified": 1, "needs_human": 1}
