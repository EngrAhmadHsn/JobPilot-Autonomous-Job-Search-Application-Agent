"""WS-05 tests: the tailoring pipeline (src/resume/pipeline.py).

The pipeline wires research, tailoring, rendering and ATS analysis together
in the plan's order. These tests check the wiring (that the deliverable is
written before it is analysed, that the insights reach the tailoring prompt,
that the outcome is complete) — the components themselves are covered by
their own test modules.
"""

from __future__ import annotations

from pathlib import Path

from src.jobs.contracts import JobListing
from src.research.engine import JobInsights
from src.resume.pipeline import run_tailoring
from src.resume.profile import (
    CandidateProfile,
    EducationEntry,
    ExperienceEntry,
    PersonalInformation,
)
from src.resume.tailor import TailoredExperience

PROFILE = CandidateProfile(
    personal_information=PersonalInformation(
        name="Ahmad Hassan",
        title="AI Engineer",
        email="ahmad@example.com",
        location="Berlin, Germany",
    ),
    skills=["python", "langgraph"],
    skill_categories={"Languages": ["python"], "Frameworks": ["langgraph"]},
    education=[EducationEntry(degree="BSc Computer Science", institution="TU Berlin")],
    experience=[ExperienceEntry(title="AI Engineer", company="Agentic Labs", years=5)],
)

JOB = JobListing(
    id="greenhouse:abc123",
    source="greenhouse",
    title="AI Engineer",
    company="Acme AI",
    required_skills=["python", "langgraph"],
    preferred_skills=["fastapi"],
    description="You will build agent pipelines with LangGraph and Python.",
)


def _fake_generate(captured: dict):
    def generate(prompt, schema):
        captured.setdefault("prompts", []).append(prompt)
        if schema.__name__ == "JobInsights":
            return schema(
                responsibilities=["You will build agent pipelines with LangGraph and Python."],
                tech_stack=["Python", "LangGraph"],
                summary="Agent pipelines.",
            )
        return schema(
            summary="AI engineer with 5 years building agent pipelines in Python.",
            highlighted_skills=["python", "langgraph"],
            experience=[
                TailoredExperience(
                    company="Agentic Labs",
                    title="AI Engineer",
                    bullets=["Built agent pipelines with LangGraph"],
                )
            ],
            projects=[],
            cover_letter="Cover letter.",
        )

    return generate


def test_pipeline_writes_the_deliverable_and_reports_on_it(tmp_path: Path) -> None:
    captured: dict = {}
    outcome = run_tailoring(
        PROFILE,
        JOB,
        generate=_fake_generate(captured),
        out_dir=tmp_path,
        profile_id="prof1",
        job_id=JOB.id,
    )

    docx = Path(outcome.docx_path)
    assert docx.is_file()
    assert docx.name.startswith("prof1_greenhouse_abc123")

    # The ATS report describes the file that was just written.
    assert outcome.ats_report.format_risks == []
    assert outcome.ats_report.score > 0
    assert outcome.ats_report.section_completeness["contact"] is True
    assert outcome.ats_report.section_completeness["education"] is True

    # The insights reached the tailoring prompt, after the research call.
    assert len(captured["prompts"]) == 2
    assert "Job insights" in captured["prompts"][1]


def test_pipeline_result_is_complete_and_consistent(tmp_path: Path) -> None:
    captured: dict = {}
    outcome = run_tailoring(
        PROFILE,
        JOB,
        generate=_fake_generate(captured),
        out_dir=tmp_path,
        profile_id="prof1",
    )

    assert outcome.factuality.passed is True
    assert outcome.tailored.highlighted_skills == ["python", "langgraph"]
    assert isinstance(outcome.insights, JobInsights)
    assert outcome.insights.tech_stack == ["Python", "LangGraph"]
    # The job id defaults to the listing id.
    assert Path(outcome.docx_path).name.startswith("prof1_greenhouse_abc123")
