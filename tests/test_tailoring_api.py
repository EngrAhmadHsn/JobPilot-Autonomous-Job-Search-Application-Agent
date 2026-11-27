"""WS-05 tests: the tailoring API (src/api/routes/tailoring.py).

Runs the real FastAPI app against a throwaway SQLite database and a tmp
output directory. The language model is a fake injected through the
``get_generate_fn`` dependency, so the suite stays offline while the route,
the pipeline, the persistence and the rendered file are all real.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import src.db.tailored  # noqa: F401
from src.api.routes.tailoring import get_generate_fn
from src.config.settings import get_settings
from src.db.base import Base
from src.db.jobs import JobDB
from src.db.profiles import build_profile_row
from src.db.session import get_db
from src.db.tailored import TailoredResumeDB
from src.db.users import LEGACY_OWNER_ID
from src.jobs.contracts import JobListing
from src.llm.errors import (
    LLMConfigError,
    LLMCredentialError,
    LLMDailyQuotaExhausted,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)
from src.main import app
from src.research.engine import JobInsights
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
    ProjectEntry,
)
from src.resume.tailor import TailoredExperience, TailoredProject, TailoredResume
from src.storage.paths import KIND_TAILORED, user_dir

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
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path / "data"))
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


# -- WS-31: the deliverable is the caller's own résumé, edited ----------------
#
# The seed above writes ``file_path="resume.docx"``, which does not exist, so
# those cases exercise the **reported** fallback: a fresh document. These cases
# put a real résumé on disk and assert that the route edits *that* file.


def _seed_with_upload(api: TestClient, tmp_path: Path, *, suffix: str = ".docx"):
    """Store a profile whose ``file_path`` is a real uploaded résumé."""
    with app.state.db_factory() as db:
        row = build_profile_row(PROFILE, "")
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
        # Commit once so the generated id is available for the file name.
        db.commit()

        if suffix == ".docx":
            upload = _write_resume_docx(tmp_path / f"{row.id}.docx")
        else:
            upload = tmp_path / f"{row.id}{suffix}"
            upload.write_text(
                "AHMAD HASSAN\n"
                "AI Engineer | ahmad@example.com | Berlin, Germany\n"
                "\n"
                "Technical Skills\n"
                "Languages: python, go\n"
                "\n"
                "Professional Summary\n"
                "AI engineer building agent systems.\n"
                "\n"
                "Experience\n"
                "AI Engineer | Agentic Labs\n"
                "- Built agent pipelines\n"
                "\n"
                "Education\n"
                "BSc Computer Science\n",
                encoding="utf-8",
            )
        row.file_path = str(upload)
        db.commit()
        return row.id, JOB.id, upload


def _write_resume_docx(path: Path) -> Path:
    """A résumé with a look the renderer would never produce."""
    from docx import Document
    from docx.shared import Pt

    document = Document()
    document.styles["Normal"].font.name = "Georgia"
    document.styles["Normal"].font.size = Pt(13)
    for text, style in (
        ("AHMAD HASSAN", None),
        ("AI Engineer | ahmad@example.com | Berlin, Germany", None),
        ("Technical Skills", "Heading 2"),
        ("Languages: python, go", None),
        ("Professional Summary", "Heading 2"),
        ("AI engineer building agent systems.", None),
        ("Experience", "Heading 2"),
        ("AI Engineer | Agentic Labs", None),
        ("Built agent pipelines", "List Bullet"),
        ("Education", "Heading 2"),
        ("BSc Computer Science", None),
    ):
        document.add_paragraph(text, style=style)
    document.save(str(path))
    return path


# -- optional research, required draft generation -----------------------------


_PROVIDER_DETAIL = "private provider detail"
_LISTING_SUMMARY = "AI Engineer at Acme AI — 2 required and 1 preferred skills listed."


@pytest.mark.parametrize("failure", ["timeout", "invalid-output", "invalid-payload"])
def test_research_failure_uses_listing_only_insights_for_a_real_draft(
    api: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    fake = _fabricating_generate()
    draft_prompts = []

    def generate(prompt, schema):
        if schema is JobInsights:
            if failure == "timeout":
                raise LLMTimeout(_PROVIDER_DETAIL)
            if failure == "invalid-output":
                raise LLMInvalidOutput(_PROVIDER_DETAIL)
            return {"summary": {"invalid": _PROVIDER_DETAIL}}
        assert schema is TailoredResume
        draft_prompts.append(prompt)
        return fake(prompt, schema)

    monkeypatch.setitem(app.dependency_overrides, get_generate_fn, lambda: generate)
    profile_id, job_id = _seed(api)
    with caplog.at_level(logging.DEBUG, logger="src.resume.pipeline"):
        http = TestClient(app, raise_server_exceptions=False)
        response = http.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["insights"] == {
        "summary": _LISTING_SUMMARY,
        "responsibilities": [],
        "tech_stack": [],
        "seniority_signals": [],
        "culture_flags": [],
    }
    assert len(draft_prompts) == 1
    assert _LISTING_SUMMARY in draft_prompts[0]
    assert _PROVIDER_DETAIL not in draft_prompts[0] + response.text + caplog.text
    assert (
        body["tailored"]["summary"]
        == "AI engineer with 5 years building agent pipelines in Python."
    )
    assert body["factuality"]["passed"] is False
    assert body["factuality"]["removed_skills"] == ["kubernetes"]
    assert body["tailored"]["highlighted_skills"] == ["python"]
    assert Path(body["docx_path"]).is_file()
    stored = api.get(f"/api/tailored/{body['tailoring_id']}").json()
    assert stored["insights"] == body["insights"]


def _assert_no_draft() -> None:
    with app.state.db_factory() as db:
        assert db.scalars(select(TailoredResumeDB)).first() is None
    assert not list(user_dir(LEGACY_OWNER_ID, KIND_TAILORED).glob("*"))


@pytest.mark.parametrize(
    ("research_fails", "draft_error", "expected_detail"),
    [
        pytest.param(False, LLMTimeout, "timed out", id="draft-timeout"),
        pytest.param(False, LLMInvalidOutput, "usable tailored draft", id="draft-invalid-output"),
        pytest.param(True, LLMUnavailable, "unavailable", id="draft-fails-after-fallback"),
    ],
)
def test_failed_draft_generation_returns_a_safe_error_and_saves_nothing(
    api: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    research_fails: bool,
    draft_error: type[LLMError],
    expected_detail: str,
) -> None:
    fake = _fake_generate()
    drafted = False

    def generate(prompt, schema):
        nonlocal drafted
        if schema is JobInsights:
            if research_fails:
                raise LLMTimeout(_PROVIDER_DETAIL)
            return fake(prompt, schema)
        drafted = True
        raise draft_error(_PROVIDER_DETAIL)

    monkeypatch.setitem(app.dependency_overrides, get_generate_fn, lambda: generate)
    profile_id, job_id = _seed(api)
    response = api.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id})

    assert drafted  # including when the optional stage failed
    assert response.status_code == 503, response.text
    assert expected_detail in response.json()["detail"]
    assert _PROVIDER_DETAIL not in response.text
    _assert_no_draft()


@pytest.mark.parametrize(
    ("failure", "detail", "status", "expected_detail"),
    [
        pytest.param(
            LLMCredentialError,
            "Update under Profile → Model credentials.",
            409,
            "Account → Model credentials",
            id="byok",
        ),
        pytest.param(
            LLMConfigError, "LLM_API_KEY is not set", 503, "no API key is set", id="missing-key"
        ),
        pytest.param(
            LLMConfigError, "LLM rejected the API key", 503, "rejected", id="rejected-key"
        ),
        pytest.param(LLMDailyQuotaExhausted, "429", 503, "daily quota", id="daily-quota"),
        pytest.param(LLMRateLimited, "429", 503, "rate-limiting", id="rate-limit"),
        pytest.param(LLMUnavailable, "503", 503, "unavailable", id="provider-unavailable"),
    ],
)
def test_nonrecoverable_research_errors_stop_before_drafting(
    api: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: type[LLMError],
    detail: str,
    status: int,
    expected_detail: str,
) -> None:
    def generate(prompt, schema):
        assert schema is JobInsights, "This failure must stop before drafting."
        raise failure(f"{detail} ({_PROVIDER_DETAIL})")

    monkeypatch.setitem(app.dependency_overrides, get_generate_fn, lambda: generate)
    profile_id, job_id = _seed(api)
    with caplog.at_level(logging.DEBUG, logger="src.api.routes.tailoring"):
        response = api.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id})

    assert response.status_code == status, response.text
    assert expected_detail in response.json()["detail"]
    assert _PROVIDER_DETAIL not in response.text + caplog.text
    _assert_no_draft()


def test_the_route_edits_the_callers_own_upload(api: TestClient, tmp_path: Path) -> None:
    from docx import Document

    profile_id, job_id, upload = _seed_with_upload(api, tmp_path)
    body = api.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id}).json()

    assert body["render"]["mode"] == "in_place"
    assert body["render"]["source_format"] == ".docx"
    assert body["render"]["edits"] >= 1

    # The deliverable is NOT the uploaded file (never written to), and it keeps
    # the upload's own formatting.
    assert Path(body["docx_path"]) != upload
    edited = Document(body["docx_path"])
    font = edited.styles["Normal"].font
    assert font.name == "Georgia"
    text = "\n".join(p.text for p in edited.paragraphs)
    assert "Built agent pipelines with LangGraph" in text
    assert "Technical Skills" in text  # the document's own heading


def test_the_route_reports_a_rewrite_as_a_rewrite(api: TestClient) -> None:
    """No upload on disk: a fresh document, and the response says so."""
    profile_id, job_id = _seed(api)
    body = api.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id}).json()

    assert body["render"]["mode"] == "regenerated"
    assert body["render"]["source_format"] == "none"
    assert any("not available" in note for note in body["render"]["notes"])


def test_a_text_upload_is_edited_and_comes_back_as_text(api: TestClient, tmp_path: Path) -> None:
    profile_id, job_id, _upload = _seed_with_upload(api, tmp_path, suffix=".txt")
    body = api.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id}).json()

    assert body["render"]["mode"] == "in_place"
    assert body["render"]["source_format"] == ".txt"
    delivered = Path(body["docx_path"])
    assert delivered.suffix == ".txt"
    text = delivered.read_text(encoding="utf-8")
    assert "Technical Skills" in text
    assert "- Built agent pipelines with LangGraph" in text


def test_an_unreadable_text_upload_falls_back_to_a_real_docx(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from docx import Document

    profile_id, job_id, upload = _seed_with_upload(api, tmp_path, suffix=".txt")
    original_open = Path.open

    def fail_to_read_upload(self, *args, **kwargs):
        if self == upload:
            raise OSError("simulated read failure")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_to_read_upload)
    response = api.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["render"]["mode"] == "regenerated"
    assert body["render"]["source_format"] == ".txt"
    delivered = Path(body["docx_path"])
    assert delivered.name == f"{body['tailoring_id']}.docx"
    assert "Professional Summary" in [p.text for p in Document(str(delivered)).paragraphs]


def test_the_render_report_survives_the_round_trip(api: TestClient, tmp_path: Path) -> None:
    profile_id, job_id, _upload = _seed_with_upload(api, tmp_path)
    created = api.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id}).json()

    stored = api.get(f"/api/tailored/{created['tailoring_id']}").json()
    assert stored["render"] == created["render"]
    assert stored["render"]["mode"] == "in_place"
