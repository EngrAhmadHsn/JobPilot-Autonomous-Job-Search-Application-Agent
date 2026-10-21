"""Application submission adapters and contracts."""

from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter
from src.applications.form import (
    FormControl,
    FormPlan,
    FormQuestion,
    ProfileFacts,
    build_form_plan,
    facts_from_profile,
)

__all__ = [
    "ApplicationAdapter",
    "ApplicationRequest",
    "ApplicationResult",
    "FakeAtsPlaywrightAdapter",
    "FormControl",
    "FormPlan",
    "FormQuestion",
    "PreparedApplication",
    "ProfileFacts",
    "SubmissionEvidence",
    "build_form_plan",
    "facts_from_profile",
]
