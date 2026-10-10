"""Tests for Phase 5 hybrid matching engine."""

from src.jobs.contracts import JobListing
from src.matching.contracts import JobMatchResult
from src.matching.engine import calculate_match


def test_calculate_match_basic():
    job = JobListing(
        id="1",
        source="linkedin",
        title="Python Engineer",
        company="Tech",
        required_skills=["python", "sql"],
        preferred_skills=["aws"],
    )
    result = calculate_match(job, candidate_skills=["python", "sql", "aws"])
    assert isinstance(result, JobMatchResult)
    assert result.overall_score >= 0
    assert result.overall_score <= 100
    assert "python" in result.matched_requirements


def test_calculate_match_explanation():
    job = JobListing(
        id="2",
        source="indeed",
        title="DevOps",
        company="Cloud",
        required_skills=["kubernetes"],
    )
    result = calculate_match(job, candidate_skills=[])
    assert "kubernetes" in result.missing_requirements
    assert len(result.explanation) > 0
