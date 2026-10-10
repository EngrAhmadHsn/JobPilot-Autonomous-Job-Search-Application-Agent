"""Deterministic resume parser: DOCX/TXT -> CandidateProfile.

Extracts only what the document actually says, section by section. There is no
fabricated fallback: if a file cannot be read, the parser raises instead of
inventing profile data (project rule: never fabricate candidate data).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from src.resume.profile import (
    CandidateProfile,
    EducationEntry,
    ExperienceEntry,
    PersonalInformation,
    ProjectEntry,
)

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_GPA_RE = re.compile(r"GPA\s*:?\s*([0-9.]+)\s*/\s*([0-9.]+)", re.IGNORECASE)
_YEAR_RANGE_RE = re.compile(
    r"(\b(?:19|20)\d{2}\b\s*(?:-|–|—|to)\s*(?:\b(?:19|20)\d{2}\b|present))", re.IGNORECASE
)
_DEGREE_RE = re.compile(r"bachelor|master|ph\.?d|b\.?sc|m\.?sc|associate|diploma", re.IGNORECASE)
_INSTITUTION_RE = re.compile(r"university|college|institute|academy|school", re.IGNORECASE)

# Section headings this parser recognizes (normalized: lowercase, letters/spaces only).
_SECTION_HEADINGS = {
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


def _normalize_heading(line: str) -> str:
    return re.sub(r"[^a-z ]", " ", line.lower()).strip()


def _is_bullet(text: str, style: str | None) -> bool:
    if style and "list" in style.lower():
        return True
    return text.lstrip().startswith(("-", "•", "·"))


def _read_docx_lines(path: Path) -> list[tuple[str, bool]]:
    from docx import Document

    document = Document(str(path))
    return [
        (p.text.strip(), _is_bullet(p.text, p.style.name if p.style else None))
        for p in document.paragraphs
        if p.text.strip()
    ]


def _read_txt_lines(path: Path) -> list[tuple[str, bool]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [(line.strip(), _is_bullet(line, None)) for line in text.splitlines() if line.strip()]


def _read_lines(file_path: str) -> list[tuple[str, bool]]:
    path = Path(file_path)
    if not path.is_file():
        raise ValueError(f"Resume file not found: {file_path}")
    if path.suffix.lower() == ".docx":
        return _read_docx_lines(path)
    if path.suffix.lower() in {".txt", ".md"}:
        return _read_txt_lines(path)
    raise ValueError(f"Unsupported resume format: {path.suffix!r} (use .docx or .txt)")


def _split_sections(
    lines: list[tuple[str, bool]],
) -> tuple[list[str], dict[str, list[tuple[str, bool]]]]:
    header: list[str] = []
    sections: dict[str, list[tuple[str, bool]]] = {}
    current: str | None = None
    for text, is_bullet in lines:
        heading = _SECTION_HEADINGS.get(_normalize_heading(text))
        if heading and not is_bullet:
            current = heading
            sections.setdefault(current, [])
            continue
        if current is None:
            header.append(text)
        else:
            sections[current].append((text, is_bullet))
    return header, sections


def _clean_bullet(text: str) -> str:
    return text.lstrip("-•·").strip()


def _parse_header(header: list[str]) -> dict:
    info: dict = {"name": "", "title": "", "email": "", "phone": "", "location": "", "website": ""}
    if header:
        raw_name = header[0]
        info["name"] = raw_name.title() if raw_name.isupper() else raw_name
    if len(header) > 1:
        second = header[1]
        if not (
            _EMAIL_RE.search(second) or _PHONE_RE.search(second) or _INSTITUTION_RE.search(second)
        ):
            info["title"] = second.title() if second.isupper() else second
    for line in header:
        if email := _EMAIL_RE.search(line):
            info["email"] = email.group(0)
        if phone := _PHONE_RE.search(line):
            info["phone"] = phone.group(0).strip()
        if website := re.search(r"\b[\w.-]+\.(?:com|io|dev|net|org|me)\b", line):
            info["website"] = website.group(0)
    contact = next((line for line in header if _EMAIL_RE.search(line)), "")
    if contact:
        leftover = _EMAIL_RE.sub("", _PHONE_RE.sub("", contact))
        parts = [p.strip(" |") for p in leftover.split("|")]
        info["location"] = next((p for p in parts if p and "." not in p), "")
    return info


def _parse_skills(rows: list[tuple[str, bool]]) -> tuple[list[str], dict[str, list[str]]]:
    skills: list[str] = []
    categories: dict[str, list[str]] = {}
    for text, _is_bullet in rows:
        if ":" in text:
            category, _, items = text.partition(":")
            parsed = [item.strip() for item in items.split(",") if item.strip()]
        else:
            category, parsed = "", [item.strip() for item in text.split(",") if item.strip()]
        for skill in parsed:
            if skill not in skills:
                skills.append(skill)
        if category.strip() and parsed:
            categories[category.strip()] = parsed
    return skills, categories


def _parse_education(rows: list[tuple[str, bool]]) -> list[dict]:
    entries: list[dict] = []
    for text, is_bullet in rows:
        if is_bullet:
            if entries:
                entries[-1].setdefault("details", []).append(_clean_bullet(text))
            continue
        if _DEGREE_RE.search(text):
            parts = [p.strip() for p in text.split("\t") if p.strip()]
            entry: dict = {"degree": parts[0]}
            date_match = _YEAR_RANGE_RE.search(text)
            if date_match:
                entry["dates"] = date_match.group(0)
            elif len(parts) > 1:
                entry["dates"] = parts[1]
            entries.append(entry)
        elif _INSTITUTION_RE.search(text):
            if entries:
                entries[-1]["institution"] = text
            else:
                entries.append({"institution": text})
        elif gpa := _GPA_RE.search(text):
            if entries:
                entries[-1]["gpa"] = f"{gpa.group(1)}/{gpa.group(2)}"
            else:
                entries.append({"gpa": f"{gpa.group(1)}/{gpa.group(2)}"})
        elif entries:
            entries[-1].setdefault("details", []).append(text)
    return entries


def _split_header_parts(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\t|\||—|–", text) if p.strip()]


def _parse_experience(rows: list[tuple[str, bool]]) -> list[dict]:
    entries: list[dict] = []
    for text, is_bullet in rows:
        if is_bullet:
            if entries:
                entries[-1].setdefault("bullets", []).append(_clean_bullet(text))
            continue
        parts = _split_header_parts(text)
        if len(parts) >= 2:
            entries.append(
                {
                    "title": parts[0],
                    "company": parts[1],
                    "dates": parts[2] if len(parts) > 2 else "",
                }
            )
        else:
            entries.append({"title": text, "company": "", "dates": ""})
    return entries


def _parse_projects(rows: list[tuple[str, bool]]) -> list[dict]:
    projects: list[dict] = []
    for text, is_bullet in rows:
        if is_bullet:
            if projects:
                projects[-1].setdefault("bullets", []).append(_clean_bullet(text))
            continue
        if "\t" in text:
            name_part, _, tech = text.partition("\t")
        elif " — " in text:
            name_part, _, tech = text.partition(" — ")
        elif " – " in text:
            name_part, _, tech = text.partition(" – ")
        else:
            name_part, tech = text, ""
        subtitle = ""
        for sep in (" — ", " – "):
            if sep in name_part:
                name_part, _, subtitle = name_part.partition(sep)
                break
        entry = {"name": name_part.strip(), "tech": tech.strip(), "bullets": []}
        if subtitle.strip():
            entry["subtitle"] = subtitle.strip()
        projects.append(entry)
    return projects


def _parse_list_section(rows: list[tuple[str, bool]]) -> list[str]:
    return [_clean_bullet(text) if is_bullet else text for text, is_bullet in rows]


def parse_resume(file_path: str) -> CandidateProfile:
    """Parse a resume file into a validated Pydantic candidate profile.

    Supports .docx (primary) and .txt/.md. All content is taken verbatim from
    the document; missing sections are simply empty. Run
    ``validate_candidate_profile`` on the result for the pipeline's
    validation step.

    Raises:
        ValueError: If the file does not exist or the format is unsupported.
    """
    lines = _read_lines(file_path)
    header, sections = _split_sections(lines)
    skills, categories = _parse_skills(sections["skills"]) if sections.get("skills") else ([], {})

    summary_texts = [text for text, _ in sections.get("summary", [])]
    return CandidateProfile(
        personal_information=PersonalInformation(**_parse_header(header)),
        summary=" ".join(summary_texts),
        skills=skills,
        skill_categories=categories,
        education=[EducationEntry(**entry) for entry in _parse_education(sections["education"])]
        if sections.get("education")
        else [],
        experience=[ExperienceEntry(**entry) for entry in _parse_experience(sections["experience"])]
        if sections.get("experience")
        else [],
        projects=[ProjectEntry(**entry) for entry in _parse_projects(sections["projects"])]
        if sections.get("projects")
        else [],
        certifications=(
            _parse_list_section(sections["certifications"])
            if sections.get("certifications")
            else []
        ),
        achievements=_parse_list_section(sections["achievements"])
        if sections.get("achievements")
        else [],
    )
