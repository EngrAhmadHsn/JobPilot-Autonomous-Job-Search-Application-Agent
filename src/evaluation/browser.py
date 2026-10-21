"""Browser-automation metrics over recorded application runs (WS-09 Part 2).

The plan's §7 "Browser automation" group asks for three numbers: the form
completion success rate, the navigation failure rate and the verification
success rate. They describe what the browser layer did, so they are
computed from what the run recorded — the status the adapter returned and
the evidence it left — rather than from a re-derivation of the run.

The statuses are the adapter's own vocabulary (WS-08 §S3.3):

``verified``
    the form was completed, submitted and confirmed;
``needs_human``
    a question the candidate's evidence does not answer — the run stopped
    before typing anything;
``form_error``
    the server rejected the form;
``blocked_human_review``
    the page presented a challenge;
``unsafe_navigation``
    a page URL failed the allowlist;
``verification_failed``
    a submission was attempted but the confirmation was absent.

Every function here is pure: it takes the recorded runs and returns a
number.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

__all__ = [
    "BROWSER_STATUSES",
    "browser_scores",
]

#: Every status the browser layer can end a run in.
BROWSER_STATUSES = (
    "verified",
    "needs_human",
    "form_error",
    "blocked_human_review",
    "unsafe_navigation",
    "verification_failed",
    "submission_failed",
    "permission_denied",
    "workflow_error",
)


def browser_scores(runs: Sequence[Mapping[str, object]]) -> dict[str, float | int]:
    """The plan §7 "Browser automation" metrics over a set of runs.

    Args:
        runs: One record per run. Each record carries the ``status`` the
            adapter returned and, optionally, the ``evidence_status``.

    Returns:
        The rates, plus the counts behind them and the status
        distribution.
    """
    total = len(runs)
    completed = 0
    navigation_failures = 0
    submitted = 0
    verified = 0
    paused = 0
    distribution: dict[str, int] = {}

    for run in runs:
        status = str(run.get("status") or "")
        distribution[status] = distribution.get(status, 0) + 1

        if status == "verified":
            # The form was completed, submitted and confirmed: the whole
            # browser path succeeded.
            completed += 1
            submitted += 1
            verified += 1
        elif status == "verification_failed":
            # The form went out but the confirmation never arrived.
            submitted += 1
        elif status == "unsafe_navigation":
            navigation_failures += 1
        elif status in {"needs_human", "blocked_human_review"}:
            # The agent stopped and handed the run to a human.
            paused += 1

    return {
        "runs": total,
        "form_completion_rate": round(completed / total, 6) if total else 0.0,
        "navigation_failure_rate": round(navigation_failures / total, 6) if total else 0.0,
        "verification_success_rate": round(verified / submitted, 6) if submitted else 0.0,
        "completed": completed,
        "submitted": submitted,
        "verified": verified,
        "paused_for_human": paused,
        "navigation_failures": navigation_failures,
        "status_distribution": distribution,
    }
