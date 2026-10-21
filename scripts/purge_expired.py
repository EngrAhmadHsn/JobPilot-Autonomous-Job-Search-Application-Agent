"""The operator's purge (WS-14 · Phase D).

Three jobs, one command:

- ``--expired`` — remove the rows and the files that are past the
  retention window;
- ``--deactivated`` — remove the accounts that asked to be deleted more
  than the grace period ago, and everything they owned;
- ``--user <id>`` — remove one account, and everything it owned.

The purge is **idempotent**: running it twice changes nothing the
second time. That is what makes it safe to run on a schedule and safe
to retry after a crash.

The audit rows of a purged account are **anonymized, not deleted**: a
trail that can be rewritten is not a trail, and non-repudiation needs
the record of what happened to survive the person it happened to.

Run it with::

    python scripts/purge_expired.py --expired
    python scripts/purge_expired.py --deactivated
    python scripts/purge_expired.py --user <account id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow ``python scripts/purge_expired.py`` from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.session import SessionLocal
from src.retention import (
    deactivated_accounts_older_than,
    get_policy,
    purge_expired,
    purge_user,
)


def main(argv: list[str] | None = None) -> int:
    """Run the purge. Returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--expired",
        action="store_true",
        help="Remove the rows and files that are past the retention window.",
    )
    parser.add_argument(
        "--deactivated",
        action="store_true",
        help="Remove the accounts deleted more than the grace period ago.",
    )
    parser.add_argument(
        "--user",
        metavar="ID",
        help="Remove one account, and everything it owned.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be removed, without removing it.",
    )
    args = parser.parse_args(argv)

    if not (args.expired or args.deactivated or args.user):
        parser.error("Choose at least one of --expired, --deactivated, --user.")

    policy = get_policy()
    report: dict[str, object] = {}

    with SessionLocal() as db:
        if args.expired:
            if args.dry_run:
                report["expired"] = "would be purged"
            else:
                report["expired"] = purge_expired(db, policy)

        if args.deactivated:
            accounts = deactivated_accounts_older_than(db, policy.deletion_grace_days)
            report["deactivated_accounts"] = accounts
            if not args.dry_run:
                report["deactivated"] = {
                    account: purge_user(db, account, policy) for account in accounts
                }

        if args.user:
            if args.dry_run:
                report["user"] = {"id": args.user, "status": "would be purged"}
            else:
                report["user"] = {"id": args.user, "removed": purge_user(db, args.user, policy)}

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
