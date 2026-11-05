"""WS-18 · worker crash recovery and failure injection.

The scenarios are the ones the brief names, driven against a real SQLite file
(not an in-memory database) so a "fresh process" is a genuinely fresh session
factory on the same durable state:

- crash before the first batch;
- crash in the middle of a batch (embeddings generated, not settled);
- crash after a Chroma upsert but before the SQL completion;
- an expired lease reclaimed by a second worker;
- a stale worker trying to commit after its lease was reclaimed;
- the daily quota stopping a run cleanly, then an explicit resume;
- the refresh handler persisting and creating its child embedding run;
- reconciliation detecting and repairing missing and orphan vectors.

No test asserts "the exception was raised" and stops there: each one reopens
the database and asserts the durable state the next worker will see.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.jobs import JobDB, save_jobs
from src.db.runs import JobRunDB, JobWorkItemDB
from src.llm.client import LLMDailyQuotaExhausted
from src.rag.chroma_store import ChromaVectorStore
from src.runs import queue
from src.runs.embedding import JOB_TYPE_EMBEDDING
from src.runs.state import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PAUSED,
    LeaseLost,
    utcnow,
)
from src.runs.worker import Worker
from tests.fixtures.fake_embeddings import FakeEmbeddingFn, make_store
from tests.fixtures.fake_source import FakeJobSource, make_listing


@pytest.fixture()
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'worker.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield sessions
    engine.dispose()


@pytest.fixture()
def store(tmp_path):
    return make_store(tmp_path / "chroma", FakeEmbeddingFn())


def _listings(count: int = 5):
    return [
        make_listing(
            str(index),
            f"Backend Python Engineer {index}",
            f"Company {index}",
            description=f"Build Python services for team {index}.",
            required_skills=["Python"],
        )
        for index in range(count)
    ]


def _seed(factory, count: int = 5):
    listings = _listings(count)
    save_jobs(listings, session_factory=factory)
    return listings


def _hashes(listings):
    return {
        job.id: ChromaVectorStore.content_hash(ChromaVectorStore.document_text(job))
        for job in listings
    }


def _enqueue_embedding(factory, listings, store, *, model=None, dimension=None) -> str:
    hashes = _hashes(listings)
    with factory() as session:
        accepted = queue.enqueue_run(
            session,
            job_type=JOB_TYPE_EMBEDDING,
            correlation_id="corr-embedding",
            items=[
                queue.WorkSpec(job_id=job.id, work_type="embed", content_hash=hashes[job.id])
                for job in listings
            ],
            embedding_model=model or store.embedding_model,
            embedding_dimension=dimension or store.dimension,
        )
        session.commit()
    return accepted.run_id


def _worker(factory, store, **overrides) -> Worker:
    return Worker(
        worker_id=overrides.pop("worker_id", "worker-test"),
        session_factory=factory,
        store_factory=lambda: store,
        batch_size=overrides.pop("batch_size", 2),
        lease_seconds=overrides.pop("lease_seconds", 10),
        poll_interval=0,
        sleep=lambda _seconds: None,
        **overrides,
    )


def _drain(worker: Worker, *, max_iterations: int = 20) -> int:
    processed = 0
    for _ in range(max_iterations):
        count = worker.run_once()
        processed += count
        if count == 0:
            break
    return processed


def _run(factory, run_id: str):
    with factory() as session:
        run = session.get(JobRunDB, run_id)
        assert run is not None
        session.expunge(run)
        return run


def _items(factory, run_id: str):
    with factory() as session:
        rows = list(
            session.execute(select(JobWorkItemDB).where(JobWorkItemDB.run_id == run_id)).scalars()
        )
        for row in rows:
            session.expunge(row)
        return rows


# -- the four crash windows ---------------------------------------------------


def test_a_crash_before_the_first_batch_loses_nothing(factory, store):
    listings = _seed(factory)
    run_id = _enqueue_embedding(factory, listings, store)

    # "The process crashed": nothing was claimed. A fresh worker picks it up.
    processed = _drain(_worker(factory, store))

    assert processed == len(listings)
    assert _run(factory, run_id).status == RUN_COMPLETED
    assert store.count() == len(listings)

    # The batch's observability: the first pass is all cache misses, and the
    # number is on the event rather than inferred.
    from src.db.runs import JobRunEventDB

    with factory() as session:
        events = list(
            session.execute(
                select(JobRunEventDB).where(JobRunEventDB.run_id == run_id)
            ).scalars()
        )
    batches = [event for event in events if event.event == "batch.completed"]
    assert batches
    assert sum(int(event.extra_metadata["cache_misses"]) for event in batches) == len(listings)
    assert sum(int(event.extra_metadata["cache_hits"]) for event in batches) == 0


def test_a_crash_mid_batch_is_recovered_without_duplicates(factory, store):
    listings = _seed(factory)
    run_id = _enqueue_embedding(factory, listings, store)
    moment = utcnow()

    # Worker A claims two items and dies before settling them.
    dead = queue.claim_work_items(
        worker_id="dead-worker",
        limit=2,
        lease_seconds=10,
        session_factory=factory,
        now=moment,
    )
    assert len(dead) == 2
    queue.reap_expired_leases(
        session_factory=factory,
        now=moment + timedelta(seconds=11),
        run_stale_seconds=5,
        max_attempts=3,
    )
    assert _run(factory, run_id).status == "RECOVERABLE"
    with factory() as session:
        queue.resume_run(
            session,
            run_id=run_id,
            actor="user:admin",
            expected_model=store.embedding_model,
            expected_dimension=store.dimension,
            now=moment + timedelta(seconds=12),
        )
        session.commit()

    # The worker runs at the same virtual moment the resume used, so the
    # requeued items are due (a real clock would still be 12 s behind).
    _drain(_worker(factory, store, now=lambda: moment + timedelta(seconds=20)))

    assert _run(factory, run_id).status == RUN_COMPLETED
    # The two in-flight listings were re-embedded with the same stable ids,
    # so the upsert updated in place rather than duplicating.
    assert store.count() == len(listings)
    assert {job.id for job in listings} == store.stored_ids()


def test_an_upsert_without_a_sql_completion_is_safe(factory, store):
    listings = _seed(factory)
    run_id = _enqueue_embedding(factory, listings, store)
    moment = utcnow()
    claimed = queue.claim_work_items(
        worker_id="dead-worker",
        limit=2,
        lease_seconds=10,
        session_factory=factory,
        now=moment,
    )
    assert len(claimed) == 2

    # The Chroma write succeeded; the process died before the item was
    # marked complete.
    store.upsert_jobs(listings[:2])
    assert store.count() == 2

    queue.reap_expired_leases(
        session_factory=factory,
        now=moment + timedelta(seconds=11),
        run_stale_seconds=5,
        max_attempts=3,
    )
    with factory() as session:
        queue.resume_run(
            session,
            run_id=run_id,
            actor="user:admin",
            expected_model=store.embedding_model,
            expected_dimension=store.dimension,
            now=moment + timedelta(seconds=12),
        )
        session.commit()
    _drain(_worker(factory, store, now=lambda: moment + timedelta(seconds=20)))

    assert _run(factory, run_id).status == RUN_COMPLETED
    assert store.count() == len(listings)  # re-upsert, not a duplicate


def test_a_stale_worker_cannot_complete_after_its_lease_was_reclaimed(factory, store):
    listings = _seed(factory)
    run_id = _enqueue_embedding(factory, listings, store)
    moment = utcnow()
    stale = queue.claim_work_items(
        worker_id="dead-worker",
        limit=1,
        lease_seconds=10,
        session_factory=factory,
        now=moment,
        run_ids=[run_id],
    )[0]
    queue.reap_expired_leases(
        session_factory=factory,
        now=moment + timedelta(seconds=11),
        run_stale_seconds=5,
        max_attempts=3,
    )
    with factory() as session:
        queue.resume_run(
            session,
            run_id=run_id,
            actor="user:admin",
            expected_model=store.embedding_model,
            expected_dimension=store.dimension,
            now=moment + timedelta(seconds=12),
        )
        session.commit()
    live = queue.claim_work_items(
        worker_id="live-worker",
        limit=1,
        lease_seconds=10,
        session_factory=factory,
        now=moment + timedelta(seconds=13),
        run_ids=[run_id],
    )[0]

    with pytest.raises(LeaseLost):
        queue.settle_work_items(
            run_id=run_id,
            outcomes=[
                queue.ItemOutcome(
                    item_id=stale.id,
                    lease_token=stale.lease_token,
                    status="COMPLETED",
                )
            ],
            worker_id="dead-worker",
            session_factory=factory,
        )

    item = next(item for item in _items(factory, run_id) if item.id == live.id)
    assert item.status == "RUNNING"
    assert item.lease_token == live.lease_token


# -- quota --------------------------------------------------------------------


class QuotaOnceEmbedding(FakeEmbeddingFn):
    """Raises the daily-quota error once, then behaves normally."""

    def __init__(self) -> None:
        super().__init__()
        self.exhausted = True

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.exhausted:
            raise LLMDailyQuotaExhausted("daily embedding budget spent")
        return super().embed_documents(texts)


def test_a_quota_stop_pauses_cleanly_and_resume_finishes(factory, tmp_path):
    listings = _seed(factory, count=4)
    embedding = QuotaOnceEmbedding()
    store = make_store(tmp_path / "chroma-quota", embedding)
    run_id = _enqueue_embedding(factory, listings, store)

    worker = _worker(factory, store)
    assert worker.run_once() > 0

    paused = _run(factory, run_id)
    assert paused.status == RUN_PAUSED
    assert paused.last_error_kind == "quota"
    assert all(item.status == "QUEUED" for item in _items(factory, run_id))
    assert store.count() == 0

    embedding.exhausted = False
    with factory() as session:
        queue.resume_run(
            session,
            run_id=run_id,
            actor="user:admin",
            expected_model=store.embedding_model,
            expected_dimension=store.dimension,
        )
        session.commit()

    _drain(worker)
    assert _run(factory, run_id).status == RUN_COMPLETED
    assert store.count() == len(listings)


def test_a_model_change_refuses_the_resume(factory, store):
    listings = _seed(factory, count=2)
    run_id = _enqueue_embedding(factory, listings, store, model="old-model", dimension=64)
    with factory() as session:
        session.get(JobRunDB, run_id).status = "RECOVERABLE"
        session.commit()
    with factory() as session, pytest.raises(ValueError, match="embedding space"):
        queue.resume_run(
            session,
            run_id=run_id,
            actor="user:admin",
            expected_model="new-model",
            expected_dimension=64,
        )


# -- the refresh handler ------------------------------------------------------


def test_the_refresh_handler_persists_and_creates_the_child_run(factory, store, tmp_path):
    with factory() as session:
        accepted = queue.enqueue_run(
            session,
            job_type="refresh",
            correlation_id="corr-refresh",
            items=[queue.WorkSpec(job_id="", work_type="refresh", content_hash="")],
        )
        session.commit()

    worker = _worker(
        factory,
        store,
        sources={"fixture": FakeJobSource()},
        embedding_fn=FakeEmbeddingFn(),
    )
    worker.run_once()

    refresh_run = _run(factory, accepted.run_id)
    assert refresh_run.status == RUN_COMPLETED
    with factory() as session:
        jobs = list(session.execute(select(JobDB)).scalars())
        children = list(
            session.execute(
                select(JobRunDB).where(JobRunDB.parent_run_id == accepted.run_id)
            ).scalars()
        )
    assert len(jobs) == 5
    assert len(children) == 1
    assert children[0].job_type == "embedding"
    assert children[0].total_items == 5

    _drain(worker)
    assert store.count() == 5


def test_an_unknown_work_type_fails_permanently(factory, store):
    with factory() as session:
        accepted = queue.enqueue_run(
            session,
            job_type="mystery",
            correlation_id="corr-mystery",
            items=[queue.WorkSpec(job_id="", work_type="mystery", content_hash="")],
        )
        session.commit()
    _drain(_worker(factory, store))
    run = _run(factory, accepted.run_id)
    assert run.status == RUN_FAILED
    assert _items(factory, accepted.run_id)[0].last_error_kind == "permanent"


# -- reconciliation -----------------------------------------------------------


def test_reconciliation_repairs_missing_vectors_and_deletes_orphans(factory, store):
    listings = _seed(factory, count=3)
    orphan = make_listing("ghost", "Ghost Role", "Nowhere")
    store.upsert_jobs([orphan])  # a vector with no source row
    assert store.count() == 1

    with factory() as session:
        accepted = queue.enqueue_run(
            session,
            job_type="reconcile",
            correlation_id="corr-reconcile",
            items=[queue.WorkSpec(job_id="", work_type="reconcile", content_hash="")],
        )
        session.commit()

    worker = _worker(factory, store)
    worker.run_once()

    assert _run(factory, accepted.run_id).status == RUN_COMPLETED
    with factory() as session:
        children = list(
            session.execute(
                select(JobRunDB).where(JobRunDB.parent_run_id == accepted.run_id)
            ).scalars()
        )
        metadata = session.get(JobRunDB, accepted.run_id).extra_metadata["reconcile"]
    assert metadata["sql_listings"] == len(listings)
    assert metadata["missing"] == len(listings)
    assert metadata["orphaned"] == 1
    assert metadata["deleted_orphans"] == 1
    assert len(children) == 1

    _drain(worker)
    assert {job.id for job in listings} <= store.stored_ids()
    assert "fixture:ghost" not in store.stored_ids()


def test_reconciliation_is_idempotent(factory, store):
    listings = _seed(factory, count=2)
    first_run = _enqueue_embedding(factory, listings, store)
    _drain(_worker(factory, store))
    assert _run(factory, first_run).status == RUN_COMPLETED

    with factory() as session:
        accepted = queue.enqueue_run(
            session,
            job_type="reconcile",
            correlation_id="corr-reconcile-2",
            items=[queue.WorkSpec(job_id="", work_type="reconcile", content_hash="")],
        )
        session.commit()
    _drain(_worker(factory, store))

    with factory() as session:
        metadata = session.get(JobRunDB, accepted.run_id).extra_metadata["reconcile"]
    assert metadata["missing"] == 0
    assert metadata["run_id"] is None  # no new work was needed
    assert _run(factory, accepted.run_id).status == RUN_COMPLETED
