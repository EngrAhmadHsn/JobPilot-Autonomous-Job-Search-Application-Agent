"""WS-05 tests: the tailoring API (src/api/routes/tailoring.py).

Runs the real FastAPI app against a throwaway SQLite database and a tmp
output directory. The language model is a fake injected through the
``get_generate_fn`` dependency, so the suite stays offline while the route,
the pipeline, the persistence and the rendered file are all real.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.db.tailored  # noqa: F401
from src.api.routes.tailoring import get_generate_fn
from src.config.settings import get_settings
from src.db.base import Base
from src.db.jobs import JobDB
from src.db.profiles import build_profile_row
from src.db.session import get_db
from src.jobs.contracts import JobListing
from src.main import app
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
    ProjectEntry,
)
from src.resume.tailor import TailoredExperience, TailoredProject

PROFILE = CandidateProfile(
    personal_information=PersonalInformation(
        name="Ahmad Hassan",
        title="AI Engineer",
        email="ahmad@example.com",
        phone="+49 30 1234567",
        location="Berlin, Germany",
    ),
    summary="AI engineer building agent systems.",
    skills=["python", "langgraph", "fastapi"],
    skill_categories={"Languages": ["python"], "Frameworks": ["langgraph", "fastapi"]},
    experience=[ExperienceEntry(title="AI Engineer", company="Agentic Labs", years=5)],
    projects=[ProjectEntry(name="Autonomous Job Agent", bullets=["Agent system"])],
)

JOB = JobListing(
    id="greenhouse:abc123",
    source="greenhouse",
    title="AI Engineer",
    company="Acme AI",
    location="Berlin, Germany",
    required_skills=["python", "langgraph"],
    preferred_skills=["fastapi"],
    description=(
        "You will build agent pipelines with LangGraph and Python.\n"
        "You will design REST APIs with FastAPI and write automated tests.\n"
    ),
)


def _fake_generate():
    """A deterministic generator for both the research and the tailoring call.

    The dependency override must be a zero-argument callable: FastAPI
    inspects a dependency's signature and would otherwise treat the
    generator's own parameters as request fields.
    """

    def generate(prompt, schema):
        if schema.__name__ == "JobInsights":
            return schema(
                responsibilities=["You will build agent pipelines with LangGraph and Python."],
                tech_stack=["Python", "LangGraph", "FastAPI"],
                summary="Agent pipelines built with LangGraph and Python.",
            )
        return schema(
            summary="AI engineer with 5 years building agent pipelines in Python.",
            highlighted_skills=["python", "langgraph", "fastapi"],
            experience=[
                TailoredExperience(
                    company="Agentic Labs",
                    title="AI Engineer",
                    bullets=["Built agent pipelines with LangGraph"],
                )
            ],
            projects=[
                TailoredProject(name="Autonomous Job Agent", bullets=["Built an agent system"])
            ],
            cover_letter="Dear hiring team, ...",
        )

    return generate


def _fabricating_generate():
    """A generator that invents a skill the profile does not support."""

    def generate(prompt, schema):
        if schema.__name__ == "JobInsights":
            return schema(summary="Agent pipelines built with LangGraph and Python.")
        return schema(
            summary="AI engineer with 5 years building agent pipelines in Python.",
            highlighted_skills=["python", "kubernetes"],
            experience=[
                TailoredExperience(
                    company="Agentic Labs",
                    title="AI Engineer",
                    bullets=["Built agent pipelines with LangGraph"],
                )
            ],
            projects=[],
            cover_letter="Dear hiring team, ...",
        )

    return generate


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient bound to a throwaway DB + tailored output dir."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_generate_fn] = lambda: _fake_generate()
    monkeypatch.setattr(get_settings(), "tailored_dir", str(tmp_path / "tailored"))
    # The seed helper writes through the same database the app serves.
    app.state.db_factory = factory
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.state.db_factory = None
    engine.dispose()


def _seed(api: TestClient) -> tuple[str, str]:
    """Store a profile and a job, returning their ids."""
    with app.state.db_factory() as db:
        row = build_profile_row(PROFILE, "resume.docx")
        db.add(row)
        db.add(
            JobDB(
                id=JOB.id,
                source=JOB.source,
                source_job_id=JOB.source_job_id,
                title=JOB.title,
                company=JOB.company,
                description=JOB.description,
                location=JOB.location,
                required_skills=JOB.required_skills,
                preferred_skills=JOB.preferred_skills,
            )
        )
        db.commit()
        return row.id, JOB.id


def test_tailor_returns_a_rendered_docx_and_reports(api: TestClient) -> None:
    profile_id, job_id = _seed(api)
    response = api.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id})

    assert response.status_code == 200
    body = response.json()
    assert body["tailoring_id"]
    assert body["profile_id"] == profile_id
    assert body["job_id"] == job_id
    assert body["factuality"]["passed"] is True
    assert body["ats_report"]["score"] > 0
    assert body["insights"]["tech_stack"] == ["Python", "LangGraph", "FastAPI"]

    # The deliverable exists on disk and is a real DOCX.
    docx_path = Path(body["docx_path"])
    assert docx_path.is_file()
    assert docx_path.suffix == ".docx"


def test_tailor_document_reparses_with_the_facts_intact(api: TestClient) -> None:
    from src.resume.parser import parse_resume

    profile_id, job_id = _seed(api)
    body = api.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id}).json()

    parsed = parse_resume(body["docx_path"])
    assert parsed.personal_information.name == "Ahmad Hassan"
    assert parsed.personal_information.email == "ahmad@example.com"
    assert [entry.company for entry in parsed.experience] == ["Agentic Labs"]
    assert parsed.experience[0].bullets == ["Built agent pipelines with LangGraph"]
    assert [project.name for project in parsed.projects] == ["Autonomous Job Agent"]


def test_factuality_violations_are_reported_with_200_not_an_error(api: TestClient) -> None:
    """A fabricated skill is stripped; the endpoint still answers 200."""

    app.dependency_overrides[get_generate_fn] = lambda: _fabricating_generate()
    profile_id, job_id = _seed(api)
    response = api.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id})

    assert response.status_code == 200
    body = response.json()
    assert body["factuality"]["passed"] is False
    assert "kubernetes" in body["factuality"]["removed_skills"]
    assert "kubernetes" not in body["tailored"]["highlighted_skills"]


def test_tailored_record_is_stored_and_served_again(api: TestClient) -> None:
    profile_id, job_id = _seed(api)
    created = api.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id}).json()

    fetched = api.get(f"/api/tailored/{created['tailoring_id']}")
    assert fetched.status_code == 200
    stored = fetched.json()
    assert stored["tailoring_id"] == created["tailoring_id"]
    assert stored["docx_path"] == created["docx_path"]
    assert stored["ats_report"]["score"] == created["ats_report"]["score"]
    assert stored["tailored"] == created["tailored"]
    assert stored["created_at"]


def test_unknown_ids_are_404(api: TestClient) -> None:
    response = api.post("/api/tailor", json={"profile_id": "nope", "job_id": "greenhouse:abc123"})
    assert response.status_code == 404
    response = api.post("/api/tailor", json={"profile_id": "nope", "job_id": "nope"})
    assert response.status_code == 404
    assert api.get("/api/tailored/does-not-exist").status_code == 404
