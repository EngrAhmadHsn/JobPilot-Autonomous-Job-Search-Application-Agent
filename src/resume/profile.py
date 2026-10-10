"""CandidateProfile contracts: Pydantic models for parsed resume data.

Implements the plan's Parser -> CandidateProfile -> Validation pipeline
(PHASE 2 - RESUME INTELLIGENCE): the parser emits a typed, validated profile
instead of a raw dict.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


class PersonalInformation(BaseModel):
    name: str = ""
    title: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    website: str = ""


class EducationEntry(BaseModel):
    degree: str = ""
    institution: str = ""
    dates: str = ""
    gpa: str = ""
    details: list[str] = Field(default_factory=list)


class ExperienceEntry(BaseModel):
    title: str = ""
    company: str = ""
    dates: str = ""
    bullets: list[str] = Field(default_factory=list)
    years: int | None = None


class ProjectEntry(BaseModel):
    name: str
    subtitle: str = ""
    tech: str = ""
    bullets: list[str] = Field(default_factory=list)


class CandidateProfile(BaseModel):
    """Structured candidate profile produced by the resume parser."""

    personal_information: PersonalInformation = Field(default_factory=PersonalInformation)
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    skill_categories: dict[str, list[str]] = Field(default_factory=dict)
    education: list[EducationEntry] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def validate_candidate_profile(profile: CandidateProfile) -> list[str]:
    """Deterministic validation step of the Phase 2 pipeline.

    Returns human-readable warnings; an empty list means the profile is
    well-formed enough for downstream use. Never raises, never mutates.
    """
    warnings: list[str] = []
    info = profile.personal_information
    if not info.name.strip():
        warnings.append("Profile has no name")
    if not info.email.strip() or not _EMAIL_RE.fullmatch(info.email):
        warnings.append("Profile has no parseable email")
    if not profile.skills:
        warnings.append("Profile has no skills extracted")
    if not profile.summary.strip():
        warnings.append("Profile has no summary")
    if not profile.experience and not profile.projects:
        warnings.append("Profile has neither experience nor projects")
    return warnings
