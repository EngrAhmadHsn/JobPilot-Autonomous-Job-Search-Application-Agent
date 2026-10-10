"""Factuality-first resume tailoring backed by the LLM brain.

The LLM may only select, emphasize, and rephrase facts that exist in the
candidate profile. A deterministic validator strips anything else (unknown
skills, unknown employers, inflated years) before the result is returned, per
the project rule: never fabricate candidate data.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from src.jobs.contracts import JobListing
from src.llm.client import get_client

logger = logging.getLogger(__name__)

GenerateFn = Callable[..., Any]

_YEAR_RE = re.compile(r"(\d+)\+?\s*(?:years?|yrs)\b", re.IGNORECASE)

SYSTEM_RULES = (
    "You tailor a candidate's resume for one specific job opening.\n"
    "STRICT FACTUALITY RULES:\n"
    "- Use ONLY facts explicitly present in the candidate profile.\n"
    "- Never invent skills, employers, job titles, dates, degrees, certifications,"
    " numbers, or achievements.\n"
    "- You may reorder, emphasize, and rephrase existing facts for the target job.\n"
)


class TailoredExperience(BaseModel):
    """One experience entry as it should appear in the tailored resume."""

    company: str = Field(description="Company name, copied exactly from the profile.")
    title: str = Field(description="Job title, copied exactly from the profile.")
    bullets: list[str] = Field(description="Achievement bullets rephrased from profile facts only.")


class TailoredProject(BaseModel):
    """One project entry as it should appear in the tailored resume."""

    name: str = Field(description="Project name, copied exactly from the profile.")
    bullets: list[str] = Field(description="Project bullets rephrased from profile facts only.")


class TailoredResume(BaseModel):
    """Tailored resume content produced from profile facts only."""

    summary: str = Field(description="Short professional summary using profile facts only.")
    highlighted_skills: list[str] = Field(
        description="Skills drawn from the profile that match the job."
    )
    experience: list[TailoredExperience]
    projects: list[TailoredProject] = Field(
        default_factory=list,
        description="Profile projects relevant to the job (use instead of invented employment).",
    )
    cover_letter: str = Field(description="Short cover letter draft using profile facts only.")


class FactualityReport(BaseModel):
    """Deterministic validation outcome for a tailored resume."""

    passed: bool
    removed_skills: list[str] = Field(default_factory=list)
    removed_experience: list[str] = Field(default_factory=list)
    removed_projects: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)


class TailoringResult(BaseModel):
    """Tailored content plus its factuality report."""

    tailored: TailoredResume
    factuality: FactualityReport


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9+#. ]", " ", value.lower()).strip()


def _skill_known(skill: str, profile_skills: list[str]) -> bool:
    candidate = _norm(skill)
    return bool(candidate) and any(
        candidate == _norm(known) or candidate in _norm(known) or _norm(known) in candidate
        for known in profile_skills
    )


def _name_known(name: str, known_names: list[str]) -> bool:
    """Match against known names with bidirectional normalized containment.

    Handles minor variants ("Agentic Labs" vs "Agentic Labs Inc."); an empty
    known-name list matches nothing, so fabricated entries are always stripped.
    """
    candidate = _norm(name)
    if not candidate:
        return False
    return any(
        candidate in _norm(known) or _norm(known) in candidate for known in known_names if known
    )


def _strip_exaggerated_years(text: str, max_years: int | None, violations: list[str]) -> str:
    """Drop sentences claiming more years of experience than the profile supports."""
    if max_years is None:
        return text
    kept: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        claimed = [int(n) for n in _YEAR_RE.findall(sentence)]
        excessive = [n for n in claimed if n > max_years]
        if excessive:
            violations.append(
                f"Removed claim of {excessive[0]} years of experience (profile max {max_years})"
            )
        else:
            kept.append(sentence)
    return " ".join(kept)


def _build_prompt(profile: dict, job: JobListing) -> str:
    safe_profile = {k: v for k, v in profile.items() if k != "raw_text_preview"}
    return (
        f"{SYSTEM_RULES}\n"
        f"Target job listing:\n{job.model_dump_json()}\n\n"
        f"Candidate profile:\n{json.dumps(safe_profile)}"
    )


def _default_generate[T: BaseModel](prompt: str, schema: type[T]) -> T:
    return get_client().generate_structured(prompt, schema)


def tailor_resume(
    profile: dict,
    job: JobListing,
    *,
    generate: GenerateFn | None = None,
) -> TailoringResult:
    """Tailor resume content for a job using only facts from the profile.

    Args:
        profile: Structured candidate profile (as produced by the resume parser).
        job: Normalized job listing to tailor for.
        generate: Optional injection point for structured generation
            (prompt, schema) -> schema instance; defaults to the configured LLM.

    Returns:
        TailoringResult with the tailored content and its factuality report.
        factuality.passed is False when anything had to be stripped; the
        returned content is always safe (violations removed, never passed on).
    """
    generate_fn = generate if generate is not None else _default_generate
    draft: TailoredResume = generate_fn(_build_prompt(profile, job), TailoredResume)

    profile_skills = [str(s) for s in profile.get("skills", [])]
    experience_entries = profile.get("experience", []) or []
    known_companies = [str(e.get("company", "")) for e in experience_entries if e.get("company")]
    known_projects = [
        str(p.get("name", "")) for p in (profile.get("projects", []) or []) if p.get("name")
    ]
    years_values = [int(e["years"]) for e in experience_entries if isinstance(e.get("years"), int)]
    max_years: int | None = max(years_values) if years_values else None

    violations: list[str] = []
    removed_skills = [s for s in draft.highlighted_skills if not _skill_known(s, profile_skills)]
    kept_skills = [s for s in draft.highlighted_skills if _skill_known(s, profile_skills)]

    kept_experience: list[TailoredExperience] = []
    removed_experience: list[str] = []
    for entry in draft.experience:
        if not _name_known(entry.company, known_companies):
            removed_experience.append(entry.company)
            violations.append(f"Removed experience for unknown company {entry.company!r}")
            continue
        bullets = [
            _strip_exaggerated_years(bullet, max_years, violations) for bullet in entry.bullets
        ]
        kept_experience.append(
            TailoredExperience(
                company=entry.company, title=entry.title, bullets=[b for b in bullets if b]
            )
        )

    kept_projects: list[TailoredProject] = []
    removed_projects: list[str] = []
    for project in draft.projects:
        if not _name_known(project.name, known_projects):
            removed_projects.append(project.name)
            violations.append(f"Removed project with unknown name {project.name!r}")
            continue
        bullets = [
            _strip_exaggerated_years(bullet, max_years, violations) for bullet in project.bullets
        ]
        kept_projects.append(TailoredProject(name=project.name, bullets=[b for b in bullets if b]))

    summary = _strip_exaggerated_years(draft.summary, max_years, violations)
    cover_letter = _strip_exaggerated_years(draft.cover_letter, max_years, violations)

    if removed_skills:
        violations.append(f"Removed {len(removed_skills)} skill(s) not present in profile")

    tailored = TailoredResume(
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
        logger.warning("Tailoring factuality violations stripped: %s", factuality.violations)
    return TailoringResult(tailored=tailored, factuality=factuality)
