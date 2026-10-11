"""Tests for the research engine components (chroma store has its own file)."""

from src.research.engine import research_company, research_job_description


def test_research_company():
    result = research_company("Tech Corp")
    assert result["company"] == "Tech Corp"


def test_research_job_description():
    result = research_job_description("Python engineer needed")
    assert result["description_length"] == 22
