"""WS-22 · the bring-your-own-key credential store (Phase B1).

The properties under test, and why each one is here:

- **The key is encrypted at rest.** A test reads the row and proves the
  plaintext is not in it — the database file is the thing that gets copied,
  backed up and exfiltrated.
- **The key is never disclosed.** No status payload, no audit row, no log
  line, no exception carries it. The hint (last four characters) is the one
  deliberate, bounded disclosure.
- **One user's key is one user's key.** Another user's read is nothing, and
  even a superuser scope reads no farther than its own row: the platform's
  cross-owner audit exception does not extend to a private key.
- **The base URL is guarded.** It is a URL the *server* posts to with the
  user's key, so it passes the SSRF predicate; loopback is a development
  privilege only.
- **The resolution rule holds.** A stored credential is used; no credential
  falls back to the platform key unless the mode forbids it; undecryptable
  row material is a clear configuration error, never a silent fallback to
  the platform key.
- **A user's failures are the user's.** The circuit breaker and the rate
  limiter bucket are keyed per credential, so one broken key cannot open the
  platform's breaker.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.db import access
from src.db.access import UserScope
from src.db.base import Base
from src.db.byok import LlmCredentialDB
from src.llm import credentials as creds
from src.llm.client import SPEND_BYOK, SPEND_PLATFORM, LLMClient, LLMConfigError
from src.llm.errors import LLMCredentialError
from src.llm.providers import ProviderResponse
from src.llm.tenant import tenant_scope
from src.security.audit import AuditEventDB
from src.security.secrets import (
    SecretBoxUnavailable,
    decrypt_secret,
    encrypt_secret,
    key_material_source,
    reset_box,
)

ALICE = "alice"
BOB = "bob"

ALICE_KEY = "sk-alice-0123456789-verysecret"
BOB_KEY = "sk-bob-9876543210-alsosecret"


class DbEnv(SimpleNamespace):
    """A throwaway database: a session for the test, a factory for the code."""

    session: Session
    factory: sessionmaker
    engine: object


def _new_db(name: str = "byok.db", directory: Path | None = None) -> DbEnv:
    """A fresh SQLite database with every table (in-memory when no path)."""
    if directory is None:
        from sqlalchemy.pool import StaticPool

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    else:
        engine = create_engine(f"sqlite:///{(directory / name).as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return DbEnv(engine=engine, factory=factory, session=factory())


@pytest.fixture
def db(tmp_path: Path) -> DbEnv:
    return _new_db("byok.db", tmp_path)


@pytest.fixture(autouse=True)
def local_key_material(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Deterministic key material, and never inside the developer's data dir."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("BYOK_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    from src.config.settings import get_settings

    get_settings.cache_clear()
    reset_box()
    creds.reset_client_cache()
    yield
    # A settings-cached value must not outlive the fixture, and the settings
    # cache must not be left empty either: pytest tears the *conftest*
    # fixtures down after this one and before monkeypatch undoes the
    # environment, and one of them rebuilds Settings. A test that left
    # APP_ENV=production (with its companions deleted) or an invalid
    # BYOK_MODE behind would then fail in a teardown that has nothing to do
    # with it. Restore a constructible environment first, then clear.
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("BYOK_MODE", "optional")
    get_settings.cache_clear()
    reset_box()
    creds.reset_client_cache()


@pytest.fixture
def wired(db: DbEnv, monkeypatch: pytest.MonkeyPatch) -> DbEnv:
    """Point the module-level session factory at *db* (as a live app would)."""
    monkeypatch.setattr("src.db.session.SessionLocal", db.factory)
    return db


def _payload(
    api_key: str,
    *,
    provider: str = "google",
    model: str = "gemini-3.8-flash",
    base_url: str | None = None,
) -> creds.LlmCredentialInput:
    return creds.LlmCredentialInput(
        provider=provider, model=model, api_key=api_key, base_url=base_url
    )


def _store(db: Session, owner: str, api_key: str, **kwargs) -> creds.LlmCredentialStatus:
    return creds.store_credential(db, owner, _payload(api_key, **kwargs))


def _audit_rows(db: Session) -> list[AuditEventDB]:
    return list(db.execute(select(AuditEventDB)).scalars())


class _FakeProvider:
    """A provider that answers without a network (the WS-10 seam)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.name = "google"
        self.fail = fail
        self.requests: list[object] = []

    def complete(self, request) -> ProviderResponse:
        self.requests.append(request)
        if self.fail:
            # A rejected key is the realistic BYOK failure, and it is
            # deliberately not retryable — the client must not pace through
            # a backoff over a key that will never work.
            raise LLMConfigError("the provider rejected the API key")
        return ProviderResponse(text="ok", total_tokens=3)


# -- encryption at rest -------------------------------------------------------


class TestEncryptionAtRest:
    def test_the_stored_row_holds_a_token_not_the_key(self, db: DbEnv) -> None:
        _store(db.session, ALICE, ALICE_KEY)
        row = db.session.execute(select(LlmCredentialDB)).scalar_one()
        assert ALICE_KEY not in row.encrypted_key
        assert row.encrypted_key != ALICE_KEY
        assert decrypt_secret(row.encrypted_key) == ALICE_KEY

    def test_the_row_carries_only_a_bounded_hint(self, db: DbEnv) -> None:
        _store(db.session, ALICE, ALICE_KEY)
        row = db.session.execute(select(LlmCredentialDB)).scalar_one()
        assert row.hint == ALICE_KEY[-4:]
        assert row.hint != ALICE_KEY

    def test_encryption_round_trips(self) -> None:
        token = encrypt_secret(ALICE_KEY)
        assert token != ALICE_KEY
        assert decrypt_secret(token) == ALICE_KEY

    def test_a_foreign_token_is_a_clear_configuration_error(self) -> None:
        from cryptography.fernet import Fernet

        foreign = Fernet(Fernet.generate_key())
        token = foreign.encrypt(b"something else").decode()
        with pytest.raises(SecretBoxUnavailable, match="could not be decrypted"):
            decrypt_secret(token)

    def test_the_development_key_file_lives_under_the_data_tree(self, db: DbEnv) -> None:
        from src.security.secrets import _local_key_file

        _store(db.session, ALICE, ALICE_KEY)
        assert key_material_source() == "local_file"
        assert _local_key_file().exists()


# -- the base URL guard -------------------------------------------------------


class TestBaseUrlGuard:
    def test_a_public_host_is_allowed(self) -> None:
        url = "https://93.184.216.34/v1"
        assert creds.validate_base_url(url) == url

    def test_loopback_is_a_development_privilege(self) -> None:
        assert creds.validate_base_url("http://127.0.0.1:8901/v1").startswith("http://127.0.0.1")

    def test_loopback_is_refused_outside_development(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(creds, "get_settings", lambda: SimpleNamespace(app_env="production"))
        with pytest.raises(ValueError, match="loopback"):
            creds.validate_base_url("http://127.0.0.1:8901/v1")

    def test_metadata_addresses_are_blocked(self) -> None:
        with pytest.raises(ValueError, match="internal or metadata"):
            creds.validate_base_url("http://169.254.169.254/latest")

    def test_a_non_http_scheme_is_refused(self) -> None:
        with pytest.raises(ValueError, match="http or https"):
            creds.validate_base_url("file:///etc/passwd")

    def test_an_unresolvable_host_is_refused(self) -> None:
        with pytest.raises(ValueError, match="does not resolve"):
            creds.validate_base_url("https://no-such-host.invalid/v1")

    def test_openai_compatible_requires_a_base_url(self) -> None:
        env = _new_db()
        with pytest.raises(ValueError, match="base_url is required"):
            creds.store_credential(
                env.session,
                ALICE,
                _payload("k" * 20, provider="openai-compatible", model="gpt-4o-mini"),
            )

    def test_the_vendor_aliases_carry_their_defaults(self) -> None:
        env = _new_db()
        status = creds.store_credential(
            env.session, ALICE, _payload("k" * 20, provider="openai", model="gpt-4o-mini")
        )
        assert status.base_url == "https://api.openai.com/v1"


# -- storing, reading, deleting ----------------------------------------------


class TestStoreAndState:
    def test_a_stored_credential_is_the_one_in_use(self, db: DbEnv) -> None:
        status = _store(db.session, ALICE, ALICE_KEY)
        assert status.hint == ALICE_KEY[-4:]
        state = creds.credential_state(db.session, ALICE)
        assert state.using == "user"
        assert state.credential is not None
        assert state.credential.provider == "google"
        assert state.available is True

    def test_no_credential_and_no_platform_key_is_none(self, db: DbEnv) -> None:
        # LLM_API_KEY is deleted by the fixture, so no key is configured.
        state = creds.credential_state(db.session, ALICE)
        assert state.credential is None
        assert state.platform_configured is False
        assert state.using == "none"

    def test_no_credential_with_a_platform_key_falls_back(self, db: DbEnv, monkeypatch) -> None:
        monkeypatch.setenv("LLM_API_KEY", "platform-key")
        from src.config.settings import get_settings

        get_settings.cache_clear()
        try:
            state = creds.credential_state(db.session, ALICE)
            assert state.using == "platform"
        finally:
            get_settings.cache_clear()

    def test_replacing_a_key_replaces_the_row(self, db: DbEnv) -> None:
        _store(db.session, ALICE, ALICE_KEY, model="gemini-3.8-flash")
        _store(db.session, ALICE, BOB_KEY, model="gemini-3.8-pro")
        rows = list(db.session.execute(select(LlmCredentialDB)).scalars())
        assert len(rows) == 1
        assert rows[0].hint == BOB_KEY[-4:]
        assert rows[0].model == "gemini-3.8-pro"
        assert decrypt_secret(rows[0].encrypted_key) == BOB_KEY

    def test_delete_removes_the_row_and_reports_it(self, db: DbEnv) -> None:
        _store(db.session, ALICE, ALICE_KEY)
        assert creds.delete_credential(db.session, ALICE) is True
        assert creds.delete_credential(db.session, ALICE) is False
        assert creds.credential_state(db.session, ALICE).credential is None

    def test_the_state_is_per_user(self, db: DbEnv) -> None:
        _store(db.session, ALICE, ALICE_KEY)
        assert creds.credential_state(db.session, ALICE).credential is not None
        assert creds.credential_state(db.session, BOB).credential is None


# -- isolation ----------------------------------------------------------------


class TestIsolation:
    def test_a_foreign_row_is_invisible(self, db: DbEnv) -> None:
        _store(db.session, ALICE, ALICE_KEY)
        assert access.get_llm_credential(db.session, UserScope(user_id=BOB)) is None

    def test_a_superuser_scope_reads_no_further_than_its_own(self, db: DbEnv) -> None:
        """The audit exception does not extend to a private key."""
        _store(db.session, ALICE, ALICE_KEY)
        platform = UserScope(user_id="operator", is_superuser=True)
        assert access.get_llm_credential(db.session, platform) is None

    def test_one_user_cannot_delete_anothers(self, db: DbEnv) -> None:
        _store(db.session, ALICE, ALICE_KEY)
        assert access.delete_llm_credential(db.session, UserScope(user_id=BOB)) is False
        assert access.get_llm_credential(db.session, UserScope(user_id=ALICE)) is not None


# -- resolution ---------------------------------------------------------------


class TestResolution:
    def test_a_stored_key_is_what_the_call_runs_on(self, wired: DbEnv) -> None:
        _store(wired.session, ALICE, ALICE_KEY, model="gemini-3.8-pro")
        with tenant_scope(ALICE):
            client = creds.resolve_client()
        assert isinstance(client, LLMClient)
        assert client.model == "gemini-3.8-pro"
        assert client.provider == "google"

    def test_no_tenant_resolves_to_the_platform_client(self, wired: DbEnv) -> None:
        from src.llm.client import get_client

        _store(wired.session, ALICE, ALICE_KEY)
        assert creds.resolve_client() is get_client()

    def test_no_credential_falls_back_when_the_mode_allows_it(
        self, wired: DbEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.llm.client import get_client

        monkeypatch.setenv("LLM_API_KEY", "platform-key")
        from src.config.settings import get_settings

        get_settings.cache_clear()
        try:
            with tenant_scope(ALICE):
                assert creds.resolve_client() is get_client()
        finally:
            get_settings.cache_clear()

    def test_the_required_mode_refuses_the_platform_key(
        self, wired: DbEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BYOK_MODE", "required")
        from src.config.settings import get_settings

        get_settings.cache_clear()
        try:
            with tenant_scope(ALICE), pytest.raises(LLMConfigError, match="requires your own"):
                creds.resolve_client()
        finally:
            get_settings.cache_clear()

    def test_the_disabled_mode_ignores_a_stored_key(
        self, wired: DbEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.llm.client import get_client

        _store(wired.session, ALICE, ALICE_KEY)
        monkeypatch.setenv("BYOK_MODE", "disabled")
        from src.config.settings import get_settings

        get_settings.cache_clear()
        try:
            with tenant_scope(ALICE):
                assert creds.resolve_client() is get_client()
        finally:
            get_settings.cache_clear()

    def test_a_rotation_takes_effect_without_a_restart(self, wired: DbEnv) -> None:
        _store(wired.session, ALICE, ALICE_KEY, model="gemini-3.8-flash")
        with tenant_scope(ALICE):
            first = creds.resolve_client()
        _store(wired.session, ALICE, BOB_KEY, model="gemini-3.8-pro")
        with tenant_scope(ALICE):
            second = creds.resolve_client()
        assert first.model == "gemini-3.8-flash"
        assert second.model == "gemini-3.8-pro"
        assert first is not second

    def test_a_same_model_key_rotation_still_takes_effect(self, wired: DbEnv) -> None:
        """The cache key includes the key material, not just the config."""
        _store(wired.session, ALICE, ALICE_KEY, model="gemini-3.8-flash")
        with tenant_scope(ALICE):
            first = creds.resolve_client()
        _store(wired.session, ALICE, BOB_KEY, model="gemini-3.8-flash")
        with tenant_scope(ALICE):
            second = creds.resolve_client()
        assert first is not second

    def test_the_users_breaker_and_spend_source_are_their_own(self, wired: DbEnv) -> None:
        _store(wired.session, ALICE, ALICE_KEY)
        with tenant_scope(ALICE):
            client = creds.resolve_client()
        assert client._breaker_key() == f"llm:byok:{ALICE}"
        assert client._spend_source == SPEND_BYOK

    def test_an_undecryptable_row_is_a_clear_error_not_a_fallback(self, wired: DbEnv) -> None:
        _store(wired.session, ALICE, ALICE_KEY)
        row = wired.session.execute(select(LlmCredentialDB)).scalar_one()
        row.encrypted_key = "not-a-fernet-token"
        wired.session.commit()
        with tenant_scope(ALICE), pytest.raises(LLMConfigError, match="re-register"):
            creds.resolve_client()
        # The platform client was not silently substituted.
        from src.llm.client import get_client

        assert get_client()._spend_source == SPEND_PLATFORM

    def test_one_users_broken_key_does_not_open_another_bucket(self, wired: DbEnv) -> None:
        _store(wired.session, ALICE, ALICE_KEY)
        _store(wired.session, BOB, BOB_KEY)
        with tenant_scope(ALICE):
            alice_client = creds.resolve_client()
        with tenant_scope(BOB):
            bob_client = creds.resolve_client()
        assert alice_client._breaker_key() != bob_client._breaker_key()
        assert alice_client._breaker_key() != f"llm:{alice_client.provider}"


# -- exercising the credential ------------------------------------------------


class TestCredentialExercise:
    def test_testing_a_credential_makes_one_small_call(
        self, wired: DbEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeProvider()
        monkeypatch.setattr("src.llm.credentials.build_provider", lambda *a, **k: fake)
        _store(wired.session, ALICE, ALICE_KEY)
        result = creds.test_credential(wired.session, ALICE)
        assert result["ok"] is True
        assert result["provider"] == "google"
        assert isinstance(result["latency_ms"], int)
        assert len(fake.requests) == 1
        wired.session.expire_all()
        row = wired.session.execute(select(LlmCredentialDB)).scalar_one()
        assert row.last_used_at is not None

    def test_a_failing_credential_reports_a_type_not_a_provider_message(
        self, db: DbEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.llm.credentials.build_provider", lambda *a, **k: _FakeProvider(fail=True)
        )
        _store(db.session, ALICE, ALICE_KEY)
        result = creds.test_credential(db.session, ALICE)
        assert result["ok"] is False
        # The provider's own words are replaced by ours, so the type is the
        # credential error rather than the provider's configuration error.
        assert result["error_type"] == "LLMCredentialError"

    def test_a_rejected_key_is_explained_in_our_words(
        self, wired: DbEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A provider 401 becomes a pointer at the credentials card."""
        monkeypatch.setattr(
            "src.llm.credentials.build_provider", lambda *a, **k: _FakeProvider(fail=True)
        )
        _store(wired.session, ALICE, ALICE_KEY)
        with tenant_scope(ALICE), pytest.raises(LLMCredentialError) as caught:
            client = creds.resolve_client()
            client.generate_text("hello")
        message = str(caught.value)
        assert "Profile → Model credentials" in message
        assert "the provider rejected the API key" not in message

    def test_testing_without_a_stored_key_is_a_configuration_error(self, db: DbEnv) -> None:
        with pytest.raises(LLMConfigError, match="No stored credential"):
            creds.test_credential(db.session, ALICE)


# -- the audit trail ----------------------------------------------------------


class TestAuditHygiene:
    """The audit writer opens its own session, so these tests wire the factory."""

    def test_the_key_never_reaches_the_audit_trail(self, wired: DbEnv) -> None:
        _store(wired.session, ALICE, ALICE_KEY)
        creds.delete_credential(wired.session, ALICE)
        wired.session.expire_all()
        rows = _audit_rows(wired.session)
        assert rows, "the store and the delete must both be audited"
        for row in rows:
            blob = f"{row.action} {row.resource} {row.extra_metadata} {row.actor}"
            assert ALICE_KEY not in blob

    def test_the_audit_row_names_the_provider_and_the_hint_only(self, wired: DbEnv) -> None:
        _store(wired.session, ALICE, ALICE_KEY, model="gemini-3.8-flash")
        wired.session.expire_all()
        row = _audit_rows(wired.session)[0]
        assert row.action == "llm.credential.set"
        metadata = row.extra_metadata or {}
        assert metadata.get("provider") == "google"
        assert metadata.get("model") == "gemini-3.8-flash"
        assert metadata.get("hint") == ALICE_KEY[-4:]
        # No key-shaped *name* either: the redaction filter drops those, so a
        # value smuggled under one would silently vanish from the trail.
        assert not any("key" in str(name).lower() for name in metadata)

    def test_the_exercise_route_is_audited(
        self, wired: DbEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.llm.credentials.build_provider", lambda *a, **k: _FakeProvider())
        _store(wired.session, ALICE, ALICE_KEY)
        creds.test_credential(wired.session, ALICE)
        wired.session.expire_all()
        actions = {row.action for row in _audit_rows(wired.session)}
        assert "llm.credential.test" in actions


# -- the deployment modes -----------------------------------------------------


class TestDeploymentModes:
    def _production_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
        monkeypatch.setenv("SUBMISSION_POLICY", "REQUIRE_APPROVAL")
        monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")

    def test_production_without_auth_secret_refuses_to_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The identity check is the first line: no secret, no startup.

        In production ``AUTH_SECRET`` is guaranteed by that check, so it is
        the fallback source BYOK actually uses there; a deployment that
        deleted it fails before the BYOK rule is even reached.
        """
        from src.config.settings import Settings

        self._production_env(monkeypatch)
        monkeypatch.delenv("BYOK_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("AUTH_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="AUTH_SECRET"):
            Settings()

    def test_a_mistyped_explicit_key_refuses_to_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.config.settings import Settings

        self._production_env(monkeypatch)
        monkeypatch.setenv("BYOK_ENCRYPTION_KEY", "not-a-fernet-key")
        monkeypatch.setenv("AUTH_SECRET", "s" * 48)
        with pytest.raises(RuntimeError, match="BYOK_ENCRYPTION_KEY is not a valid"):
            Settings()

    def test_an_explicit_key_satisfies_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cryptography.fernet import Fernet

        from src.config.settings import Settings

        self._production_env(monkeypatch)
        # AUTH_SECRET stays: the identity check requires it in production, so
        # it is never the variable under test here — the explicit key is.
        monkeypatch.setenv("AUTH_SECRET", "s" * 48)
        monkeypatch.setenv("BYOK_ENCRYPTION_KEY", Fernet.generate_key().decode())
        assert Settings().byok_mode == "optional"

    def test_auth_secret_satisfies_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config.settings import Settings

        self._production_env(monkeypatch)
        monkeypatch.delenv("BYOK_ENCRYPTION_KEY", raising=False)
        monkeypatch.setenv("AUTH_SECRET", "s" * 48)
        assert Settings().byok_mode == "optional"

    def test_the_disabled_mode_needs_no_key_material(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config.settings import Settings

        self._production_env(monkeypatch)
        monkeypatch.delenv("BYOK_ENCRYPTION_KEY", raising=False)
        monkeypatch.setenv("AUTH_SECRET", "s" * 48)
        monkeypatch.setenv("BYOK_MODE", "disabled")
        assert Settings().byok_mode == "disabled"

    def test_an_unknown_mode_refuses_to_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config.settings import Settings

        monkeypatch.setenv("BYOK_MODE", "sometimes")
        with pytest.raises(RuntimeError, match="BYOK_MODE"):
            Settings()


# -- the log surface ----------------------------------------------------------


def test_the_key_never_reaches_a_log_line(
    wired: DbEnv, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Store, resolve, exercise and delete — with the log captured throughout."""
    monkeypatch.setattr("src.llm.credentials.build_provider", lambda *a, **k: _FakeProvider())
    with caplog.at_level(logging.DEBUG):
        _store(wired.session, ALICE, ALICE_KEY)
        with tenant_scope(ALICE):
            creds.resolve_client()
        creds.test_credential(wired.session, ALICE)
        creds.delete_credential(wired.session, ALICE)
    assert ALICE_KEY not in caplog.text
