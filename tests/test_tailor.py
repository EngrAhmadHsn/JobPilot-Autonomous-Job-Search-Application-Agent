"""Tests for factuality-first resume tailoring (offline, fake LLM)."""

from src.jobs.contracts import JobListing
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
    ProjectEntry,
)
from src.resume.tailor import (
    TailoredExperience,
    TailoredProject,
    TailoredResume,
    tailor_resume,
)

PROFILE = CandidateProfile(
    personal_information=PersonalInformation(name="Ahmad Hassan", email="ahmad@example.com"),
    experience=[ExperienceEntry(title="AI Engineer", company="Agentic Labs", years=5)],
    skills=["python", "langgraph", "pydantic", "fastapi", "playwright", "sqlalchemy"],
    projects=[
        ProjectEntry(name="Autonomous Job Agent", bullets=["Agentic AI job application system"])
    ],
    certifications=["AWS Certified ML Specialist"],
    achievements=["Built autonomous agent pipeline with LangGraph"],
)

JOB = JobListing(
    id="job-1",
    source="linkedin",
    title="AI Engineer",
    company="Acme AI",
    required_skills=["python", "langgraph"],
    preferred_skills=["fastapi"],
)


def _fake(highlighted_skills=None, experience=None, summary=None, cover_letter=None, projects=None):
    def generate(prompt, schema):
        return TailoredResume(
            summary=summary or "AI engineer with 5 years building agent pipelines.",
            highlighted_skills=highlighted_skills or ["python", "langgraph"],
            experience=experience
            or [
                TailoredExperience(
                    company="Agentic Labs",
                    title="AI Engineer",
                    bullets=["Built autonomous agent pipeline with LangGraph"],
                )
            ],
            projects=projects
            or [TailoredProject(name="Autonomous Job Agent", bullets=["Built agent pipeline"])],
            cover_letter=cover_letter or "I am excited about the AI Engineer role at Acme AI.",
        )

    return generate


def test_true_facts_pass_validation() -> None:
    result = tailor_resume(PROFILE, JOB, generate=_fake())
    assert result.factuality.passed is True
    assert result.tailored.highlighted_skills == ["python", "langgraph"]
    assert result.tailored.experience[0].company == "Agentic Labs"
    assert [p.name for p in result.tailored.projects] == ["Autonomous Job Agent"]


def test_fabricated_skill_is_stripped() -> None:
    result = tailor_resume(
        PROFILE, JOB, generate=_fake(highlighted_skills=["python", "kubernetes"])
    )
    assert result.factuality.passed is False
    assert "kubernetes" in result.factuality.removed_skills
    assert result.tailored.highlighted_skills == ["python"]


def test_unknown_company_is_stripped() -> None:
    fake_experience = [
        TailoredExperience(company="Fake Corp", title="AI Engineer", bullets=["Did things"]),
        TailoredExperience(company="Agentic Labs", title="AI Engineer", bullets=["Built agents"]),
    ]
    result = tailor_resume(PROFILE, JOB, generate=_fake(experience=fake_experience))
    assert result.factuality.passed is False
    assert "Fake Corp" in result.factuality.removed_experience
    assert [e.company for e in result.tailored.experience] == ["Agentic Labs"]


def test_fabricated_project_is_stripped() -> None:
    fake_projects = [
        TailoredProject(name="Made-Up Startup App", bullets=["Invented work"]),
        TailoredProject(name="Autonomous Job Agent", bullets=["Built agent pipeline"]),
    ]
    result = tailor_resume(PROFILE, JOB, generate=_fake(projects=fake_projects))
    assert result.factuality.passed is False
    assert "Made-Up Startup App" in result.factuality.removed_projects
    assert [p.name for p in result.tailored.projects] == ["Autonomous Job Agent"]


def test_exaggerated_years_are_removed_from_text() -> None:
    summary = "AI engineer focused on agents. I have 9 years of experience with agents."
    result = tailor_resume(PROFILE, JOB, generate=_fake(summary=summary))
    assert result.factuality.passed is False
    assert any("9 years" in v for v in result.factuality.violations)
    assert "9 years" not in result.tailored.summary
    assert "focused on agents" in result.tailored.summary


def test_prompt_carries_factual_constraints_and_inputs() -> None:
    captured = {}

    def generate(prompt, schema):
        captured["prompt"] = prompt
        return TailoredResume(
            summary="AI engineer with 5 years building agent pipelines.",
            highlighted_skills=["python"],
            experience=[
                TailoredExperience(
                    company="Agentic Labs",
                    title="AI Engineer",
                    bullets=["Built autonomous agent pipeline with LangGraph"],
                )
            ],
            cover_letter="I am excited about the AI Engineer role at Acme AI.",
        )

    tailor_resume(PROFILE, JOB, generate=generate)
    prompt = captured["prompt"].lower()
    assert "never invent" in prompt
    assert "ai engineer" in prompt  # job title present
    assert "python" in prompt  # profile skills present
