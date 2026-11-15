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
from src.db.runs import JobWorkItemDB
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
    recover it. ``crash_after_submit`` kills it after the durable record of the
    submission exists and before the work item is settled, which is the shape a
    real crash takes: what was committed is kept, what was not is lost.
    """

    def __init__(
        self,
        *args: Any,
        crash_after_claim: bool = False,
        crash_after_submit: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.crash_after_claim = crash_after_claim
        self.crash_after_submit = crash_after_submit
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
        super()._record_submission_outcome(session, row, result)
        if self.crash_after_submit:
            raise _Crash("simulated crash after the submission was recorded")


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
        )
        if crash_after_claim or crash_after_submit:
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


def test_a_submission_that_crashes_mid_run_is_reclaimable(
    client, approved_payload, db_session, run_worker_once, expire_lease
) -> None:
    """The lease expires, the run is retried, and the row never reads EXECUTED."""
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


def test_a_retried_submission_does_not_submit_twice(
    client, approved_payload, db_session, run_worker_once
) -> None:
    """At-most-once matters: a double submission is a real harm, not a nuisance.

    The crash lands *after* the board accepted the application, so the retry
    must refuse rather than apply again.
    """
    _approve(client, approved_payload.approval_id)
    counter = _CountingAdapter()

    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter, crash_after_submit=True)
    run_worker_once(kind=SUBMISSION_WORK_TYPE, adapter=counter)

    assert counter.submit_calls == 1
    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status == ApprovalStatus.EXECUTED


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
