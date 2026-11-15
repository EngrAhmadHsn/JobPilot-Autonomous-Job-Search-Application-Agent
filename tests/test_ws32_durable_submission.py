"""WS-32 · The approve returns accepted, not submitted.

The approve route ran the whole submission inline, with a MemorySaver and no
recovery: on the local fake ATS that is invisible, and against a real board it
is an HTTP request that outlives its client and a run a crash can lose.

The WS-18 queue already solved this for the refresh and the embedding drain, so
this reuses it rather than inventing a second mechanism.

The tests drive the real seams: the approval goes through the API route and the
real queue service, and the worker is the real
:class:`~src.runs.worker.Worker` with a test session factory and an injected
adapter list. A simulated crash is a ``BaseException`` raised where a killed
process would stop writing — deliberately *not* an ``Exception``, because every
handler on the worker's path catches those so a bad item cannot kill the loop,
and a process that was killed cannot be caught by the code it interrupted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from src.api.routes import applications as applications_route
from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.db.approval import ApprovalRequestDB, ApprovalStatus, build_approval_row
from src.db.base import Base
from src.db.runs import JobRunDB, JobRunEventDB, JobWorkItemDB
from src.db.session import get_db
from src.db.users import LEGACY_OWNER_ID
from src.graph import executor as graph_executor
from src.main import app
from src.runs import queue
from src.runs.state import WORK_QUEUED, utcnow
from src.runs.worker import Worker

ROOT = Path(__file__).resolve().parents[1]

WORKFLOW_ID = "ws32-workflow-1"
JOB_URL = "http://localhost:8000/jobs/123/apply"
SUBMISSION_WORK_TYPE = "submission"


class _Crash(BaseException):
    """A simulated process death.

    A ``BaseException`` on purpose: the worker catches ``Exception`` so that a
    bad item cannot kill the loop, and a process that was killed cannot be
    caught by the code it was running. The test is what catches this one.
    """


class _CountingAdapter(ApplicationAdapter):
    """The fake ATS, with a tally instead of a browser.

    It keeps the real adapter's name so the capability matrix (WS-06 · SEC-08)
    grants it the submit capability the submit node checks, and so the worker's
    resolver finds it under the name the approval row carries.
    """

    name = "fake-ats-playwright"

    def __init__(self) -> None:
        self.submit_calls = 0

    def supports_url(self, url: str) -> bool:
        return url.startswith("http://localhost")

    def prepare(self, request: ApplicationRequest) -> PreparedApplication:
        return PreparedApplication(
            request=request,
            prepared_fields={"candidate_name": request.candidate_name},
        )

    def submit(self, prepared: PreparedApplication) -> ApplicationResult:
        self.submit_calls += 1
        return ApplicationResult(
            success=True,
            status="submitted",
            message="stub submission",
            evidence=SubmissionEvidence(
                url=prepared.request.job_url,
                confirmation_text="Application submitted",
                status="submitted",
            ),
        )

    def verify(self, result: ApplicationResult) -> ApplicationResult:
        return ApplicationResult(
            success=True,
            status="verified",
            message="verified",
            evidence=result.evidence,
        )


@dataclass(frozen=True)
class _SeededApproval:
    """A pending approval row for the fake ATS, as the prepare route writes it."""

    approval_id: str
    workflow_id: str


class _TestWorker(Worker):
    """The real worker, with the two crash seams the invariants need.

    ``crash_after_claim`` kills the process after the claim and before any
    work — the item is left RUNNING with a lease, and only the lease reaper can
    recover it. ``crash_after_submit`` kills it **after the board accepted the
    application and before the outcome is committed**: the adapter really ran,
    the employer may already hold the application, and the approval row still
    reads ``APPROVED``. ``crash_after_outcome`` kills it after the outcome was
    committed, which is the other side of the window.
    """

    def __init__(
        self,
        *args: Any,
        crash_after_claim: bool = False,
        crash_after_submit: bool = False,
        crash_after_outcome: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.crash_after_claim = crash_after_claim
        self.crash_after_submit = crash_after_submit
        self.crash_after_outcome = crash_after_outcome
        #: What this worker was actually handed, so a test can tell "nothing
        #: was claimed" (which would be a false pass) from "the right work was
        #: claimed".
        self.claimed_work_types: list[str] = []

    def _execute(self, items) -> None:
        self.claimed_work_types = [item.work_type for item in items]
        if self.crash_after_claim:
            raise _Crash("simulated crash after the claim, before any work")
        super()._execute(items)

    def _record_submission_outcome(self, session, row, result) -> None:
        # The seam is exactly the window the plan names. This method is called
        # as soon as ``_submit_approved_application`` returns — so raising
        # *before* ``super()`` is a death that lands after the adapter ran and
        # before any outcome is durable. Raising *after* ``super()`` is the
        # easier side: the row already records what happened, so the existing
        # guard alone would catch it.
        if self.crash_after_submit:
            raise _Crash("simulated crash after the submission, before the outcome was recorded")
        super()._record_submission_outcome(session, row, result)
        if self.crash_after_outcome:
            raise _Crash("simulated crash after the outcome was recorded")


@pytest.fixture
def session_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An isolated database for the approvals, the queue and the audit trail."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'ws32-submission.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    # The audit writer, the evidence writer and the graph nodes open their own
    # session when the caller hands over none; point them at this database too.
    monkeypatch.setattr("src.db.session.SessionLocal", factory)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    yield factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


class _FreshReader:
    """Reads through a **new** session per lookup.

    The row is written by another session — the request's, or the worker's —
    and a long-lived session would answer from its identity map, so the
    assertion would describe the object the test already knew about instead of
    what the system actually stored. A read that cannot see another session's
    commit is a read that cannot fail.
    """

    def __init__(self, factory: sessionmaker) -> None:
        self._factory = factory

    def get(self, model, identifier):
        with self._factory() as session:
            return session.get(model, identifier)


@pytest.fixture
def client(session_factory) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session(session_factory) -> _FreshReader:
    return _FreshReader(session_factory)


@pytest.fixture
def approved_payload(session_factory) -> _SeededApproval:
    prepared = PreparedApplication(
        request=ApplicationRequest(
            job_title="Senior Python Engineer",
            company_name="Acme Labs",
            job_url=JOB_URL,
            candidate_name="Ada Lovelace",
            email="ada@example.com",
            phone="+1 555 0101",
        ),
        prepared_fields={"candidate_name": "Ada Lovelace", "email": "ada@example.com"},
        workflow_id=WORKFLOW_ID,
        owner_id=LEGACY_OWNER_ID,
    )
    row = build_approval_row(
        owner_id=LEGACY_OWNER_ID,
        workflow_id=WORKFLOW_ID,
        adapter_name="fake-ats-playwright",
        prepared=prepared,
    )
    with session_factory() as session:
        session.add(row)
        session.commit()
        approval_id = row.id
    return _SeededApproval(approval_id=approval_id, workflow_id=WORKFLOW_ID)


@pytest.fixture
def run_worker_once(session_factory, monkeypatch: pytest.MonkeyPatch):
    """Drain the queue once, with the real worker and an injected adapter list.

    ``lease_seconds=0`` is deliberate: a claim's lease is already expired when
    the next call looks, so an item an earlier call abandoned is genuinely
    reclaimable. Under the production 900-second lease the second call would
    find nothing claimable, and the at-most-once assertion would pass without
    ever exercising the guard it exists for.
    """

    def run(
        *,
        kind: str = SUBMISSION_WORK_TYPE,
        adapter: ApplicationAdapter | None = None,
        crash_after_claim: bool = False,
        crash_after_submit: bool = False,
        crash_after_outcome: bool = False,
    ) -> None:
        if adapter is not None:
            # The worker resolves by the name the approval row carries, from
            # the one adapter list the route and the worker share.
            monkeypatch.setattr(graph_executor, "AVAILABLE_ADAPTERS", [adapter])
        worker = _TestWorker(
            worker_id="w-submit-test",
            session_factory=session_factory,
            sleep=lambda _seconds: None,
            lease_seconds=0.0,
            crash_after_claim=crash_after_claim,
            crash_after_submit=crash_after_submit,
            crash_after_outcome=crash_after_outcome,
        )
        if crash_after_claim or crash_after_submit or crash_after_outcome:
            with pytest.raises(_Crash):
                worker.run_once()
        else:
            worker.run_once()
        assert kind in worker.claimed_work_types, (
            f"the worker claimed {worker.claimed_work_types or 'nothing'}; it was "
            f"supposed to claim {kind!r} work"
        )

    return run


@pytest.fixture
def expire_lease(session_factory):
    """Expire every live work-item lease, then let the reaper requeue it."""

    def expire() -> None:
        with session_factory() as session:
            session.execute(
                update(JobWorkItemDB)
                .where(JobWorkItemDB.lease_expires_at.is_not(None))
                .values(lease_expires_at=utcnow() - timedelta(seconds=60))
            )
            session.commit()
        queue.reap_expired_leases(session_factory=session_factory)

    return expire


@pytest.fixture
def run_events(session_factory):
    """The lifecycle events of the submission run for a workflow id."""

    def read(workflow_id: str):
        with session_factory() as session:
            run = session.execute(
                select(JobRunDB).where(JobRunDB.correlation_id == workflow_id)
            ).scalar_one()
            events = list(
                session.execute(
                    select(JobRunEventDB)
                    .where(JobRunEventDB.run_id == run.id)
                    .order_by(JobRunEventDB.id)
                ).scalars()
            )
            for event in events:
                session.expunge(event)
            return events

    return read


def _item_for(session_factory, approval_id: str) -> JobWorkItemDB:
    """The queued submission work item, read through a fresh session."""
    with session_factory() as session:
        item = session.execute(
            select(JobWorkItemDB).where(JobWorkItemDB.job_id == approval_id)
        ).scalar_one()
        session.expunge(item)
        return item


def _approve(client: TestClient, approval_id: str, **body) -> str:
    """Approve over HTTP and return the accepted run id."""
    response = client.post(f"/api/applications/{approval_id}/approve", json=body)
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


# -- the tests -----------------------------------------------------------------


def test_approving_enqueues_a_submission_run(client, approved_payload, session_factory) -> None:
    response = client.post(
        f"/api/applications/{approved_payload.approval_id}/approve", json={}
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["run_id"]
    # The wording matters: the operator must be able to tell "queued" from
    # "applied". A 200 with a success-shaped body would be a false claim.
    assert "submitted" not in body["status"].lower()

    # The accepted work is really on the queue: one run, one submission item,
    # carrying the approval it belongs to.
    with session_factory() as session:
        run = queue.get_run(session, body["run_id"])
        assert run is not None
        assert run.job_type == SUBMISSION_WORK_TYPE
        assert run.correlation_id == approved_payload.workflow_id
        metadata = dict(run.extra_metadata or {})
        assert metadata["approval_id"] == approved_payload.approval_id
        assert metadata["workflow_id"] == approved_payload.workflow_id

    item = _item_for(session_factory, approved_payload.approval_id)
    assert item.work_type == SUBMISSION_WORK_TYPE
    assert item.status == WORK_QUEUED


def test_the_approval_row_is_not_marked_executed_before_the_run_finishes(
    client, approved_payload, db_session
) -> None:
    """A row that reads EXECUTED while the work is queued is a lie in the audit
    trail — the one place this system promises not to lie."""
    client.post(f"/api/applications/{approved_payload.approval_id}/approve", json={})

    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status == ApprovalStatus.APPROVED  # decided, not executed
    assert row.status != ApprovalStatus.EXECUTED


def test_the_worker_executes_the_queued_submission(
    client, approved_payload, db_session, run_worker_once
) -> None:
    """Draining the queue performs the same call the route used to."""
    _approve(client, approved_payload.approval_id, reason="reviewed")
    counter = _CountingAdapter()

    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter)

    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status in {ApprovalStatus.EXECUTED, ApprovalStatus.FAILED}
    assert row.status == ApprovalStatus.EXECUTED
    assert counter.submit_calls == 1
    # The submitted payload is the persisted, approved one, and its outcome is
    # the durable record the operator reads afterwards.
    assert row.result is not None
    assert row.result["status"] == "verified"
    assert row.approver == LEGACY_OWNER_ID


def test_a_submission_that_crashes_before_anything_was_attempted_is_retried(
    client, approved_payload, db_session, run_worker_once, expire_lease
) -> None:
    """No attempt marker means nothing reached the board, so the retry runs.

    This is the first of the three cases, and the one where refusing would be
    wrong: an approved application that is never applied is its own failure, and
    a crash *before* the submission carries no evidence that anything was sent.
    """
    _approve(client, approved_payload.approval_id)
    counter = _CountingAdapter()

    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter, crash_after_claim=True)
    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status != ApprovalStatus.EXECUTED
    assert counter.submit_calls == 0  # the crash preceded the submission

    expire_lease()
    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter)  # reclaimed and completed

    assert counter.submit_calls == 1
    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status == ApprovalStatus.EXECUTED


def test_a_submission_that_crashes_after_the_board_accepted_is_not_resubmitted(
    client, approved_payload, db_session, run_worker_once, expire_lease, run_events
) -> None:
    """At-most-once, on the window that actually matters.

    The crash lands **after the adapter submitted** and **before the outcome was
    committed** — so the employer may already hold the application, and the
    approval row still reads ``APPROVED`` with no result. That is the state a
    lease reaper requeues and an administrator's resume re-runs, and a system
    that cannot tell it from "nothing happened yet" applies twice.

    So the retry refuses: it settles the item with a ``submission.uncertain``
    event and leaves the row ``APPROVED`` (decided, outcome unknown) for a human
    to check. The row must not claim ``EXECUTED`` — nothing was confirmed — and
    must not claim ``FAILED`` either, because that would assert the application
    was not sent, which nobody knows.
    """
    _approve(client, approved_payload.approval_id)
    counter = _CountingAdapter()

    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter, crash_after_submit=True)
    assert counter.submit_calls == 1, "the crash must land after a real submission"
    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status == ApprovalStatus.APPROVED, "the crash happened before the outcome was written"
    assert row.result is None

    # The lease expires (as it would on a killed process) and the item is
    # requeued — the same path an administrator's resume drives.
    expire_lease()
    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter)

    assert counter.submit_calls == 1, "the retry submitted the application a second time"
    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status == ApprovalStatus.APPROVED
    assert row.result is None

    refusal = run_events(approved_payload.workflow_id)
    assert any(event.event == "submission.uncertain" for event in refusal), (
        "the refusal must be recorded on the run, visible to the operator"
    )
    message = " ".join(event.message or "" for event in refusal)
    assert "may or may not" in message and "check" in message, (
        f"the event must say plainly that a human has to check; it said: {message!r}"
    )


def test_a_submission_whose_outcome_was_recorded_is_not_resubmitted(
    client, approved_payload, db_session, run_worker_once
) -> None:
    """The outcome is durable, so the retry refuses from the row alone.

    The third case: the board accepted and the result was committed, then the
    process died before the item was settled. Nothing is ambiguous here — the
    record says what happened — and the refusal must not touch the row.
    """
    _approve(client, approved_payload.approval_id)
    counter = _CountingAdapter()

    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter, crash_after_outcome=True)
    assert counter.submit_calls == 1

    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter)

    assert counter.submit_calls == 1
    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status == ApprovalStatus.EXECUTED
    assert row.result is not None


def test_a_full_queue_refuses_the_approval_without_stranding_it(
    client, approved_payload, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused enqueue is a 503, and the approval stays undecided.

    The alternative — record the decision, then discover the queue is full —
    leaves a decided-but-never-queued row: an approval the operator granted and
    the system silently dropped.
    """
    from types import SimpleNamespace

    monkeypatch.setattr(
        queue, "_limits", lambda: SimpleNamespace(max_pending_runs=0, max_pending_work_items=100)
    )

    response = client.post(f"/api/applications/{approved_payload.approval_id}/approve", json={})

    assert response.status_code == 503, response.text
    assert response.headers.get("Retry-After")
    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status == ApprovalStatus.PENDING, (
        "the approval was recorded but never queued, so the operator's decision was dropped"
    )


def test_a_tracking_failure_cannot_discard_the_accepted_run(
    client,
    approved_payload,
    db_session,
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
    run_worker_once,
) -> None:
    """Tracking is best-effort; the acceptance is not.

    ``_record_tracking_event`` swallows its exception and calls ``db.rollback``.
    When it ran *before* the request's single commit, a failure there discarded
    the APPROVED write and the run and item rows the enqueue had flushed — and
    the handler still returned 202 with a ``run_id`` no worker would ever see,
    because the run had been rolled back out of existence. The acceptance must
    survive a tracking failure, so the order is: commit the decision and the
    run, then record the tracking event.

    A mid-flight ``database is locked`` on SQLite (a worker writing at the same
    moment) is the plausible trigger. The stub below reproduces **both** shapes
    of the failure: the real helper's own recovery (a ``db.rollback()`` that
    discards whatever the shared session has pending) and an outright raise.
    The assertion that matters is the consequence, not the mechanism: does the
    run the operator was promised actually execute?

    The tracked application is seeded explicitly, because the tracking write
    only happens when one exists — without it this test would pass without ever
    reaching the code it is about.

    The stub reproduces the real helper's **silent** shape, which is what makes
    the finding dangerous: it rolls the shared session back and then swallows
    the error, so nothing propagates and the handler answers 202 as if all were
    well. The damage is checked where it lands — on the run.
    """
    from src.api.routes import applications as applications_route
    from src.applications.tracking import create_application

    with session_factory() as session:
        row = session.get(ApprovalRequestDB, approved_payload.approval_id)
        create_application(
            session,
            owner_id=LEGACY_OWNER_ID,
            workflow_id=row.workflow_id,
            adapter_name=row.adapter_name,
            job_url=row.job_url,
            job_title=row.job_title,
            company_name=row.company_name,
            approval_id=approved_payload.approval_id,
        )
        session.commit()

    tracking_calls: list[int] = []
    logged: list[str] = []

    def fail(db, *_args, **_kwargs):
        tracking_calls.append(1)
        db.rollback()
        logged.append("database is locked")  # what the real helper logs

    monkeypatch.setattr(applications_route, "_record_tracking_event", fail)

    response = client.post(f"/api/applications/{approved_payload.approval_id}/approve", json={})

    assert tracking_calls, "the tracking path was never reached, so this test proves nothing"
    assert logged, "the failure must be recorded, not silently ignored"
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    assert run_id

    # The run really exists and a worker can claim and execute it.
    with session_factory() as session:
        assert queue.get_run(session, run_id) is not None

    counter = _CountingAdapter()
    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter)

    assert counter.submit_calls == 1
    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status == ApprovalStatus.EXECUTED


def test_no_code_path_executes_a_submission_inside_a_request_thread() -> None:
    """The inline path is gone, not merely unused.

    A leftover call is a path that runs again the moment someone re-wires the
    route, and the failure it causes (a timeout mid-submission) is one nobody
    would connect back to this refactor.
    """
    source = (ROOT / "src" / "api" / "routes" / "applications.py").read_text("utf-8")
    assert "execute_approved" not in source


def test_the_route_and_the_worker_resolve_adapters_from_one_registry() -> None:
    """One resolver over one list, so the route and the worker cannot drift.

    The route used to hold its own list; the worker importing the route module
    to share it would be a layering inversion — a request handler is not a
    registry. The list lives beside the adapter-selection logic, and the name
    lookup (what the worker needs, since it has the recorded name and not the
    URL) sits next to the URL lookup and reads the same live list.
    """
    assert applications_route.select_adapter_for_url is graph_executor.select_adapter_for_url

    # Both resolvers read the module-level list at call time, so replacing it
    # (a test, or a deployment) changes both answers at once. A captured copy
    # would leave the worker resolving from a list nobody updates — which is
    # the drift this test exists to prevent.
    assert graph_executor.select_adapter_for_url.__defaults__ == (None,)
    assert graph_executor.select_adapter_by_name.__defaults__ == (None,)

    chosen = graph_executor.select_adapter_by_name("fake-ats-playwright")
    assert chosen.name == "fake-ats-playwright"
    assert graph_executor.select_adapter_for_url(JOB_URL).name == "fake-ats-playwright"
    assert [adapter.name for adapter in graph_executor.AVAILABLE_ADAPTERS] == [
        "fake-ats-playwright",
        "greenhouse",
        "lever",
    ]

    with pytest.raises(LookupError):
        graph_executor.select_adapter_by_name("no-such-board")
    with pytest.raises(RuntimeError):
        graph_executor.select_adapter_for_url("https://unknown.example/1")


def test_the_policy_is_rechecked_at_execution_not_only_at_accept(
    client, approved_payload, db_session, run_worker_once, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queued submission re-checks the policy, so a kill switch works.

    WS-32 moved the execution off the request thread onto a durable queue,
    which widened the window between the decision and the submission from
    milliseconds to an unbounded queue delay. The policy was only ever read at
    accept time, so an approval granted while submitting was allowed would
    still submit after an operator flipped ``SUBMISSION_POLICY`` to
    ``PREPARE_ONLY`` — the control the policy exists to be.

    The check therefore runs where the submission actually happens.
    """
    from src.security import policy as submission_policy

    _approve(client, approved_payload.approval_id)
    counter = _CountingAdapter()
    monkeypatch.setattr(
        submission_policy,
        "get_submission_policy",
        lambda: submission_policy.SubmissionPolicy.PREPARE_ONLY,
    )

    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter)

    assert counter.submit_calls == 0, (
        "the policy forbids executing a prepared application, and the submission ran anyway"
    )
    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status != ApprovalStatus.EXECUTED, (
        "a policy-refused submission must not read as executed"
    )
    assert row.result is None or row.result.get("success") is not True


def test_the_policy_allowing_execution_does_not_break_the_happy_path(
    client, approved_payload, db_session, run_worker_once
) -> None:
    """The new gate must not silently refuse a submission that is allowed.

    A policy check added to the worker path is one ``if`` away from refusing
    everything, so the allowed case is pinned beside the refused one.
    """
    _approve(client, approved_payload.approval_id)
    counter = _CountingAdapter()

    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter)

    assert counter.submit_calls == 1
    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status == ApprovalStatus.EXECUTED


def test_an_unreadable_policy_configuration_refuses_rather_than_crashing(
    client, approved_payload, db_session, run_worker_once, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A policy that cannot even be read must refuse the submission, not crash.

    ``get_submission_policy`` raises ``PolicyError`` on an unknown configured
    value. That is the same fail-closed outcome as a policy that forbids
    submitting, and it must arrive as one: a worker that died on it would leave
    the item to the lease reaper and look like an infrastructure fault.
    """
    from src.security import policy as submission_policy

    _approve(client, approved_payload.approval_id)
    counter = _CountingAdapter()

    def _unreadable() -> submission_policy.SubmissionPolicy:
        raise submission_policy.PolicyError("Unknown submission policy 'NONSENSE'")

    monkeypatch.setattr(submission_policy, "get_submission_policy", _unreadable)

    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter)

    assert counter.submit_calls == 0
    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status != ApprovalStatus.EXECUTED
