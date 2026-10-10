"""Requirement extraction: Job -> JobRequirements (plan #25 pipeline stage).

Deterministic-first per the plan's architectural principle: the listing's
structured skill fields are authoritative; the description is scanned for
mentions of known skills (listing + candidate) so prose requirements are not
ignored, but nothing is inferred that is not in the listing or the profile.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from src.jobs.contracts import JobListing


class JobRequirements(BaseModel):
    """Extracted requirements feeding the tailoring stage."""

    title: str = ""
    company: str = ""
    location: str = ""
    required: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)
    description_skill_mentions: list[str] = Field(
        default_factory=list,
        description="Skills seen in the description text that were not in the structured fields.",
    )


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9+#. ]", " ", value.lower()).strip()


def extract_requirements(
    job: JobListing, profile_skills: list[str] | None = None
) -> JobRequirements:
    """Extract job requirements deterministically from a normalized listing.

    Args:
        job: Normalized job listing.
        profile_skills: Optional candidate skills; when the description
            mentions one of them, it is reported as a description mention so
            the tailoring stage can emphasize it (it is never treated as a
            hard requirement the candidate lacks).

    Returns:
        JobRequirements with structured fields preserved and description
        mentions collected separately.
    """
    required = [s.strip() for s in job.required_skills if s.strip()]
    preferred = [s.strip() for s in job.preferred_skills if s.strip()]

    mentions: list[str] = []
    description = _norm(job.description or "")
    if description:
        seen = {_norm(s) for s in required + preferred}
        candidates = list(dict.fromkeys([*required, *preferred, *(profile_skills or [])]))
        for skill in candidates:
            token = _norm(skill)
            if token and token not in seen and token in description:
                mentions.append(skill)
                seen.add(token)

    return JobRequirements(
        title=job.title,
        company=job.company,
        location=job.location or "",
        required=required,
        preferred=preferred,
        description_skill_mentions=mentions,
    )
