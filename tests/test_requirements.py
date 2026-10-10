"""Tests for deterministic job requirement extraction (plan #25 stage)."""

from src.jobs.contracts import JobListing
from src.jobs.requirements import extract_requirements


def _job(**overrides) -> JobListing:
    defaults = {
        "id": "job-1",
        "source": "greenhouse",
        "title": "AI Engineer",
        "company": "Acme AI",
        "required_skills": ["python", "sql"],
        "preferred_skills": ["django"],
        "description": "Build LLM features with Python, SQL and MySQL. Django experience a plus.",
    }
    defaults.update(overrides)
    return JobListing(**defaults)


def test_structured_fields_are_authoritative() -> None:
    reqs = extract_requirements(_job())
    assert reqs.required == ["python", "sql"]
    assert reqs.preferred == ["django"]
    assert reqs.title == "AI Engineer"
    assert reqs.company == "Acme AI"


def test_description_mentions_profile_skills() -> None:
    reqs = extract_requirements(_job(), profile_skills=["Python", "MySQL", "React"])
    assert "MySQL" in reqs.description_skill_mentions  # mentioned in prose only
    assert "React" not in reqs.description_skill_mentions  # not mentioned anywhere
    assert "django" not in reqs.description_skill_mentions  # already a structured requirement


def test_no_description_no_mentions() -> None:
    reqs = extract_requirements(_job(description=None), profile_skills=["MySQL"])
    assert reqs.description_skill_mentions == []


def test_empty_structured_fields() -> None:
    reqs = extract_requirements(_job(required_skills=[], preferred_skills=[]))
    assert reqs.required == []
    assert reqs.preferred == []
