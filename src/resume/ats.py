"""Deterministic ATS-style analysis of a tailored resume (plan §26, WS-05).

The analyzer measures a *deliverable*: the keyword coverage of the validated
tailored content, the completeness of its sections, the alignment of its title
with the job title, and the format risks of the rendered file.

Two rules bind this module:

- **No LLM anywhere.** The report is a pure function of its inputs, so the
  same inputs always produce the same report.
- **No keyword stuffing.** The analyzer *reports* what is missing; it never
  edits the resume and never proposes a skill the candidate profile does not
  support (plan §26: optimize for truthful relevance, not maximum keywords).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field

from src.core.text import STOPWORDS, content_tokens, normalize, tokenize
from src.jobs.contracts import JobListing
from src.jobs.requirements import extract_requirements
from src.resume.profile import CandidateProfile
from src.resume.tailor import TailoredResume

logger = logging.getLogger(__name__)

# --- Scoring constants (single source of truth, documented) -----------------

#: Weights of the four score components; they sum to 1.0.
ATS_WEIGHTS: dict[str, float] = {
    "keywords": 0.45,
    "sections": 0.20,
    "title_alignment": 0.20,
    "format_safety": 0.15,
}

#: A preferred keyword counts half as much as a required one.
PREFERRED_KEYWORD_WEIGHT = 0.5

#: Score used when the job declares no structured skills (coverage is unknown,
#: not perfect) — the same "evidence availability" discipline as FU-5.
NEUTRAL_KEYWORD_SCORE = 50.0

#: Score used when the candidate has no usable title to compare.
NEUTRAL_TITLE_ALIGNMENT = 50.0

#: Score used when there is no rendered file to inspect: nothing observed is
#: not the same as "no risk".
NEUTRAL_FORMAT_SAFETY = 100.0

#: Points deducted per distinct format risk.
FORMAT_RISK_PENALTY = 20.0

#: Sections a machine-readable resume is expected to carry.
REQUIRED_SECTIONS: tuple[str, ...] = ("contact", "summary", "skills", "experience", "education")

#: Headings the resume parser recognizes (mirrors ``parser._SECTION_HEADINGS``;
#: ``tests/test_ats.py`` asserts the two stay in sync).
STANDARD_HEADINGS: dict[str, str] = {
    "professional summary": "summary",
    "summary": "summary",
    "objective": "summary",
    "technical skills": "skills",
    "skills": "skills",
    "education": "education",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "projects": "projects",
    "certifications": "certifications",
    "achievements": "achievements",
}

#: Abbreviations expanded when comparing job and candidate titles. The original
#: token is kept as well, so "AI Engineer" and "Artificial Intelligence
#: Engineer" still match.
TITLE_ALIASES: dict[str, str] = {
    "ai": "artificial intelligence",
    "ml": "machine learning",
    "swe": "software engineer",
    "sde": "software engineer",
    "fe": "front end",
    "frontend": "front end",
    "be": "back end",
    "backend": "back end",
    "fullstack": "full stack",
    "sr": "senior",
    "jr": "junior",
    "pm": "product manager",
    "qa": "quality assurance",
    "ux": "user experience",
    "ui": "user interface",
    "db": "database",
    "ops": "operations",
    "eng": "engineer",
    "mgr": "manager",
}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_TEXTBOX_RE = re.compile(r"<(?:\w+:)?txbxContent\b")


class KeywordCoverage(BaseModel):
    """How much of the job's stated keyword surface the resume actually shows."""

    required_hit: list[str] = Field(default_factory=list)
    required_missing: list[str] = Field(default_factory=list)
    preferred_hit: list[str] = Field(default_factory=list)
    preferred_missing: list[str] = Field(default_factory=list)
    required_coverage: float = 0.0
    preferred_coverage: float = 0.0


class AtsReport(BaseModel):
    """Deterministic ATS analysis of one tailored resume."""

    keyword_coverage: KeywordCoverage
    section_completeness: dict[str, bool]
    format_risks: list[str] = Field(default_factory=list)
    title_alignment: float = 0.0
    score: float = 0.0
    notes: list[str] = Field(default_factory=list)


def _core_tokens(text: str) -> set[str]:
    """Content tokens of a title with abbreviations expanded.

    The abbreviation is *replaced* by its expansion, so "AI Engineer" and
    "Artificial Intelligence Engineer" describe the same title and align
    fully, while "Senior AI Engineer" keeps "senior" as a separate demand.
    """
    core: set[str] = set()
    for token in tokenize(text):
        if token in STOPWORDS:
            continue
        alias = TITLE_ALIASES.get(token)
        if alias:
            core.update(tokenize(alias))
        else:
            core.add(token)
    return core


def _keyword_supported(keyword: str, profile: CandidateProfile) -> bool:
    """True when one profile skill supports the keyword (token containment)."""
    wanted = set(content_tokens(keyword))
    if not wanted:
        return False
    for skill in profile.skills:
        available = set(tokenize(skill))
        if wanted <= available:
            return True
    return False


def _tailored_text(tailored: TailoredResume) -> str:
    """The searchable text of the validated tailored content."""
    parts: list[str] = [tailored.summary]
    parts.extend(tailored.highlighted_skills)
    for entry in tailored.experience:
        parts.extend([entry.title, entry.company, *entry.bullets])
    for project in tailored.projects:
        parts.extend([project.name, *project.bullets])
    return "\n".join(part for part in parts if part)


def _covers(keyword: str, text_tokens: set[str]) -> bool:
    """True when every content token of the keyword occurs in the text."""
    wanted = set(content_tokens(keyword))
    if not wanted:
        return False
    return wanted <= text_tokens


def _keyword_coverage(
    tailored: TailoredResume, job: JobListing
) -> tuple[KeywordCoverage, list[str], list[str], list[str], list[str]]:
    """Split the job's keywords into hit/missing against the tailored text."""
    requirements = extract_requirements(job)
    text_tokens = set(tokenize(_tailored_text(tailored)))

    required_hit = [k for k in requirements.required if _covers(k, text_tokens)]
    required_missing = [k for k in requirements.required if k not in required_hit]
    preferred_hit = [k for k in requirements.preferred if _covers(k, text_tokens)]
    preferred_missing = [k for k in requirements.preferred if k not in preferred_hit]

    coverage = KeywordCoverage(
        required_hit=required_hit,
        required_missing=required_missing,
        preferred_hit=preferred_hit,
        preferred_missing=preferred_missing,
        required_coverage=(len(required_hit) / len(requirements.required))
        if requirements.required
        else 0.0,
        preferred_coverage=(len(preferred_hit) / len(requirements.preferred))
        if requirements.preferred
        else 0.0,
    )
    return (
        coverage,
        requirements.required,
        requirements.preferred,
        required_missing,
        preferred_missing,
    )


def _keyword_score(coverage: KeywordCoverage, has_required: bool, has_preferred: bool) -> float:
    """Weighted keyword sub-score (0-100).

    Only the classes that exist contribute: an empty class adds no weight and
    does not dilute the other one. When the job states no skills at all the
    coverage is unknown, so the neutral value is used.
    """
    if not has_required and not has_preferred:
        return NEUTRAL_KEYWORD_SCORE
    total_weight = 0.0
    total = 0.0
    if has_required:
        total_weight += 1.0
        total += 1.0 * coverage.required_coverage
    if has_preferred:
        total_weight += PREFERRED_KEYWORD_WEIGHT
        total += PREFERRED_KEYWORD_WEIGHT * coverage.preferred_coverage
    return 100.0 * (total / total_weight)


def _section_completeness(tailored: TailoredResume, profile: CandidateProfile) -> dict[str, bool]:
    """Which sections the deliverable actually carries."""
    info = profile.personal_information
    has_contact = bool(info.name.strip()) and bool(info.email.strip() or info.phone.strip())
    return {
        "contact": has_contact,
        "summary": bool(tailored.summary.strip()),
        "skills": bool(tailored.highlighted_skills),
        "experience": bool(tailored.experience),
        "education": bool(profile.education),
    }


def _title_alignment(tailored: TailoredResume, profile: CandidateProfile, job: JobListing) -> float:
    """0-100 alignment between the candidate's title(s) and the job title."""
    job_title = (job.title or "").strip()
    candidate_titles = [profile.personal_information.title or ""]
    candidate_titles.extend(entry.title for entry in tailored.experience)
    candidate_text = " ".join(title for title in candidate_titles if title)

    if not job_title or not candidate_text:
        return NEUTRAL_TITLE_ALIGNMENT

    if normalize(job_title) == normalize(candidate_text):
        return 100.0

    job_tokens = _core_tokens(job_title)
    candidate_tokens = _core_tokens(candidate_text)
    if not job_tokens or not candidate_tokens:
        return NEUTRAL_TITLE_ALIGNMENT

    overlap = job_tokens & candidate_tokens
    return 100.0 * len(overlap) / len(job_tokens)


def _heading_key(text: str) -> str | None:
    """The standard section a heading line belongs to, if any."""
    return STANDARD_HEADINGS.get(re.sub(r"[^a-z ]", " ", text.lower()).strip())


def _format_risks(docx_path: Path) -> list[str]:
    """Format risks of a rendered resume, read from the file itself."""
    try:
        from docx import Document
    except ImportError:  # pragma: no cover - python-docx is a hard dependency
        logger.warning("python-docx unavailable; skipping format inspection")
        return []

    try:
        document = Document(str(docx_path))
    except Exception as exc:  # noqa: BLE001 - an unreadable file is reported, not raised
        logger.warning("Could not inspect rendered file: %s", exc)
        return [f"Could not inspect the rendered file: {type(exc).__name__}"]

    risks: list[str] = []
    paragraphs = [p for p in document.paragraphs if p.text.strip()]

    if document.tables:
        risks.append(f"Tables used for layout ({len(document.tables)} table(s))")

    textboxes = len(_TEXTBOX_RE.findall(document.element.xml))
    if textboxes:
        risks.append(f"Text boxes detected ({textboxes})")

    images = len(document.inline_shapes)
    if images:
        risks.append(f"{images} image(s) present; text inside images is not machine-readable")

    heading_indexes = [
        index for index, paragraph in enumerate(paragraphs) if _heading_key(paragraph.text)
    ]
    seen_sections: list[str] = []
    for index in heading_indexes:
        section = _heading_key(paragraphs[index].text)
        if section and section not in seen_sections:
            seen_sections.append(section)
    missing = [
        name
        for name in ("summary", "skills", "experience", "education")
        if name not in seen_sections
    ]
    if missing:
        risks.append(f"Missing standard section heading(s): {', '.join(missing)}")

    for index in heading_indexes:
        section = _heading_key(paragraphs[index].text)
        following = paragraphs[index + 1 :] if index + 1 < len(paragraphs) else []
        if not following or _heading_key(following[0].text):
            risks.append(f"Empty section: {section}")

    sizes: set[float] = set()
    fonts: set[str] = set()
    for index, paragraph in enumerate(paragraphs):
        if index in heading_indexes:
            continue
        style_size = getattr(paragraph.style, "font", None)
        default_size = style_size.size if style_size is not None else None
        default_font = style_size.name if style_size is not None else None
        for run in paragraph.runs:
            size = run.font.size or default_size
            if size is not None:
                sizes.add(round(size.pt, 1))
            font = run.font.name or default_font
            if font:
                fonts.add(font)
    if len(sizes) > 2:
        risks.append(f"{len(sizes)} distinct body font sizes (2 recommended)")
    if len(fonts) > 2:
        risks.append(f"{len(fonts)} distinct font families (2 recommended)")

    full_text = "\n".join(paragraph.text for paragraph in paragraphs)
    if not _EMAIL_RE.search(full_text) and not _PHONE_RE.search(full_text):
        risks.append("No machine-readable contact line")

    # One entry per distinct risk, in a stable order.
    unique: list[str] = []
    for risk in risks:
        if risk not in unique:
            unique.append(risk)
    return unique


def analyze_ats(
    tailored: TailoredResume,
    profile: CandidateProfile,
    job: JobListing,
    *,
    docx_path: Path | None = None,
) -> AtsReport:
    """Analyze a tailored resume for ATS-readiness.

    Args:
        tailored: The validated tailored content (already factuality-checked).
        profile: The candidate profile the tailored content came from.
        job: The job listing the resume targets.
        docx_path: Optional path of the rendered file; when given, format risks
            are read from it.

    Returns:
        AtsReport — deterministic, with no model call anywhere.
    """
    coverage, required, preferred, required_missing, preferred_missing = _keyword_coverage(
        tailored, job
    )
    sections = _section_completeness(tailored, profile)
    alignment = _title_alignment(tailored, profile, job)
    risks = _format_risks(docx_path) if docx_path is not None else []

    keyword_score = _keyword_score(coverage, bool(required), bool(preferred))
    section_score = (
        100.0 * sum(1 for present in sections.values() if present) / len(REQUIRED_SECTIONS)
    )
    format_score = (
        max(0.0, 100.0 - FORMAT_RISK_PENALTY * len(risks))
        if docx_path is not None
        else NEUTRAL_FORMAT_SAFETY
    )

    score = (
        ATS_WEIGHTS["keywords"] * keyword_score
        + ATS_WEIGHTS["sections"] * section_score
        + ATS_WEIGHTS["title_alignment"] * alignment
        + ATS_WEIGHTS["format_safety"] * format_score
    )

    notes: list[str] = []
    for keyword in required_missing:
        if _keyword_supported(keyword, profile):
            notes.append(
                f"Missing required keyword: {keyword} — supported by the profile but not "
                "surfaced in the tailored resume."
            )
        else:
            notes.append(
                f"Missing required keyword: {keyword} — not supported by the candidate profile."
            )
    for keyword in preferred_missing:
        notes.append(f"Missing preferred keyword: {keyword}.")
    for name in REQUIRED_SECTIONS:
        if not sections.get(name, False):
            notes.append(f"Section missing or empty: {name}.")
    if not required and not preferred:
        notes.append(
            "Job listing declares no structured skills; keyword coverage could not be measured."
        )
    if alignment < 50.0:
        notes.append("Tailored title does not align with the job title.")

    return AtsReport(
        keyword_coverage=coverage,
        section_completeness=sections,
        format_risks=risks,
        title_alignment=round(alignment, 1),
        score=round(min(100.0, max(0.0, score)), 1),
        notes=notes,
    )
