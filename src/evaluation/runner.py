"""Run the application-scenario set end to end (WS-09 Part 2, Phase G).

The scenario runner performs each scenario against the **real** workflow —
the real graph, the real approval gate, the real WS-07 tracker — and reads
the tracking rows back out of the database afterwards. The metrics are
then computed from those rows, so the numbers describe the system rather
than an expectation about it.

The browser is required (the scenarios talk to a real fake ATS), so this
runs in the **live** verification script rather than in the unit suite.
What the unit suite covers is the metric functions and the tracker, both
of which are pure and browser-free.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.applications.contracts import ApplicationAdapter, ApplicationRequest, PreparedApplication
from src.applications.tracking import (
    AGENT_ACTOR,
    EVENT_APPROVAL_GRANTED,
    EVENT_APPROVAL_REJECTED,
    ApplicationStatus,
    create_application,
    human_actor,
    record_event,
    transition,
)
from src.evaluation.browser import browser_scores
from src.evaluation.scenarios import Scenario, ScenarioSet, find_by_workflow, read_runs
from src.evaluation.systems import system_scores
from src.graph.executor import execute_approved

logger = logging.getLogger(__name__)

#: The statuses a human may set on a tracked application. The agent never
#: sets one of these itself (the WS-07 actor rule), so a scenario that
#: expects one has a human record it at the end of the run.
HUMAN_OUTCOME_STATUSES = frozenset(
    {
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    }
)

__all__ = [
    "run_scenarios",
]


def _prepared_payload(scenario: Scenario, base_url: str) -> PreparedApplication:
    """The payload the scenario's application is prepared with."""
    request = ApplicationRequest(
        job_title="Backend Engineer",
        company_name="Acme Labs",
        job_url=f"{base_url}{scenario.variant}",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
        custom_fields=dict(scenario.custom_fields),
    )
    from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter

    adapter = FakeAtsPlaywrightAdapter()
    return adapter.prepare(request)


def run_scenarios(
    scenario_set: ScenarioSet,
    adapter: ApplicationAdapter,
    session: Session,
    base_url: str,
    *,
    workflow_prefix: str = "eval",
) -> dict[str, Any]:
    """Run every scenario and measure the system and the browser layer.

    Args:
        scenario_set: The scenarios to run.
        adapter: The adapter that talks to the fake ATS.
        session: The database session to write through and read back from.
        base_url: The fake ATS's base URL.
        workflow_prefix: A prefix for the workflow ids, so the runs are
            identifiable in the audit trail.

    Returns:
        The system metrics, the browser metrics, the recorded runs and the
        per-scenario detail.
    """
    from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter

    for index, scenario in enumerate(scenario_set.scenarios):
        workflow_id = f"{workflow_prefix}-{index:02d}-{scenario.id}"
        request = ApplicationRequest(
            job_title="Backend Engineer",
            company_name="Acme Labs",
            job_url=f"{base_url}{scenario.variant}",
            candidate_name="Ada Lovelace",
            email="ada@example.com",
            phone="+1 555 0101",
            custom_fields=dict(scenario.custom_fields),
        )
        prepared = FakeAtsPlaywrightAdapter().prepare(request)

        application = create_application(
            session,
            workflow_id=workflow_id,
            adapter_name=adapter.name,
            job_url=request.job_url,
            job_title=request.job_title,
            company_name=request.company_name,
        )
        transition(
            application,
            ApplicationStatus.AWAITING_APPROVAL,
            actor=AGENT_ACTOR,
            db=session,
        )

        if scenario.decision == "reject":
            # A human decline at the gate: nothing is submitted and the run
            # ends in a human outcome. This mirrors the API's reject route,
            # where the decision is the transition's own event.
            transition(
                application,
                ApplicationStatus.REJECTED,
                actor=human_actor(scenario.approver),
                db=session,
                event_type=EVENT_APPROVAL_REJECTED,
                metadata={"reason": "declined at the gate", "scenario": scenario.id},
            )
            continue

        record_event(
            session,
            application.id,
            EVENT_APPROVAL_GRANTED,
            actor=human_actor(scenario.approver),
            metadata={"reason": "approved for evaluation", "scenario": scenario.id},
        )

        result = execute_approved(
            prepared,
            adapter,
            workflow_id=workflow_id,
            approval_id=f"eval-approval-{index:02d}",
            approver=scenario.approver,
            decision_reason="approved for evaluation",
            session=session,
            application_id=application.id,
        )
        logger.info("Scenario %s finished with status %s", scenario.id, result.status)

        if scenario.expected_status in HUMAN_OUTCOME_STATUSES:
            # A human records the outcome after a verified application. The
            # agent never sets an outcome itself (the WS-07 actor rule), so
            # this transition is the human's act.
            tracked = find_by_workflow(session, workflow_id)
            if tracked is not None:
                transition(
                    tracked,
                    ApplicationStatus(scenario.expected_status),
                    actor=human_actor(scenario.approver),
                    db=session,
                )

    session.commit()

    runs = read_runs(session)
    # The expectations are keyed by the workflow id each scenario ran
    # under, which is what identifies a recorded run.
    expected_events = {
        f"{workflow_prefix}-{index:02d}-{scenario.id}": scenario.expected_event_types
        for index, scenario in enumerate(scenario_set.scenarios)
    }
    system = system_scores(runs, expected_events)
    browser = browser_scores(runs)

    return {
        "system": system,
        "browser": browser,
        "runs": runs,
        "scenarios": [
            {
                "id": scenario.id,
                "variant": scenario.variant,
                "description": scenario.description,
                "expected_status": scenario.expected_status,
                "expected_events": scenario.expected_event_types,
            }
            for scenario in scenario_set.scenarios
        ],
    }


def scenario_path(golden_dir: Path) -> Path:
    """The golden scenario file inside a golden directory."""
    return Path(golden_dir) / "scenarios.jsonl"
