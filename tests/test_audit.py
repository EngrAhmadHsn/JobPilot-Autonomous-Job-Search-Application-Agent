"""WS-06 · Phase D — the append-only audit trail and its redaction (SEC-13 / SEC-12).

The audit trail is only trustworthy if it cannot leak a credential and cannot
silently lose a fact. These tests pin the sanitize matrix (secret keys
dropped, personal data masked, long strings truncated), the append-only
property of the store, and the fact that a failing audit store never breaks
the request that produced the event.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.core.logging import PiiMaskingFilter
from src.db.audit import AuditEventDB
from src.db.base import Base
from src.security import audit as audit_module
from src.security.audit import AuditEvent, record_audit
from src.security.redaction import (
    MAX_VALUE_CHARS,
    is_secret_key,
    mask_pii,
    sanitize_metadata,
)


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    """An isolated SQLite session with the audit table created."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'audit.db').as_posix()}")
    Base.metadata.create_all(engine, tables=[AuditEventDB.__table__])
    with Session(engine) as session:
        yield session
    engine.dispose()


class TestSanitizeMetadata:
    """The sanitize matrix."""

    def test_secret_keys_are_dropped_entirely(self) -> None:
        sanitized = sanitize_metadata(
            {
                "api_key": "sk-live-123",
                "API_KEY": "sk-live-123",
                "token": "abc",
                "access_token": "abc",
                "password": "hunter2",
                "secret": "s",
                "cookie": "c",
                "authorization": "Bearer x",
                "credential": "c",
                "job_url": "https://boards.greenhouse.io/acme/jobs/1",
            }
        )
        assert sanitized == {"job_url": "https://boards.greenhouse.io/acme/jobs/1"}

    def test_secret_keys_are_dropped_in_nested_structures(self) -> None:
        sanitized = sanitize_metadata(
            {"outer": {"api_key": "sk-live-123", "keep": "yes"}, "items": [{"password": "p"}]}
        )
        assert sanitized == {"outer": {"keep": "yes"}, "items": [{}]}

    def test_emails_are_masked(self) -> None:
        sanitized = sanitize_metadata({"email": "ahmad@example.com"})
        assert sanitized["email"] == "<email>"
        assert "ahmad" not in sanitized["email"]

    def test_phone_numbers_are_masked(self) -> None:
        sanitized = sanitize_metadata({"phone": "+1 555 0101"})
        assert sanitized["phone"] == "<phone>"

    def test_dates_are_not_mistaken_for_phone_numbers(self) -> None:
        sanitized = sanitize_metadata({"day": "2026-10-21"})
        assert sanitized["day"] == "2026-10-21"

    def test_long_strings_are_truncated(self) -> None:
        sanitized = sanitize_metadata({"blob": "x" * (MAX_VALUE_CHARS + 200)})
        assert len(sanitized["blob"]) < MAX_VALUE_CHARS + 100
        assert "truncated" in sanitized["blob"]

    def test_non_string_values_are_preserved(self) -> None:
        sanitized = sanitize_metadata({"count": 3, "ok": True, "none": None, "ratio": 0.5})
        assert sanitized == {"count": 3, "ok": True, "none": None, "ratio": 0.5}

    def test_empty_metadata(self) -> None:
        assert sanitize_metadata(None) == {}
        assert sanitize_metadata({}) == {}

    def test_is_secret_key(self) -> None:
        assert is_secret_key("api_key") is True
        assert is_secret_key("job_url") is False


class TestMaskPii:
    def test_mask_pii_masks_both_kinds(self) -> None:
        masked = mask_pii("write to ahmad@example.com or +1 555 0101")
        assert "<email>" in masked
        assert "<phone>" in masked

    def test_mask_pii_leaves_clean_text_alone(self) -> None:
        assert mask_pii("nothing sensitive here") == "nothing sensitive here"

    def test_mask_pii_handles_empty(self) -> None:
        assert mask_pii("") == ""


class TestRecordAudit:
    """The event is stored, sanitized, and correlated."""

    def test_event_is_written_to_the_store(self, db_session: Session) -> None:
        event = record_audit(
            audit_module.ACTION_PREPARE,
            actor="operator",
            resource="approval-1",
            outcome=audit_module.OUTCOME_SUCCESS,
            metadata={"api_key": "sk-live-123", "job_url": "https://greenhouse.io/x"},
            workflow_id="wf-1",
            session=db_session,
        )

        assert event.id is not None
        rows = db_session.scalars(select(AuditEventDB)).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.action == audit_module.ACTION_PREPARE
        assert row.actor == "operator"
        assert row.resource == "approval-1"
        assert row.outcome == audit_module.OUTCOME_SUCCESS
        assert row.workflow_id == "wf-1"
        # The secret never reached the row; the useful field did.
        assert "api_key" not in (row.extra_metadata or {})
        assert (row.extra_metadata or {})["job_url"] == "https://greenhouse.io/x"

    def test_returned_event_carries_sanitized_metadata(self, db_session: Session) -> None:
        event = record_audit(
            audit_module.ACTION_RESUME_UPLOAD,
            actor=audit_module.SYSTEM_ACTOR,
            resource="profile-1",
            outcome=audit_module.OUTCOME_SUCCESS,
            metadata={"email": "ahmad@example.com", "api_key": "sk-live-123"},
            session=db_session,
        )
        assert event.metadata == {"email": "<email>"}

    def test_a_failing_store_never_raises(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_args, **_kwargs):
            raise RuntimeError("audit store is down")

        monkeypatch.setattr(audit_module, "_write_row", _boom)

        event = record_audit(
            audit_module.ACTION_SUBMIT,
            actor=audit_module.SYSTEM_ACTOR,
            resource="approval-1",
            outcome=audit_module.OUTCOME_SUCCESS,
            session=db_session,
        )
        # The event is still produced — the log line remains the fallback trail.
        assert isinstance(event, AuditEvent)
        assert event.action == audit_module.ACTION_SUBMIT

    def test_events_are_ordered_by_id(self, db_session: Session) -> None:
        first = record_audit(
            audit_module.ACTION_PREPARE,
            actor="operator",
            resource="a",
            outcome=audit_module.OUTCOME_SUCCESS,
            session=db_session,
        )
        second = record_audit(
            audit_module.ACTION_APPROVE,
            actor="operator",
            resource="a",
            outcome=audit_module.OUTCOME_SUCCESS,
            session=db_session,
        )
        assert first.id is not None and second.id is not None
        assert second.id > first.id


class TestAppendOnly:
    """The audit store offers no way to rewrite history."""

    def test_the_module_exposes_no_update_or_delete_helper(self) -> None:
        forbidden = [
            name
            for name in dir(audit_module)
            if name.startswith(("update_", "delete_", "remove_", "purge_"))
        ]
        assert forbidden == []

    def test_the_db_module_exposes_no_update_or_delete_helper(self) -> None:
        from src.db import audit as db_audit

        forbidden = [
            name
            for name in dir(db_audit)
            if name.startswith(("update_", "delete_", "remove_", "purge_"))
        ]
        assert forbidden == []


class TestPiiMaskingFilter:
    """The logging filter masks personal data in every record."""

    def test_message_is_masked(self) -> None:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="candidate ahmad@example.com applied",
            args=None,
            exc_info=None,
        )
        PiiMaskingFilter().filter(record)
        assert "ahmad@example.com" not in record.msg
        assert "<email>" in record.msg

    def test_positional_args_are_masked(self) -> None:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="candidate %s applied",
            args=("ahmad@example.com",),
            exc_info=None,
        )
        PiiMaskingFilter().filter(record)
        assert record.args == ("<email>",)

    def test_mapping_args_are_masked(self) -> None:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="candidate %(email)s applied",
            args=({"email": "ahmad@example.com"},),
            exc_info=None,
        )
        PiiMaskingFilter().filter(record)
        assert record.args == {"email": "<email>"}

    def test_non_string_args_are_untouched(self) -> None:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="found %d jobs",
            args=(7,),
            exc_info=None,
        )
        PiiMaskingFilter().filter(record)
        assert record.args == (7,)
