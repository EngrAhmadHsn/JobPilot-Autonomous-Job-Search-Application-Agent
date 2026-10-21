"""Token usage accounting for the LLM client (WS-10).

Every generation call is accounted for: which provider and model answered,
how many tokens were spent, how long the call took and how many attempts it
needed. The record is written to the append-only audit trail so the token
spend of the free tier is visible instead of guessed at.

**Counts only, never content.** The usage record holds no prompt, no answer
and no key — the prompt and the completion exist in memory for the duration
of the call and nowhere else.

The metadata key names are ``usage_input`` / ``usage_output`` /
``usage_total`` rather than the more natural ``*_tokens``, because the
redaction filter (``src/security/redaction.py``) drops any metadata key whose
name contains the substring ``token`` — a deliberately blunt rule, since a
masked secret is still a hint about its shape. That rule is a security
control and is not loosened for the sake of a prettier name; the counts are
read perfectly well as ``usage_total``.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# The kinds of call that are accounted for.
KIND_TEXT = "text"
KIND_STRUCTURED = "structured"


class GenerationUsage(BaseModel):
    """What one generation call cost."""

    provider: str
    model: str
    kind: str = KIND_TEXT
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    duration_ms: int = 0
    attempts: int = 1
    error_type: str | None = None

    def to_audit_metadata(self) -> dict[str, Any]:
        """The audit metadata for this call — counts only, never content."""
        return {
            "provider": self.provider,
            "model": self.model,
            "kind": self.kind,
            "usage_input": self.input_tokens,
            "usage_output": self.output_tokens,
            "usage_total": self.total_tokens,
            "duration_ms": self.duration_ms,
            "attempts": self.attempts,
            "error_type": self.error_type,
        }


def record_usage(
    usage: GenerationUsage,
    *,
    outcome: str = "success",
    workflow_id: str | None = None,
) -> None:
    """Write one usage record to the audit trail.

    Never raises: a failing audit store must not break an LLM call in
    flight. The failure is logged, and the caller carries on.
    """
    from src.security.audit import (
        ACTION_LLM_USAGE,
        OUTCOME_ERROR,
        OUTCOME_SUCCESS,
        SYSTEM_ACTOR,
        record_audit,
    )

    try:
        record_audit(
            action=ACTION_LLM_USAGE,
            actor=SYSTEM_ACTOR,
            resource=f"llm:{usage.provider}:{usage.model}",
            outcome=outcome or (OUTCOME_SUCCESS if usage.error_type is None else OUTCOME_ERROR),
            metadata=usage.to_audit_metadata(),
            workflow_id=workflow_id,
        )
    except Exception as exc:  # noqa: BLE001 - the audit store must never break a call
        logger.error("Could not record the LLM usage row: %s", exc)
