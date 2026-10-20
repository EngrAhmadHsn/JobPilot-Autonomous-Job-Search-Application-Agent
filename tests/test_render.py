"""WS-05 tests: the DOCX renderer (src/resume/render.py).

The central test is the round-trip: a rendered resume is re-parsed with the
project's own parser and must still carry the candidate's name, contact
details, skills, companies, projects and bullets. Anything the renderer
invented or dropped would show up here.
"""

from __future__ import annotations

from pathlib import Path

from src.resume.parser import parse_resume
from src.resume.profile import (
    CandidateProfile,
    EducationEntry,
    ExperienceEntry,
    PersonalInformation,
    ProjectEntry,
)
from src.resume.render import render_tailored_docx, tailored_docx_path
from src.resume.tailor import TailoredExperience, TailoredProject, TailoredResume

FULL_PROFILE = CandidateProfile(
    personal_information=PersonalInformation(
        name="Ahmad Hassan",
        title="AI Engineer",
        email="ahmad@example.com",
        phone="+49 30 1234567",
        location="Berlin, Germany",
        website="ahmad.dev",
    ),
    summary="AI engineer building agent systems.",
    skills=["Python", "LangGraph", "FastAPI", "Pydantic"],
    skill_categories={
        "Languages": ["Python"],
        "Frameworks": ["LangGraph", "FastAPI", "Pydantic"],
    },
    education=[
        EducationEntry(
            degree="BSc Computer Science",
            institution="Technical University of Berlin",
            dates="2016-2020",
        )
    ],
    experience=[
        ExperienceEntry(
            title="AI Engineer",
            company="Agentic Labs",
            dates="2020-2023",
            years=3,
            bullets=["Built agent pipelines"],
        )
    ],
    projects=[ProjectEntry(name="Autonomous Job Agent", bullets=["End-to-end application system"])],
    certifications=["AWS Certified ML Specialist"],
    achievements=["Built an autonomous agent pipeline with LangGraph"],
)

FULL_TAILORED = TailoredResume(
    summary="AI engineer with 5 years building agent pipelines in Python.",
    highlighted_skills=["Python", "LangGraph", "FastAPI"],
    experience=[
        TailoredExperience(
            company="Agentic Labs",
            title="AI Engineer",
            bullets=[
                "Built agent pipelines with LangGraph",
                "Shipped REST APIs with FastAPI",
            ],
        )
    ],
    projects=[
        TailoredProject(
            name="Autonomous Job Agent",
            bullets=["Built an end-to-end application system"],
        )
    ],
    cover_letter="Dear hiring team, ...",
)

MINIMAL_PROFILE = CandidateProfile(
    personal_information=PersonalInformation(name="Ahmad Hassan", email="ahmad@example.com"),
    skills=["Python"],
    skill_categories={},
)

MINIMAL_TAILORED = TailoredResume(
    summary="",
    highlighted_skills=["Python"],
    experience=[],
    projects=[],
    cover_letter="",
)


def test_rendered_resume_reparses_with_all_facts_intact(tmp_path: Path) -> None:
    path = render_tailored_docx(FULL_TAILORED, FULL_PROFILE, tmp_path / "resume.docx")
    assert path.is_file()

    parsed = parse_resume(str(path))
    info = parsed.personal_information
    assert info.name == "Ahmad Hassan"
    assert info.title == "AI Engineer"
    assert info.email == "ahmad@example.com"
    assert info.phone == "+49 30 1234567"
    assert info.location == "Berlin, Germany"
    assert info.website == "ahmad.dev"

    # Skills and their categories survive the group-by-category rendering.
    assert set(parsed.skills) == {"Python", "LangGraph", "FastAPI"}
    assert parsed.skill_categories["Languages"] == ["Python"]
    assert parsed.skill_categories["Frameworks"] == ["LangGraph", "FastAPI"]

    # Experience: company, title, dates and every bullet.
    assert len(parsed.experience) == 1
    entry = parsed.experience[0]
    assert entry.company == "Agentic Labs"
    assert entry.title == "AI Engineer"
    assert entry.dates == "2020-2023"
    assert entry.bullets == [
        "Built agent pipelines with LangGraph",
        "Shipped REST APIs with FastAPI",
    ]

    # Projects.
    assert [project.name for project in parsed.projects] == ["Autonomous Job Agent"]
    assert parsed.projects[0].bullets == ["Built an end-to-end application system"]

    # Education, certifications and achievements.
    assert parsed.education[0].degree == "BSc Computer Science"
    assert parsed.education[0].institution == "Technical University of Berlin"
    assert parsed.certifications == ["AWS Certified ML Specialist"]
    assert parsed.achievements == ["Built an autonomous agent pipeline with LangGraph"]


def test_minimal_resume_renders_and_reparses(tmp_path: Path) -> None:
    path = render_tailored_docx(MINIMAL_TAILORED, MINIMAL_PROFILE, tmp_path / "minimal.docx")
    parsed = parse_resume(str(path))

    assert parsed.personal_information.name == "Ahmad Hassan"
    assert parsed.personal_information.email == "ahmad@example.com"
    assert parsed.skills == ["Python"]
    # Sections with no content are omitted, not rendered empty.
    assert parsed.experience == []
    assert parsed.projects == []
    assert parsed.education == []


def test_empty_sections_are_omitted_from_the_document(tmp_path: Path) -> None:
    from docx import Document

    path = render_tailored_docx(MINIMAL_TAILORED, MINIMAL_PROFILE, tmp_path / "empty.docx")
    headings = [p.text for p in Document(str(path)).paragraphs]
    assert "Experience" not in headings
    assert "Projects" not in headings
    assert "Education" not in headings
    assert "Professional Summary" not in headings
    assert "Technical Skills" in headings


def test_rendered_file_is_a_valid_docx(tmp_path: Path) -> None:
    from docx import Document

    path = render_tailored_docx(FULL_TAILORED, FULL_PROFILE, tmp_path / "valid.docx")
    document = Document(str(path))
    assert any("Ahmad Hassan" in paragraph.text for paragraph in document.paragraphs)


def test_path_is_deterministic_and_never_contains_illegal_characters(tmp_path: Path) -> None:
    first = tailored_docx_path("prof123", "greenhouse:abc123", tmp_path)
    second = tailored_docx_path("prof123", "greenhouse:abc123", tmp_path)
    assert first == second
    assert first.name.startswith("prof123_")
    assert first.suffix == ".docx"
    assert ":" not in first.name


def test_different_job_ids_never_collide(tmp_path: Path) -> None:
    a = tailored_docx_path("prof123", "greenhouse:abc", tmp_path)
    b = tailored_docx_path("prof123", "greenhouse:abc_", tmp_path)
    c = tailored_docx_path("prof123", "lever:abc", tmp_path)
    assert a != b
    assert a != c
    assert b != c


def test_renderer_creates_missing_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "resume.docx"
    path = render_tailored_docx(FULL_TAILORED, FULL_PROFILE, target)
    assert path.is_file()
