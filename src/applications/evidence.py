"""Evidence artifacts of a submission (WS-06 · SEC-14).

A submission is only a success when it left artifacts behind: a screenshot of
the confirmation page, and a trace of what the browser did. The paths are
stored **relative to the evidence directory** so a stored record stays
meaningful when the data directory moves.

:func:`missing_evidence_files` is the check the verify node uses: a result
that claims success but whose artifacts are gone is not verified.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.config.settings import get_settings

logger = logging.getLogger(__name__)


def evidence_dir() -> Path:
    """The directory the evidence artifacts live in."""
    return Path(get_settings().evidence_dir)


def resolve_evidence_path(path: str | None, owner_id: str | None = None) -> Path | None:
    """Resolve a stored evidence path.

    An absolute path is returned as it is. A bare file name is resolved
    inside the **owner's own** evidence directory (WS-14 · Phase B) —
    the shared evidence directory is the fallback for the rows that
    pre-date the per-user layout.

    The owner matters: the evidence of a run is written into the account
    that run was made for, so resolving the name against the shared
    directory would look for the artifact in the wrong place and report
    a **missing** evidence file for a submission that in fact left one
    behind. That failure is not cosmetic — a missing artifact downgrades
    a verified submission to ``verification_failed``.
    """
    if not path:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if owner_id:
        from src.storage.paths import KIND_EVIDENCE, user_dir

        try:
            return user_dir(owner_id, KIND_EVIDENCE) / candidate
        except Exception:  # noqa: BLE001 - an unusable owner falls back
            logger.warning("Could not resolve the owner's evidence directory: %s", owner_id)
    return evidence_dir() / candidate


def missing_evidence_files(evidence, owner_id: str | None = None) -> list[str]:
    """The evidence artifacts that were promised but are not on disk.

    Only the artifacts the result actually claims are checked: a result
    without a screenshot path is not "missing" a screenshot, it simply did not
    capture one.
    """
    missing: list[str] = []
    for label, path in (
        ("screenshot", getattr(evidence, "screenshot_path", None)),
        ("trace", getattr(evidence, "trace_path", None)),
    ):
        if not path:
            continue
        resolved = resolve_evidence_path(path, owner_id)
        if resolved is None or not resolved.exists():
            missing.append(label)
    return missing
