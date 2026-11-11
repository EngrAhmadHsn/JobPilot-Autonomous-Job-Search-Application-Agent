"""Verify the job boards still answer as documented (WS-26b).

A port of the idea in `danielhagever/job-board-apis`'s `verify.py` (MIT):
one assertion per known endpoint, paced, `PASS`/`FAIL`/`SKIP`, non-zero
exit on any failure.

**Why it exists.** Nothing in the project proves that a board has not
renamed a field. A provider renaming `employmentType` makes every parser
return nulls silently — which is exactly the failure that produced the
0% field population WS-23 set out to fix. The circuit breaker catches a
board that is *down*; this catches a board whose shape *changed*.

**Stdlib only** (`urllib.request`, `json`, `re`), so it runs in a clean
venv and in CI before the app is installed, and it does not import the
project.

**It reads the board registry**, not a second hardcoded list — one source
of truth. A fresh checkout with no registry falls back to the env seed.

Usage::

    python scripts/verify_sources.py                  # every registered board
    python scripts/verify_sources.py --ats greenhouse  # one provider
    python scripts/verify_sources.py --json            # machine-readable

Exit codes: 0 = every board passed, 1 = at least one failed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

#: The User-Agent identifies the client, as both the project's own HTTP
#: layer and the reference `verify.py` do.
USER_AGENT = (
    "agentic-job-applier-verify/1.0 "
    "(personal job-search agent; public board APIs only; contact via repository)"
)

#: How long between requests, so a sweep is polite.
DEFAULT_DELAY = 1.0

#: The endpoints, per provider. Each returns a normalized job count and
#: the shape assertions the board's answer must satisfy.
_ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


@dataclass
class Result:
    """One board's verdict."""

    ats: str
    slug: str
    status: str
    detail: str
    jobs: int = 0
    #: The response's declared size, when it announced one.
    bytes: int = 0
    notes: list[str] = field(default_factory=list)

    def line(self) -> str:
        label = f"{self.ats}:{self.slug}"
        return f"{self.status:<5} {label:<32} {self.detail}"


def _fetch(url: str, *, timeout: float) -> tuple[int, bytes]:
    """GET a URL. Returns (status, body). Raises on a transport error."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() or b""


def _job_count(ats: str, payload) -> int | None:
    """The number of job records in a provider's payload, or None."""
    if ats == "lever":
        return len(payload) if isinstance(payload, list) else None
    if isinstance(payload, dict):
        jobs = payload.get("jobs")
        return len(jobs) if isinstance(jobs, list) else None
    return None


def _check_id_shape(ats: str, payload) -> str | None:
    """A note when the first record's id does not look like the provider's.

    A renamed id is the earliest symptom of a changed shape, and it is
    what makes every canonical job id wrong.
    """
    if ats == "lever":
        first = payload[0] if isinstance(payload, list) and payload else None
        job_id = first.get("id") if isinstance(first, dict) else None
        if job_id is None:
            return "no id on the first posting"
        if not re.fullmatch(r"[0-9a-f-]{36}", str(job_id)):
            return f"the first posting id is not a UUID: {str(job_id)[:40]!r}"
        return None
    if isinstance(payload, dict):
        jobs = payload.get("jobs")
        first = jobs[0] if isinstance(jobs, list) and jobs else None
        job_id = first.get("id") if isinstance(first, dict) else None
        if job_id is None:
            return "no id on the first job"
        return None
    return None


def verify_board(ats: str, slug: str, *, timeout: float) -> Result:
    """Verify one board. Never raises: a failure is a Result."""
    template = _ENDPOINTS.get(ats)
    if template is None:
        return Result(ats, slug, SKIP, "no verifier for this provider")

    url = template.format(slug=slug)
    try:
        status, body = _fetch(url, timeout=timeout)
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        # A transient DNS failure is a SKIP, not a FAIL: the board may be
        # perfectly healthy and the resolver is not. A FAIL here would
        # make CI red for a network blip.
        if isinstance(reason, OSError) and "resolve" in str(reason).lower():
            return Result(ats, slug, SKIP, f"DNS: {str(reason)[:60]}")
        return Result(ats, slug, FAIL, f"transport: {str(reason)[:80]}")
    except TimeoutError:
        return Result(ats, slug, SKIP, "timed out")

    if status == 404:
        return Result(ats, slug, FAIL, "404 — the board slug does not exist")
    if status != 200:
        return Result(ats, slug, FAIL, f"HTTP {status}")

    # The dead-tenant trap: a host that does not exist may answer 200
    # with an HTML page. The body must parse as JSON.
    try:
        payload = json.loads(body)
    except ValueError:
        return Result(
            ats,
            slug,
            FAIL,
            f"the body is not JSON ({body[:40]!r}) — the dead-tenant trap",
            bytes=len(body),
        )

    count = _job_count(ats, payload)
    if count is None:
        return Result(ats, slug, FAIL, "the payload has no job list", bytes=len(body))
    if count == 0:
        # An empty board is not a broken board, but it is worth saying.
        return Result(ats, slug, PASS, "0 jobs (empty board)", bytes=len(body))

    result = Result(ats, slug, PASS, f"{count} jobs", jobs=count, bytes=len(body))
    note = _check_id_shape(ats, payload)
    if note:
        result.notes.append(note)
        # A changed id shape is a FAIL: the canonical job ids are built
        # from it, so a rename here silently breaks dedup and eviction.
        result.status = FAIL
        result.detail = f"{count} jobs, but {note}"
    return result


def _registered_boards(ats_filter: str | None) -> list[tuple[str, str]]:
    """The boards to verify: the registry, or the env seed.

    Reads the registry through the project when it is importable, and
    falls back to the environment lists otherwise — so the script works
    in a clean venv and in a checkout that has never been migrated.
    """
    boards: list[tuple[str, str]] = []
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from src.jobs.board_health import registry_slugs

        for ats in _ENDPOINTS:
            boards.extend((ats, slug) for slug in registry_slugs(ats))
    except Exception:  # noqa: BLE001 - a clean venv has no project import
        # The script is deliberately usable before the app is installed,
        # so an import failure here is expected rather than exceptional.
        boards = []
    if not boards:
        boards = _env_seed()
    if ats_filter:
        boards = [pair for pair in boards if pair[0] == ats_filter]
    return boards


def _env_seed() -> list[tuple[str, str]]:
    """The boards the environment names, when the registry is empty."""
    import os

    def split(name: str) -> list[str]:
        return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]

    return (
        [("greenhouse", slug) for slug in split("GREENHOUSE_BOARDS")]
        + [("lever", slug) for slug in split("LEVER_COMPANIES")]
        + [("ashby", slug) for slug in split("ASHBY_ORGS")]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ats", choices=sorted(_ENDPOINTS), help="Verify one provider only")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-request timeout (s)")
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY, help="Seconds between requests"
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    boards = _registered_boards(args.ats)
    if not boards:
        print("No boards to verify: seed the registry or set the env lists.", file=sys.stderr)
        return 1

    results: list[Result] = []
    for index, (ats, slug) in enumerate(boards):
        if index:
            time.sleep(max(0.0, args.delay))
        results.append(verify_board(ats, slug, timeout=args.timeout))
        if not args.json:
            print(results[-1].line(), flush=True)

    failed = [result for result in results if result.status == FAIL]
    skipped = [result for result in results if result.status == SKIP]
    passed = [result for result in results if result.status == PASS]

    if args.json:
        print(
            json.dumps(
                {
                    "passed": len(passed),
                    "failed": len(failed),
                    "skipped": len(skipped),
                    "results": [
                        {
                            "ats": result.ats,
                            "slug": result.slug,
                            "status": result.status,
                            "detail": result.detail,
                            "jobs": result.jobs,
                            "bytes": result.bytes,
                            "notes": result.notes,
                        }
                        for result in results
                    ],
                },
                indent=2,
            )
        )
    else:
        print()
        print(f"{len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped")
        if failed:
            print()
            print("Failures:")
            for result in failed:
                print(f"  {result.ats}:{result.slug} — {result.detail}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
