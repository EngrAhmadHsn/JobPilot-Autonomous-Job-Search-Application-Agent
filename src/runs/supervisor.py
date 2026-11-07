"""Starting and stopping worker processes from the API (WS-20 follow-up).

WS-18 deliberately kept the worker **out** of the API process: different
lifetime, different failure mode, supervised by the deployment. That is still
how production runs. But an operator watching the Administration screen with a
queue that is not moving should not have to leave it, find a terminal and paste
a command — so this module gives the API a *bounded* ability to start and stop
workers, and the console a button.

**The bound is the safety.** This is an HTTP endpoint that spawns processes, so
three things are true by construction:

- it is **off unless enabled** (``WORKER_CONTROL_ENABLED``; on in development,
  off in production by default) and the endpoint refuses when it is off;
- it spawns **one fixed command** built from ``sys.executable`` and the
  application's own worker module — no shell, no user-supplied arguments, and a
  worker id restricted to a safe charset;
- it refuses once ``WORKER_MAX_CONCURRENT`` workers are running.

**Stopping is cooperative.** The API never kills a process it did not spawn
(and cannot, after a restart). Stop sets a flag in the worker's heartbeat row,
which the worker reads on its next heartbeat and turns into a clean shutdown
that finishes the current batch and releases its leases. That reaches a worker
started by anyone, on any host sharing the database.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "SpawnedWorker",
    "WorkerControlDisabled",
    "WorkerLimitReached",
    "spawned_workers",
    "start_worker",
    "stop_worker",
]

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A worker id is a label, not input: letters, digits, dash, dot, underscore.
_WORKER_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class WorkerControlDisabled(RuntimeError):
    """The API is not configured to manage worker processes."""


class WorkerLimitReached(RuntimeError):
    """The configured maximum number of concurrent workers is already running."""


@dataclass
class SpawnedWorker:
    """A worker process this API started (in-process bookkeeping only)."""

    worker_id: str
    pid: int
    started_at: float
    log_path: str | None = None


@dataclass
class _Registry:
    workers: dict[str, SpawnedWorker] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_REGISTRY = _Registry()


def _settings():
    from src.config.settings import get_settings

    return get_settings()


def _validate_worker_id(worker_id: str) -> str:
    if not _WORKER_ID_RE.match(worker_id):
        raise ValueError("worker id must be 1-64 characters of letters, digits, '.', '_' or '-'")
    return worker_id


def spawned_workers() -> list[SpawnedWorker]:
    """The workers this API process started and has not forgotten."""
    with _REGISTRY.lock:
        # Forget processes that have exited, so the count stays honest.
        alive: dict[str, SpawnedWorker] = {}
        for worker_id, handle in _REGISTRY.workers.items():
            if _process_alive(handle.pid):
                alive[worker_id] = handle
        _REGISTRY.workers = alive
        return list(alive.values())


def _process_alive(pid: int) -> bool:
    """Whether a pid is still running (best effort, no signal sent)."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except Exception:  # noqa: BLE001 - liveness is best-effort
        return True
    return True


def _running_worker_count() -> int:
    """How many workers are actually alive, not just spawned here.

    The database is the source of truth for liveness (a worker may have been
    started outside the API), so the bound counts heartbeating workers rather
    than only this process's children.
    """
    try:
        from src.db.session import SessionLocal
        from src.runs import queue

        with SessionLocal() as session:
            health = queue.worker_health(session)
        return int(health.get("healthy", 0))
    except Exception:
        logger.exception("Counting running workers failed; falling back to spawned children")
        return len(spawned_workers())


def start_worker(*, worker_id: str | None = None) -> SpawnedWorker:
    """Start one worker process; refuse when disabled or already at the limit.

    Raises:
        WorkerControlDisabled: when ``WORKER_CONTROL_ENABLED`` is off.
        WorkerLimitReached: when ``WORKER_MAX_CONCURRENT`` are already running.
        ValueError: when the supplied worker id is not a safe label.
    """
    settings = _settings()
    if not settings.worker_control_enabled:
        raise WorkerControlDisabled(
            "Starting workers from the API is disabled "
            "(set WORKER_CONTROL_ENABLED=true to allow it)."
        )
    limit = settings.worker_max_concurrent
    if _running_worker_count() >= limit:
        raise WorkerLimitReached(f"The worker limit of {limit} is already running; stop one first.")

    if worker_id is None:
        resolved_id = f"{_hostname()}-{uuid.uuid4().hex[:6]}"
    else:
        resolved_id = _validate_worker_id(worker_id)

    log_dir = Path(settings.data_dir) / "workers"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{resolved_id}.log"

    command = [sys.executable, "-m", "src.runs.worker", "--worker-id", resolved_id]
    creationflags = 0
    popen_kwargs: dict = {
        "cwd": str(REPO_ROOT),
        "stdout": open(log_path, "ab"),  # noqa: SIM115 - the child owns the fd
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":  # pragma: no cover - exercised on Windows
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        popen_kwargs["creationflags"] = creationflags
    else:
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(command, **popen_kwargs)
    handle = SpawnedWorker(
        worker_id=resolved_id, pid=process.pid, started_at=time.time(), log_path=str(log_path)
    )
    with _REGISTRY.lock:
        _REGISTRY.workers[resolved_id] = handle
    logger.info("Started worker %s as pid %d", resolved_id, process.pid)
    return handle


def stop_worker(*, worker_id: str) -> bool:
    """Ask one worker to finish its batch and exit; True when it was running.

    Cooperative: the request is written to the worker's heartbeat row and the
    worker acts on it. Nothing is signalled, so a worker started by a service
    manager is stopped the same way as one started here.
    """
    settings = _settings()
    if not settings.worker_control_enabled:
        raise WorkerControlDisabled(
            "Stopping workers from the API is disabled "
            "(set WORKER_CONTROL_ENABLED=true to allow it)."
        )
    from src.db.session import SessionLocal
    from src.runs import queue

    with SessionLocal() as session:
        changed = queue.request_worker_stop(session, worker_id=_validate_worker_id(worker_id))
    if changed:
        logger.info("Asked worker %s to stop", worker_id)
    return changed


def _hostname() -> str:
    import socket

    return socket.gethostname()
