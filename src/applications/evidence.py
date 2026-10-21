"""Evidence artifacts of a submission (WS-06 · SEC-14).

A submission is only a success when it left artifacts behind: a screenshot of
the confirmation page, and a trace of what the browser did. The paths are
stored **relative to the evidence directory** so a stored record stays
meaningful when the data directory moves.

:func:`missing_evidence_files` is the check the verify node uses: a result
that claims success but whose artifacts are gone is not verified.
"""

from __future__ import annotations

from pathlib import Path

from src.config.settings import get_settings


def evidence_dir() -> Path:
    """The directory the evidence artifacts live in."""
    return Path(get_settings().evidence_dir)


def resolve_evidence_path(path: str | None) -> Path | None:
    """Resolve a stored evidence path against the evidence directory.

    An absolute path is returned as it is; a bare file name is resolved
    inside the evidence directory.
    """
    if not path:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return evidence_dir() / candidate


def missing_evidence_files(evidence) -> list[str]:
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
        resolved = resolve_evidence_path(path)
        if resolved is None or not resolved.exists():
            missing.append(label)
    return missing
