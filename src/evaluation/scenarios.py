"""The application-scenario set and its runner (WS-09 Part 2, Phase G).

The plan's §7 "Application system" group needs numbers that only exist
once the whole workflow has run: did the application reach ``verified``,
did a human have to act, was a submission made that was never confirmed.

This module runs the **real** workflow — the real graph, the real
approval gate, the real WS-07 tracker — against the local fake ATS, and
then reads the tracking rows back out of the database. The metrics are
computed from those rows, so the numbers describe the system rather than
a hand-written expectation about it.

The scenario *inputs* live in ``tests/evaluation/golden/scenarios.jsonl``.
That file names a fake-ATS variant and the lifecycle the run is expected
to produce; it holds no copy of the fake ATS's markup, which stays the
single source of truth (the WS-08 decision, D14).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.applications.contracts import ApplicationRequest
from src.applications.tracking import (
    AGENT_ACTOR,
    ApplicationStatus,
    create_application,
    find_application,
    human_actor,
    transition,
)
from src.db.applications import ApplicationDB, ApplicationEventDB
from src.db.base import Base

logger = logging.getLogger(__name__)

__all__ = [
    "Scenario",
    "ScenarioSet",
    "load_scenarios",
    "read_runs",
]


@dataclass
class Scenario:
    """One application run the harness will perform."""

    id: str
    variant: str
    description: str
    expected_status: str
    expected_events: list[str] = field(default_factory=list)
    approver: str = "human:ada"
    decision: str = "approve"
    custom_fields: dict[str, str] = field(default_factory=dict)

    @property
    def expected_event_types(self) -> list[str]:
        """The expected event-type sequence, as the lifecycle recorded it."""
        return list(self.expected_events)


@dataclass
class ScenarioSet:
    """The loaded scenario set."""

    scenarios: list[Scenario] = field(default_factory=list)

    def by_id(self, scenario_id: str) -> Scenario:
        """The scenario with this id."""
        for scenario in self.scenarios:
            if scenario.id == scenario_id:
                return scenario
        raise KeyError(f"No scenario named {scenario_id!r}")

    @property
    def expected_events(self) -> dict[str, list[str]]:
        """The expected event sequence per scenario id."""
        return {scenario.id: scenario.expected_event_types for scenario in self.scenarios}


def load_scenarios(path: Path) -> ScenarioSet:
    """Load the scenario set from its golden file.

    Args:
        path: The ``scenarios.jsonl`` file.

    Returns:
        The loaded scenarios.

    Raises:
        ValueError: A scenario is malformed. A scenario file that cannot
            be trusted is a hard error, not a silently skipped line.
    """
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"Scenario line {number} is not valid JSON: {exc}") from exc
        for required in ("id", "variant", "description", "expected_status"):
            if required not in raw:
                raise ValueError(f"Scenario line {number} is missing {required!r}")
        scenario_id = str(raw["id"])
        if scenario_id in seen:
            raise ValueError(f"Scenario line {number} repeats the id {scenario_id!r}")
        seen.add(scenario_id)
        scenarios.append(
            Scenario(
                id=scenario_id,
                variant=str(raw["variant"]),
                description=str(raw["description"]),
                expected_status=str(raw["expected_status"]),
                expected_events=[str(event) for event in raw.get("expected_events", [])],
                approver=str(raw.get("approver", "human:ada")),
                decision=str(raw.get("decision", "approve")),
                custom_fields={str(k): str(v) for k, v in (raw.get("custom_fields") or {}).items()},
            )
        )
    return ScenarioSet(scenarios=scenarios)


def read_runs(session: Session) -> list[dict[str, Any]]:
    """Read the tracked applications and their events back out of the database.

    The rows are returned in a form the metric functions can consume
    directly: the application's final status and its event log, in append
    order (the event id is the ordering, not the timestamp).

    Args:
        session: The session to read through.

    Returns:
        One record per tracked application.
    """
    runs: list[dict[str, Any]] = []
    for application in session.scalars(select(ApplicationDB).order_by(ApplicationDB.created_at)):
        events = list(
            session.scalars(
                select(ApplicationEventDB)
                .where(ApplicationEventDB.application_id == application.id)
                .order_by(ApplicationEventDB.id)
            )
        )
        runs.append(
            {
                "id": application.id,
                "workflow_id": application.workflow_id,
                "status": application.status,
                "job_url": application.job_url,
                "events": [
                    {
                        "event_type": event.event_type,
                        "actor": event.actor,
                        "from_status": event.from_status,
                        "to_status": event.to_status,
                    }
                    for event in events
                ],
            }
        )
    return runs


def prepare_scenario(
    session: Session,
    scenario: Scenario,
    base_url: str,
    *,
    workflow_id: str,
) -> ApplicationDB:
    """Run a scenario's preparation and approval, up to the submission.

    This performs the real WS-06 two-phase flow: the application is
    created and moved to ``awaiting_approval``, and the human decision is
    recorded. A rejection stops here — the run never reaches a submission,
    which is exactly the point of that scenario.

    Args:
        session: The database session to write through.
        scenario: The scenario to prepare.
        base_url: The fake ATS's base URL.
        workflow_id: The workflow id to stamp the run with.

    Returns:
        The tracked application, already moved to its post-approval state.
    """
    request = ApplicationRequest(
        job_title="Backend Engineer",
        company_name="Acme Labs",
        job_url=f"{base_url}{scenario.variant}",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
        custom_fields=dict(scenario.custom_fields),
    )

    application = create_application(
        session,
        workflow_id=workflow_id,
        adapter_name="fake-ats-playwright",
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
        transition(
            application,
            ApplicationStatus.REJECTED,
            actor=human_actor(scenario.approver),
            db=session,
            event_type="approval_rejected",
        )
    return application


def human_outcome(
    session: Session,
    application: ApplicationDB,
    *,
    actor: str,
    status: ApplicationStatus = ApplicationStatus.INTERVIEW,
) -> ApplicationDB:
    """Record a human outcome on a tracked application.

    A human outcome is only settable by a human actor (the WS-07 actor
    rule), which is what makes the "human intervention" measurement
    meaningful: the row proves a human acted, not the agent.

    Args:
        session: The database session to write through.
        application: The tracked application.
        actor: The human's identity.
        status: The outcome to set.

    Returns:
        The moved application.
    """
    return transition(
        application,
        status,
        actor=human_actor(actor),
        db=session,
    )


def make_session_factory(database_path: Path) -> sessionmaker:
    """A session factory over a fresh database with the current schema.

    The tables are created from the models rather than from the migration
    history, because the harness measures the *current* code; the
    migrations are the deployment path, and they are exercised by their
    own test module.

    Every model module is imported first. ``Base.metadata`` only knows
    about the tables whose modules have been *imported*, so a session
    factory built without them would produce a database that silently
    lacks the evidence and approval tables.

    Args:
        database_path: Where the database lives.

    Returns:
        The session factory.
    """
    from src.db import (  # noqa: F401 - imported for their table registrations
        applications,
        approval,
        audit,
        evidence,
        jobs,
        matches,
        profiles,
        tailored,
    )

    engine = create_engine(f"sqlite:///{Path(database_path).as_posix()}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def find_by_workflow(session: Session, workflow_id: str) -> ApplicationDB | None:
    """The tracked application of a workflow, if there is one."""
    return find_application(session, workflow_id=workflow_id)
