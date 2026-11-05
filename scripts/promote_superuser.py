"""Grant (or revoke) platform-administrator access on the local database.

Usage::

    env\\Scripts\\python.exe scripts\\promote_superuser.py operator@example.com
    env\\Scripts\\python.exe scripts\\promote_superuser.py operator@example.com --revoke

The Administration screen (``/app/admin``) and its API route are gated on
``users.is_superuser``, which is read from the session on every request. The
account must sign out and back in (or just reload) to see the change.

This is a **local development** helper. It edits ``app.db`` in place; nothing
here belongs in a deployment's operations runbook, where promotion should go
through whatever identity process the deployment actually has.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "app.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="the account to change")
    parser.add_argument(
        "--revoke",
        action="store_true",
        help="remove administrator access instead of granting it",
    )
    args = parser.parse_args()

    if not DB.exists():
        print(f"no database at {DB}", file=sys.stderr)
        return 1

    connection = sqlite3.connect(DB)
    try:
        exists = connection.execute(
            "select 1 from users where email = ?", (args.email,)
        ).fetchone()
        if not exists:
            print(f"no account with email {args.email!r}", file=sys.stderr)
            return 1
        connection.execute(
            "update users set is_superuser = ? where email = ?",
            (0 if args.revoke else 1, args.email),
        )
        connection.commit()
    finally:
        connection.close()

    verb = "revoked" if args.revoke else "granted"
    print(f"administrator access {verb} for {args.email}")
    print("sign out and back in (or reload) to see it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())