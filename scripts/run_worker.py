"""Run the durable background worker (WS-18).

The worker is a **separate, supervised process**. It is not started by the
API, for the same reason the API does not run the refresh inside a request:
the two have different lifetimes and different failure modes.

    env\\Scripts\\python.exe scripts\\run_worker.py            # until Ctrl-C
    env\\Scripts\\python.exe scripts\\run_worker.py --once     # drain due work, then exit

Use the project's interpreter (``env\\Scripts\\python.exe`` on Windows). A bare
``python`` may be a different installation — the system Python, or a conda base
— that does not have this project's dependencies, and the failure then reads as
a missing package rather than the wrong interpreter. This script says which one
it is when that happens.

A deployment supervises the worker with systemd, a container or a Windows
service; see docs/RUNBOOK.md §4.4. The console's Administration screen can also
start and stop workers when ``WORKER_CONTROL_ENABLED`` is on — on in
development, off in production by default — bounded by ``WORKER_MAX_CONCURRENT``.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

try:
    from src.runs.worker import main
except ModuleNotFoundError as exc:  # pragma: no cover - depends on the environment
    missing = getattr(exc, "name", None) or "a project dependency"
    separator = "\\" if sys.platform == "win32" else "/"
    sys.stderr.write(
        f"\nThe worker could not start: {missing!r} is not available to this Python.\n"
        f"  running:  {sys.executable}\n"
        "This is almost always the wrong interpreter. Use the project's virtual\n"
        "environment, for example:\n"
        f"  env{separator}Scripts{separator}python.exe scripts{separator}run_worker.py\n\n"
    )
    raise SystemExit(2) from exc

if __name__ == "__main__":
    sys.exit(main())
