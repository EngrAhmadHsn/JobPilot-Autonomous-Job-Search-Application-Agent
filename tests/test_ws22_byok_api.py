"""WS-22 · the bring-your-own-key HTTP surface (Phase B2).

The unit tests in ``test_ws22_byok.py`` prove the store and the resolution.
This file proves the surface an operator actually touches:

- the response shapes carry a mask and **never** the key — asserted against
  the raw JSON, not against a model, so a field added later cannot quietly
  carry it;
- a bad provider, a bad base URL and a private base URL are refusals the
  caller can act on (422), not 500s;
- the credential is per-principal over HTTP: a second caller sees nothing and
  cannot delete the first caller's row;
- the deployment modes are honoured at the edge (403 when disabled);
- a failing key is a 200 with ``ok: false`` — the operator asked a question,
  and "no" is an answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.api.scope import UserScope, current_scope
from src.db.base import Base
from src.db.byok import LlmCredentialDB
from src.db.session import get_db
from src.llm import credentials as creds
from src.llm.errors import LLMCredentialError
from src.llm.providers import ProviderResponse
from src.security.secrets import reset_box

ALICE = "alice"
BOB = "bob"
ALICE_KEY = "sk-alice-0123456789-verysecret"

ROUTE = "/api/llm/credentials"


class _FakeProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.name = "google"
        self.fail = fail
        self.requests: list[object] = []

    def complete(self, request) -> ProviderResponse:
        self.requests.append(request)
        if self.fail:
            raise LLMCredentialError("rejected")
        return ProviderResponse(text="ok", total_tokens=2)


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A TestClient whose scope and session the test controls per request."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("BYOK_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    from src.config.settings import get_settings

    get_settings.cache_clear()
    reset_box()
    creds.reset_client_cache()

    engine = create_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    monkeypatch.setattr("src.db.session.SessionLocal", factory)

    from src.main import app

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[current_scope] = lambda: UserScope(user_id=ALICE)
    with TestClient(app) as client:
        client.db = session  # type: ignore[attr-defined]
        yield client
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(current_scope, None)
    get_settings.cache_clear()
    reset_box()
    creds.reset_client_cache()


def _as(client: TestClient, user_id: str) -> None:
    """Switch the caller: the scope is what the store is keyed on."""
    from src.main import app

    app.dependency_overrides[current_scope] = lambda: UserScope(user_id=user_id)


def _put_body(api_key: str = ALICE_KEY, **overrides) -> dict:
    body = {
        "provider": "google",
        "model": "gemini-3.8-flash",
        "api_key": api_key,
    }
    body.update(overrides)
    return body


class TestTheStatusRead:
    def test_a_fresh_caller_reports_the_deployment_mode(self, api: TestClient) -> None:
        response = api.get(ROUTE)
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "optional"
        assert body["credential"] is None
        assert body["using"] == "none"
        assert body["encryption"] == "local_file"

    def test_the_read_never_carries_a_key(self, api: TestClient) -> None:
        api.put(ROUTE, json=_put_body())
        raw = api.get(ROUTE).text
        assert ALICE_KEY not in raw
        assert ALICE_KEY[-4:] in raw  # the mask is the one disclosure


class TestTheWrite:
    def test_a_stored_credential_is_masked_and_encrypted(self, api: TestClient) -> None:
        response = api.put(ROUTE, json=_put_body())
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "google"
        assert body["hint"] == ALICE_KEY[-4:]
        assert ALICE_KEY not in response.text

        row = api.db.execute(select(LlmCredentialDB)).scalar_one()  # type: ignore[attr-defined]
        assert ALICE_KEY not in row.encrypted_key

        state = api.get(ROUTE).json()
        assert state["using"] == "user"
        assert state["credential"]["hint"] == ALICE_KEY[-4:]

    def test_an_unknown_provider_is_refused(self, api: TestClient) -> None:
        response = api.put(ROUTE, json=_put_body(provider="anthropic"))
        assert response.status_code == 422

    def test_a_short_key_is_refused(self, api: TestClient) -> None:
        assert api.put(ROUTE, json=_put_body(api_key="short")).status_code == 422

    def test_openai_compatible_without_a_base_url_is_refused(self, api: TestClient) -> None:
        response = api.put(ROUTE, json=_put_body(provider="openai-compatible", model="gpt-4o-mini"))
        assert response.status_code == 422
        assert "base_url is required" in response.text

    def test_a_private_base_url_is_refused(self, api: TestClient) -> None:
        response = api.put(
            ROUTE,
            json=_put_body(
                provider="openai-compatible",
                model="gpt-4o-mini",
                base_url="http://10.0.0.5/v1",
            ),
        )
        assert response.status_code == 422
        assert "internal" in response.text or "loopback" in response.text

    def test_a_loopback_base_url_is_fine_in_development(self, api: TestClient) -> None:
        response = api.put(
            ROUTE,
            json=_put_body(
                provider="openai-compatible",
                model="gpt-4o-mini",
                base_url="http://127.0.0.1:8901/v1",
            ),
        )
        assert response.status_code == 200

    def test_the_disabled_mode_refuses_the_write(
        self, api: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BYOK_MODE", "disabled")
        from src.config.settings import get_settings

        get_settings.cache_clear()
        try:
            assert api.put(ROUTE, json=_put_body()).status_code == 403
            state = api.get(ROUTE).json()
            assert state["available"] is False
        finally:
            get_settings.cache_clear()

    def test_replacing_a_key_leaves_one_row(self, api: TestClient) -> None:
        second = "sk-second-0123456789-key"
        api.put(ROUTE, json=_put_body())
        api.put(ROUTE, json=_put_body(api_key=second))
        rows = list(api.db.execute(select(LlmCredentialDB)).scalars())  # type: ignore[attr-defined]
        assert len(rows) == 1
        assert rows[0].hint == second[-4:]


class TestTheDelete:
    def test_delete_is_idempotent(self, api: TestClient) -> None:
        api.put(ROUTE, json=_put_body())
        assert api.delete(ROUTE).json() == {"removed": True}
        assert api.delete(ROUTE).json() == {"removed": False}


class TestTheExercise:
    def test_a_working_key_answers_ok(
        self, api: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.llm.credentials.build_provider", lambda *a, **k: _FakeProvider())
        api.put(ROUTE, json=_put_body())
        response = api.post(f"{ROUTE}/test")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["provider"] == "google"
        assert isinstance(body["latency_ms"], int)

    def test_a_rejected_key_answers_not_ok_not_an_error(
        self, api: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.llm.credentials.build_provider", lambda *a, **k: _FakeProvider(fail=True)
        )
        api.put(ROUTE, json=_put_body())
        response = api.post(f"{ROUTE}/test")
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert response.json()["error_type"] == "LLMCredentialError"

    def test_exercising_nothing_is_a_conflict(self, api: TestClient) -> None:
        assert api.post(f"{ROUTE}/test").status_code == 409


class TestTheTenantPublication:
    """WS-22: the scope dependency must publish a tenant the route can see.

    This is the mechanism the whole feature rests on: ``resolve_client()``
    asks ``current_tenant()`` whose credential to use, and that value comes
    from ``current_scope``. A **sync** dependency's ``ContextVar.set`` is
    discarded inside the worker-thread context copy FastAPI gives it, so the
    route — and every call under it — saw no tenant and BYOK silently fell
    back to the platform key. The live run caught it; this test pins it.
    """

    def test_a_sync_route_body_sees_the_published_tenant(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.auth.routes import current_active_user
        from src.db.users import UserDB
        from src.llm.tenant import current_tenant

        caller = UserDB(
            id="tenant-probe-user",
            email="probe@example.com",
            hashed_password="!",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        probe_app = FastAPI()

        @probe_app.get("/probe")
        def probe(scope: Annotated[UserScope, Depends(current_scope)]) -> dict:
            # A sync route: the case that was broken.
            return {"scope": scope.user_id, "tenant": current_tenant()}

        probe_app.dependency_overrides[current_active_user] = lambda: caller
        with TestClient(probe_app) as client:
            body = client.get("/probe").json()
        assert body["scope"] == "tenant-probe-user"
        assert body["tenant"] == "tenant-probe-user"


class TestIsolationOverHttp:
    def test_a_second_caller_sees_nothing_and_cannot_delete(self, api: TestClient) -> None:
        api.put(ROUTE, json=_put_body())
        _as(api, BOB)
        assert api.get(ROUTE).json()["credential"] is None
        assert api.delete(ROUTE).json() == {"removed": False}
        # The first caller's row survived.
        _as(api, ALICE)
        assert api.get(ROUTE).json()["credential"]["hint"] == ALICE_KEY[-4:]

    def test_each_caller_gets_their_own_row(self, api: TestClient) -> None:
        api.put(ROUTE, json=_put_body())
        _as(api, BOB)
        api.put(ROUTE, json=_put_body(api_key="sk-bob-9876543210-alsosecret"))
        rows = list(api.db.execute(select(LlmCredentialDB)).scalars())  # type: ignore[attr-defined]
        assert {row.owner_id for row in rows} == {ALICE, BOB}
