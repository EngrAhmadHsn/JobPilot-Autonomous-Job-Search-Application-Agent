"""WS-18 · the run API: ownership, authorization and administrator recovery.

The two surfaces are tested for the answers that matter:

- an ordinary caller sees their **own** runs and gets the same 404 for a
  foreign run and a missing one;
- every recovery action is an administrator action, refused on the server
  for an ordinary account (403) and for an anonymous caller (401);
- a resume is a validated state transition: a second resume conflicts, a
  model change conflicts, and the audit row names the administrator.

The database is a throwaway SQLite file per test; the identity is injected
through FastAPI's dependency override, the same seam the rest of the suite
uses (the real cookie transport is proved in ``test_auth.py``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.auth.routes import current_active_user
from src.db.audit import AuditEventDB
from src.db.base import Base
from src.db.runs import JobRunDB
from src.db.session import get_db
from src.db.users import UserDB
from src.main import app
from src.runs import queue


def _user(user_id: str, *, superuser: bool = False) -> UserDB:
    return UserDB(
        id=user_id,
        email=f"{user_id}@example.com",
        hashed_password="!",
        is_active=True,
        is_superuser=superuser,
        is_verified=True,
    )


ALICE = _user("alice")
BOB = _user("bob")
ADMIN = _user("admin-1", superuser=True)


@pytest.fixture()
def api(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'runs-api.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # The resume route validates against the configured provider; inject an
    # identity without loading a model or touching the developer's data dir.
    monkeypatch.setattr(
        "src.llm.embeddings.build_embedding_fn",
        lambda *args, **kwargs: SimpleNamespace(model="test-model", dimensionality=8),
    )
    yield TestClient(app), factory
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(current_active_user, None)
    engine.dispose()


def _act_as(user: UserDB) -> None:
    app.dependency_overrides[current_active_user] = lambda: user


def _make_run(
    factory,
    *,
    owner: str | None,
    status: str | None = None,
    job_type: str = "embedding",
    model: str = "test-model",
    dimension: int = 8,
    items: int = 3,
) -> str:
    with factory() as session:
        accepted = queue.enqueue_run(
            session,
            job_type=job_type,
            correlation_id="corr",
            owner_id=owner,
            items=[
                queue.WorkSpec(job_id=f"job-{index}", content_hash=f"hash-{index}")
                for index in range(items)
            ],
            embedding_model=model,
            embedding_dimension=dimension,
        )
        if status is not None:
            session.get(JobRunDB, accepted.run_id).status = status
        session.commit()
    return accepted.run_id


# -- ownership ----------------------------------------------------------------


def test_a_caller_reads_their_own_run(api):
    client, factory = api
    _act_as(ALICE)
    run_id = _make_run(factory, owner="alice")

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 200
    body = response.json()["run"]
    assert body["id"] == run_id
    assert body["owner_id"] == "alice"
    assert body["items"]["queued"] == 3


def test_a_caller_cannot_read_another_users_run(api):
    client, factory = api
    _act_as(ALICE)
    run_id = _make_run(factory, owner="bob")

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 404
    # The same answer as a run that never existed: no existence oracle.
    assert client.get("/api/runs/no-such-run").status_code == 404


def test_a_platform_run_is_administrator_only(api):
    client, factory = api
    run_id = _make_run(factory, owner=None)
    _act_as(ALICE)
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    _act_as(ADMIN)
    assert client.get(f"/api/runs/{run_id}").status_code == 200


def test_the_run_list_is_scoped(api):
    client, factory = api
    _make_run(factory, owner="alice", items=1)
    _make_run(factory, owner="bob", items=1)
    _make_run(factory, owner=None, items=1)

    _act_as(ALICE)
    body = client.get("/api/runs").json()
    assert body["count"] == 1
    assert body["runs"][0]["owner_id"] == "alice"

    _act_as(ADMIN)
    assert client.get("/api/runs").json()["count"] == 3


# -- the administrator authorization boundary --------------------------------


def test_an_ordinary_account_cannot_list_embedding_runs(api):
    client, _factory = api
    _act_as(ALICE)
    assert client.get("/api/admin/embedding-runs").status_code == 403


def test_an_ordinary_account_cannot_resume(api):
    client, factory = api
    _act_as(ALICE)
    run_id = _make_run(factory, owner="alice", status="RECOVERABLE")
    assert client.post(f"/api/admin/embedding-runs/{run_id}/resume").status_code == 403


def test_an_anonymous_caller_is_refused(api):
    client, factory = api
    run_id = _make_run(factory, owner="alice", status="RECOVERABLE")
    app.dependency_overrides.pop(current_active_user, None)
    assert client.get("/api/runs").status_code == 401
    assert client.post(f"/api/admin/embedding-runs/{run_id}/resume").status_code == 401
    assert client.get("/api/admin/jobs/metrics").status_code == 401


# -- resume -------------------------------------------------------------------


def test_an_administrator_resumes_a_recoverable_run(api):
    client, factory = api
    _act_as(ADMIN)
    run_id = _make_run(factory, owner="alice", status="RECOVERABLE")

    response = client.post(f"/api/admin/embedding-runs/{run_id}/resume")

    assert response.status_code == 202
    body = response.json()
    assert body["run_id"] == run_id
    assert body["status"] == "QUEUED"
    assert body["queued"] is True

    with factory() as session:
        run = session.get(JobRunDB, run_id)
        assert run.status == "QUEUED"
        assert run.priority == queue.PRIORITY_RECOVERY
        # The action is attributable, with the administrator's own identity.
        audit = list(
            session.execute(
                select(AuditEventDB).where(AuditEventDB.action == "run.resume")
            ).scalars()
        )
    assert len(audit) == 1
    assert audit[0].actor == "user:admin-1"
    assert audit[0].actor_kind == "user"
    assert audit[0].resource == run_id


def test_a_second_resume_conflicts(api):
    client, factory = api
    _act_as(ADMIN)
    run_id = _make_run(factory, owner="alice", status="RECOVERABLE")
    assert client.post(f"/api/admin/embedding-runs/{run_id}/resume").status_code == 202
    second = client.post(f"/api/admin/embedding-runs/{run_id}/resume")
    assert second.status_code == 409


def test_a_model_change_conflicts(api):
    client, factory = api
    _act_as(ADMIN)
    run_id = _make_run(factory, owner="alice", status="RECOVERABLE", model="old-model")
    response = client.post(f"/api/admin/embedding-runs/{run_id}/resume")
    assert response.status_code == 409
    assert "embedding space" in response.json()["detail"]


def test_a_missing_run_is_a_404(api):
    client, _factory = api
    _act_as(ADMIN)
    assert client.post("/api/admin/embedding-runs/nope/resume").status_code == 404


def test_the_detail_reports_checkpoints_and_failures(api):
    client, factory = api
    _act_as(ADMIN)
    run_id = _make_run(factory, owner="alice")
    response = client.get(f"/api/admin/embedding-runs/{run_id}")
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["items"]["queued"] == 3
    assert "checkpoint" in run
    assert any(event["event"] == "run.created" for event in run["events"])


# -- cancel, reconcile and metrics -------------------------------------------


def test_an_administrator_can_cancel(api):
    client, factory = api
    _act_as(ADMIN)
    run_id = _make_run(factory, owner="alice")
    response = client.post(f"/api/admin/embedding-runs/{run_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_reconcile_is_enqueued_once(api):
    client, _factory = api
    _act_as(ADMIN)
    first = client.post("/api/admin/embeddings/reconcile")
    second = client.post("/api/admin/embeddings/reconcile")
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    assert second.json()["queued"] is False


def test_the_metrics_and_worker_health_are_administrator_views(api):
    client, _factory = api
    _act_as(ADMIN)
    metrics = client.get("/api/admin/jobs/metrics")
    assert metrics.status_code == 200
    body = metrics.json()
    assert {"queue", "workers", "breakers", "embedding"} <= set(body)
    assert "oldest_pending_age_seconds" in body["queue"]["items"]

    health = client.get("/api/admin/health/workers")
    assert health.status_code == 200
    assert {"workers", "queue"} <= set(health.json())

    _act_as(ALICE)
    assert client.get("/api/admin/jobs/metrics").status_code == 403

# -- the platform-wide run listing (WS-18 follow-up) --------------------------


def test_the_admin_listing_covers_every_type_of_run(api):
    """A queued refresh or reconciliation must not be invisible.

    The embedding-runs listing answers the recovery question for one kind of
    work. An administrator who queues a reconciliation and then sees nothing
    in the list concludes the button did nothing — the run has to be listed,
    of whatever type it is.
    """
    client, factory = api
    _act_as(ADMIN)
    embedding = _make_run(factory, owner="alice", job_type="embedding", items=2)
    refresh = _make_run(factory, owner=None, job_type="refresh", items=1)
    reconcile = _make_run(factory, owner=None, job_type="reconcile", items=1)

    everything = client.get("/api/admin/runs")
    assert everything.status_code == 200
    ids = {run["id"] for run in everything.json()["runs"]}
    assert {embedding, refresh, reconcile} <= ids

    # The embedding-only listing keeps its meaning.
    only_embeddings = client.get("/api/admin/embedding-runs")
    assert {run["id"] for run in only_embeddings.json()["runs"]} == {embedding}

    # Filters are applied by the data layer.
    filtered = client.get("/api/admin/runs?job_type=reconcile")
    assert [run["id"] for run in filtered.json()["runs"]] == [reconcile]
    queued = client.get("/api/admin/runs?status=QUEUED")
    assert {run["id"] for run in queued.json()["runs"]} == {embedding, refresh, reconcile}


def test_any_runs_detail_is_readable_but_only_by_an_administrator(api):
    client, factory = api
    run_id = _make_run(factory, owner=None, job_type="reconcile", items=1)

    _act_as(ALICE)
    assert client.get(f"/api/admin/runs/{run_id}").status_code == 403
    assert client.get("/api/admin/runs").status_code == 403

    _act_as(ADMIN)
    response = client.get(f"/api/admin/runs/{run_id}")
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["id"] == run_id
    assert run["job_type"] == "reconcile"
    assert any(event["event"] == "run.created" for event in run["events"])

    assert client.get("/api/admin/runs/no-such-run").status_code == 404
