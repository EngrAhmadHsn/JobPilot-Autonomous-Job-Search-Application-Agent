"""WS-18 · liveness, readiness and worker health.

The API answering a request says nothing about whether the background worker
is alive, and a provider outage says nothing about whether the API can serve
a search. These tests pin the separation:

- ``/api/health/live`` is process liveness and never touches the database;
- ``/api/health/ready`` fails when the database does, and reports the worker
  without failing for a provider;
- the worker's own health is an administrator view and goes stale on its own.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from src.auth.routes import current_active_user
from src.db.runs import WorkerHeartbeatDB
from src.db.session import get_db
from src.db.users import UserDB
from src.main import app
from src.runs import queue
from src.runs.state import utcnow


@pytest.fixture()
def api(_suite_database):
    factory = sessionmaker(bind=_suite_database, autoflush=False)
    with factory() as session:
        session.query(WorkerHeartbeatDB).delete()
        session.commit()

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), factory
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(current_active_user, None)


def _admin() -> UserDB:
    return UserDB(
        id="admin-health",
        email="admin-health@example.com",
        hashed_password="!",
        is_active=True,
        is_superuser=True,
        is_verified=True,
    )


def test_liveness_does_not_touch_the_database(api, monkeypatch):
    client, _factory = api

    def boom():
        raise AssertionError("liveness must not open a session")

    monkeypatch.setattr("src.db.session.SessionLocal", boom)
    response = client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json()["check"] == "liveness"


def test_readiness_reports_the_database_and_the_worker(api):
    client, _factory = api
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    assert "workers" in body


def test_readiness_is_503_when_the_database_is_gone(api, monkeypatch):
    client, _factory = api

    class BrokenFactory:
        def __call__(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr("src.db.session.SessionLocal", BrokenFactory())
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["checks"]["database"].startswith("error:")


def test_the_worker_health_goes_stale(api):
    client, factory = api
    with factory() as session:
        queue.register_worker(session, worker_id="worker-1")

    app.dependency_overrides[current_active_user] = _admin
    healthy = client.get("/api/admin/health/workers").json()
    assert healthy["workers"]["healthy"] == 1
    assert healthy["workers"]["workers"][0]["healthy"] is True

    with factory() as session:
        row = session.get(WorkerHeartbeatDB, "worker-1")
        row.last_heartbeat_at = utcnow() - timedelta(hours=1)
        session.commit()
    stale = client.get("/api/admin/health/workers").json()
    assert stale["workers"]["healthy"] == 0
    assert stale["workers"]["workers"][0]["healthy"] is False


def test_a_stale_running_row_reports_as_crashed_not_running(api):
    """A worker killed without a chance to exit leaves its row at "running".

    The console read that raw value and told the operator a dead process was
    running — the reported defect. The effective status is derived from the
    heartbeat age, and the raw value is kept beside it so nothing is hidden.
    """
    client, factory = api
    with factory() as session:
        queue.register_worker(session, worker_id="worker-killed")
        row = session.get(WorkerHeartbeatDB, "worker-killed")
        row.last_heartbeat_at = utcnow() - timedelta(minutes=30)
        # The row literally still claims to be running: the process died
        # before it could write anything else.
        row.status = "running"
        session.commit()

    app.dependency_overrides[current_active_user] = _admin
    body = client.get("/api/admin/health/workers").json()
    entry = body["workers"]["workers"][0]

    assert entry["status"] == "crashed"
    assert entry["reported_status"] == "running"
    assert entry["stale"] is True
    assert entry["healthy"] is False
    assert body["workers"]["healthy"] == 0


def test_a_fresh_running_row_reports_as_running(api):
    """The derivation must not cry crash on a worker that is merely working:
    a batch can go minutes without a heartbeat update."""
    client, factory = api
    with factory() as session:
        queue.register_worker(session, worker_id="worker-live")
        row = session.get(WorkerHeartbeatDB, "worker-live")
        row.last_heartbeat_at = utcnow() - timedelta(seconds=5)
        session.commit()

    app.dependency_overrides[current_active_user] = _admin
    entry = client.get("/api/admin/health/workers").json()["workers"]["workers"][0]

    assert entry["status"] == "running"
    assert entry["reported_status"] == "running"
    assert entry["stale"] is False
    assert entry["healthy"] is True


def test_a_clean_stop_is_not_reclassified(api):
    """A worker that exited cleanly said so; age does not override its word."""
    client, factory = api
    with factory() as session:
        queue.register_worker(session, worker_id="worker-done")
        row = session.get(WorkerHeartbeatDB, "worker-done")
        row.status = "stopped"
        row.last_heartbeat_at = utcnow() - timedelta(hours=2)
        session.commit()

    app.dependency_overrides[current_active_user] = _admin
    entry = client.get("/api/admin/health/workers").json()["workers"]["workers"][0]

    assert entry["status"] == "stopped"
    assert entry["healthy"] is False


def test_worker_health_is_administrator_only(api):
    client, _factory = api
    ordinary = UserDB(
        id="ordinary",
        email="ordinary@example.com",
        hashed_password="!",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    app.dependency_overrides[current_active_user] = lambda: ordinary
    assert client.get("/api/admin/health/workers").status_code == 403
