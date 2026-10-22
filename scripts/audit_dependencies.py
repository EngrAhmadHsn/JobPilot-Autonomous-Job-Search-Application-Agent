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

**The one exemption, and why it is checked.** The project itself is
installed from this checkout, so it is not a PyPI artifact and cannot be
audited as a dependency of itself: ``pip-audit`` would look
``agentic-job-applier`` up on PyPI, not find it, and (with ``--strict``)
fail the build on the *project*. The audit therefore runs with
``--skip-editable``, and the project is the one package it skips.

That exemption is only safe while the package being skipped is *this*
code, so the script checks it: a distribution of the same name
installed from PyPI would be somebody else's code, and skipping it
would hide that.

**Why the strictness lives here and not in ``pip-audit``.** ``--strict``
and ``--skip-editable`` cannot be combined — ``--strict`` turns
*every* skipped package into a fatal error, and the project is skipped
— so the audit runs without ``--strict`` and this script enforces the
same rule over the report: a dependency that could not be audited is a
failure, unless it is the project itself.

The script also checks that the report has the shape it expects. A gate
that cannot read its own tool's output is not a gate.

Usage::

    python scripts/audit_dependencies.py
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
IGNORE_FILE = REPO_ROOT / "security" / "dependency-audit-ignores.txt"

#: The id shapes the audit database uses.
_ID = re.compile(r"^(CVE-\d{4}-\d+|PYSEC-\d{4}-\d+|GHSA-[a-z0-9-]+)$")

#: The packages the exception list is allowed to name. A group for a
#: package the project does not depend on is a mistake, not an
#: exception.
KNOWN_PACKAGES = {"chromadb", "pillow", "certifi", "pip", "fastembed"}

#: The project's own distribution. It is installed from this checkout, so
#: it is not on PyPI and is not a third-party dependency of itself.
PROJECT_NAME = "agentic-job-applier"


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


# -- the one exemption --------------------------------------------------------


def _local_checkout(url: str) -> Path | None:
    """The local directory a ``file:`` URL points at, if it is one."""
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    # A Windows file URL is "/C:/path"; pathlib would read the leading
    # slash as the root of the current drive.
    if os.name == "nt" and re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    return Path(path)


def check_the_project_is_local() -> list[str]:
    """The problems with the way the project itself is installed.

    The audit skips editable packages, because the project is one. That
    exemption is only safe while the package being skipped is *this*
    code — a distribution of the same name installed from PyPI would be
    somebody else's code, and skipping it would hide that.

    Returns:
        One message per problem; empty when the project is an editable
        install of this checkout (or is not installed at all).
    """
    try:
        distribution = importlib.metadata.distribution(PROJECT_NAME)
    except importlib.metadata.PackageNotFoundError:
        # The project is not installed: nothing is exempted, nothing to
        # check.
        return []

    version = distribution.version
    raw = distribution.read_text("direct_url.json")
    if not raw:
        return [
            (
                f"{PROJECT_NAME} {version} is installed but not from a local "
                "checkout, so the audit cannot exempt it"
            )
        ]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [f"{PROJECT_NAME} {version} has an unreadable direct_url.json"]

    if not payload.get("dir_info", {}).get("editable"):
        return [
            (
                f"{PROJECT_NAME} {version} is installed as a wheel rather than "
                "as an editable install of this checkout, so the audit cannot "
                "exempt it"
            )
        ]

    location = _local_checkout(str(payload.get("url", "")))
    if location is None:
        return [
            (
                f"{PROJECT_NAME} {version} is installed from "
                f"{payload.get('url')!r}, which is not a local checkout"
            )
        ]
    try:
        location.resolve().relative_to(REPO_ROOT.resolve())
    except (ValueError, OSError):
        return [
            (f"{PROJECT_NAME} {version} is installed from {location}, which is not this checkout")
        ]
    return []


# -- the report ---------------------------------------------------------------


def parse_report(text: str) -> object | None:
    """The audit report, or ``None`` when the output is not a report."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def check_the_report(report: object) -> list[str]:
    """The problems in pip-audit's report.

    Two kinds, and the first is the strictness ``--strict`` used to
    provide:

    - a dependency that **could not be audited** — it is not on PyPI, or
      its version does not parse. An unaudited dependency is an
      unaudited dependency, and the build must not pass over it; and
    - a dependency with a **finding**. The ids on the exception list
      are passed to pip-audit as ``--ignore-vuln``, so a vulnerability
      in the report is by definition one that is not on the list.

    The project's own distribution is the single exemption, and only
    when it was skipped for being editable.

    Returns:
        One message per problem; empty when the report is clean.
    """
    if not isinstance(report, dict):
        return ["pip-audit's report was not understood; the gate cannot trust it"]
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list):
        return ["pip-audit's report has no 'dependencies' list; the gate cannot trust it"]

    problems: list[str] = []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            problems.append("pip-audit's report has an entry that is not a dependency")
            continue
        name = str(dependency.get("name", "<unnamed>"))
        skip_reason = dependency.get("skip_reason")
        if skip_reason:
            if name == PROJECT_NAME and "editable" in str(skip_reason):
                # The one exemption: the project, installed from this
                # checkout. `check_the_project_is_local` has already
                # proved that it is *this* code.
                continue
            problems.append(f"{name} could not be audited: {skip_reason}")
            continue
        for vulnerability in dependency.get("vulns", []):
            if not isinstance(vulnerability, dict):
                problems.append(f"{name} has a finding the report does not describe")
                continue
            identifier = vulnerability.get("id", "<unknown>")
            version = dependency.get("version", "")
            problems.append(f"{name} {version} has {identifier}")
    return problems


def build_command(ids: list[str]) -> list[str]:
    """The pip-audit command line for the documented exceptions.

    Two flags carry the whole design:

    - ``--skip-editable``, because the project itself is installed from
      this checkout and is not on PyPI; and
    - **not** ``--strict``, because ``--strict`` turns *every* skipped
      package into a fatal error, and the project is one. The strictness
      is enforced over the report instead — see :func:`check_the_report`.
    """
    command = [
        sys.executable,
        "-m",
        "pip_audit",
        "--skip-editable",
        "-f",
        "json",
        "--progress-spinner",
        "off",
    ]
    for entry in ids:
        command.extend(["--ignore-vuln", entry])
    return command


def main(argv: list[str] | None = None) -> int:
    """Run the audit. Returns the process exit code."""
    problems = check_the_list()
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1

    problems = check_the_project_is_local()
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1

    ids = read_ignores()
    print(f"Auditing with {len(ids)} documented exception(s).")

    result = subprocess.run(
        build_command(ids),
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    report = parse_report(result.stdout)
    if report is None:
        print("FAIL: pip-audit produced no report.", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        return 1

    problems = check_the_report(report)
    if not problems and result.returncode != 0:
        problems = [f"pip-audit exited with {result.returncode} and reported nothing"]
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        print(
            "The dependency audit found something that is not on the exception list, "
            "or the exception list needs a reason.",
            file=sys.stderr,
        )
        return 1

    audited = sum(
        1
        for dependency in report.get("dependencies", [])
        if isinstance(dependency, dict) and not dependency.get("skip_reason")
    )
    print(f"Audited {audited} dependencies; nothing outside the exception list.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
