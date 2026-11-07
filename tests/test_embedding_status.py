"""WS-20 · the embedding-status read over the WS-18 work queue."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.matching.embedding_status import embedding_status_for_jobs, is_pending_status
from src.runs import queue
from src.runs.state import WORK_COMPLETED, WORK_FAILED, WORK_QUEUED, WORK_RETRY_WAIT


def factory(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'embed.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _enqueue(factory, job_ids: list[str]) -> str:
    with factory() as session:
        accepted = queue.enqueue_run(
            session,
            job_type="embedding",
            correlation_id="corr",
            priority=queue.PRIORITY_EMBEDDING,
            items=[queue.WorkSpec(job_id=job_id, content_hash=f"h-{job_id}") for job_id in job_ids],
            embedding_model="m",
            embedding_dimension=8,
        )
        session.commit()
    return accepted.run_id


def test_status_absent_when_no_work_item(tmp_path):
    f = factory(tmp_path)
    assert embedding_status_for_jobs(["job-1"], session_factory=f) == {}


def test_status_reports_queued_items(tmp_path):
    f = factory(tmp_path)
    _enqueue(f, ["job-1", "job-2"])
    statuses = embedding_status_for_jobs(["job-1", "job-2"], session_factory=f)
    assert statuses["job-1"] == WORK_QUEUED
    assert statuses["job-2"] == WORK_QUEUED


def test_status_reports_failed_items(tmp_path):
    f = factory(tmp_path)
    run_id = _enqueue(f, ["job-1"])
    with f() as session:
        item = queue.get_run_items(session, run_id)[0]
    with f() as session:
        row = session.get(type(item), item.id)
        row.status = WORK_FAILED
        session.commit()
    assert embedding_status_for_jobs(["job-1"], session_factory=f)["job-1"] == WORK_FAILED


def test_pending_status_classification():
    assert is_pending_status(WORK_QUEUED)
    assert is_pending_status(WORK_RETRY_WAIT)
    assert is_pending_status(WORK_FAILED)
    assert not is_pending_status(WORK_COMPLETED)
    assert not is_pending_status(None)


def test_only_requested_ids_are_returned(tmp_path):
    f = factory(tmp_path)
    _enqueue(f, ["job-1", "job-2", "job-3"])
    statuses = embedding_status_for_jobs(["job-2"], session_factory=f)
    assert set(statuses) == {"job-2"}


def test_empty_input_is_empty_output(tmp_path):
    f = factory(tmp_path)
    assert embedding_status_for_jobs([], session_factory=f) == {}
