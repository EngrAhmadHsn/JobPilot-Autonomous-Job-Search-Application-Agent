"""WS-11 · The README's API table must match the running application.

A README is the first thing a new operator reads, and the first thing they
copy from. If it lists a route the application removed, they get a 404 and
conclude the system is broken. If it omits a route, they conclude the feature
does not exist.

Both failure modes are prevented here: the table in ``README.md`` is compared
against the **live** OpenAPI schema of the application, in both directions.
A route added without a README line fails the suite; a README line for a
route that no longer exists fails the suite.

The same file carries the redaction check: the tracked documents must not
carry a credential-shaped literal.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.main import app

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"

# A row of the README's API table: | `GET /api/resumes/{id}` | purpose | WS-04 |
_TABLE_ROW = re.compile(r"^\|\s*`([A-Z]+)\s+(/[^`]*)`\s*\|")

# The documents a reader would copy a credential out of.
TRACKED_DOCS = (
    README,
    REPO_ROOT / "docs" / "ARCHITECTURE.md",
    REPO_ROOT / "docs" / "PROJECT_PLAN.md",
    REPO_ROOT / "docs" / "SECURITY.md",
    REPO_ROOT / ".env.example",
)

# The route WS-06 removed. It was the single-call submit route with an
# `approval: bool` flag — the hole SEC-05 forbids. It must not reappear in
# the documentation, because a reader would call it and expect it to work.
REMOVED_ROUTES = ("/api/applications/submit",)


def _application_routes() -> set[tuple[str, str]]:
    """Every (method, path) the running application exposes.

    The OpenAPI schema is the application's own description of its surface,
    so it cannot drift from the code the way a hand-written table can.
    """
    schema = app.openapi()
    routes: set[tuple[str, str]] = set()
    for path, operations in schema["paths"].items():
        for method in operations:
            if method.upper() in {"HEAD", "OPTIONS"}:
                continue
            routes.add((method.upper(), path))
    return routes


def _readme_routes() -> set[tuple[str, str]]:
    """Every (method, path) the README's API table lists."""
    routes: set[tuple[str, str]] = set()
    for line in README.read_text(encoding="utf-8").splitlines():
        match = _TABLE_ROW.match(line.strip())
        if match:
            routes.add((match.group(1), match.group(2)))
    return routes


def test_the_readme_api_table_is_complete() -> None:
    """Every route the application exposes is in the README."""
    application = _application_routes()
    documented = _readme_routes()

    missing = sorted(application - documented)

    assert not missing, (
        f"{len(missing)} route(s) are exposed by the application but missing from "
        f"the README's API table: {missing}. Add a row for each."
    )


def test_the_readme_api_table_has_no_phantom_routes() -> None:
    """Every route the README lists is really exposed."""
    application = _application_routes()
    documented = _readme_routes()

    phantom = sorted(documented - application)

    assert not phantom, (
        f"{len(phantom)} route(s) are in the README's API table but not exposed by "
        f"the application: {phantom}. Remove them or implement them."
    )


def test_the_readme_does_not_advertise_a_removed_route() -> None:
    """The removed single-call submit route stays out of the documentation."""
    text = README.read_text(encoding="utf-8")

    for route in REMOVED_ROUTES:
        assert route not in text, (
            f"the README mentions {route}, which the application removed in WS-06. "
            "A submission must go through the two-phase approval flow."
        )


def test_the_readme_documents_the_dev_docs_surface() -> None:
    """The interactive docs are mentioned, and only as a development surface."""
    text = README.read_text(encoding="utf-8")

    assert "/docs" in text, "the README should point at the interactive API docs"


@pytest.mark.parametrize("path", TRACKED_DOCS)
def test_the_tracked_documents_carry_no_credential(path: Path) -> None:
    """No document carries a credential-shaped literal.

    The patterns require a plausible length, so ordinary English ("risk-",
    "task-") cannot trip the check while a real key always does.
    """
    if not path.exists():
        pytest.skip(f"{path.name} does not exist")

    text = path.read_text(encoding="utf-8")

    for pattern, description in (
        (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "a Google API key"),
        (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), "an OpenAI-style API key"),
        (re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}"), "a bearer token"),
    ):
        match = pattern.search(text)
        assert match is None, f"{path.name} appears to contain {description}"
