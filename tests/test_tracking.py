"""WS-07 · the application status machine and its event log.

The properties under test:

1. the transition matrix is the only authority on what may follow what;
2. a **human outcome** can only be set by a human actor;
3. an illegal move changes nothing at all;
4. every state change appends exactly one event, and the history is ordered;
5. the event log is append-only — no code path can rewrite it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src.applications.tracking import (
    AGENT_ACTOR,
    ALLOWED_TRANSITIONS,
    EVENT_APPLICATION_CREATED,
    EVENT_APPROVAL_GRANTED,
    EVENT_EVIDENCE_RECORDED,
    EVENT_STATUS_TRANSITION,
    EVENT_VERIFICATION_FAILED,
    HUMAN_OUTCOME_STATUSES,
    ActorNotPermittedError,
    ApplicationStatus,
    IllegalTransitionError,
    application_events,
    create_application,
    ensure_job_row,
    find_application,
    human_actor,
    is_human_actor,
    manual_job_id,
    record_event,
    transition,
)
from src.db.applications import ApplicationDB, ApplicationEventDB
from src.db.audit import AuditEventDB
from src.db.base import Base
from src.db.jobs import JobDB

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

JOB_URL = "http://localhost:8000/jobs/1/apply"


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{(tmp_path / 'tracking.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _make_app(db: Session, status: ApplicationStatus = ApplicationStatus.PREPARED) -> ApplicationDB:
    """A tracked application in *status* (created without walking the machine)."""
    app = create_application(
        db,
        workflow_id="wf-1",
        adapter_name="fake-ats-playwright",
        job_url=JOB_URL,
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        status=status,
    )
    return app


def _actor_for(to: ApplicationStatus) -> str:
    """An actor that is allowed to set *to*."""
    return human_actor("ada") if to in HUMAN_OUTCOME_STATUSES else AGENT_ACTOR


class TestActorModel:
    """The actor string says who acted, in a form that cannot be faked."""

    def test_a_human_actor_is_the_reserved_prefix_plus_a_name(self):
        assert is_human_actor("human:ada")
        assert not is_human_actor("human:")
        assert not is_human_actor("ada")
        assert not is_human_actor(AGENT_ACTOR)
        assert not is_human_actor("")
        assert not is_human_actor("system")

    def test_human_actor_normalizes_a_free_form_name(self):
        assert human_actor("operator") == "human:operator"
        assert human_actor("  operator  ") == "human:operator"

    def test_human_actor_is_idempotent(self):
        assert human_actor("human:ada") == "human:ada"
        assert human_actor(human_actor("ada")) == "human:ada"


class TestTransitionMatrix:
    """The matrix is the only authority on what may follow what."""

    def test_every_legal_move_is_accepted(self, db_session: Session):
        for from_status, targets in ALLOWED_TRANSITIONS.items():
            for to in targets:
                app = _make_app(db_session)
                app.status = from_status.value
                db_session.commit()

                transition(app, to, actor=_actor_for(to), db=db_session)

                assert app.status == to.value

    def test_every_illegal_move_is_refused(self, db_session: Session):
        for from_status, targets in ALLOWED_TRANSITIONS.items():
            for to in ApplicationStatus:
                if to in targets:
                    continue
                app = _make_app(db_session)
                app.status = from_status.value
                db_session.commit()

                with pytest.raises(IllegalTransitionError):
                    transition(app, to, actor=_actor_for(to), db=db_session)

                assert app.status == from_status.value

    def test_a_self_transition_is_illegal(self, db_session: Session):
        for status in ApplicationStatus:
            app = _make_app(db_session)
            app.status = status.value
            db_session.commit()

            with pytest.raises(IllegalTransitionError):
                transition(app, status, actor=_actor_for(status), db=db_session)

    def test_an_illegal_move_writes_nothing(self, db_session: Session):
        app = _make_app(db_session)
        events_before = db_session.scalar(select(func.count()).select_from(ApplicationEventDB))
        audits_before = db_session.scalar(select(func.count()).select_from(AuditEventDB))

        with pytest.raises(IllegalTransitionError):
            transition(
                app,
                ApplicationStatus.OFFER,
                actor=human_actor("ada"),
                db=db_session,
            )

        assert app.status == ApplicationStatus.PREPARED.value
        assert (
            db_session.scalar(select(func.count()).select_from(ApplicationEventDB)) == events_before
        )
        assert db_session.scalar(select(func.count()).select_from(AuditEventDB)) == audits_before


class TestActorEnforcement:
    """The agent never invents an outcome."""

    @pytest.mark.parametrize("status", sorted(HUMAN_OUTCOME_STATUSES, key=lambda s: s.value))
    def test_the_agent_cannot_set_a_human_outcome(self, db_session: Session, status):
        app = _make_app(db_session, status=ApplicationStatus.VERIFIED)

        with pytest.raises(ActorNotPermittedError):
            transition(app, status, actor=AGENT_ACTOR, db=db_session)

        assert app.status == ApplicationStatus.VERIFIED.value

    @pytest.mark.parametrize("status", sorted(HUMAN_OUTCOME_STATUSES, key=lambda s: s.value))
    def test_the_system_cannot_set_a_human_outcome(self, db_session: Session, status):
        app = _make_app(db_session, status=ApplicationStatus.VERIFIED)

        with pytest.raises(ActorNotPermittedError):
            transition(app, status, actor="system", db=db_session)

    def test_a_human_can_set_a_human_outcome(self, db_session: Session):
        app = _make_app(db_session, status=ApplicationStatus.VERIFIED)

        transition(app, ApplicationStatus.OFFER, actor=human_actor("ada"), db=db_session)

        assert app.status == ApplicationStatus.OFFER.value
        event = application_events(db_session, app.id)[-1]
        assert event.actor == "human:ada"
        assert event.to_status == ApplicationStatus.OFFER.value

    def test_a_plain_name_is_not_a_human_actor(self, db_session: Session):
        """The prefix is what makes the rule checkable."""
        app = _make_app(db_session, status=ApplicationStatus.VERIFIED)

        with pytest.raises(ActorNotPermittedError):
            transition(app, ApplicationStatus.INTERVIEW, actor="ada", db=db_session)


class TestTransitionEffects:
    """A transition moves the row and records the move."""

    def test_the_event_records_the_move(self, db_session: Session):
        app = _make_app(db_session)

        transition(
            app,
            ApplicationStatus.AWAITING_APPROVAL,
            actor=AGENT_ACTOR,
            db=db_session,
            metadata={"reason": "prepared"},
        )

        events = application_events(db_session, app.id)
        assert len(events) == 2
        move = events[-1]
        assert move.event_type == EVENT_STATUS_TRANSITION
        assert move.actor == AGENT_ACTOR
        assert move.from_status == ApplicationStatus.PREPARED.value
        assert move.to_status == ApplicationStatus.AWAITING_APPROVAL.value
        assert move.extra_metadata == {"reason": "prepared"}

    def test_the_audit_trail_records_the_transition(self, db_session: Session):
        app = _make_app(db_session)

        transition(
            app,
            ApplicationStatus.AWAITING_APPROVAL,
            actor=AGENT_ACTOR,
            db=db_session,
        )

        audits = db_session.scalars(
            select(AuditEventDB).where(AuditEventDB.action == "application.transition")
        ).all()
        assert len(audits) == 1
        assert audits[0].actor == AGENT_ACTOR
        assert audits[0].resource == app.id
        assert audits[0].extra_metadata["from_status"] == "prepared"
        assert audits[0].extra_metadata["to_status"] == "awaiting_approval"

    def test_the_submission_timestamp_is_set(self, db_session: Session):
        app = _make_app(db_session)

        assert app.submitted_at is None
        transition(app, ApplicationStatus.AWAITING_APPROVAL, actor=AGENT_ACTOR, db=db_session)
        transition(app, ApplicationStatus.SUBMITTED, actor=AGENT_ACTOR, db=db_session)

        assert app.submitted_at is not None
        assert app.verified_at is None

    def test_the_verification_timestamp_is_set(self, db_session: Session):
        app = _make_app(db_session)
        transition(app, ApplicationStatus.AWAITING_APPROVAL, actor=AGENT_ACTOR, db=db_session)
        transition(app, ApplicationStatus.SUBMITTED, actor=AGENT_ACTOR, db=db_session)

        transition(app, ApplicationStatus.VERIFIED, actor=AGENT_ACTOR, db=db_session)

        assert app.verified_at is not None
        assert app.verified_at >= app.submitted_at

    def test_the_updated_timestamp_moves(self, db_session: Session):
        app = _make_app(db_session)
        before = app.updated_at

        transition(app, ApplicationStatus.AWAITING_APPROVAL, actor=AGENT_ACTOR, db=db_session)

        assert app.updated_at >= before

    def test_the_application_url_is_recorded(self, db_session: Session):
        app = _make_app(db_session)
        transition(app, ApplicationStatus.AWAITING_APPROVAL, actor=AGENT_ACTOR, db=db_session)

        transition(
            app,
            ApplicationStatus.SUBMITTED,
            actor=AGENT_ACTOR,
            db=db_session,
            application_url="http://localhost:8000/jobs/1/thanks",
        )

        assert app.application_url == "http://localhost:8000/jobs/1/thanks"

    def test_the_event_metadata_is_sanitized(self, db_session: Session):
        app = _make_app(db_session)

        transition(
            app,
            ApplicationStatus.AWAITING_APPROVAL,
            actor=AGENT_ACTOR,
            db=db_session,
            metadata={"api_key": "super-secret", "email": "ada@example.com"},
        )

        metadata = application_events(db_session, app.id)[-1].extra_metadata
        assert "api_key" not in metadata
        assert metadata["email"] == "<email>"


class TestEventLog:
    """The event log is append-only and ordered."""

    def test_the_creation_is_the_first_event(self, db_session: Session):
        app = _make_app(db_session)

        events = application_events(db_session, app.id)
        assert len(events) == 1
        assert events[0].event_type == EVENT_APPLICATION_CREATED
        assert events[0].from_status is None
        assert events[0].to_status == ApplicationStatus.PREPARED.value

    def test_events_are_ordered_by_id(self, db_session: Session):
        app = _make_app(db_session)
        transition(app, ApplicationStatus.AWAITING_APPROVAL, actor=AGENT_ACTOR, db=db_session)
        transition(app, ApplicationStatus.SUBMITTED, actor=AGENT_ACTOR, db=db_session)

        events = application_events(db_session, app.id)

        assert [event.id for event in events] == sorted(event.id for event in events)
        assert [event.to_status for event in events] == [
            ApplicationStatus.PREPARED.value,
            ApplicationStatus.AWAITING_APPROVAL.value,
            ApplicationStatus.SUBMITTED.value,
        ]

    def test_record_event_does_not_move_the_application(self, db_session: Session):
        app = _make_app(db_session)

        record_event(
            db_session,
            app.id,
            EVENT_APPROVAL_GRANTED,
            actor=human_actor("ada"),
            metadata={"reason": "looks good"},
        )

        assert app.status == ApplicationStatus.PREPARED.value
        events = application_events(db_session, app.id)
        assert events[-1].event_type == EVENT_APPROVAL_GRANTED
        assert events[-1].from_status is None
        assert events[-1].to_status is None
        assert events[-1].actor == "human:ada"

    def test_the_audit_trail_records_a_plain_event(self, db_session: Session):
        app = _make_app(db_session)

        record_event(
            db_session,
            app.id,
            EVENT_EVIDENCE_RECORDED,
            actor=AGENT_ACTOR,
            metadata={"evidence_id": 7},
        )

        audits = db_session.scalars(
            select(AuditEventDB)
            .where(AuditEventDB.action == "application.event")
            .order_by(AuditEventDB.id)
        ).all()
        # The creation is itself an event, so the trail holds both.
        assert len(audits) == 2
        assert audits[-1].extra_metadata["event_type"] == EVENT_EVIDENCE_RECORDED
        assert audits[-1].extra_metadata["evidence_id"] == 7

    def test_a_failed_verification_is_one_move_with_a_reason(self, db_session: Session):
        app = _make_app(db_session)
        transition(app, ApplicationStatus.AWAITING_APPROVAL, actor=AGENT_ACTOR, db=db_session)
        transition(app, ApplicationStatus.SUBMITTED, actor=AGENT_ACTOR, db=db_session)

        transition(
            app,
            ApplicationStatus.AWAITING_APPROVAL,
            actor=AGENT_ACTOR,
            db=db_session,
            event_type=EVENT_VERIFICATION_FAILED,
            metadata={"reason": "confirmation text missing"},
        )

        assert app.status == ApplicationStatus.AWAITING_APPROVAL.value
        events = application_events(db_session, app.id)
        assert len(events) == 4
        failure = events[-1]
        assert failure.event_type == EVENT_VERIFICATION_FAILED
        assert failure.from_status == ApplicationStatus.SUBMITTED.value
        assert failure.to_status == ApplicationStatus.AWAITING_APPROVAL.value
        assert failure.extra_metadata["reason"] == "confirmation text missing"


class TestJobResolution:
    """A tracked application always points at a real listing row."""

    def test_a_stub_listing_is_created_for_an_unknown_url(self, db_session: Session):
        job_id = ensure_job_row(db_session, JOB_URL, "Engineer", "Acme Labs")

        row = db_session.get(JobDB, job_id)
        assert row is not None
        assert row.source == "manual"
        assert row.application_url == JOB_URL
        assert row.title == "Engineer"
        assert row.company == "Acme Labs"

    def test_the_stub_id_is_derived_from_the_url(self):
        assert manual_job_id(JOB_URL) == manual_job_id(JOB_URL)
        assert manual_job_id(JOB_URL) != manual_job_id(JOB_URL + "x")
        assert manual_job_id(JOB_URL).startswith("manual:")

    def test_resolving_the_same_url_twice_reuses_the_row(self, db_session: Session):
        first = ensure_job_row(db_session, JOB_URL, "Engineer", "Acme Labs")
        second = ensure_job_row(db_session, JOB_URL, "Engineer", "Acme Labs")

        assert first == second
        assert db_session.scalar(select(func.count()).select_from(JobDB)) == 1

    def test_an_existing_listing_is_reused(self, db_session: Session):
        db_session.add(
            JobDB(
                id="greenhouse:acme:42",
                source="greenhouse",
                title="Engineer",
                company="Acme Labs",
                application_url=JOB_URL,
            )
        )
        db_session.commit()

        assert ensure_job_row(db_session, JOB_URL, "Engineer", "Acme Labs") == "greenhouse:acme:42"
        assert db_session.scalar(select(func.count()).select_from(JobDB)) == 1

    def test_the_application_resolves_its_job(self, db_session: Session):
        app = _make_app(db_session)

        job = db_session.get(JobDB, app.job_id)
        assert job is not None
        assert job.application_url == JOB_URL


class TestLookup:
    """An application is findable by every id it carries."""

    def test_find_by_application_id(self, db_session: Session):
        app = _make_app(db_session)
        found = find_application(db_session, application_id=app.id)
        assert found is not None
        assert found.id == app.id

    def test_find_by_approval_id(self, db_session: Session):
        app = create_application(
            db_session,
            workflow_id="wf-2",
            adapter_name="fake-ats-playwright",
            job_url=JOB_URL,
            job_title="Engineer",
            company_name="Acme Labs",
            approval_id="apr-1",
        )
        found = find_application(db_session, approval_id="apr-1")
        assert found is not None
        assert found.id == app.id

    def test_find_by_workflow_id(self, db_session: Session):
        app = _make_app(db_session)
        found = find_application(db_session, workflow_id="wf-1")
        assert found is not None
        assert found.id == app.id

    def test_an_unknown_application_is_not_found(self, db_session: Session):
        assert find_application(db_session, application_id="nope") is None
        assert find_application(db_session, approval_id="nope") is None
        assert find_application(db_session, workflow_id="nope") is None
        assert find_application(db_session) is None


#: The modules that may delete an event row, and why.
#:
#: The retention purge (WS-14 · Phase D) is the **one** thing that may
#: remove history: an event that is past the retention window is
#: removed, and the removal is audited. Every other module may only
#: append — an audit trail that can be rewritten is not an audit trail.
APPEND_ONLY_EXCEPTIONS = {
    "retention.py": "the retention purge, which is audited",
}


class TestEventLogIsAppendOnly:
    """No code path may rewrite the history."""

    @staticmethod
    def _mutation_findings(path: Path) -> list[str]:
        """Calls in *path* that could update or delete an event row."""
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports_events = "ApplicationEventDB" in source
        findings: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name not in ("update", "delete"):
                continue
            rendered = ast.dump(node)
            targets_events = "application_events" in rendered or "ApplicationEventDB" in rendered
            # A session.delete() in a module that knows the event model is
            # the only way it could delete an event.
            if name == "delete" and imports_events:
                findings.append(f"{path.name}:{node.lineno} deletes an event row")
            elif targets_events:
                findings.append(f"{path.name}:{node.lineno} updates or deletes event rows")
        return findings

    def test_no_module_updates_or_deletes_an_event(self):
        findings: list[str] = []
        for path in sorted(SRC_ROOT.rglob("*.py")):
            if path.name in APPEND_ONLY_EXCEPTIONS:
                continue
            findings.extend(self._mutation_findings(path))

        assert findings == [], f"the event log must be append-only: {findings}"

    def test_the_only_exception_is_the_retention_purge(self):
        """The exception is named, and it is the one that was intended.

        A silent exception is an exception that grows: the next module
        that wants to rewrite the history would add itself to the list
        and nobody would notice. So the list is checked here — the
        exception exists, it is the one that was designed, and the
        module it names is still there.
        """
        assert set(APPEND_ONLY_EXCEPTIONS) == {"retention.py"}
        for name in APPEND_ONLY_EXCEPTIONS:
            assert (SRC_ROOT / "retention.py").is_file(), (
                f"the append-only exception names {name}, which no longer exists"
            )

    def test_the_tracking_module_offers_no_update_or_delete(self):
        source = (SRC_ROOT / "applications" / "tracking.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        exported = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        assert not {name for name in exported if "delete" in name or "update" in name}
