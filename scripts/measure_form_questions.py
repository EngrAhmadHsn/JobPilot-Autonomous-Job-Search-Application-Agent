"""Measure the questions the boards actually ask (WS-25b §9.3).

Walks the Greenhouse boards in the registry, fetches each job's
application form schema, and records every question in ``form_questions``
with its frequency.

Why this exists: the profile asks the user a **guessed** set of fields,
while the boards state what they actually ask. A probe on 2026-11-11
found **310 distinct labels across 12 boards**, with **10 of the 22
most-asked labels unclassified — 51% of occurrences**. This script turns
that one-off probe into a stored, repeatable measurement the console can
read.

**It is an operator command, not part of the nightly refresh.** It costs
one request per job, so it runs deliberately, with the same per-host
pacing the refresh uses.

Usage::

    python scripts/measure_form_questions.py                 # 8 jobs/board
    python scripts/measure_form_questions.py --per-board 25
    python scripts/measure_form_questions.py --board stripe --board figma
    python scripts/measure_form_questions.py --dry-run

Only Greenhouse publishes a key-less form schema; the other providers'
forms are behind authentication or absent entirely, so they are skipped
with a note rather than silently omitted.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.applications.greenhouse_forms import build_form_schema
from src.applications.questions import classify_text
from src.db.form_questions import ObservedQuestion, record_questions
from src.jobs.board_health import registry_slugs
from src.jobs.http_client import SourceError, create_client, guarded_get


def _boards(explicit: list[str] | None) -> list[str]:
    """The boards to sweep: the operator's choice, or the registry."""
    if explicit:
        return explicit
    registered = registry_slugs("greenhouse")
    if registered:
        return registered
    from src.config.settings import get_settings

    return get_settings().greenhouse_boards


async def _sweep_board(
    client,
    board: str,
    *,
    per_board: int,
    dry_run: bool,
) -> tuple[int, int]:
    """Record one board's questions. Returns (jobs read, questions seen)."""
    listing_url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    try:
        response = await guarded_get(client, listing_url)
        payload = response.json()
    except (SourceError, ValueError) as exc:
        print(f"  {board}: SKIP ({type(exc).__name__}: {str(exc)[:80]})")
        return 0, 0

    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list) or not jobs:
        print(f"  {board}: SKIP (no jobs in the payload)")
        return 0, 0

    observations: list[ObservedQuestion] = []
    jobs_read = 0
    for job in jobs[:per_board]:
        job_id = job.get("id")
        if job_id is None:
            continue
        detail_url = (
            f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}?questions=true"
        )
        try:
            detail = await guarded_get(client, detail_url)
            schema = build_form_schema(detail.json())
        except (SourceError, ValueError):
            # One job's schema failing must not stop the board.
            continue
        jobs_read += 1
        for question in schema.all_questions:
            observations.append(
                ObservedQuestion(
                    label=question.label,
                    board=board,
                    ats="greenhouse",
                    field_name=question.field_names[0] if question.field_names else None,
                    field_type=question.field_types[0] if question.field_types else None,
                    required=question.required,
                    block=question.block,
                    category=classify_text(question.label).category.value,
                )
            )

    if not observations:
        print(f"  {board}: no questions published")
        return jobs_read, 0

    if dry_run:
        print(f"  {board}: {jobs_read} jobs, {len(observations)} questions (dry run)")
    else:
        written = record_questions(observations)
        print(f"  {board}: {jobs_read} jobs, {written} questions recorded")
    return jobs_read, len(observations)


async def main_async(args) -> int:
    boards = _boards(args.board)
    if not boards:
        print("No Greenhouse boards configured. Set GREENHOUSE_BOARDS or seed the registry.")
        return 1

    print(f"Sweeping {len(boards)} Greenhouse board(s), {args.per_board} jobs each")
    if args.dry_run:
        print("DRY RUN — nothing is written\n")

    total_jobs = 0
    total_questions = 0
    async with create_client() as client:
        for board in boards:
            jobs, questions = await _sweep_board(
                client, board, per_board=args.per_board, dry_run=args.dry_run
            )
            total_jobs += jobs
            total_questions += questions

    print()
    print(f"Jobs read      : {total_jobs}")
    print(f"Questions seen : {total_questions}")
    if not args.dry_run and total_questions:
        from src.db.form_questions import question_gaps

        # Without a profile every question reads as uncovered, which is
        # misleading in a summary meant to show the *actionable* gaps.
        # The operator's first profile is the reference: it is the one the
        # console would show the gaps against.
        profile = _reference_profile()
        gaps = question_gaps(profile, limit=15)
        if gaps:
            print()
            source = "the reference profile" if profile is not None else "any profile (none found)"
            print(f"Most-asked questions not answered by {source}:")
            print(f"  {'seen':>6}  {'boards':>6}  {'coverage':<16} label")
            for gap in gaps:
                print(
                    f"  {gap.times_seen:>6}  {gap.boards:>6}  {gap.coverage:<16} {gap.label[:70]}"
                )
    return 0


def _reference_profile():
    """The profile the gap summary is computed against, if there is one."""
    try:
        from src.db.profiles import CandidateProfileDB, profile_from_row
        from src.db.session import SessionLocal

        with SessionLocal() as session:
            row = session.query(CandidateProfileDB).first()
            return profile_from_row(row) if row is not None else None
    except Exception:  # noqa: BLE001 - a summary must not fail without a profile
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--board",
        action="append",
        metavar="TOKEN",
        help="A Greenhouse board token to sweep (repeatable). Defaults to the registry.",
    )
    parser.add_argument(
        "--per-board",
        type=int,
        default=8,
        metavar="N",
        help="How many jobs per board to read (default 8).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and classify, but write nothing.",
    )
    args = parser.parse_args()
    if args.per_board < 1:
        parser.error("--per-board must be at least 1")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
