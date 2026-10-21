"""Serve the local fake ATS, so the application flow can be driven by hand.

The browser layer is exercised against a **local fake ATS** — a small
applicant-tracking system that serves the page variants the adapter has to
survive (a plain form, a multi-page wizard, widget controls, an unknown
question, a rejected form, a challenge, a required upload). It lives in
``tests/fixtures/fake_ats/`` because the tests drive it; this script serves
the same pages so an operator can drive the flow from the README.

Nothing here is a test. It is a **development-time** server, in the same
sense as ``scripts/refresh_jobs.py``: it is how you see the system work, not
part of the runtime.

Usage:
    python scripts/serve_fake_ats.py                 # http://127.0.0.1:8901
    python scripts/serve_fake_ats.py --port 9000

Then, with the API running:

    curl -X POST http://localhost:8000/api/applications/prepare \\
      -H "Content-Type: application/json" \\
      -d '{"job_title": "AI Engineer", "company_name": "Acme",
           "job_url": "http://127.0.0.1:8901/basic",
           "candidate_name": "Ada Lovelace", "email": "ada@example.com",
           "phone": "+44 20 7946 0000"}'
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import uvicorn

from tests.fixtures.fake_ats.variants import create_app

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8901

# The pages the fake ATS serves. They are the page variants the WS-08
# browser layer is tested against; the README demo uses /basic.
PAGES = (
    ("/basic", "a plain application form"),
    ("/multipage", "a three-step wizard"),
    ("/widgets", "a select, a checkbox and a radio group"),
    ("/unknown", "a question the candidate's evidence cannot answer"),
    ("/validation", "a form the server rejects, and keeps rejecting"),
    ("/validation-recoverable", "a form the server rejects once, then accepts"),
    ("/captcha", "a challenge — the flow must stop, not guess"),
    ("/upload-required", "a form that needs a file"),
    ("/submitted", "an already-confirmed page"),
    ("/error", "a page the server fails on"),
    ("/session", "a page that shows and sets a cookie"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help="interface to bind (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="port to bind (default: 8901)"
    )
    args = parser.parse_args()

    app = create_app()
    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level="warning",
        lifespan="off",
        access_log=False,
    )

    print(f"Fake ATS on http://{args.host}:{args.port}")
    for path, description in PAGES:
        print(f"  {path:<18} {description}")
    print("\nCtrl-C to stop.")

    uvicorn.Server(config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
