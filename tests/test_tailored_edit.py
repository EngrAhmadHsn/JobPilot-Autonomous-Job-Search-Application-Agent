"""WS-47 tests: the studio's edit endpoint (PUT /api/tailored/{id}).

An edit is a **human's** wording change on top of a stored tailoring, and the
route's job is to treat it exactly like the pipeline treats a generation: the
delivered content may only carry claims the stored profile states, the ATS
report and the deliverable are re-produced from what the edit actually left,
and everything — including a factuality violation — is reported, never hidden.

The suite runs the real FastAPI app against a throwaway SQLite database and a
tmp output directory, with the deterministic fake generator from
``tests/test_tailoring_api.py`` producing the base tailoring. No model call
happens on the edit path at all: validation, the ATS analysis and the
deliverable are deterministic, so the whole flow is offline.
"""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from docx import Document
from docx.document import Document as DocxDocument
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.db.tailored  # noqa: F401  (model registration)
from src.api.routes.tailoring import get_generate_fn
from src.auth.routes import current_active_user
from src.config.settings import get_settings
from src.db.base import Base
from src.db.jobs import JobDB
from src.db.profiles import build_profile_row
from src.db.session import get_db
from src.db.tailored import build_tailored_row, stored_from_row
from src.db.users import LEGACY_OWNER_ID, UserDB
from src.main import app
from src.resume.ats import AtsReport, KeywordCoverage
from src.resume.pipeline import apply_tailored_edit, revalidate_tailored
from src.resume.render import tailored_docx_path
from src.resume.tailor import FactualityReport, TailoredExperience, TailoredProject, TailoredResume
from src.storage.paths import KIND_TAILORED, user_dir
from tests.test_tailoring_api import (
    JOB,
    PROFILE,
    _fake_generate,
    _seed_with_upload,
)

MAX_SECTION_CHARS = 8000


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
    # The seed helpers write through the same database the app serves.
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


def _tailor(api: TestClient, profile_id: str, job_id: str) -> dict:
    """Run one tailoring and return the response body."""
    response = api.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id})
    assert response.status_code == 200, response.text
    return response.json()


# -- the happy path -------------------------------------------------------------


def test_an_edit_persists_and_refreshes_the_reports(api: TestClient) -> None:
    profile_id, job_id = _seed(api)
    created = _tailor(api, profile_id, job_id)
    stored_before = api.get(f"/api/tailored/{created['tailoring_id']}").json()
    assert stored_before["edited_at"] is None  # a fresh run is never edited

    response = api.put(
        f"/api/tailored/{created['tailoring_id']}",
        json={"summary": "AI engineer focused on LangGraph pipelines in Python."},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # The edited content is what the record now carries…
    assert body["tailored"]["summary"] == "AI engineer focused on LangGraph pipelines in Python."
    # …the revalidation ran (the edit introduced nothing the profile lacks)…
    assert body["factuality"]["passed"] is True
    # …the ATS report was re-produced for the edited content…
    assert body["ats_report"]["score"] > 0
    # …the deliverable was re-produced through the WS-31 path, with its report…
    assert body["render"]["mode"] in ("in_place", "regenerated")
    assert Path(body["docx_path"]).is_file()
    # …and the edit is tracked (the creation time is the run's own).
    assert body["edited_at"]
    assert body["created_at"] == stored_before["created_at"]

    # The stored record serves the edited state again after a restart-shaped
    # round trip: the GET is the shape the console reloads with.
    fetched = api.get(f"/api/tailored/{created['tailoring_id']}")
    assert fetched.status_code == 200
    stored = fetched.json()
    assert stored["tailored"]["summary"] == "AI engineer focused on LangGraph pipelines in Python."
    assert stored["edited_at"] == body["edited_at"]
    assert stored["factuality"] == body["factuality"]
    assert stored["ats_report"] == body["ats_report"]


def test_an_edit_regenerates_the_deliverable_in_place(api: TestClient, tmp_path: Path) -> None:
    """A bullet edit reaches the delivered file, which keeps the source's look."""
    profile_id, job_id, upload = _seed_with_upload(api, tmp_path)
    created = _tailor(api, profile_id, job_id)
    assert created["render"]["mode"] == "in_place"

    response = api.put(
        f"/api/tailored/{created['tailoring_id']}",
        json={"experience": "Pipelines rebuilt around LangGraph\nA second honest bullet"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # The lines re-chunk onto the existing entries in order; the surplus line
    # lands on the entry's tail, where the in-place editor appends it.
    entry = body["tailored"]["experience"][0]
    assert entry["company"] == "Agentic Labs"
    assert entry["bullets"] == ["Pipelines rebuilt around LangGraph", "A second honest bullet"]
    assert body["render"]["mode"] == "in_place"
    assert body["render"]["appended"] == 1

    edited = Document(str(body["docx_path"]))
    text = "\n".join(p.text for p in edited.paragraphs)
    assert "Pipelines rebuilt around LangGraph" in text
    assert "A second honest bullet" in text
    # The deliverable is a new file — the upload is never written to.
    assert Path(body["docx_path"]) != upload


def test_a_cover_letter_edit_persists(api: TestClient) -> None:
    profile_id, job_id = _seed(api)
    created = _tailor(api, profile_id, job_id)

    response = api.put(
        f"/api/tailored/{created['tailoring_id']}",
        json={"cover_letter": "Dear hiring team, I build agent pipelines with LangGraph."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tailored"]["cover_letter"] == (
        "Dear hiring team, I build agent pipelines with LangGraph."
    )
    # An edit that changes one section leaves the others exactly as stored.
    assert body["tailored"]["summary"] == created["tailored"]["summary"]
    assert body["tailored"]["experience"] == created["tailored"]["experience"]


# -- deliverable identity --------------------------------------------------------


def _download(api: TestClient, tailoring_id: str) -> bytes:
    response = api.get(f"/api/tailored/{tailoring_id}/download")
    assert response.status_code == 200, response.text
    return response.content


def _document_text(data: bytes) -> str:
    return "\n".join(p.text for p in Document(BytesIO(data)).paragraphs)


def test_two_runs_for_the_same_profile_and_job_have_distinct_downloads(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_id, job_id = _seed(api)
    first_summary = "AI engineer building agent pipelines."
    second_summary = "AI engineer building APIs with FastAPI."
    summaries = iter((first_summary, second_summary))
    fake = _fake_generate()

    def generate(prompt, schema):
        result = fake(prompt, schema)
        if schema is TailoredResume:
            result.summary = next(summaries)
        return result

    monkeypatch.setitem(app.dependency_overrides, get_generate_fn, lambda: generate)
    first = _tailor(api, profile_id, job_id)
    first_bytes = _download(api, first["tailoring_id"])
    second = _tailor(api, profile_id, job_id)

    assert first["docx_path"] != second["docx_path"]
    for record in (first, second):
        tailoring_id = record["tailoring_id"]
        assert UUID(tailoring_id).version == 4
        expected = user_dir(LEGACY_OWNER_ID, KIND_TAILORED) / f"{tailoring_id}.docx"
        assert Path(record["docx_path"]) == expected.resolve()
        assert record["job_id"] == job_id
    assert _download(api, first["tailoring_id"]) == first_bytes
    second_bytes = _download(api, second["tailoring_id"])
    assert first_bytes != second_bytes
    assert first_summary in _document_text(first_bytes)
    assert second_summary in _document_text(second_bytes)


def test_edit_changes_only_the_addressed_drafts_download(api: TestClient) -> None:
    profile_id, job_id = _seed(api)
    first = _tailor(api, profile_id, job_id)
    second = _tailor(api, profile_id, job_id)
    second_id = second["tailoring_id"]
    second_bytes = _download(api, second_id)
    summary = "AI engineer building APIs with FastAPI."

    response = api.put(f"/api/tailored/{first['tailoring_id']}", json={"summary": summary})

    assert response.status_code == 200, response.text
    assert _download(api, second_id) == second_bytes
    assert summary in _document_text(_download(api, first["tailoring_id"]))
    assert response.json()["docx_path"] == first["docx_path"]
    second_stored = api.get(f"/api/tailored/{second_id}").json()
    assert second_stored["docx_path"] == second["docx_path"]
    assert second_stored["edited_at"] is None
    assert second_stored["tailored"] == second["tailored"]


def test_legacy_shared_artifact_is_left_in_place_when_one_row_is_edited(api: TestClient) -> None:
    profile_id, job_id = _seed(api)
    directory = user_dir(LEGACY_OWNER_ID, KIND_TAILORED)
    directory.mkdir(parents=True)
    legacy_path = tailored_docx_path(profile_id, job_id, directory)
    document = Document()
    document.add_paragraph("Legacy bytes shared by both records.")
    document.save(str(legacy_path))
    legacy_bytes = legacy_path.read_bytes()
    with app.state.db_factory() as db:
        first, second = [
            build_tailored_row(
                profile_id=profile_id,
                job_id=job_id,
                tailored=_fake_generate()("", TailoredResume),
                factuality=FactualityReport(passed=True),
                ats_report=AtsReport(keyword_coverage=KeywordCoverage(), section_completeness={}),
                docx_path=str(legacy_path.resolve()),
            )
            for _ in range(2)
        ]
        # The historical IDs were 12 hex characters rather than full UUIDs.
        first.id = "0123456789ab"
        second.id = "0123456789cd"
        db.add_all((first, second))
        db.commit()
        first_id, second_id = first.id, second.id
    assert _download(api, first_id) == _download(api, second_id) == legacy_bytes
    summary = "AI engineer building APIs with FastAPI."

    response = api.put(f"/api/tailored/{first_id}", json={"summary": summary})

    assert response.status_code == 200, response.text
    edited_path = directory / f"{first_id}.docx"
    assert Path(response.json()["docx_path"]) == edited_path.resolve()
    assert summary in _document_text(_download(api, first_id))
    assert legacy_path.read_bytes() == _download(api, second_id) == legacy_bytes
    second_stored = api.get(f"/api/tailored/{second_id}").json()
    assert Path(second_stored["docx_path"]) == legacy_path.resolve()
    assert second_stored["edited_at"] is None


@pytest.mark.parametrize("failure", ["partial-write", "replace"])
def test_failed_artifact_publication_preserves_saved_document_and_row(
    api: TestClient, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    profile_id, job_id = _seed(api)
    created = _tailor(api, profile_id, job_id)
    tailoring_id = created["tailoring_id"]
    before = api.get(f"/api/tailored/{tailoring_id}").json()
    before_bytes = _download(api, tailoring_id)
    saved_path = Path(before["docx_path"])
    directory = saved_path.parent
    initial_files = set(directory.iterdir())

    if failure == "partial-write":

        def fail_save(self, path):
            Path(path).write_bytes(b"incomplete document")
            raise OSError("simulated write failure")

        monkeypatch.setattr(DocxDocument, "save", fail_save)
    else:
        original_replace = Path.replace

        def fail_replace(self, target):
            if Path(target).resolve() == saved_path:
                raise PermissionError("simulated destination in use")
            return original_replace(self, target)

        monkeypatch.setattr(Path, "replace", fail_replace)

    http = TestClient(app, raise_server_exceptions=False)
    response = http.put(f"/api/tailored/{tailoring_id}", json={"summary": "AI engineer."})

    assert response.status_code == 500
    assert _download(api, tailoring_id) == before_bytes
    assert api.get(f"/api/tailored/{tailoring_id}").json() == before
    assert set(directory.iterdir()) == initial_files


# -- honesty: violations are reported, never blocked ----------------------------


def test_a_factuality_violation_is_a_reported_200_not_an_error(api: TestClient) -> None:
    """An inflated claim is stripped and reported; the save still succeeds."""
    profile_id, job_id = _seed(api)
    created = _tailor(api, profile_id, job_id)

    response = api.put(
        f"/api/tailored/{created['tailoring_id']}",
        json={"summary": "AI engineer with 9 years of experience in agent systems."},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["factuality"]["passed"] is False
    assert any("9 years" in violation for violation in body["factuality"]["violations"])
    # The delivered content is the *stripped* text — the claim never ships.
    assert "9 years" not in body["tailored"]["summary"]
    assert body["edited_at"]

    # The stored record carries the same report (the console's Validation tab
    # reads it after a reload).
    stored = api.get(f"/api/tailored/{created['tailoring_id']}").json()
    assert stored["factuality"]["passed"] is False
    assert "9 years" not in stored["tailored"]["summary"]


def test_a_stripped_edit_still_regenerates_the_deliverable(api: TestClient, tmp_path: Path) -> None:
    """The deliverable is re-produced from what the validator left standing."""
    profile_id, job_id, _upload = _seed_with_upload(api, tmp_path)
    created = _tailor(api, profile_id, job_id)

    response = api.put(
        f"/api/tailored/{created['tailoring_id']}",
        json={"summary": "AI engineer with 12 years of experience."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["factuality"]["passed"] is False
    # The in-place path still ran on the reduced content.
    assert body["render"]["mode"] == "in_place"
    delivered = "\n".join(p.text for p in Document(str(body["docx_path"])).paragraphs)
    assert "12 years" not in delivered


# -- the authorization boundary --------------------------------------------------


def test_a_missing_tailoring_is_404(api: TestClient) -> None:
    response = api.put("/api/tailored/does-not-exist", json={"summary": "Anything."})
    assert response.status_code == 404


def test_a_foreign_tailoring_is_404_and_never_edited(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another account's tailoring does not exist for the edit path either."""
    profile_id, job_id = _seed(api)
    with app.state.db_factory() as db:
        row = build_tailored_row(
            owner_id=LEGACY_OWNER_ID,
            profile_id=profile_id,
            job_id=job_id,
            tailored=TailoredResume(
                summary="Untouched summary.",
                highlighted_skills=["python"],
                experience=[
                    TailoredExperience(
                        company="Agentic Labs", title="AI Engineer", bullets=["Built agents"]
                    )
                ],
                projects=[],
                cover_letter="Letter.",
            ),
            factuality=FactualityReport(passed=True),
            ats_report=AtsReport(keyword_coverage=KeywordCoverage(), section_completeness={}),
            docx_path="unused.docx",
        )
        db.add(row)
        db.commit()
        tailoring_id = row.id
        row_type = type(row)

    # Act as a different principal: the row is foreign, so it is "not found".
    stranger = UserDB(
        id="stranger-id",
        email="stranger@example.com",
        hashed_password="!",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    monkeypatch.setitem(app.dependency_overrides, current_active_user, lambda: stranger)
    response = api.put(f"/api/tailored/{tailoring_id}", json={"summary": "A foreign edit."})
    assert response.status_code == 404

    # The row survived, byte for byte: a 404 never edits.
    with app.state.db_factory() as db:
        fresh = db.get(row_type, tailoring_id)
        assert fresh is not None
        assert stored_from_row(fresh).tailored.summary == "Untouched summary."
        assert fresh.edited_at is None


# -- the request contract --------------------------------------------------------


def test_sections_are_length_bounded(api: TestClient) -> None:
    profile_id, job_id = _seed(api)
    created = _tailor(api, profile_id, job_id)

    response = api.put(
        f"/api/tailored/{created['tailoring_id']}",
        json={"summary": "x" * (MAX_SECTION_CHARS + 1)},
    )
    assert response.status_code == 422


def test_the_boundary_length_is_accepted(api: TestClient) -> None:
    profile_id, job_id = _seed(api)
    created = _tailor(api, profile_id, job_id)

    response = api.put(
        f"/api/tailored/{created['tailoring_id']}",
        json={"summary": "x" * MAX_SECTION_CHARS},
    )
    assert response.status_code == 200


def test_an_empty_body_is_422(api: TestClient) -> None:
    profile_id, job_id = _seed(api)
    created = _tailor(api, profile_id, job_id)

    response = api.put(f"/api/tailored/{created['tailoring_id']}", json={})
    assert response.status_code == 422


# -- the edit application, unit-level ---------------------------------------------


def _structured() -> TailoredResume:
    """A two-entry, one-project tailored resume for the mapping tests."""
    return TailoredResume(
        summary="Original summary.",
        highlighted_skills=["python"],
        experience=[
            TailoredExperience(company="Agentic Labs", title="AI Engineer", bullets=["One", "Two"]),
            TailoredExperience(company="Northstar", title="Backend Engineer", bullets=["Three"]),
        ],
        projects=[TailoredProject(name="Job Agent", bullets=["Built"])],
        cover_letter="Letter.",
    )


def _empty() -> TailoredResume:
    return TailoredResume(
        summary="s",
        highlighted_skills=[],
        experience=[],
        projects=[],
        cover_letter="c",
    )


class TestApplyTailoredEdit:
    """The section-to-structure mapping, without HTTP around it."""

    def test_lines_rechunk_onto_the_entries_in_order(self) -> None:
        edited = apply_tailored_edit(_structured(), experience="a\nb\nc")
        assert [entry.bullets for entry in edited.experience] == [["a", "b"], ["c"]]

    def test_surplus_lines_land_on_the_last_entry(self) -> None:
        edited = apply_tailored_edit(_structured(), experience="a\nb\nc\nd\ne")
        assert [entry.bullets for entry in edited.experience] == [["a", "b"], ["c", "d", "e"]]

    def test_fewer_lines_shrink_the_entries(self) -> None:
        edited = apply_tailored_edit(_structured(), experience="only")
        assert [entry.bullets for entry in edited.experience] == [["only"], []]
        # Identities survive an edit — only the wording changes.
        assert [(e.company, e.title) for e in edited.experience] == [
            ("Agentic Labs", "AI Engineer"),
            ("Northstar", "Backend Engineer"),
        ]

    def test_bullet_markers_are_stripped_and_blanks_dropped(self) -> None:
        edited = apply_tailored_edit(_structured(), experience="- a\n\n• b\n   \n")
        assert [entry.bullets for entry in edited.experience] == [["a", "b"], []]

    def test_projects_rechunk_the_same_way(self) -> None:
        edited = apply_tailored_edit(_structured(), projects="x\ny")
        assert [project.bullets for project in edited.projects] == [["x", "y"]]

    def test_untouched_sections_stay_put(self) -> None:
        base = _structured()
        edited = apply_tailored_edit(base, summary="New summary.")
        assert edited.summary == "New summary."
        assert edited.experience == base.experience
        assert edited.projects == base.projects
        assert edited.cover_letter == base.cover_letter

    def test_an_experience_edit_with_no_entries_is_refused(self) -> None:
        with pytest.raises(ValueError):
            apply_tailored_edit(_empty(), experience="a line")

    def test_a_projects_edit_with_no_projects_is_refused(self) -> None:
        with pytest.raises(ValueError):
            apply_tailored_edit(_empty(), projects="a bullet")


class TestRevalidateTailored:
    """The edit runs through the pipeline's own validator."""

    def _edited(self, summary: str) -> TailoredResume:
        return TailoredResume(
            summary=summary,
            highlighted_skills=["python", "langgraph"],
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

    def test_an_inflated_year_claim_is_stripped_and_reported(self) -> None:
        profile = PROFILE.model_copy(deep=True)
        revalidated, factuality = revalidate_tailored(
            self._edited("AI engineer with 30 years of practice."), profile
        )
        assert factuality.passed is False
        assert any("30 years" in v for v in factuality.violations)
        assert revalidated.summary == ""

    def test_an_honest_edit_passes(self) -> None:
        revalidated, factuality = revalidate_tailored(
            self._edited("AI engineer building LangGraph pipelines."), PROFILE.model_copy(deep=True)
        )
        assert factuality.passed is True
        assert revalidated.summary == "AI engineer building LangGraph pipelines."

    def test_an_unknown_skill_in_an_edit_is_stripped(self) -> None:
        """Defence in depth: the edit contract carries no skills field, and the
        validator would still strip one that reached the content somehow."""
        tailored = _edited_for_skills()
        tailored.highlighted_skills = ["python", "kubernetes"]
        revalidated, factuality = revalidate_tailored(tailored, PROFILE.model_copy(deep=True))
        assert factuality.passed is False
        assert "kubernetes" in factuality.removed_skills
        assert revalidated.highlighted_skills == ["python"]


def _edited_for_skills() -> TailoredResume:
    return TailoredResume(
        summary="Summary.",
        highlighted_skills=["python"],
        experience=[
            TailoredExperience(
                company="Agentic Labs",
                title="AI Engineer",
                bullets=["Built agent pipelines with LangGraph"],
            )
        ],
        projects=[],
        cover_letter="Letter.",
    )
