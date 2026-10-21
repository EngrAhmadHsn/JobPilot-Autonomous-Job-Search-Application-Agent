"""The dependency audit (WS-14 · Phase E).

``pip-audit`` checks the installed packages against the vulnerability
database. It has no configuration file, so the exception list lives in
``security/dependency-audit-ignores.txt`` — a file in the repository,
reviewed with the dependencies it applies to — and this script applies
it.

**The rule.** The audit fails the build on any finding that is not on
the list. The list is a set of *documented* exceptions: every id in it
belongs to a package whose reason is written next to it, and the reason
says why the vulnerable code is not reachable from a request.

The script also checks that the list is **well-formed**, because a list
that quietly grows — or one entry that no longer has a reason — is how
an audit gate stops meaning anything.

Usage::

    python scripts/audit_dependencies.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IGNORE_FILE = REPO_ROOT / "security" / "dependency-audit-ignores.txt"

#: The id shapes the audit database uses.
_ID = re.compile(r"^(CVE-\d{4}-\d+|PYSEC-\d{4}-\d+|GHSA-[a-z0-9-]+)$")

#: The packages the exception list is allowed to name. A group for a
#: package the project does not depend on is a mistake, not an
#: exception.
KNOWN_PACKAGES = {"chromadb", "pillow", "certifi", "pip", "fastembed"}


def parse_ignores(path: Path = IGNORE_FILE) -> dict[str, list[str]]:
    """The exception list, grouped by package.

    Returns:
        The vulnerability ids of each package group.
    """
    groups: dict[str, list[str]] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip()
            groups.setdefault(current, [])
            continue
        if current is None:
            continue
        groups[current].append(stripped)
    return groups


def read_ignores(path: Path = IGNORE_FILE) -> list[str]:
    """The vulnerability ids on the exception list, in order."""
    ids: list[str] = []
    for entries in parse_ignores(path).values():
        ids.extend(entries)
    return ids


def check_the_list(path: Path = IGNORE_FILE) -> list[str]:
    """The problems with the exception list, if it has any.

    Returns:
        One message per problem; empty when the list is well-formed.
    """
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")
    groups = parse_ignores(path)

    if not groups:
        problems.append("the exception list is empty")

    for package, entries in groups.items():
        if package not in KNOWN_PACKAGES:
            problems.append(f"{package!r} is not a package this project depends on")
        if not entries:
            problems.append(f"the {package} group has no reason and no ids")
            continue
        # The reason is the comment block that follows the group header.
        header = f"[{package}]"
        index = text.index(header)
        tail = text[index + len(header) :].splitlines()
        reason = [line for line in tail if line.strip().startswith("#")]
        if not reason:
            problems.append(f"the {package} group has no stated reason")

    seen: set[str] = set()
    for package, entries in groups.items():
        for entry in entries:
            if not _ID.match(entry):
                problems.append(f"{entry!r} does not look like a vulnerability id")
            if entry in seen:
                problems.append(f"{entry} is on the list more than once")
            seen.add(entry)

    return problems


def main(argv: list[str] | None = None) -> int:
    """Run the audit. Returns the process exit code."""
    problems = check_the_list()
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1

    ids = read_ignores()
    print(f"Auditing with {len(ids)} documented exception(s).")

    command = [sys.executable, "-m", "pip_audit", "--strict", "--progress-spinner", "off"]
    for entry in ids:
        command.extend(["--ignore-vuln", entry])

    result = subprocess.run(command, cwd=str(REPO_ROOT), check=False)
    if result.returncode != 0:
        print(
            "The dependency audit found something that is not on the exception list, "
            "or the exception list needs a reason.",
            file=sys.stderr,
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
