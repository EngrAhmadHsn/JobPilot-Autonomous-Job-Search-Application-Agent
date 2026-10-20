"""The tailoring pipeline: job facts -> tailored resume -> deliverable (WS-05).

This is the plan's #25 pipeline in one place, in the plan's order:

1. grounded job facts (research),
2. tailored content (LLM, factuality-validated),
3. rendered DOCX (the deliverable),
4. ATS analysis of that deliverable.

The stages are deterministic code, not a prompt: the model only fills the
tailored-content slot, and everything after it is verifiable.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from src.config.settings import ensure_dir, get_settings
from src.jobs.contracts import JobListing
from src.research.engine import JobInsights, research_job
from src.resume.ats import AtsReport, analyze_ats
from src.resume.profile import CandidateProfile
from src.resume.render import render_tailored_docx, tailored_docx_path
from src.resume.tailor import (
    FactualityReport,
    GenerateFn,
    TailoredResume,
    tailor_resume,
)

logger = logging.getLogger(__name__)


class TailoringOutcome(BaseModel):
    """Everything one tailoring run produced."""

    tailored: TailoredResume
    factuality: FactualityReport
    ats_report: AtsReport
    insights: JobInsights
    docx_path: str


def default_tailored_dir() -> Path:
    """The directory rendered resumes are written to."""
    return ensure_dir(get_settings().tailored_dir)


def run_tailoring(
    profile: CandidateProfile,
    job: JobListing,
    *,
    generate: GenerateFn | None = None,
    out_dir: Path | None = None,
    profile_id: str = "profile",
    job_id: str | None = None,
) -> TailoringOutcome:
    """Tailor a resume for one job and render the deliverable.

    Args:
        profile: The candidate profile to tailor from.
        job: The job listing to tailor for.
        generate: Optional injection point for structured generation
            (prompt, schema) -> schema instance; defaults to the configured LLM.
        out_dir: Where the DOCX is written; defaults to the configured
            ``tailored`` directory.
        profile_id: Id used in the file name.
        job_id: Id of the target job; defaults to ``job.id``.

    Returns:
        TailoringOutcome with the tailored content, the factuality report, the
        ATS report, the grounded insights and the path of the rendered file.
    """
    target_id = job_id or job.id
    directory = Path(out_dir) if out_dir is not None else default_tailored_dir()

    insights = research_job(job, generate=generate)
    result = tailor_resume(profile, job, generate=generate, insights=insights)

    path = tailored_docx_path(profile_id, target_id, directory)
    render_tailored_docx(result.tailored, profile, path)

    report = analyze_ats(result.tailored, profile, job, docx_path=path)

    logger.info(
        "Tailoring complete",
        extra={
            "profile_id": profile_id,
            "job_id": target_id,
            "factuality_passed": result.factuality.passed,
            "ats_score": report.score,
        },
    )

    return TailoringOutcome(
        tailored=result.tailored,
        factuality=result.factuality,
        ats_report=report,
        insights=insights,
        docx_path=str(path.resolve()),
    )
