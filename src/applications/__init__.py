"""Application submission adapters and contracts."""

from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter

__all__ = [
    "ApplicationAdapter",
    "ApplicationRequest",
    "ApplicationResult",
    "FakeAtsPlaywrightAdapter",
    "PreparedApplication",
    "SubmissionEvidence",
]
