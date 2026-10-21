"""Tests for the WS-09 application-scenario set and the tracker it drives.

The scenario file is a golden artifact, so it is checked for well-formedness
and for reachability: every scenario must name a fake-ATS variant that
exists, and every expectation must be one the state machine can produce.

The scenarios themselves are run against a real browser in
``scripts/verify_ws09.py``; what is proven here is that the file is sound
and that the tracker records what the scenarios expect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.applications.tracking import (
    AGENT_ACTOR,
    EVENT_APPLICATION_CREATED,
    EVENT_APPROVAL_GRANTED,
    EVENT_APPROVAL_REJECTED,
    EVENT_EVIDENCE_RECORDED,
    EVENT_STATUS_TRANSITION,
    EVENT_VERIFICATION_FAILED,
    ApplicationStatus,
    create_application,
    human_actor,
    record_event,
    transition,
)
from src.evaluation.scenarios import load_scenarios, make_session_factory, read_runs

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "evaluation" / "golden"
SCENARIO_FILE = GOLDEN_DIR / "scenarios.jsonl"


@pytest.fixture(scope="module")
def scenario_set():
    return load_scenarios(SCENARIO_FILE)


def test_the_scenario_file_exists_and_parses(scenario_set):
    assert scenario_set.scenarios, "the scenario set is empty"
    assert all(scenario.id for scenario in scenario_set.scenarios)


def test_every_scenario_names_a_unique_id(scenario_set):
    ids = [scenario.id for scenario in scenario_set.scenarios]
    assert len(ids) == len(set(ids))


def test_every_scenario_names_a_variant_that_exists(scenario_set):
    """A scenario pointing at a page the fake ATS does not serve would
    measure a 404 rather than the behaviour it claims to."""
    from tests.fixtures.fake_ats import variants

    served = {
        getattr(route, "path", "")
        for route in variants.create_app().routes
        if getattr(route, "path", "")
    }
    for scenario in scenario_set.scenarios:
        assert scenario.variant.startswith("/"), scenario.id
        assert scenario.variant in served, f"{scenario.id} names an unserved path"


def test_every_scenario_expects_a_reachable_status(scenario_set):
    reachable = {status.value for status in ApplicationStatus}
    for scenario in scenario_set.scenarios:
        assert scenario.expected_status in reachable, scenario.id


def test_the_scenario_mix_covers_every_outcome_the_metrics_distinguish(scenario_set):
    """The rates are only meaningful if the set contains runs of each
    kind: a completed one, one that pauses for a human, and one a human
    declines."""
    statuses = {scenario.expected_status for scenario in scenario_set.scenarios}
    assert "verified" in statuses
    assert "awaiting_approval" in statuses
    assert "rejected" in statuses
    decisions = {scenario.decision for scenario in scenario_set.scenarios}
    assert decisions == {"approve", "reject"}


def test_the_expected_event_sequences_use_real_event_types(scenario_set):
    known = {
        EVENT_APPLICATION_CREATED,
        EVENT_STATUS_TRANSITION,
        EVENT_APPROVAL_GRANTED,
        EVENT_APPROVAL_REJECTED,
        EVENT_EVIDENCE_RECORDED,
        EVENT_VERIFICATION_FAILED,
    }
    for scenario in scenario_set.scenarios:
        for event in scenario.expected_event_types:
            assert event in known, f"{scenario.id} expects the unknown event {event!r}"


def test_a_malformed_scenario_file_is_rejected(tmp_path):
    bad = tmp_path / "scenarios.jsonl"
    bad.write_text('{"id": "x"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        load_scenarios(bad)


def test_a_duplicate_scenario_id_is_rejected(tmp_path):
    bad = tmp_path / "scenarios.jsonl"
    line = json.dumps(
        {
            "id": "x",
            "variant": "/basic",
            "description": "d",
            "expected_status": "verified",
        }
    )
    bad.write_text(f"{line}\n{line}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="repeats"):
        load_scenarios(bad)


def test_the_tracker_records_the_lifecycle_the_scenarios_expect(tmp_path):
    """The tracker, driven the way the scenario runner drives it, writes
    the event sequence the golden file declares."""
    session_factory = make_session_factory(tmp_path / "tracker.db")
    with session_factory() as session:
        application = create_application(
            session,
            workflow_id="wf-test",
            adapter_name="fake-ats-playwright",
            job_url="http://127.0.0.1:1/basic",
            job_title="Backend Engineer",
            company_name="Acme Labs",
        )
        transition(
            application,
            ApplicationStatus.AWAITING_APPROVAL,
            actor=AGENT_ACTOR,
            db=session,
        )
        record_event(
            session,
            application.id,
            EVENT_APPROVAL_GRANTED,
            actor=human_actor("ada"),
        )
        transition(
            application,
            ApplicationStatus.SUBMITTED,
            actor=AGENT_ACTOR,
            db=session,
        )
        record_event(
            session,
            application.id,
            EVENT_EVIDENCE_RECORDED,
            actor=AGENT_ACTOR,
        )
        transition(
            application,
            ApplicationStatus.VERIFIED,
            actor=AGENT_ACTOR,
            db=session,
        )
        session.commit()

        runs = read_runs(session)

    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "verified"
    assert [event["event_type"] for event in run["events"]] == [
        EVENT_APPLICATION_CREATED,
        EVENT_STATUS_TRANSITION,
        EVENT_APPROVAL_GRANTED,
        EVENT_STATUS_TRANSITION,
        EVENT_EVIDENCE_RECORDED,
        EVENT_STATUS_TRANSITION,
    ]
    # The approval is a human act; the rest is the agent's.
    actors = {event["event_type"]: event["actor"] for event in run["events"]}
    assert actors[EVENT_APPROVAL_GRANTED] == "human:ada"
    assert actors[EVENT_STATUS_TRANSITION] == AGENT_ACTOR


def test_read_runs_reports_the_events_in_append_order(tmp_path):
    session_factory = make_session_factory(tmp_path / "order.db")
    with session_factory() as session:
        application = create_application(
            session,
            workflow_id="wf-order",
            adapter_name="fake-ats-playwright",
            job_url="http://127.0.0.1:1/basic",
            job_title="Backend Engineer",
            company_name="Acme Labs",
        )
        transition(
            application,
            ApplicationStatus.AWAITING_APPROVAL,
            actor=AGENT_ACTOR,
            db=session,
        )
        session.commit()
        runs = read_runs(session)

    statuses = [event["to_status"] for event in runs[0]["events"]]
    assert statuses == ["prepared", "awaiting_approval"]
