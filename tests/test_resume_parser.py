"""Tests for the deterministic resume parser against the real DOCX fixture."""

from pathlib import Path

import pytest

from src.resume.parser import parse_resume
from src.resume.profile import CandidateProfile, validate_candidate_profile

FIXTURES = Path(__file__).parent / "fixtures"
RESUME_DOCX = FIXTURES / "Ahmad_Hassan_AI_Engineer_Resume.docx"


@pytest.fixture(scope="module")
def profile() -> CandidateProfile:
    return parse_resume(str(RESUME_DOCX))


def test_personal_information_extracted(profile: CandidateProfile) -> None:
    info = profile.personal_information
    assert info.name == "Ahmad Hassan"
    assert info.email.endswith("@gmail.com")
    assert info.phone.startswith("+92")
    assert "Pakistan" in info.location


def test_skills_extracted_from_categories(profile: CandidateProfile) -> None:
    skills = profile.skills
    assert "Python" in skills
    assert "Django" in skills
    assert "Prompt Engineering" in skills
    assert "MySQL" in skills
    categories = profile.skill_categories
    assert "Languages" in categories
    assert "AI & Machine Learning" in categories


def test_summary_extracted(profile: CandidateProfile) -> None:
    assert "large language model integration" in profile.summary


def test_education_extracted(profile: CandidateProfile) -> None:
    education = profile.education
    assert any("Bachelor of Computer Science" in e.degree for e in education)
    assert any("Islamia University" in e.institution for e in education)
    assert any(e.gpa == "3.99/4.0" for e in education)


def test_projects_extracted_with_bullets(profile: CandidateProfile) -> None:
    projects = {p.name: p for p in profile.projects}
    assert "SmartDiet" in projects
    assert "PowerEye" in projects
    assert "ExpenseTracker" in projects
    assert len(projects["SmartDiet"].bullets) >= 3
    assert "Groq API" in projects["SmartDiet"].tech


def test_certifications_and_achievements_extracted(profile: CandidateProfile) -> None:
    assert any("DataCamp" in cert for cert in profile.certifications)
    assert any("3.99" in achievement for achievement in profile.achievements)


def test_validation_passes_on_real_resume(profile: CandidateProfile) -> None:
    # The fixture resume is otherwise complete but has no experience section
    # and states no work preferences, so the documented neutral-scoring
    # warning (WS-03) is expected and nothing else.
    assert validate_candidate_profile(profile) == [
        (
            "Profile states no work preferences and has no experience entries; "
            "location/preference/seniority scoring will use neutral defaults"
        )
    ]


def test_validation_flags_empty_profile() -> None:
    warnings = validate_candidate_profile(CandidateProfile())
    assert any("no name" in w for w in warnings)
    assert any("no skills" in w for w in warnings)


def test_unsupported_format_raises(tmp_path: Path) -> None:
    fake_pdf = tmp_path / "resume.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(ValueError, match="Unsupported resume format"):
        parse_resume(str(fake_pdf))


def test_missing_file_raises() -> None:
    with pytest.raises(ValueError, match="not found"):
        parse_resume("tests/fixtures/does_not_exist.docx")


def test_website_is_not_taken_from_the_email_domain(tmp_path: Path) -> None:
    """An address such as ahmad@example.com must not become the website."""
    resume = tmp_path / "resume.txt"
    resume.write_text(
        "Ahmad Hassan\n"
        "AI Engineer\n"
        "ahmad@example.com | +49 30 1234567 | Berlin | ahmad.dev\n"
        "\n"
        "Professional Summary\n"
        "AI engineer building agent systems.\n",
        encoding="utf-8",
    )
    info = parse_resume(str(resume)).personal_information
    assert info.email == "ahmad@example.com"
    assert info.website == "ahmad.dev"
