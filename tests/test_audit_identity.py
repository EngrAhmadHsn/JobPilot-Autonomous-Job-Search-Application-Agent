"""WS-14 · Phase C — the audit actor is a principal (threat T8).

**The property under test:** an audit row says *who* did it, in a way
that cannot be forged, cannot be misread, and cannot be used to forge
another row.

Three things are proved here:

- the **actor is a principal** — a kind and an id — and the human-
  readable label is *derived* from them, so the three can never
  disagree;
- **log injection is closed**: a newline in a user-supplied field cannot
  forge a row, because every string that reaches the store is stripped
  of its control characters;
- the **audit read is owner-scoped**: a user sees their own trail and
  nobody else's.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.audit import AuditEventDB
from src.db.base import Base
from src.db.session import get_db
from src.main import app
from src.security.audit import (
    ACTOR_KIND_AGENT,
    ACTOR_KIND_SYSTEM,
    ACTOR_KIND_USER,
    Actor,
    record_audit,
)
from src.security.redaction import sanitize_metadata, strip_control_characters


@pytest.fixture
def session(tmp_path: Path):
    """A throwaway database."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'audit.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        yield db
    engine.dispose()


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient over a throwaway database."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'audit_api.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


# -- the actor is a principal --------------------------------------------------


class TestTheActorIsAPrincipal:
    def test_an_actor_has_a_kind_and_an_id(self) -> None:
        actor = Actor.user("alice")
        assert actor.kind == ACTOR_KIND_USER
        assert actor.id == "alice"
        assert actor.label == "user:alice"

    def test_the_label_is_derived_not_supplied(self) -> None:
        """The parts are the truth; the label is what an operator reads."""
        assert Actor.user("alice").label == "user:alice"
        assert Actor.agent("fake-ats").label == "agent:fake-ats"
        assert Actor.system().label == "system"

    def test_an_unknown_kind_is_refused(self) -> None:
        with pytest.raises(ValueError):
            Actor(kind="wizard", id="merlin")

    def test_the_old_labels_are_read_back_into_the_right_kind(self) -> None:
        """The labels that pre-date this class are attributed correctly."""
        assert Actor.parse("system").kind == ACTOR_KIND_SYSTEM
        assert Actor.parse("user:alice").kind == ACTOR_KIND_USER
        assert Actor.parse("user:alice").id == "alice"
        assert Actor.parse("human:ada").kind == ACTOR_KIND_USER
        assert Actor.parse("human:ada").id == "ada"
        assert Actor.parse("api").kind == ACTOR_KIND_AGENT
        assert Actor.parse("").kind == ACTOR_KIND_SYSTEM

    def test_the_stored_row_carries_the_parts(self, session) -> None:
        record_audit(
            "auth",
            actor=Actor.user("alice"),
            resource="profile-1",
            outcome="success",
            owner_id="alice",
            session=session,
        )
        row = session.query(AuditEventDB).one()
        assert row.actor == "user:alice"
        assert row.actor_kind == ACTOR_KIND_USER
        assert row.actor_id == "alice"

    def test_a_label_is_parsed_into_a_principal(self, session) -> None:
        record_audit(
            "auth",
            actor="user:bob",
            resource="profile-2",
            outcome="success",
            owner_id="bob",
            session=session,
        )
        row = session.query(AuditEventDB).one()
        assert row.actor_kind == ACTOR_KIND_USER
        assert row.actor_id == "bob"


# -- log injection -------------------------------------------------------------


class TestLogInjectionIsClosed:
    """A newline in a user-supplied field must not be able to forge a row."""

    def test_a_newline_in_the_resource_is_removed(self, session) -> None:
        record_audit(
            "application.prepare",
            actor=Actor.user("alice"),
            resource="profile-1\napplication.submit\tresource=evil",
            outcome="success",
            owner_id="alice",
            session=session,
        )
        row = session.query(AuditEventDB).one()
        assert "\n" not in row.resource
        assert "\r" not in row.resource
        assert "\t" not in row.resource

    def test_a_newline_in_the_metadata_is_removed(self, session) -> None:
        record_audit(
            "application.prepare",
            actor=Actor.user("alice"),
            resource="profile-1",
            outcome="success",
            owner_id="alice",
            metadata={"note": "first line\nforged line"},
            session=session,
        )
        row = session.query(AuditEventDB).one()
        note = (row.extra_metadata or {})["note"]
        assert "\n" not in note
        assert note == "first lineforged line"

    def test_a_newline_in_the_actor_is_removed(self, session) -> None:
        record_audit(
            "auth",
            actor=Actor.user("alice\nforged"),
            resource="profile-1",
            outcome="success",
            owner_id="alice",
            session=session,
        )
        row = session.query(AuditEventDB).one()
        assert "\n" not in row.actor
        assert "\n" not in (row.actor_id or "")

    def test_the_stripping_is_applied_to_every_stored_string(self, session) -> None:
        record_audit(
            "auth",
            actor=Actor.user("alice"),
            resource="r",
            outcome="success",
            owner_id="alice",
            metadata={"a": "x\ny", "b": {"c": "p\rq"}, "d": ["s\nt"]},
            session=session,
        )
        row = session.query(AuditEventDB).one()
        metadata = row.extra_metadata or {}
        assert "\n" not in metadata["a"]
        assert "\r" not in metadata["b"]["c"]
        assert "\n" not in metadata["d"][0]

    def test_the_helper_itself_removes_the_control_characters(self) -> None:
        assert strip_control_characters("a\nb") == "ab"
        assert strip_control_characters("a\rb") == "ab"
        assert strip_control_characters("a\x00b") == "ab"
        assert strip_control_characters("a\x7fb") == "ab"
        assert strip_control_characters("a\tb") == "ab"
        assert strip_control_characters("plain") == "plain"
        assert strip_control_characters("") == ""

    def test_the_metadata_sanitiser_strips_too(self) -> None:
        sanitized = sanitize_metadata({"note": "a\nb"})
        assert "\n" not in sanitized["note"]

    def test_the_actor_label_cannot_contain_a_newline(self) -> None:
        assert "\n" not in Actor.user("a\nb").label
        assert "\n" not in Actor.agent("a\nb").label


# -- the owner-scoped read -----------------------------------------------------


class TestTheAuditReadIsOwnerScoped:
    def test_a_user_sees_only_their_own_trail(self, api: TestClient) -> None:
        from src.db import access
        from src.db.access import UserScope

        alice = UserScope(user_id="alice")
        bob = UserScope(user_id="bob")

        with next(api.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
            record_audit(
                "auth",
                actor=Actor.user("alice"),
                resource="profile-1",
                outcome="success",
                owner_id="alice",
                session=db,
            )
            record_audit(
                "auth",
                actor=Actor.user("bob"),
                resource="profile-2",
                outcome="success",
                owner_id="bob",
                session=db,
            )

            alice_rows = access.list_audit_events(db, alice)
            bob_rows = access.list_audit_events(db, bob)

        assert [row.resource for row in alice_rows] == ["profile-1"]
        assert [row.resource for row in bob_rows] == ["profile-2"]

    def test_the_platform_audit_view_may_read_across_owners(self, api: TestClient) -> None:
        """The one deliberate exception: a superuser scope."""
        from src.db import access
        from src.db.access import UserScope

        with next(api.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
            record_audit(
                "auth",
                actor=Actor.user("alice"),
                resource="profile-1",
                outcome="success",
                owner_id="alice",
                session=db,
            )
            rows = access.list_audit_events(db, UserScope(user_id="auditor", is_superuser=True))

        assert len(rows) == 1
