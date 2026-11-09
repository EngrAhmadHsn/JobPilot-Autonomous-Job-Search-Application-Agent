"""WS-18 · the durable queue: claiming, leases, recovery and the state machine.

These are the properties the rest of the system relies on, tested at the
layer that owns them: one database, no HTTP, deterministic clocks. The
worker/recovery tests (``test_worker_recovery.py``) drive the same machinery
through the embedding handler.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.runs import JobRunDB, JobWorkItemDB, WorkerHeartbeatDB
from src.runs import queue
from src.runs.state import (
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RECOVERABLE,
    RUN_RETRY_WAIT,
    RUN_RUNNING,
    WORK_COMPLETED,
    WORK_QUEUED,
    WORK_RUNNING,
    IllegalTransition,
    LeaseLost,
    assert_transition,
    utcnow,
)


@pytest.fixture()
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'queue.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield sessions
    engine.dispose()


def _enqueue(
    factory,
    *,
    count: int = 3,
    job_type: str = "embedding",
    priority: int = queue.PRIORITY_EMBEDDING,
    model: str = "test-model",
    dimension: int = 8,
    job_ids: list[str] | None = None,
) -> str:
    ids = job_ids or [f"job-{index}" for index in range(count)]
    with factory() as session:
        accepted = queue.enqueue_run(
            session,
            job_type=job_type,
            correlation_id="corr-1",
            priority=priority,
            items=[queue.WorkSpec(job_id=job_id, content_hash=f"hash-{job_id}") for job_id in ids],
            embedding_model=model,
            embedding_dimension=dimension,
        )
        session.commit()
    return accepted.run_id


def _run(factory, run_id: str) -> JobRunDB:
    with factory() as session:
        run = session.get(JobRunDB, run_id)
        assert run is not None
        session.expunge(run)
        return run


def _items(factory, run_id: str) -> list[JobWorkItemDB]:
    with factory() as session:
        rows = list(
            session.execute(select(JobWorkItemDB).where(JobWorkItemDB.run_id == run_id)).scalars()
        )
        for row in rows:
            session.expunge(row)
        return rows


def _settle(factory, run_id: str, item, status: str = WORK_COMPLETED) -> None:
    queue.settle_work_items(
        run_id=run_id,
        outcomes=[queue.ItemOutcome(item_id=item.id, lease_token=item.lease_token, status=status)],
        worker_id="test-worker",
        session_factory=factory,
    )


# -- enqueue ------------------------------------------------------------------


def test_enqueue_creates_items_and_a_creation_event(factory):
    run_id = _enqueue(factory, count=3)
    run = _run(factory, run_id)
    assert run.job_type == "embedding"
    assert run.status == RUN_QUEUED
    assert run.total_items == 3
    assert run.embedding_model == "test-model"
    assert run.embedding_dimension == 8
    assert len(_items(factory, run_id)) == 3
    with factory() as session:
        from src.db.runs import JobRunEventDB

        events = list(session.execute(select(JobRunEventDB)).scalars())
    assert any(event.event == "run.created" for event in events)


def test_an_identical_identity_is_one_work_item(factory):
    with factory() as session:
        accepted = queue.enqueue_run(
            session,
            job_type="embedding",
            correlation_id="corr",
            items=[
                queue.WorkSpec(job_id="job-1", content_hash="hash-a"),
                queue.WorkSpec(job_id="job-1", content_hash="hash-a"),
                queue.WorkSpec(job_id="job-1", content_hash="hash-b"),
            ],
            embedding_model="m",
            embedding_dimension=8,
        )
        session.commit()
    assert len(_items(factory, accepted.run_id)) == 2


def test_the_queue_is_bounded(factory, monkeypatch):
    monkeypatch.setattr(
        queue,
        "_limits",
        lambda: SimpleNamespace(max_pending_runs=1, max_pending_work_items=100),
    )
    _enqueue(factory, count=1)
    with pytest.raises(queue.QueueFull) as excinfo:
        _enqueue(factory, count=1, job_type="refresh", job_ids=[])
    assert excinfo.value.retry_after >= 1


def test_the_work_item_cap_is_enforced(factory, monkeypatch):
    monkeypatch.setattr(
        queue,
        "_limits",
        lambda: SimpleNamespace(max_pending_runs=10, max_pending_work_items=2),
    )
    with pytest.raises(queue.QueueFull):
        _enqueue(factory, count=3)


# -- claiming and leases ------------------------------------------------------


def test_two_workers_claim_disjoint_sets(factory):
    run_id = _enqueue(factory, count=4)
    first = queue.claim_work_items(
        worker_id="worker-a", limit=2, lease_seconds=60, session_factory=factory
    )
    second = queue.claim_work_items(
        worker_id="worker-b", limit=2, lease_seconds=60, session_factory=factory
    )
    assert len(first) == 2
    assert len(second) == 2
    assert {item.id for item in first}.isdisjoint({item.id for item in second})
    assert {item.id for item in first + second} == {item.id for item in _items(factory, run_id)}


def test_claiming_increments_the_attempt_and_commits_the_lease(factory):
    _enqueue(factory, count=1)
    claimed = queue.claim_work_items(
        worker_id="worker-a", limit=1, lease_seconds=60, session_factory=factory
    )
    assert len(claimed) == 1
    item = _items(factory, claimed[0].run_id)[0]
    assert item.status == WORK_RUNNING
    assert item.attempt_count == 1
    assert item.lease_owner == "worker-a"
    assert item.lease_token == claimed[0].lease_token
    assert item.lease_expires_at is not None


def test_a_recoverable_run_waits_for_an_explicit_resume(factory):
    run_id = _enqueue(factory, count=1)
    moment = utcnow()
    claimed = queue.claim_work_items(
        worker_id="worker-a",
        limit=1,
        lease_seconds=10,
        session_factory=factory,
        now=moment,
    )
    queue.reap_expired_leases(
        session_factory=factory,
        now=moment + timedelta(seconds=11),
        run_stale_seconds=5,
        max_attempts=3,
    )

    assert _run(factory, run_id).status == RUN_RECOVERABLE
    assert _items(factory, run_id)[0].status == WORK_QUEUED
    # The worker does not silently adopt an interrupted run.
    assert (
        queue.claim_work_items(
            worker_id="worker-b",
            limit=1,
            lease_seconds=10,
            session_factory=factory,
            now=moment + timedelta(seconds=12),
        )
        == []
    )

    with factory() as session:
        queue.resume_run(
            session,
            run_id=run_id,
            actor="user:admin",
            actor_id="admin",
            now=moment + timedelta(seconds=13),
        )
        session.commit()
        assert session.get(JobRunDB, run_id).status == RUN_QUEUED
    claimed_after = queue.claim_work_items(
        worker_id="worker-b",
        limit=1,
        lease_seconds=10,
        session_factory=factory,
        now=moment + timedelta(seconds=14),
    )
    assert len(claimed_after) == 1
    assert claimed_after[0].attempt_count == 1  # resume reset the count
    assert claimed[0].id == claimed_after[0].id

    with factory() as session:
        stats = queue.queue_stats(session, now=moment + timedelta(seconds=14))
    assert stats["items"]["running"] == 1
    assert stats["items"]["oldest_pending_age_seconds"] >= 0.0


def test_a_stale_worker_cannot_commit_after_reclaim(factory):
    run_id = _enqueue(factory, count=1)
    moment = utcnow()
    stale = queue.claim_work_items(
        worker_id="worker-a",
        limit=1,
        lease_seconds=10,
        session_factory=factory,
        now=moment,
    )[0]
    queue.reap_expired_leases(
        session_factory=factory,
        now=moment + timedelta(seconds=11),
        run_stale_seconds=5,
        max_attempts=3,
    )
    with factory() as session:
        queue.resume_run(
            session, run_id=run_id, actor="user:admin", now=moment + timedelta(seconds=12)
        )
        session.commit()
    current = queue.claim_work_items(
        worker_id="worker-b",
        limit=1,
        lease_seconds=10,
        session_factory=factory,
        now=moment + timedelta(seconds=13),
    )[0]

    with pytest.raises(LeaseLost):
        _settle(factory, run_id, stale)

    item = _items(factory, run_id)[0]
    assert item.status == WORK_RUNNING
    assert item.lease_token == current.lease_token


def test_an_exhausted_item_stops_retrying(factory):
    run_id = _enqueue(factory, count=1)
    moment = utcnow()
    queue.claim_work_items(
        worker_id="worker-a",
        limit=1,
        lease_seconds=10,
        session_factory=factory,
        now=moment,
        run_ids=[run_id],
    )
    # Simulate a crash loop: the item has already burned its attempts.
    with factory() as session:
        session.query(JobWorkItemDB).filter(JobWorkItemDB.run_id == run_id).update(
            {"attempt_count": 3}, synchronize_session=False
        )
        session.commit()
    queue.reap_expired_leases(
        session_factory=factory,
        now=moment + timedelta(seconds=11),
        run_stale_seconds=5,
        max_attempts=3,
    )
    assert _items(factory, run_id)[0].status == "FAILED"
    assert _run(factory, run_id).status == RUN_FAILED


# -- recovery -----------------------------------------------------------------


def test_resume_never_requeues_completed_work(factory):
    run_id = _enqueue(factory, count=3)
    moment = utcnow()
    first = queue.claim_work_items(
        worker_id="worker-a",
        limit=3,
        lease_seconds=10,
        session_factory=factory,
        now=moment,
    )
    _settle(factory, run_id, first[0])
    queue.reap_expired_leases(
        session_factory=factory,
        now=moment + timedelta(seconds=11),
        run_stale_seconds=5,
        max_attempts=3,
    )
    assert _run(factory, run_id).status == RUN_RECOVERABLE

    with factory() as session:
        queue.resume_run(
            session, run_id=run_id, actor="user:admin", now=moment + timedelta(seconds=12)
        )
        session.commit()

    statuses = {item.id: item.status for item in _items(factory, run_id)}
    assert statuses[first[0].id] == WORK_COMPLETED
    assert all(statuses[item.id] == WORK_QUEUED for item in first[1:])


def test_a_second_resume_is_refused(factory):
    run_id = _enqueue(factory, count=1)
    with factory() as session:
        run = session.get(JobRunDB, run_id)
        run.status = RUN_RECOVERABLE
        session.commit()
    with factory() as session:
        queue.resume_run(session, run_id=run_id, actor="user:admin")
        session.commit()
    with factory() as session, pytest.raises(IllegalTransition):
        queue.resume_run(session, run_id=run_id, actor="user:admin")


def test_resume_rejects_a_different_embedding_space(factory):
    run_id = _enqueue(factory, count=1, model="model-a", dimension=8)
    with factory() as session:
        session.get(JobRunDB, run_id).status = RUN_RECOVERABLE
        session.commit()
    with factory() as session, pytest.raises(ValueError, match="embedding space"):
        queue.resume_run(
            session,
            run_id=run_id,
            actor="user:admin",
            expected_model="model-b",
            expected_dimension=8,
        )


def test_cancel_stops_outstanding_work_and_keeps_history(factory):
    run_id = _enqueue(factory, count=2)
    queue.claim_work_items(worker_id="worker-a", limit=1, lease_seconds=60, session_factory=factory)
    with factory() as session:
        cancelled = queue.cancel_run(session, run_id=run_id, actor="user:admin")
        assert cancelled.status == RUN_CANCELLED
        session.commit()
    assert {item.status for item in _items(factory, run_id)} == {"CANCELLED"}
    assert (
        queue.claim_work_items(
            worker_id="worker-b", limit=10, lease_seconds=60, session_factory=factory
        )
        == []
    )


# -- priority and state machine ----------------------------------------------


def test_recovery_work_is_claimed_before_new_work(factory):
    _enqueue(factory, count=1, priority=queue.PRIORITY_REFRESH, job_ids=["normal"])
    _enqueue(factory, count=1, priority=queue.PRIORITY_RECOVERY, job_ids=["recovery"])
    claimed = queue.claim_work_items(
        worker_id="worker-a", limit=1, lease_seconds=60, session_factory=factory
    )
    assert claimed[0].job_id == "recovery"


def test_the_state_machine_refuses_to_turn_failure_into_success():
    with pytest.raises(IllegalTransition):
        assert_transition(RUN_FAILED, RUN_COMPLETED)
    with pytest.raises(IllegalTransition):
        assert_transition(RUN_CANCELLED, RUN_COMPLETED)
    with pytest.raises(IllegalTransition):
        assert_transition("NOT_A_STATUS", RUN_RUNNING)
    # The explicit recovery path is legal.
    assert_transition(RUN_RECOVERABLE, RUN_QUEUED)
    assert_transition(RUN_FAILED, RUN_QUEUED)


def test_a_run_with_only_retrying_items_is_retry_wait(factory):
    run_id = _enqueue(factory, count=1)
    item = queue.claim_work_items(
        worker_id="worker-a", limit=1, lease_seconds=60, session_factory=factory
    )[0]
    queue.settle_work_items(
        run_id=run_id,
        outcomes=[
            queue.ItemOutcome(
                item_id=item.id,
                lease_token=item.lease_token,
                status="RETRY_WAIT",
                error="transient",
                error_kind="retryable",
                next_attempt_at=utcnow() + timedelta(minutes=5),
            )
        ],
        worker_id="worker-a",
        session_factory=factory,
    )
    assert _run(factory, run_id).status == RUN_RETRY_WAIT


# -- worker registry ----------------------------------------------------------


def test_a_worker_heartbeat_turns_stale(factory):
    moment = utcnow()
    with factory() as session:
        queue.register_worker(session, worker_id="worker-a", now=moment)
        queue.heartbeat_worker(session, worker_id="worker-a", now=moment)

    with factory() as session:
        healthy = queue.worker_health(
            session, stale_after_seconds=30, now=moment + timedelta(seconds=5)
        )
    assert healthy["healthy"] == 1
    assert healthy["workers"][0]["healthy"] is True

    with factory() as session:
        stale = queue.worker_health(
            session, stale_after_seconds=30, now=moment + timedelta(seconds=120)
        )
    assert stale["healthy"] == 0
    assert stale["workers"][0]["healthy"] is False
    assert stale["workers"][0]["heartbeat_age_seconds"] >= 120
    assert "work_per_minute" in stale["workers"][0]


def test_registering_again_counts_the_restart(factory):
    with factory() as session:
        queue.register_worker(session, worker_id="worker-a")
        queue.register_worker(session, worker_id="worker-a")
        row = session.get(WorkerHeartbeatDB, "worker-a")
        assert row.starts == 2


def test_the_reaper_persists_a_crash_for_a_silent_worker(factory):
    """The read-side derivation is not enough on its own: the stored row is
    what every other consumer sees, and a killed process cannot write it. The
    reaper is the component that runs after the fact, so it records the
    verdict."""
    moment = utcnow()
    with factory() as session:
        queue.register_worker(session, worker_id="worker-killed", now=moment)
        # Registered a long time ago and silent since — the shape of a crash.
        row = session.get(WorkerHeartbeatDB, "worker-killed")
        row.last_heartbeat_at = moment - timedelta(hours=1)
        session.commit()

    result = queue.reap_expired_leases(
        session_factory=factory,
        now=moment,
        run_stale_seconds=1800,
        max_attempts=3,
    )

    assert result["workers_crashed"] == 1
    with factory() as session:
        row = session.get(WorkerHeartbeatDB, "worker-killed")
        assert row.status == "crashed"
        assert row.stopped_at is not None


def test_the_reaper_leaves_a_live_worker_alone(factory):
    """The reaper must not crash a worker merely because a batch is long: the
    worker-shaped window is its own, and a fresh heartbeat is inside it."""
    moment = utcnow()
    with factory() as session:
        queue.register_worker(session, worker_id="worker-live", now=moment)
        queue.heartbeat_worker(session, worker_id="worker-live", now=moment)

    result = queue.reap_expired_leases(
        session_factory=factory,
        now=moment + timedelta(seconds=30),
        run_stale_seconds=1800,
        max_attempts=3,
    )

    assert result["workers_crashed"] == 0
    with factory() as session:
        assert session.get(WorkerHeartbeatDB, "worker-live").status == "running"


def test_a_cleanly_stopped_worker_is_never_reclassified(factory):
    """A worker that exited on purpose said so; silence afterwards is not a
    crash."""
    moment = utcnow()
    with factory() as session:
        queue.register_worker(session, worker_id="worker-done", now=moment)
        queue.mark_worker_stopped(session, worker_id="worker-done", now=moment)

    result = queue.reap_expired_leases(
        session_factory=factory,
        now=moment + timedelta(hours=2),
        run_stale_seconds=1800,
        max_attempts=3,
    )

    assert result["workers_crashed"] == 0
    with factory() as session:
        assert session.get(WorkerHeartbeatDB, "worker-done").status == "stopped"
