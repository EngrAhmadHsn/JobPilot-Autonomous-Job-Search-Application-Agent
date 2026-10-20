"""Tests for the research engine components (chroma store has its own file).

The engine's real behaviour — grounding, injection filtering, the company
aggregation — is covered by ``tests/test_research.py`` (WS-05). This file
keeps the smoke-level contract of the public functions.
"""

from src.jobs.contracts import JobListing
from src.research.engine import JobInsights, research_company, research_job


def _fake_generate(prompt, schema):
    return schema(
        responsibilities=["You will build agent pipelines with Python."],
        tech_stack=["Python"],
        summary="Agent pipelines with Python.",
    )


def test_research_company_without_listings():
    result = research_company("Tech Corp")
    assert result.name == "Tech Corp"
    assert result.job_count == 0
    assert result.titles == []


def test_research_job_returns_grounded_insights():
    job = JobListing(
        id="j1",
        source="greenhouse",
        title="Python Engineer",
        company="Tech Corp",
        description="You will build agent pipelines with Python.",
    )
    insights = research_job(job, generate=_fake_generate)
    assert isinstance(insights, JobInsights)
    assert insights.tech_stack == ["Python"]
    assert insights.responsibilities == ["You will build agent pipelines with Python."]
