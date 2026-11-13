"""The tailoring pipeline: job facts -> tailored resume -> deliverable (WS-05).

This is the plan's #25 pipeline in one place, in the plan's order:

1. grounded job facts (research),
2. tailored content (LLM, factuality-validated),
3. the deliverable — the candidate's **own document**, edited in place where
   that is possible (WS-31), with a freshly rendered document as the reported
   fallback,
4. ATS analysis of that deliverable.

The stages are deterministic code, not a prompt: the model only fills the
tailored-content slot, and everything after it is verifiable.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from src.config.settings import ensure_dir, get_settings
from src.jobs.contracts import JobListing
from src.research.engine import JobInsights, research_job
from src.resume.ats import AtsReport, analyze_ats
from src.resume.edit import RenderReport, deliver_tailored_resume
from src.resume.profile import CandidateProfile
from src.resume.style import StyleReport
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
    #: WS-22: the deterministic style verdict on the delivered content.
    style: StyleReport
    insights: JobInsights
    docx_path: str
    #: WS-31: how the deliverable was produced — the candidate's own document
    #: edited in place, or a freshly formatted one. Defaults to the
    #: regenerated verdict, so an outcome built without the field (a test, an
    #: older caller) never claims an in-place edit that did not happen.
    render: RenderReport = Field(default_factory=RenderReport)


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
    upload_path: str | Path | None = None,
) -> TailoringOutcome:
    """Tailor a resume for one job and produce the deliverable.

    Args:
        profile: The candidate profile to tailor from.
        job: The job listing to tailor for.
        generate: Optional injection point for structured generation
            (prompt, schema) -> schema instance; defaults to the configured LLM.
        out_dir: Where the deliverable is written; defaults to the configured
            ``tailored`` directory.
        profile_id: Id used in the file name.
        job_id: Id of the target job; defaults to ``job.id``.
        upload_path: WS-31 — the résumé the profile was parsed from. When it is
            still on disk the deliverable is the candidate's **own document
            edited in place** (its fonts, section order and extra sections
            preserved); otherwise a fresh document is rendered and the
            outcome's ``render`` report says so.

    Returns:
        TailoringOutcome with the tailored content, the factuality report, the
        ATS report, the grounded insights, the path of the delivered file and
        the render report describing how it was produced.
    """
    target_id = job_id or job.id
    directory = Path(out_dir) if out_dir is not None else default_tailored_dir()

    insights = research_job(job, generate=generate)
    result = tailor_resume(profile, job, generate=generate, insights=insights)

    # WS-31: the deliverable is the candidate's own file with the tailored
    # wording edited into it. Every failure mode (no upload, an unreadable
    # file, an unsupported format) falls back to the WS-05 renderer and is
    # **reported** — never silently presented as an in-place edit.
    path, render_report = deliver_tailored_resume(
        result.tailored,
        profile,
        upload_path=upload_path,
        out_dir=directory,
        profile_id=profile_id,
        job_id=target_id,
    )

    report = analyze_ats(result.tailored, profile, job, docx_path=path)

    logger.info(
        "Tailoring complete",
        extra={
            "profile_id": profile_id,
            "job_id": target_id,
            "factuality_passed": result.factuality.passed,
            "ats_score": report.score,
            "render_mode": render_report.mode,
            "render_edits": render_report.edits,
        },
    )

    return TailoringOutcome(
        tailored=result.tailored,
        factuality=result.factuality,
        ats_report=report,
        style=result.style,
        insights=insights,
        docx_path=str(path.resolve()),
        render=render_report,
    )
