"""System-level metrics over the real application lifecycle (WS-09 Part 2).

The plan's §7 "Application system" group asks for four numbers:
successful applications, failed applications, human intervention rate and
incorrect submissions. Part 1 of WS-09 could not measure them, because the
WS-07 tracking tables did not exist yet. They do now.

This module holds the **pure** metric functions for that group. They take
the rows the workflow actually wrote — an application's final status and its
event log — and turn them into rates. Nothing here touches the database or
the workflow; the caller supplies the rows.

The rates are computed over a **scenario set**, not over production
traffic, so they describe the behaviour of the system over that set. The
report prints the set's size beside every rate, because a rate without its
denominator is not a measurement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

__all__ = [
    "HUMAN_ACTOR_PREFIX",
    "lifecycle_fidelity",
    "system_scores",
]

#: The prefix that marks an event actor as a named human. It matches
#: :data:`src.applications.tracking.HUMAN_ACTOR_PREFIX`; the constant is
#: repeated here so this module stays free of runtime imports, and the test
#: asserts the two agree.
HUMAN_ACTOR_PREFIX = "human:"


def _statuses(events: Sequence[Mapping[str, object]]) -> list[str]:
    """The status the application passed through, in event order.

    A transition event carries both the status it left and the status it
    reached. The reached status is what the lifecycle is made of, so that
    is what is collected — with the creation event's initial status first.
    """
    reached: list[str] = []
    for event in events:
        to_status = event.get("to_status")
        if to_status:
            reached.append(str(to_status))
    return reached


def _event_shape(events: Sequence[Mapping[str, object]]) -> list[str]:
    """The event log's shape: the type of each event, in order.

    The shape is compared rather than the full rows, because the rows
    carry timestamps and ids that differ between runs. What must be
    identical between a recording and a re-run is *what happened*, in
    what order.
    """
    return [str(event.get("event_type") or "") for event in events]


def system_scores(
    runs: Sequence[Mapping[str, object]],
    expected: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, float | int]:
    """The plan §7 "Application system" metrics over a set of runs.

    Args:
        runs: One record per application run. Each record carries the
            application's ``status`` and its ``events`` — the rows the
            workflow wrote.
        expected: The expected event-type sequence per run id, used for
            the lifecycle-fidelity rate. A run with no expectation is
            not counted in that rate.

    Returns:
        The rates, plus the counts behind them.

    Note:
        The **human intervention rate** counts the runs that *stopped for
        a human* — the agent reached a question it could not answer, a
        challenge, or a form the server rejected, so the run ended in
        ``awaiting_approval`` with no submission. It does **not** count
        the approval decision itself: the approval gate is mandatory in
        this design, so "a human was present" is true of every run and
        would make the rate a constant instead of a measurement. What is
        worth measuring is how often the agent could *not* finish on its
        own.

        Every run falls in exactly one bucket, so the buckets sum to the
        run count: ``successful`` (confirmed submission), ``failed`` (a
        human declined or the run was withdrawn), ``paused_for_human``
        (the agent stopped and the run is waiting), and
        ``human_outcome`` (a human set the terminal outcome after a
        confirmed submission).
    """
    total = len(runs)
    successful = 0
    failed = 0
    paused = 0
    human_outcome = 0
    incorrect = 0
    submitted = 0
    verified = 0
    fidelity_matches = 0
    fidelity_total = 0

    for run in runs:
        status = str(run.get("status") or "")
        events = list(run.get("events") or [])
        statuses = _statuses(events)

        if status == "verified":
            successful += 1
        elif status in {"rejected", "withdrawn"}:
            failed += 1
        elif status == "awaiting_approval":
            # The run stopped with the human: no submission was made.
            paused += 1
        elif status in {"interview", "offer"}:
            # A human set the terminal outcome after a confirmed
            # submission. The agent never sets one itself.
            human_outcome += 1

        reached_submitted = "submitted" in statuses
        reached_verified = "verified" in statuses
        if reached_submitted:
            submitted += 1
        if reached_verified:
            verified += 1
        # An *incorrect* submission is one that was recorded as submitted
        # and never confirmed by a verification. The application is not
        # claiming success, but the submission went out.
        if reached_submitted and not reached_verified:
            incorrect += 1

        run_id = str(run.get("workflow_id") or run.get("id") or "")
        if expected and run_id in expected:
            fidelity_total += 1
            if _event_shape(events) == list(expected[run_id]):
                fidelity_matches += 1

    return {
        "runs": total,
        "successful_applications": successful,
        "failed_applications": failed,
        "paused_for_human": paused,
        "human_outcome_applications": human_outcome,
        "submitted": submitted,
        "verified": verified,
        "successful_rate": round(successful / total, 6) if total else 0.0,
        "failed_rate": round(failed / total, 6) if total else 0.0,
        "human_intervention_rate": round(paused / total, 6) if total else 0.0,
        "human_outcome_rate": round(human_outcome / total, 6) if total else 0.0,
        "incorrect_submission_rate": round(incorrect / total, 6) if total else 0.0,
        "verification_rate": round(verified / submitted, 6) if submitted else 0.0,
        "lifecycle_fidelity": (
            round(fidelity_matches / fidelity_total, 6) if fidelity_total else 0.0
        ),
        "lifecycle_checked": fidelity_total,
    }


def lifecycle_fidelity(
    runs: Sequence[Mapping[str, object]],
    expected: Mapping[str, Sequence[str]],
) -> dict[str, float | int]:
    """How exactly the recorded lifecycles match the expected ones.

    Args:
        runs: The recorded runs.
        expected: The expected event-type sequence per run id.

    Returns:
        The match rate and the per-run detail.
    """
    checked = 0
    matched = 0
    detail: list[dict[str, object]] = []
    for run in runs:
        run_id = str(run.get("workflow_id") or run.get("id") or "")
        if run_id not in expected:
            continue
        checked += 1
        actual = _event_shape(list(run.get("events") or []))
        want = list(expected[run_id])
        if actual == want:
            matched += 1
        else:
            detail.append({"id": run_id, "expected": want, "actual": actual})
    return {
        "checked": checked,
        "matched": matched,
        "rate": round(matched / checked, 6) if checked else 0.0,
        "mismatches": detail,
    }
