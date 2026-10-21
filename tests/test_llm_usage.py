"""Tests for the LLM usage record (WS-10 · Phase D).

The usage record is the only place where an LLM call leaves a trace, so the
tests care about two things: the counts really are there, and **nothing else
is** — no prompt, no answer, no key.
"""

from __future__ import annotations

from sqlalchemy import select

from src.db.audit import AuditEventDB
from src.llm.usage import (
    KIND_STRUCTURED,
    GenerationUsage,
    record_usage,
)
from src.security.audit import ACTION_LLM_USAGE

SECRET_PROMPT = "Candidate Ahmad Hassan, ahmad@example.com, +1 555 0101"


def _usage(**overrides) -> GenerationUsage:
    payload = {
        "provider": "google",
        "model": "gemini-3.8-flash",
        "kind": KIND_STRUCTURED,
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
        "duration_ms": 812,
        "attempts": 1,
    }
    payload.update(overrides)
    return GenerationUsage(**payload)


def _rows() -> list[AuditEventDB]:
    from src.db.session import SessionLocal

    with SessionLocal() as session:
        return list(
            session.scalars(select(AuditEventDB).where(AuditEventDB.action == ACTION_LLM_USAGE))
        )


class TestGenerationUsage:
    def test_the_audit_metadata_holds_the_counts(self) -> None:
        metadata = _usage().to_audit_metadata()
        assert metadata["usage_input"] == 120
        assert metadata["usage_output"] == 30
        assert metadata["usage_total"] == 150
        assert metadata["duration_ms"] == 812
        assert metadata["provider"] == "google"
        assert metadata["model"] == "gemini-3.8-flash"

    def test_the_counts_survive_the_redaction_filter(self) -> None:
        """The redaction filter drops keys containing "token" — the counts
        are named so that they still reach the audit row."""
        from src.security.redaction import sanitize_metadata

        sanitized = sanitize_metadata(_usage().to_audit_metadata())
        assert sanitized["usage_total"] == 150
        assert sanitized["usage_input"] == 120
        assert sanitized["usage_output"] == 30

    def test_the_metadata_carries_no_content(self) -> None:
        metadata = _usage().to_audit_metadata()
        assert "prompt" not in metadata
        assert "text" not in metadata
        assert "content" not in metadata


class TestRecordUsage:
    def test_a_row_is_written(self) -> None:
        before = len(_rows())
        record_usage(_usage())
        rows = _rows()
        assert len(rows) == before + 1
        row = rows[-1]
        assert row.resource == "llm:google:gemini-3.8-flash"
        assert row.outcome == "success"
        assert row.extra_metadata["usage_total"] == 150
        assert row.extra_metadata["attempts"] == 1

    def test_the_row_holds_no_prompt_content(self) -> None:
        record_usage(_usage())
        row = _rows()[-1]
        rendered = str(row.extra_metadata)
        assert "Ahmad" not in rendered
        assert "ahmad@example.com" not in rendered
        assert SECRET_PROMPT not in rendered

    def test_a_failed_call_is_recorded_as_an_error(self) -> None:
        record_usage(_usage(error_type="LLMRateLimited"), outcome="error")
        row = _rows()[-1]
        assert row.outcome == "error"
        assert row.extra_metadata["error_type"] == "LLMRateLimited"

    def test_a_failing_audit_store_never_breaks_the_call(self) -> None:
        """The caller's work must not die because the trail did."""
        import src.security.audit as audit_module

        def boom(*_args, **_kwargs):
            raise RuntimeError("the audit store is down")

        original = audit_module.record_audit
        audit_module.record_audit = boom
        try:
            record_usage(_usage())  # must not raise
        finally:
            audit_module.record_audit = original
