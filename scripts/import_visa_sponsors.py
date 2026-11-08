"""Import an official visa-sponsorship register into the database (WS-22).

Two registers are supported, and both are downloaded from the government
that publishes them (this script never fetches anything itself — the file
is yours to download and check):

- **USCIS H-1B Employer Data Hub** (US). Each fiscal year is one CSV export
  with per-employer approval and denial counts. Download from
  https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub
- **UK Home Office** register of licensed sponsors (Skilled Worker and
  Temporary Worker). Download the "Worker and Temporary Worker" CSV from
  https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers

The import is idempotent per ``(source, year)``: re-running it with a
corrected file replaces that year's rows instead of duplicating them. It
prints what it read, so an operator can compare against the file's own
documentation before trusting a badge.

Usage:
    python scripts/import_visa_sponsors.py --uscis path/to/h1b_datahubexport-2024.csv
    python scripts/import_visa_sponsors.py --uk path/to/2026-11-08_-_Worker_and_Temporary_Worker.csv
    python scripts/import_visa_sponsors.py --uscis a.csv --uk b.csv --stats
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.config.settings import get_settings
from src.db.sponsors import SOURCE_UK, SOURCE_USCIS, VisaSponsorDB
from src.matching.sponsors import import_sponsor_csv, lookup_company

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("import_visa_sponsors")


def _session():
    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def _stats(session) -> None:
    rows = session.execute(
        select(
            VisaSponsorDB.source,
            VisaSponsorDB.year,
            func.count(VisaSponsorDB.id),
        )
        .group_by(VisaSponsorDB.source, VisaSponsorDB.year)
        .order_by(VisaSponsorDB.source, VisaSponsorDB.year)
    ).all()
    if not rows:
        print("The register table is empty: every listing reports sponsor_status=no_data.")
        return
    for source, year, count in rows:
        print(f"  {source} {year or '(no year)'}: {count} employer(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uscis", type=Path, default=None, help="USCIS H-1B Data Hub CSV export")
    parser.add_argument("--uk", type=Path, default=None, help="UK Home Office sponsor register CSV")
    parser.add_argument(
        "--database",
        default=None,
        help="Database URL override (defaults to DATABASE_URL)",
    )
    parser.add_argument(
        "--check",
        default=None,
        help="Print the verdict for one company name after importing",
    )
    args = parser.parse_args()

    if args.uscis is None and args.uk is None:
        parser.error("Nothing to do: pass --uscis and/or --uk")

    if args.database:
        import os

        os.environ["DATABASE_URL"] = args.database

    session = _session()
    try:
        for source, path in ((SOURCE_USCIS, args.uscis), (SOURCE_UK, args.uk)):
            if path is None:
                continue
            if not path.is_file():
                print(f"Not found: {path}", file=sys.stderr)
                return 2
            report = import_sponsor_csv(session, source, path)
            print(report.describe())

        print("Register contents:")
        _stats(session)

        if args.check:
            verdict = lookup_company(session, args.check)
            print(f"\n{args.check!r}: {verdict.status}")
            if verdict.note:
                print(f"  {verdict.note}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
