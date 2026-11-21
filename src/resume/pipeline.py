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
import re
from collections.abc import Sequence
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
    TailoredExperience,
    TailoredProject,
    TailoredResume,
    _name_known,
    _skill_known,
    _strip_exaggerated_years,
    _strip_injected,
    _title_known,
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


# -- WS-47: the studio's edit path --------------------------------------------
#
# The console can edit a stored tailoring's sections and save. The edit is a
# human's wording change, but the pipeline's rule does not move: the delivered
# content may only carry claims the candidate's profile states, and the
# deliverable is re-produced from what the edit actually left. These two
# functions are the edit path's whole domain logic, so the route stays a thin
# adapter and the flow stays verifiable exactly where the generation flow is.

#: A bullet marker at the start of an edited line — the same marker family the
#: in-place editor preserves (`src/resume/edit.py::_bullet_marker`), so a paste
#: from a markdown list survives the round trip.
_BULLET_PREFIX = re.compile(r"^\s*[-•·]\s*")


def _edit_lines(text: str) -> list[str]:
    """The bullet lines an edit carries: markers stripped, blanks dropped.

    The console's editor sends **one bullet per line**. A line's leading
    marker is the editor's decoration, not content; blank lines separate
    pasted lists and carry nothing.
    """
    lines: list[str] = []
    for line in text.splitlines():
        cleaned = _BULLET_PREFIX.sub("", line.strip()).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _rechunk(lines: list[str], counts: Sequence[int]) -> list[list[str]]:
    """Distribute *lines* across the entries that had *counts* bullets each.

    The mapping is positional, mirroring the editor's own rule (`bullet n` to
    `bullet n`): the first ``counts[0]`` lines belong to the first entry, the
    next ``counts[1]`` to the second, and so on. Lines beyond every entry's
    original count land on the **last** entry — the same place the in-place
    editor appends a bullet that has no original paragraph. Fewer lines shrink
    the entries the same way; an entry keeps its identity (company, title) and
    only its bullets change, which is what the factuality validator and the
    in-place editor both rely on.
    """
    chunks: list[list[str]] = []
    position = 0
    for count in counts:
        chunks.append(list(lines[position : position + count]))
        position += count
    if position < len(lines) and chunks:
        chunks[-1].extend(lines[position:])
    return chunks


def apply_tailored_edit(
    tailored: TailoredResume,
    *,
    summary: str | None = None,
    experience: str | None = None,
    projects: str | None = None,
    cover_letter: str | None = None,
) -> TailoredResume:
    """Apply the studio's section edits onto a tailored resume (WS-47).

    The request carries plain text; the resume is structured. The mapping is
    deliberately small and documented:

    - ``summary`` / ``cover_letter`` replace their field (whitespace trimmed);
    - ``experience`` / ``projects`` are one bullet per line, re-chunked onto
      the **existing** entries in order — no entry is added, removed or
      renamed, because the factuality validator guarantees every entry exists
      in the profile and the in-place editor matches entries by that identity.

    A field left as ``None`` leaves its section untouched, so the console can
    edit one section at a time.

    Raises:
        ValueError: when an ``experience`` or ``projects`` edit arrives for a
            resume with no such entries — the text has nowhere honest to go,
            and silently dropping accepted input is not an option.
    """
    entries = list(tailored.experience)
    if experience is not None and not entries:
        raise ValueError("The tailored resume has no experience entries to edit.")
    project_entries = list(tailored.projects)
    if projects is not None and not project_entries:
        raise ValueError("The tailored resume has no projects to edit.")

    updated = tailored.model_copy(deep=True)
    if summary is not None:
        updated.summary = summary.strip()
    if cover_letter is not None:
        updated.cover_letter = cover_letter.strip()
    if experience is not None:
        lines = _edit_lines(experience)
        chunks = _rechunk(lines, [len(entry.bullets) for entry in entries])
        updated.experience = [
            TailoredExperience(company=entry.company, title=entry.title, bullets=chunk)
            for entry, chunk in zip(entries, chunks, strict=True)
        ]
    if projects is not None:
        lines = _edit_lines(projects)
        chunks = _rechunk(lines, [len(project.bullets) for project in project_entries])
        updated.projects = [
            TailoredProject(name=project.name, bullets=chunk)
            for project, chunk in zip(project_entries, chunks, strict=True)
        ]
    return updated


def revalidate_tailored(
    tailored: TailoredResume, profile: CandidateProfile
) -> tuple[TailoredResume, FactualityReport]:
    """Re-run the factuality validator over an **edited** resume (WS-47).

    This is the generation validator's own check list, applied to content that
    arrived from the console instead of from the model — the same helpers
    ``tailor_resume`` uses, in the same order, so an edit cannot add a skill,
    an employer, a title or an inflated year the profile does not state:

    - skills the profile does not know are removed;
    - an experience entry with an unknown company is removed; a title that is
      not one the candidate held is stripped (the exact-match rule — an edit
      may not inflate "Engineer" into "Senior Staff Engineer");
    - a project with an unknown name is removed;
    - every text field loses sentences that claim more years of experience
      than the profile supports, and sentences that read as instructions
      (the console's text is trusted input, but the same deterministic strip
      is cheaper to reason about than an exception for one caller).

    What the validator strips is **removed from the content and reported**,
    never passed on and never treated as an error: the reduced content plus
    the report is the product, exactly as for a generation.
    """
    violations: list[str] = []

    profile_skills = list(profile.skills)
    known_companies = [e.company for e in profile.experience if e.company]
    known_titles = [e.title for e in profile.experience if e.title]
    known_projects = [p.name for p in profile.projects if p.name]
    years_values = [e.years for e in profile.experience if isinstance(e.years, int)]
    max_years: int | None = max(years_values) if years_values else None

    removed_skills = [
        s for s in tailored.highlighted_skills if not _skill_known(s, profile_skills)
    ]
    kept_skills = [s for s in tailored.highlighted_skills if _skill_known(s, profile_skills)]

    kept_experience: list[TailoredExperience] = []
    removed_experience: list[str] = []
    for entry in tailored.experience:
        if not _name_known(entry.company, known_companies):
            removed_experience.append(entry.company)
            violations.append(f"Removed experience for unknown company {entry.company!r}")
            continue
        title = entry.title
        if known_titles and not _title_known(title, known_titles):
            violations.append(
                f"Removed job title {title!r} for {entry.company!r}: not present in the profile"
            )
            title = ""
        bullets = [
            _strip_injected(
                _strip_exaggerated_years(bullet, max_years, violations),
                violations,
                where="experience bullet",
            )
            for bullet in entry.bullets
        ]
        kept_experience.append(
            TailoredExperience(company=entry.company, title=title, bullets=[b for b in bullets if b])
        )

    kept_projects: list[TailoredProject] = []
    removed_projects: list[str] = []
    for project in tailored.projects:
        if not _name_known(project.name, known_projects):
            removed_projects.append(project.name)
            violations.append(f"Removed project with unknown name {project.name!r}")
            continue
        bullets = [
            _strip_injected(
                _strip_exaggerated_years(bullet, max_years, violations),
                violations,
                where="project bullet",
            )
            for bullet in project.bullets
        ]
        kept_projects.append(TailoredProject(name=project.name, bullets=[b for b in bullets if b]))

    summary = _strip_injected(
        _strip_exaggerated_years(tailored.summary, max_years, violations),
        violations,
        where="summary",
    )
    cover_letter = _strip_injected(
        _strip_exaggerated_years(tailored.cover_letter, max_years, violations),
        violations,
        where="cover letter",
    )

    if removed_skills:
        violations.append(f"Removed {len(removed_skills)} skill(s) not present in profile")

    revalidated = TailoredResume(
        summary=summary,
        highlighted_skills=kept_skills,
        experience=kept_experience,
        projects=kept_projects,
        cover_letter=cover_letter,
    )
    factuality = FactualityReport(
        passed=not violations,
        removed_skills=removed_skills,
        removed_experience=removed_experience,
        removed_projects=removed_projects,
        violations=violations,
    )
    if not factuality.passed:
        logger.warning("Edited tailoring factuality violations stripped: %s", factuality.violations)
    return revalidated, factuality
