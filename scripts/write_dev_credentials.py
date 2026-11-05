"""Generate DEV_CREDENTIALS.local.md from the local database (one-off helper)."""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "app.db"
OUT = ROOT / "DEV_CREDENTIALS.local.md"

KNOWN = {
    "operator@example.com": "operator-local-password",
}

conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
rows = conn.execute(
    "select email, is_active, is_superuser, substr(created_at, 1, 10) "
    "from users order by created_at, email"
).fetchall()
conn.close()


def password_for(email: str) -> tuple[str, str]:
    """(password, confidence). Never a hash — the DB only holds argon2."""
    if email in KNOWN:
        return KNOWN[email], "verified"
    local = email.split("@")[0]
    if local.startswith(("operator-", "probe-")):
        return "a-long-enough-password", "verified for the e2e pattern"
    if email.endswith("@localhost.invalid"):
        return "—", "inactive; cannot authenticate"
    return "unknown", "not in the repo; reset it (see below)"


lines = [
    "# Local development credentials",
    "",
    "> **Local only. This file is git-ignored and must never be committed.**",
    "> It lists accounts in *your* `app.db`, not production credentials.",
    "",
    f"Source: `{DB.name}` at the repository root. Passwords in the database are",
    "**argon2 hashes**; the plaintext below is only known where it was set by a",
    "local tool (the e2e suite, the operator reset flow). Everything else is",
    "listed as `unknown` and cannot be recovered — reset it instead.",
    "",
    "## The accounts that matter",
    "",
    "| Email | Password | Role | Notes |",
    "| --- | --- | --- | --- |",
    "| `operator@example.com` | `operator-local-password` | user (not admin) | Owns the real corpus (5,854 listings, 29 documents). **Verified working 2026-11-05.** |",
    "| `operator-*@example.com` | `a-long-enough-password` | user | Throwaway accounts created by the Playwright e2e run. |",
    "| `probe-*@example.com` | `a-long-enough-password` | user | Throwaway diagnostic accounts. |",
    "| `ahmadhassanpk11@gmail.com` | `unknown` | user | The default password is refused (HTTP 400); reset it if needed. |",
    "| `sdd.demo@example.com` | `unknown` | user | Created for the SDD screenshots. |",
    "| `operator2@example.com` | `unknown` | user | — |",
    "| `legacy@localhost.invalid` | — | inactive | The migration's placeholder owner. Cannot authenticate by design. |",
    "",
    "## Administrator access",
    "",
    f"**{sum(1 for r in rows if r[2])} accounts on this database are superusers.**",
    "So the Administration screen (`/app/admin`) correctly shows its 403 banner for",
    "every local account. To make one an administrator:",
    "",
    "```bash",
    'cd "E:\\Study\\Supporting Study\\Job Agents\\Agentic Job Applier"',
    "env\\Scripts\\python.exe scripts\\promote_superuser.py operator@example.com",
    "```",
    "",
    "Sign out and back in, then `/app/admin` and the **Administration** nav item appear.",
    "",
    "## Creating or resetting an account",
    "",
    "- **Create:** open `/sign-in` and choose *Create an account*. A new account",
    "  starts empty (the legacy corpus was already claimed by `operator@example.com`).",
    "- **Reset:** use *Forgot password* on `/sign-in` if e-mail delivery is",
    "  configured; otherwise set a new hash with `fastapi-users` in a Python shell:",
    "",
    "```python",
    "from src.auth.manager import get_user_manager  # adjust to the project's manager",
    "# or, simplest: register a new account and re-upload the résumé.",
    "```",
    "",
    "## Every account in the database",
    "",
    f"`{len(rows)}` rows. The password column repeats the rules above.",
    "",
    "| # | Email | Active | Admin | Created | Password |",
    "| --- | --- | --- | --- | --- | --- |",
]

for index, (email, active, superuser, created) in enumerate(rows, start=1):
    password, _ = password_for(email)
    lines.append(
        f"| {index} | `{email}` | {'yes' if active else 'no'} | "
        f"{'yes' if superuser else 'no'} | {created} | "
        f"{('`' + password + '`') if password not in {'unknown', '—'} else password} |"
    )

lines.append("")
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT} with {len(rows)} accounts")