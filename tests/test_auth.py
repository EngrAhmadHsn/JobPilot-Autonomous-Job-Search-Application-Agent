"""WS-14 · A1 — the identity tests.

**The property under test:** a caller is a *principal*. The API can tell
who is asking, it refuses a caller it cannot identify, and the credential
it hands out is not guessable, not stored in the clear, and revocable.

The tests are written against the **real** transport — the real cookie,
the real bearer token, the real session rows — with no dependency
overrides. A test that overrode the authentication dependency would
prove that the *override* works, which is not the property that matters.

What is proved here:

- a password is never stored or logged in the clear;
- a session is issued on login and destroyed on logout;
- a bearer token and a cookie resolve to the **same** principal;
- a request without a credential is refused;
- CSRF is enforced on the cookie transport, and not on the bearer one;
- a duplicate registration is refused, and a registration cannot promote
  itself to a superuser;
- a deactivated account cannot authenticate.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.auth.routes import current_active_user
from src.config.settings import get_settings
from src.db.base import Base
from src.db.session import get_db
from src.db.users import UserDB
from src.main import app

#: A password that satisfies the policy (at least eight characters).
PASSWORD = "correct horse battery staple"
OTHER_PASSWORD = "a different long password"

#: The e-mail addresses the tests register with.
ALICE_EMAIL = "alice@example.com"
BOB_EMAIL = "bob@example.com"


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient over a throwaway database and a throwaway data dir."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'auth.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # The suite's autouse identity is removed here on purpose: this suite
    # is about the **real** authentication, so the routes must resolve the
    # principal from a real credential rather than from an override.
    app.dependency_overrides.pop(current_active_user, None)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "data" / "evidence"))
    monkeypatch.setenv("RESUME_UPLOAD_DIR", str(tmp_path / "data" / "resumes"))
    monkeypatch.setenv("TAILORED_DIR", str(tmp_path / "data" / "tailored"))
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def _register(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    """Register an account and return the response body."""
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login_cookie(client: TestClient, email: str, password: str = PASSWORD):
    """Log in through the cookie transport."""
    return client.post(
        "/api/auth/cookie/login",
        data={"username": email, "password": password},
    )


def _login_token(client: TestClient, email: str, password: str = PASSWORD) -> str:
    """Log in through the bearer transport and return the access token."""
    response = client.post(
        "/api/auth/token/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _csrf_headers(client: TestClient) -> dict[str, str]:
    """The header the double-submit check expects on an unsafe request.

    The cookie transport is ambient, so an unsafe request that carries
    the session cookie must also carry this header. A test that forgets
    it is testing the CSRF control *by accident* — which is why the CSRF
    tests below are explicit about it.
    """
    token = client.cookies.get(get_settings().auth_csrf_cookie_name)
    return {"X-CSRF-Token": token} if token else {}


# -- registration --------------------------------------------------------------


class TestRegistration:
    def test_a_registration_creates_an_account(self, api: TestClient) -> None:
        body = _register(api, ALICE_EMAIL)
        assert body["email"] == ALICE_EMAIL
        assert body["is_active"] is True
        assert body["is_superuser"] is False

    def test_the_password_is_never_returned(self, api: TestClient) -> None:
        body = _register(api, ALICE_EMAIL)
        assert "password" not in body
        assert "hashed_password" not in body

    def test_the_password_is_stored_as_a_hash(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        with next(api.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
            row = db.query(UserDB).filter(UserDB.email == ALICE_EMAIL).one()
            stored = row.hashed_password
        assert stored != PASSWORD
        assert PASSWORD not in stored
        # argon2, the memory-hard KDF.
        assert stored.startswith("$argon2")

    def test_a_duplicate_registration_is_refused(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        response = api.post(
            "/api/auth/register",
            json={"email": ALICE_EMAIL, "password": PASSWORD},
        )
        assert response.status_code == 400

    def test_a_registration_cannot_promote_itself(self, api: TestClient) -> None:
        """A registration that asks for a superuser does not get one."""
        response = api.post(
            "/api/auth/register",
            json={
                "email": ALICE_EMAIL,
                "password": PASSWORD,
                "is_superuser": True,
                "is_active": True,
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["is_superuser"] is False

    def test_a_short_password_is_refused(self, api: TestClient) -> None:
        response = api.post(
            "/api/auth/register",
            json={"email": ALICE_EMAIL, "password": "short"},
        )
        assert response.status_code == 400


# -- login and logout ----------------------------------------------------------


class TestTheCookieTransport:
    def test_a_login_issues_a_session_cookie(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        response = _login_cookie(api, ALICE_EMAIL)
        assert response.status_code == 204, response.text
        cookie = response.cookies.get(get_settings().auth_session_cookie_name)
        assert cookie, "the login response carried no session cookie"

    def test_the_session_cookie_is_httponly(self, api: TestClient) -> None:
        """The console's JavaScript must not be able to read the session."""
        _register(api, ALICE_EMAIL)
        response = _login_cookie(api, ALICE_EMAIL)
        header = response.headers["set-cookie"]
        assert "httponly" in header.lower()

    def test_the_session_cookie_is_samesite_lax(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        response = _login_cookie(api, ALICE_EMAIL)
        assert "samesite=lax" in response.headers["set-cookie"].lower()

    def test_a_cookie_resolves_to_the_principal(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        _login_cookie(api, ALICE_EMAIL)
        response = api.get("/api/auth/me")
        assert response.status_code == 200, response.text
        assert response.json()["email"] == ALICE_EMAIL

    def test_a_logout_destroys_the_session(self, api: TestClient) -> None:
        """Logging out must end the session **server-side**, not only clear
        the cookie: a stolen cookie that is merely forgotten by the
        browser would still work."""
        _register(api, ALICE_EMAIL)
        _login_cookie(api, ALICE_EMAIL)
        assert api.get("/api/auth/me").status_code == 200

        response = api.post("/api/auth/cookie/logout", headers=_csrf_headers(api))
        assert response.status_code == 204, response.text
        assert api.get("/api/auth/me").status_code == 401

    def test_a_logout_leaves_the_stolen_cookie_working(self, api: TestClient) -> None:
        """The other half of the previous test: the row is really gone."""
        _register(api, ALICE_EMAIL)
        response = _login_cookie(api, ALICE_EMAIL)
        stolen = response.cookies.get(get_settings().auth_session_cookie_name)
        assert stolen

        api.post("/api/auth/cookie/logout", headers=_csrf_headers(api))

        # A client that keeps the old cookie must not be authenticated.
        fresh = TestClient(app)
        fresh.cookies.set(get_settings().auth_session_cookie_name, stolen)
        assert fresh.get("/api/auth/me").status_code == 401

    def test_a_wrong_password_is_refused(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        response = _login_cookie(api, ALICE_EMAIL, "not the right password")
        assert response.status_code == 400

    def test_an_unknown_account_is_refused(self, api: TestClient) -> None:
        response = _login_cookie(api, "nobody@example.com")
        assert response.status_code == 400


class TestTheBearerTransport:
    def test_a_login_issues_a_bearer_token(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        token = _login_token(api, ALICE_EMAIL)
        assert token

    def test_a_bearer_token_resolves_to_the_principal(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        token = _login_token(api, ALICE_EMAIL)
        response = api.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["email"] == ALICE_EMAIL

    def test_a_bearer_token_and_a_cookie_are_the_same_principal(self, api: TestClient) -> None:
        """One identity, two transports."""
        _register(api, ALICE_EMAIL)
        cookie_login = _login_cookie(api, ALICE_EMAIL)
        token = _login_token(api, ALICE_EMAIL)

        from_cookie = api.get("/api/auth/me").json()
        from_bearer = api.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert from_cookie["id"] == from_bearer["id"]
        assert from_cookie["email"] == from_bearer["email"]
        assert cookie_login.status_code == 204

    def test_a_bearer_logout_destroys_the_session(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        token = _login_token(api, ALICE_EMAIL)
        headers = {"Authorization": f"Bearer {token}"}
        assert api.get("/api/auth/me", headers=headers).status_code == 200
        assert api.post("/api/auth/token/logout", headers=headers).status_code == 204
        assert api.get("/api/auth/me", headers=headers).status_code == 401

    def test_a_bogus_bearer_token_is_refused(self, api: TestClient) -> None:
        response = api.get("/api/auth/me", headers={"Authorization": "Bearer nope"})
        assert response.status_code == 401


class TestAnUnauthenticatedCaller:
    def test_a_request_without_a_credential_is_refused(self, api: TestClient) -> None:
        response = api.get("/api/auth/me")
        assert response.status_code == 401

    def test_a_malformed_authorization_header_is_refused(self, api: TestClient) -> None:
        response = api.get("/api/auth/me", headers={"Authorization": "Basic abc"})
        assert response.status_code == 401


# -- CSRF ----------------------------------------------------------------------


class TestCSRF:
    """The cookie transport is ambient, so it needs the double-submit check."""

    def _login_and_get_csrf(self, api: TestClient) -> str:
        """Register, log in through the cookie transport, and return the
        CSRF token the server issued."""
        _register(api, ALICE_EMAIL)
        _login_cookie(api, ALICE_EMAIL)
        api.get("/api/health")  # any safe request issues the CSRF cookie
        return api.cookies.get(get_settings().auth_csrf_cookie_name) or ""

    def test_a_safe_request_needs_no_csrf_token(self, api: TestClient) -> None:
        self._login_and_get_csrf(api)
        assert api.get("/api/auth/me").status_code == 200

    def test_the_csrf_cookie_is_issued(self, api: TestClient) -> None:
        api.get("/api/health")
        assert api.cookies.get(get_settings().auth_csrf_cookie_name)

    def test_an_unsafe_cookie_request_without_the_header_is_refused(self, api: TestClient) -> None:
        self._login_and_get_csrf(api)
        response = api.post("/api/auth/sessions/revoke")
        assert response.status_code == 403
        assert "csrf" in response.json()["detail"].lower()

    def test_an_unsafe_cookie_request_with_a_wrong_header_is_refused(self, api: TestClient) -> None:
        self._login_and_get_csrf(api)
        response = api.post(
            "/api/auth/sessions/revoke",
            headers={"X-CSRF-Token": "not-the-token"},
        )
        assert response.status_code == 403

    def test_an_unsafe_cookie_request_with_the_right_header_is_allowed(
        self, api: TestClient
    ) -> None:
        self._login_and_get_csrf(api)
        token = api.cookies.get(get_settings().auth_csrf_cookie_name)
        response = api.post(
            "/api/auth/sessions/revoke",
            headers={"X-CSRF-Token": token},
        )
        assert response.status_code == 200, response.text

    def test_a_bearer_request_needs_no_csrf_token(self, api: TestClient) -> None:
        """A bearer token is not sent ambiently, so it is not a CSRF vector."""
        _register(api, ALICE_EMAIL)
        token = _login_token(api, ALICE_EMAIL)
        response = api.post(
            "/api/auth/sessions/revoke",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text


# -- the account lifecycle ----------------------------------------------------


class TestTheAccountLifecycle:
    def test_a_password_change_revokes_the_other_sessions(self, api: TestClient) -> None:
        """The point of changing a password: the other sessions go."""
        _register(api, ALICE_EMAIL)
        first = _login_token(api, ALICE_EMAIL)
        second = _login_token(api, ALICE_EMAIL)

        response = api.patch(
            "/api/auth/me",
            json={"password": OTHER_PASSWORD},
            headers={"Authorization": f"Bearer {first}"},
        )
        assert response.status_code == 200, response.text

        # The first session survives the change it made.
        assert (
            api.get("/api/auth/me", headers={"Authorization": f"Bearer {first}"}).status_code == 200
        )
        # The second one does not.
        assert (
            api.get("/api/auth/me", headers={"Authorization": f"Bearer {second}"}).status_code
            == 401
        )

    def test_an_email_change_takes_effect(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        token = _login_token(api, ALICE_EMAIL)
        response = api.patch(
            "/api/auth/me",
            json={"email": "alice.new@example.com"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["email"] == "alice.new@example.com"

    def test_a_user_cannot_promote_itself(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        token = _login_token(api, ALICE_EMAIL)
        response = api.patch(
            "/api/auth/me",
            json={"is_superuser": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422, response.text

    def test_the_sessions_can_be_listed_without_leaking_the_tokens(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        token = _login_token(api, ALICE_EMAIL)
        response = api.get("/api/auth/sessions", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text
        sessions = response.json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["current"] is True
        assert token not in response.text
        assert sessions[0]["prefix"] == token[:8]

    def test_a_deletion_request_deactivates_the_account(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        token = _login_token(api, ALICE_EMAIL)
        response = api.delete("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text
        assert response.json()["deactivated"] is True

        # The account can no longer authenticate...
        assert (
            api.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
        )
        # ...and it cannot log in again either.
        assert _login_token_or_none(api, ALICE_EMAIL) is None

    def test_a_deactivated_account_cannot_log_in(self, api: TestClient) -> None:
        _register(api, ALICE_EMAIL)
        token = _login_token(api, ALICE_EMAIL)
        api.delete("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        response = _login_cookie(api, ALICE_EMAIL)
        assert response.status_code == 400


def _login_token_or_none(api: TestClient, email: str) -> str | None:
    """The bearer token, or ``None`` when the login was refused."""
    response = api.post(
        "/api/auth/token/login",
        data={"username": email, "password": PASSWORD},
    )
    if response.status_code != 200:
        return None
    return response.json()["access_token"]


# -- the audit trail -----------------------------------------------------------


class TestTheIdentityIsAudited:
    def test_a_registration_is_audited(self, api: TestClient, caplog) -> None:
        with caplog.at_level(logging.INFO):
            _register(api, ALICE_EMAIL)
        assert any("registered" in record.message for record in caplog.records)

    def test_the_password_never_reaches_the_log(self, api: TestClient, caplog) -> None:
        with caplog.at_level(logging.DEBUG):
            _register(api, ALICE_EMAIL)
            _login_cookie(api, ALICE_EMAIL)
        assert PASSWORD not in caplog.text
