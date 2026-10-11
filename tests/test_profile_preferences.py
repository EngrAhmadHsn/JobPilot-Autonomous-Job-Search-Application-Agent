"""Tests for WS-03 parser preference extraction (happy/absent paths).

The fabrication rule is the point: preferences appear only when the resume
text states them; a resume without preference statements yields an empty
WorkPreferences and no extra validation warnings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.resume.parser import parse_resume
from src.resume.profile import CandidateProfile, validate_candidate_profile


def write_resume(tmp_path: Path, content: str) -> str:
    path = tmp_path / "resume.txt"
    path.write_text(content, encoding="utf-8")
    return str(path)


SUMMARY = "Summary:\nBackend engineer with production experience.\n\n"


def test_preferences_extracted_from_summary_phrases(tmp_path: Path):
    resume = SUMMARY + (
        "Open to remote work. Looking for full-time roles.\n"
        "Willing to relocate to Amsterdam, Munich.\n"
        "Skills:\nLanguages: Python\n"
    )
    prefs = parse_resume(write_resume(tmp_path, resume)).work_preferences
    assert prefs.remote_preference == "remote"
    assert prefs.employment_types == ["full-time"]
    assert prefs.preferred_locations == ["Amsterdam", "Munich"]
    assert prefs.min_salary is None
    assert prefs.work_authorization is None


def test_preferences_extracted_from_labeled_lines(tmp_path: Path):
    resume = (
        "Jane Doe\nPreferences: hybrid, Berlin, salary $120k, no sponsorship required\n"
        "Skills:\nLanguages: Python\n"
    )
    prefs = parse_resume(write_resume(tmp_path, resume)).work_preferences
    assert prefs.remote_preference == "hybrid"
    assert prefs.preferred_locations == ["Berlin"]
    assert prefs.min_salary == "$120k"
    assert prefs.work_authorization == "no sponsorship required"


def test_salary_line_and_sponsorship_phrases(tmp_path: Path):
    resume = SUMMARY + (
        "Salary expectation: $120,000. Requires visa sponsorship.\nSkills:\nLanguages: Python\n"
    )
    prefs = parse_resume(write_resume(tmp_path, resume)).work_preferences
    assert prefs.min_salary == "$120,000"
    assert prefs.work_authorization == "requires sponsorship"


def test_remote_wins_when_both_remote_and_hybrid_mentioned(tmp_path: Path):
    resume = SUMMARY + "Open to remote work and hybrid arrangements.\nSkills:\nLanguages: Python\n"
    prefs = parse_resume(write_resume(tmp_path, resume)).work_preferences
    assert prefs.remote_preference == "remote"


def test_employment_type_captured_from_seeking_phrase(tmp_path: Path):
    resume = SUMMARY + "Seeking contract work.\nSkills:\nLanguages: Python\n"
    prefs = parse_resume(write_resume(tmp_path, resume)).work_preferences
    assert prefs.employment_types == ["contract"]


def test_resume_without_preferences_stays_empty(tmp_path: Path):
    # Fabrication test: nothing preference-like stated -> nothing inferred.
    resume = (
        "Bob Smith\nbob@example.com\n\n"
        + SUMMARY
        + "Skills:\nLanguages: Python\n\nExperience:\nEngineer, Corp\n2019 - 2023\n- Built things\n"
    )
    profile: CandidateProfile = parse_resume(write_resume(tmp_path, resume))
    assert profile.work_preferences.remote_preference is None
    assert profile.work_preferences.preferred_locations == []
    assert profile.work_preferences.min_salary is None
    assert profile.work_preferences.work_authorization is None
    assert profile.work_preferences.employment_types == []
    # The only warnings are the documented parse-completeness ones (none here).
    assert validate_candidate_profile(profile) == []


def test_no_preferences_and_no_experience_produce_documented_warning(tmp_path: Path):
    resume = "Bob Smith\nbob@example.com\n\n" + SUMMARY + "Skills:\nLanguages: Python\n"
    profile = parse_resume(write_resume(tmp_path, resume))
    # Both are documented warnings: no experience/projects, and the WS-03
    # neutral-scoring notice when preferences are also absent.
    assert validate_candidate_profile(profile) == [
        "Profile has neither experience nor projects",
        (
            "Profile states no work preferences and has no experience entries; "
            "location/preference/seniority scoring will use neutral defaults"
        ),
    ]


def test_everyday_prose_does_not_create_preferences(tmp_path: Path):
    # Skills/history must never be read as preferences (precision-first).
    resume = (
        "Summary:\n"
        "Worked remotely with a distributed team and led hybrid cloud migrations; "
        "handled the internship program and full-time recruiting.\n"
        "Skills:\nLanguages: Python\n"
        "Experience:\nRemote Team Lead, Corp\n2019 - 2023\n- Built things\n"
    )
    prefs = parse_resume(write_resume(tmp_path, resume)).work_preferences
    assert prefs.remote_preference is None
    assert prefs.employment_types == []
    assert prefs.work_authorization is None


def test_preferences_survive_docx_roundtrip(tmp_path: Path):
    docx = pytest.importorskip("docx")
    from docx import Document

    document = Document()
    document.add_paragraph("Jane Doe")
    document.add_paragraph("Summary")
    document.add_paragraph("Open to remote work. Salary expectation: 100k.")
    document.add_paragraph("Skills")
    document.add_paragraph("Languages: Python")
    path = tmp_path / "resume.docx"
    document.save(str(path))

    prefs = parse_resume(str(path)).work_preferences
    assert prefs.remote_preference == "remote"
    assert prefs.min_salary == "100k"
    assert docx is not None  # import marker for linters
