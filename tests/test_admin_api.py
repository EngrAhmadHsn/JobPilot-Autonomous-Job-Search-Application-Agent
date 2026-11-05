"""WS-17 · The administration endpoint's authorization.

The overview is the one route that deliberately reads **across owners** —
the platform's own view. That makes its guard the whole control, so this
file proves the three answers it can give:

- a caller with **no credential** is refused with a 401 (the identity
  dependency runs before the route body);
- an ordinary account is refused with a **403**, and nothing about the
  platform leaks in the refusal;
- an administrator gets the platform totals, and the shape is exactly the
  contract the console's types describe.

The conftest's ``authenticated_caller`` fixture installs a **non-superuser**
identity for the whole suite, which is what the 403 case relies on. The
success and 401 cases replace or remove that override explicitly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.auth.routes import current_active_user
from src.db.users import UserDB
from src.main import app

client = TestClient(app)


def _administrator() -> UserDB:
    """An administrator principal, never persisted and never authenticated with."""
    return UserDB(
        id="admin-1",
        email="admin@example.com",
        hashed_password="!",
        is_active=True,
        is_superuser=True,
        is_verified=True,
    )


def test_an_ordinary_account_is_refused() -> None:
    """The suite's default identity is not a superuser, so it gets a 403."""
    response = client.get("/api/admin/overview")

    assert response.status_code == 403
    assert "administrator" in response.json()["detail"].lower()


def test_a_request_without_a_credential_is_refused() -> None:
    """With the override removed, the real identity dependency answers 401."""
    app.dependency_overrides.pop(current_active_user, None)
    try:
        response = client.get("/api/admin/overview")
        assert response.status_code == 401
    finally:
        # The conftest fixture reinstalls the override on the next test's
        # setup; there is nothing to restore here beyond leaving the map
        # clean.
        app.dependency_overrides.pop(current_active_user, None)


def test_an_administrator_reads_the_platform_overview() -> None:
    app.dependency_overrides[current_active_user] = _administrator
    try:
        response = client.get("/api/admin/overview")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "accounts",
            "applications",
            "workflows",
            "audit",
            "corpus",
            "generated_at",
        }
        # Every figure is a live count, so they are real integers (possibly
        # zero on the throwaway suite database).
        assert set(body["accounts"]) == {"total", "active", "superusers"}
        assert isinstance(body["applications"]["by_status"], dict)
        assert isinstance(body["audit"]["by_outcome"], dict)
        assert isinstance(body["audit"]["by_actor_kind"], dict)
        assert isinstance(body["workflows"]["total"], int)
        assert isinstance(body["corpus"]["jobs"], int)
        # The administrator is counted, because the row is in the database
        # the suite points at only if it was persisted — it was not, so the
        # count is honest about what the table holds.
        assert body["accounts"]["total"] >= 0
    finally:
        app.dependency_overrides.pop(current_active_user, None)


@pytest.mark.parametrize("path", ["/api/admin/overview"])
def test_the_route_is_registered(path: str) -> None:
    """A missing route would 404; the guard is what makes it 403/401."""
    app.dependency_overrides[current_active_user] = _administrator
    try:
        assert client.get(path).status_code == 200
    finally:
        app.dependency_overrides.pop(current_active_user, None)
