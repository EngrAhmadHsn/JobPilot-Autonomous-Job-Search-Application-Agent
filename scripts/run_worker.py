"""Run the durable background worker (WS-18).

The worker is a **separate, supervised process**. It is not started by the
API, for the same reason the API does not run the refresh inside a request:
the two have different lifetimes and different failure modes.

    python scripts/run_worker.py                # run until SIGINT/SIGTERM
    python scripts/run_worker.py --once         # drain due work, then exit

A deployment supervises it with systemd, a container or a Windows service;
see docs/RUNBOOK.md §4.4. Run exactly one worker unless Chroma is deployed
in a mode that supports concurrent writers — the code keeps a single-writer
policy for the vector store.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.runs.worker import main

if __name__ == "__main__":
    sys.exit(main())
