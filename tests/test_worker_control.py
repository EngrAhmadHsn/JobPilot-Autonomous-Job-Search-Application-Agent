"""WS-20 follow-up: starting and stopping workers, and the cooperative stop.

Two things are checked: the **queue's** cooperative stop (a heartbeat must not
erase a stop request, and a worker must act on it), and the **supervisor's**
guards (disabled, over the limit, bad id) plus the fixed command it builds.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.runs import queue, supervisor
from src.runs.state import WORKER_RUNNING, WORKER_STOPPING
from src.runs.worker import Worker


def factory(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'w.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


# -- the cooperative stop in the queue ---------------------------------------


def test_a_heartbeat_does_not_erase_a_stop_request(tmp_path):
    f = factory(tmp_path)
    with f() as session:
        queue.register_worker(session, worker_id="w1")
        session.commit()
    with f() as session:
        assert queue.request_worker_stop(session, worker_id="w1") is True
    with f() as session:
        assert queue.read_worker_status(session, worker_id="w1") == WORKER_STOPPING
        # A heartbeat from the still-running worker must not reset it.
        queue.heartbeat_worker(session, worker_id="w1")
    with f() as session:
        assert queue.read_worker_status(session, worker_id="w1") == WORKER_STOPPING


def test_a_normal_heartbeat_keeps_a_worker_running(tmp_path):
    f = factory(tmp_path)
    with f() as session:
        queue.register_worker(session, worker_id="w1")
        queue.heartbeat_worker(session, worker_id="w1")
    with f() as session:
        assert queue.read_worker_status(session, worker_id="w1") == WORKER_RUNNING


def test_requesting_a_stop_for_an_unknown_worker_changes_nothing(tmp_path):
    f = factory(tmp_path)
    assert queue.request_worker_stop(f(), worker_id="nobody") is False


def test_the_worker_stops_itself_when_it_observes_the_flag(tmp_path):
    f = factory(tmp_path)
    worker = Worker(worker_id="w-selfstop", session_factory=f, sleep=lambda _s: None)
    worker.register()
    with f() as session:
        queue.request_worker_stop(session, worker_id="w-selfstop")

    assert worker.stopping is False
    worker.run_once()  # heartbeats, sees "stopping", sets its own flag
    assert worker.stopping is True


# -- the supervisor's guards --------------------------------------------------


def _settings(**overrides):
    base = {"worker_control_enabled": True, "worker_max_concurrent": 2, "data_dir": "/tmp/ws20-data"}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_start_is_refused_when_control_is_disabled(monkeypatch):
    monkeypatch.setattr(supervisor, "_settings", lambda: _settings(worker_control_enabled=False))
    with pytest.raises(supervisor.WorkerControlDisabled):
        supervisor.start_worker()


def test_start_is_refused_at_the_limit(monkeypatch):
    monkeypatch.setattr(supervisor, "_settings", lambda: _settings(worker_max_concurrent=2))
    monkeypatch.setattr(supervisor, "_running_worker_count", lambda: 2)
    with pytest.raises(supervisor.WorkerLimitReached):
        supervisor.start_worker()


def test_a_bad_worker_id_is_rejected(monkeypatch):
    monkeypatch.setattr(supervisor, "_settings", lambda: _settings())
    monkeypatch.setattr(supervisor, "_running_worker_count", lambda: 0)
    for bad in ("../escape", "has space", "", "x" * 65):
        with pytest.raises(ValueError):
            supervisor.start_worker(worker_id=bad)


def test_start_builds_the_fixed_command(monkeypatch, tmp_path):
    """The command is the app's own worker module — never shell, never input."""
    captured: dict = {}

    class FakePopen:
        def __init__(self, command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            self.pid = 4242

    monkeypatch.setattr(supervisor, "_settings", lambda: _settings(data_dir=str(tmp_path)))
    monkeypatch.setattr(supervisor, "_running_worker_count", lambda: 0)
    monkeypatch.setattr(supervisor.subprocess, "Popen", FakePopen)

    handle = supervisor.start_worker(worker_id="console-abc123")

    assert handle.worker_id == "console-abc123"
    assert handle.pid == 4242
    command = captured["command"]
    assert command[1:4] == ["-m", "src.runs.worker", "--worker-id"]
    assert command[4] == "console-abc123"
    assert captured["kwargs"]["cwd"] == str(supervisor.REPO_ROOT)
    # No shell: the command is an argv list, and it is the only thing spawned.
    assert "shell" not in captured["kwargs"] or captured["kwargs"]["shell"] is False


def test_stop_is_refused_when_control_is_disabled(monkeypatch):
    monkeypatch.setattr(supervisor, "_settings", lambda: _settings(worker_control_enabled=False))
    with pytest.raises(supervisor.WorkerControlDisabled):
        supervisor.stop_worker(worker_id="w1")
