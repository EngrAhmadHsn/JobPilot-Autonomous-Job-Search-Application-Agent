"""Live end-to-end verification of the WS-09 system and browser metrics.

Runs the **real** application workflow against the **real** fake ATS in
Chromium, with a **real** database, and then computes the plan §7 system
and browser metrics from the rows the workflow actually wrote.

The script is the gate for the phases that need a browser. It does not
merely check that a run happened: it asserts the *values* the metrics
produce against the expectations the golden scenario set declares, so a
broken lifecycle shows up as a wrong number rather than as a green run.

1. the fake ATS is served (the WS-08 variant pages);
2. a throwaway database is created with the current schema;
3. every scenario runs: prepare → the human decision → submit → verify;
4. the tracking rows are read back and the metrics are computed;
5. every scenario's final status and event sequence is checked against
   the golden expectation, and the aggregate rates are checked against
   the rates the scenario mix implies;
6. the offline harness is run over the same golden set and the report is
   written, so the two can be compared.

Every check prints PASS/FAIL; the script exits non-zero when a check fails.

Usage::

    env\\Scripts\\python.exe scripts\\verify_ws09.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The verification runs against a throwaway database and evidence
# directory, so it never touches the developer's data. The environment
# must be set before the application modules are imported (the settings
# are read at import time).
_WORKDIR = Path(tempfile.mkdtemp(prefix="ws09-verify-"))
EVIDENCE_DIR = _WORKDIR / "evidence"
os.environ["DATABASE_URL"] = f"sqlite:///{(_WORKDIR / 'verify.db').as_posix()}"
os.environ["EVIDENCE_DIR"] = str(EVIDENCE_DIR)
os.environ["ALEMBIC_DATABASE_URL"] = f"sqlite:///{(_WORKDIR / 'verify.db').as_posix()}"
os.environ.setdefault("APP_ENV", "development")

from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter
from src.evaluation.runner import run_scenarios
from src.evaluation.scenarios import (
    load_scenarios,
    make_session_factory,
    read_runs,
)
from tests.fixtures.fake_ats import serve_fake_ats_variants

GOLDEN_DIR = REPO_ROOT / "tests" / "evaluation" / "golden"
SCENARIO_FILE = GOLDEN_DIR / "scenarios.jsonl"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record one check and print its outcome."""
    RESULTS.append((name, condition, detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _expected_rates(scenario_set) -> dict[str, float]:
    """The rates the scenario mix implies, computed from the expectations.

    The metrics are checked against these, so a wrong number in the
    harness cannot hide behind a scenario that behaved as declared.
    """
    total = len(scenario_set.scenarios)
    successful = sum(1 for s in scenario_set.scenarios if s.expected_status == "verified")
    failed = sum(1 for s in scenario_set.scenarios if s.expected_status == "rejected")
    paused = sum(1 for s in scenario_set.scenarios if s.expected_status == "awaiting_approval")
    human_outcome = sum(
        1 for s in scenario_set.scenarios if s.expected_status in {"interview", "offer"}
    )
    return {
        "successful_rate": successful / total if total else 0.0,
        "failed_rate": failed / total if total else 0.0,
        "human_intervention_rate": paused / total if total else 0.0,
        "human_outcome_rate": human_outcome / total if total else 0.0,
    }


def _metric(system: dict, browser: dict, name: str) -> float | None:
    """The value of a named metric, from whichever family it belongs to."""
    area, _, key = name.partition(".")
    source = {"system": system, "browser": browser}.get(area, {})
    value = source.get(key)
    if value is None:
        return None
    return float(value)


def main() -> int:
    scenario_set = load_scenarios(SCENARIO_FILE)
    session_factory = make_session_factory(_WORKDIR / "verify.db")

    with serve_fake_ats_variants() as ats, session_factory() as session:
        outcome = run_scenarios(
            scenario_set,
            FakeAtsPlaywrightAdapter(),
            session,
            ats,
        )
        runs = read_runs(session)

    system = outcome["system"]
    browser = outcome["browser"]

    # -- the per-scenario lifecycles ------------------------------------
    by_workflow = {run["workflow_id"]: run for run in runs}
    for index, scenario in enumerate(scenario_set.scenarios):
        workflow_id = f"eval-{index:02d}-{scenario.id}"
        run = by_workflow.get(workflow_id)
        if run is None:
            check(f"the {scenario.id} scenario was tracked", False, f"no run for {workflow_id}")
            continue
        check(
            f"the {scenario.id} scenario ends in {scenario.expected_status}",
            run["status"] == scenario.expected_status,
            f"status={run['status']}",
        )
        actual = [event["event_type"] for event in run["events"]]
        check(
            f"the {scenario.id} scenario records the expected lifecycle",
            actual == scenario.expected_event_types,
            f"actual={actual}",
        )

    # -- the aggregate rates --------------------------------------------
    expected = _expected_rates(scenario_set)
    check(
        "the successful-application rate matches the scenario mix",
        abs(system["successful_rate"] - expected["successful_rate"]) < 1e-6,
        f"measured={system['successful_rate']} expected={expected['successful_rate']}",
    )
    check(
        "the failed-application rate matches the scenario mix",
        abs(system["failed_rate"] - expected["failed_rate"]) < 1e-6,
        f"measured={system['failed_rate']} expected={expected['failed_rate']}",
    )
    check(
        "the human-intervention rate matches the scenario mix",
        abs(system["human_intervention_rate"] - expected["human_intervention_rate"]) < 1e-6,
        (
            f"measured={system['human_intervention_rate']} "
            f"expected={expected['human_intervention_rate']}"
        ),
    )
    check(
        "the human-outcome rate matches the scenario mix",
        abs(system["human_outcome_rate"] - expected["human_outcome_rate"]) < 1e-6,
        (f"measured={system['human_outcome_rate']} expected={expected['human_outcome_rate']}"),
    )
    check(
        "every run falls in exactly one outcome bucket",
        (
            system["successful_applications"]
            + system["failed_applications"]
            + system["paused_for_human"]
            + system["human_outcome_applications"]
        )
        == system["runs"],
        (
            f"{system['successful_applications']}+{system['failed_applications']}"
            f"+{system['paused_for_human']}+{system['human_outcome_applications']}"
            f" != {system['runs']}"
        ),
    )
    check(
        "every run's lifecycle matched its expectation",
        system["lifecycle_fidelity"] == 1.0,
        f"fidelity={system['lifecycle_fidelity']} checked={system['lifecycle_checked']}",
    )
    check(
        "no submission was left unconfirmed",
        system["incorrect_submission_rate"] == 0.0,
        f"incorrect={system['incorrect_submission_rate']}",
    )

    # -- the browser layer ----------------------------------------------
    check(
        "the form-completion rate matches the scenario mix",
        abs(
            browser["form_completion_rate"]
            - sum(1 for s in scenario_set.scenarios if s.expected_status == "verified")
            / len(scenario_set.scenarios)
        )
        < 1e-6,
        f"measured={browser['form_completion_rate']}",
    )
    check(
        "no run failed on navigation",
        browser["navigation_failure_rate"] == 0.0,
        f"navigation_failures={browser['navigation_failure_rate']}",
    )
    check(
        "every completed run was verified",
        browser["verification_success_rate"] == 1.0,
        f"verification_rate={browser['verification_success_rate']}",
    )

    # -- the thresholds ---------------------------------------------------
    thresholds = (
        json.loads(
            (REPO_ROOT / "src" / "evaluation" / "thresholds.json").read_text(encoding="utf-8")
        ).get("system")
        or {}
    )
    for name, minimum in (thresholds.get("min") or {}).items():
        value = _metric(system, browser, name)
        if value is None:
            continue
        check(
            f"{name} meets its minimum",
            value >= float(minimum),
            f"measured={value} minimum={minimum}",
        )
    for name, maximum in (thresholds.get("max") or {}).items():
        value = _metric(system, browser, name)
        if value is None:
            continue
        check(
            f"{name} meets its maximum",
            value <= float(maximum),
            f"measured={value} maximum={maximum}",
        )

    # -- the report ------------------------------------------------------
    report = {
        "system": system,
        "browser": browser,
        "runs": [
            {
                "id": run["id"],
                "workflow_id": run["workflow_id"],
                "status": run["status"],
                "events": [event["event_type"] for event in run["events"]],
            }
            for run in runs
        ],
        "scenarios": outcome["scenarios"],
    }
    report_path = _WORKDIR / "system-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("\nSystem metrics:")
    for name in (
        "runs",
        "successful_applications",
        "failed_applications",
        "paused_for_human",
        "human_outcome_applications",
        "submitted",
        "verified",
        "successful_rate",
        "failed_rate",
        "human_intervention_rate",
        "human_outcome_rate",
        "incorrect_submission_rate",
        "verification_rate",
        "lifecycle_fidelity",
    ):
        print(f"  {name:<28} {system[name]}")
    print("\nBrowser metrics:")
    for name in (
        "runs",
        "form_completion_rate",
        "navigation_failure_rate",
        "verification_success_rate",
        "completed",
        "submitted",
        "verified",
        "paused_for_human",
    ):
        print(f"  {name:<28} {browser[name]}")
    print(f"  status_distribution           {browser['status_distribution']}")
    print(f"\nreport written: {report_path}")

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} checks passed.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
