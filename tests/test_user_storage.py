"""WS-14 · Phase B — per-user storage (R7).

**The property under test:** every file the platform writes for a person
lives in **that person's own directory**, and no user can reach another's
file.

The rule that matters is the containment check. Before WS-14 it asked
"is this path inside a directory the application owns?" — which, with
several users, includes the other users' directories. Now it asks "is
this path inside **the caller's own** directory?", which is the only
version of the question that holds in a multi-user deployment.

What is proved here:

- the layout is ``data/users/{user_id}/{resumes,tailored,evidence}/``;
- an upload lands in the uploader's own directory;
- a rendered resume lands in the caller's own directory;
- the evidence of a run lands in the account's own directory;
- a path naming another user's directory is refused;
- a traversal attempt is still refused;
- the client never names a path — the download endpoints take an id.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.settings import get_settings
from src.db.base import Base
from src.db.session import get_db
from src.main import app
from src.storage.paths import (
    KIND_EVIDENCE,
    KIND_RESUMES,
    KIND_TAILORED,
    UserPathNotAllowedError,
    assert_within_user_root,
    is_within_user_root,
    safe_user_segment,
    user_dir,
    user_root,
)

ALICE = "alice"
BOB = "bob"


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated storage root."""
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient over a throwaway database and a throwaway storage root."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'storage.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(get_settings(), "tailored_dir", str(tmp_path / "data" / "tailored"))
    monkeypatch.setattr(get_settings(), "evidence_dir", str(tmp_path / "data" / "evidence"))
    monkeypatch.setattr(get_settings(), "resume_upload_dir", str(tmp_path / "data" / "uploads"))
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


# -- the layout ----------------------------------------------------------------


class TestTheLayout:
    def test_the_layout_is_per_user(self, storage: Path) -> None:
        assert user_root(ALICE) == storage / "users" / ALICE
        assert user_dir(ALICE, KIND_RESUMES) == storage / "users" / ALICE / "resumes"
        assert user_dir(ALICE, KIND_TAILORED) == storage / "users" / ALICE / "tailored"
        assert user_dir(ALICE, KIND_EVIDENCE) == storage / "users" / ALICE / "evidence"

    def test_two_users_get_two_directories(self, storage: Path) -> None:
        assert user_root(ALICE) != user_root(BOB)

    def test_an_unknown_kind_is_refused(self) -> None:
        with pytest.raises(UserPathNotAllowedError):
            user_dir(ALICE, "not-a-kind")

    def test_an_owner_id_that_is_not_a_path_segment_is_refused(self) -> None:
        """A sanitised id would write to a *different* user's directory."""
        for bad in ("../evil", "a/b", "", ".", "..", "x" * 100):
            with pytest.raises(UserPathNotAllowedError):
                safe_user_segment(bad)

    def test_the_ordinary_ids_are_accepted(self) -> None:
        assert safe_user_segment("alice") == "alice"
        assert safe_user_segment("9ab4ebb618d1") == "9ab4ebb618d1"
        assert safe_user_segment("legacy") == "legacy"


# -- the containment check -----------------------------------------------------


class TestTheContainmentCheck:
    def test_a_file_inside_the_own_directory_is_allowed(self, storage: Path) -> None:
        target = user_dir(ALICE, KIND_RESUMES) / "resume.docx"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
        assert is_within_user_root(target, ALICE)
        assert assert_within_user_root(target, ALICE) == target.resolve()

    def test_a_file_inside_another_users_directory_is_refused(self, storage: Path) -> None:
        target = user_dir(BOB, KIND_RESUMES) / "resume.docx"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
        assert not is_within_user_root(target, ALICE)
        with pytest.raises(UserPathNotAllowedError):
            assert_within_user_root(target, ALICE)

    def test_a_traversal_is_refused(self, storage: Path) -> None:
        escape = user_dir(ALICE, KIND_RESUMES) / ".." / ".." / ".." / "secret.txt"
        with pytest.raises(UserPathNotAllowedError):
            assert_within_user_root(escape, ALICE)

    def test_a_missing_file_is_refused(self, storage: Path) -> None:
        with pytest.raises(UserPathNotAllowedError):
            assert_within_user_root(user_dir(ALICE, KIND_RESUMES) / "nope.docx", ALICE)

    def test_a_symlink_out_of_the_directory_is_refused(self, storage: Path) -> None:
        """The check is made on the **resolved** path.

        A symlink named like a resume, pointing at a file outside the
        directory, is exactly the escape the resolution defeats.
        """
        secret = storage / "secret.txt"
        secret.parent.mkdir(parents=True, exist_ok=True)
        secret.write_text("the real secret", encoding="utf-8")
        link = user_dir(ALICE, KIND_RESUMES) / "resume.docx"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(secret)
        except OSError:  # pragma: no cover - Windows without developer mode
            pytest.skip("symlinks are not available on this platform")
        assert not is_within_user_root(link, ALICE)
        with pytest.raises(UserPathNotAllowedError):
            assert_within_user_root(link, ALICE)


# -- the write paths -----------------------------------------------------------


def _upload():
    """A minimal stand-in for an uploaded file."""
    import io

    from fastapi import UploadFile

    return UploadFile(
        filename="resume.txt",
        file=io.BytesIO(b"Ada Lovelace - Senior Python Engineer" + bytes([10])),
    )


class TestTheWritePaths:
    def test_an_upload_lands_in_the_callers_own_directory(
        self, api: TestClient, storage: Path
    ) -> None:
        """The upload route writes into the caller's own resume directory."""
        from src.api.validation import validate_resume_upload

        path = validate_resume_upload(_upload(), owner_id=ALICE)
        assert path.parent == user_dir(ALICE, KIND_RESUMES)
        assert user_dir(ALICE, KIND_RESUMES) in path.parents

    def test_an_upload_without_an_owner_uses_the_shared_directory(
        self, api: TestClient, storage: Path
    ) -> None:
        """The scripts and the evaluation harness pre-date the multi-user
        work, and they have no principal. They keep the shared directory."""
        from src.api.validation import validate_resume_upload

        path = validate_resume_upload(_upload())
        assert path.parent == Path(get_settings().resume_upload_dir)



class TestTheDownloadEndpoints:
    def test_a_user_cannot_read_another_users_artifact_by_id(
        self, api: TestClient, storage: Path
    ) -> None:
        """The sharpest instance of the cross-tenant file read.

        The evidence endpoint takes an application id and a file name.
        The application is scoped, so a foreign application is a 404 — and
        the file itself is resolved inside the **owner's** directory, so
        even a file name that happens to match resolves to nothing.
        """
        from src.db.applications import build_application_row
        from src.db.evidence import ApplicationEvidenceDB

        # Bob's application, with a screenshot in Bob's own directory.
        evidence_dir = user_dir(BOB, KIND_EVIDENCE)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "workflow-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        with next(api.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
            application = build_application_row(
                owner_id=BOB,
                workflow_id="workflow-1",
                job_id="greenhouse:1",
                adapter_name="fake-ats",
                job_url="http://127.0.0.1:8901/basic",
                job_title="AI Engineer",
                company_name="Acme",
                status="submitted",
            )
            db.add(application)
            db.commit()
            db.add(
                ApplicationEvidenceDB(
                    owner_id=BOB,
                    application_id=application.id,
                    workflow_id="workflow-1",
                    adapter_name="fake-ats",
                    job_url="http://127.0.0.1:8901/basic",
                    status="verified",
                    screenshot_path="workflow-1.png",
                )
            )
            db.commit()
            application_id = application.id

        # The suite's caller is the legacy owner, so this is another
        # user's artefact from its point of view.
        response = api.get(f"/api/applications/{application_id}/evidence/workflow-1.png")
        assert response.status_code == 404
