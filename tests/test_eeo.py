"""WS-20 · EEO data: isolated, opt-in, never used for ranking."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.db.eeo
import src.db.profiles  # noqa: F401
from src.config.settings import get_settings
from src.db.base import Base
from src.db.session import get_db
from src.main import app
from src.resume.eeo import DECLINED, EeoProfile, is_answered

FIXTURE_DOCX = Path(__file__).parent / "fixtures" / "Ahmad_Hassan_AI_Engineer_Resume.docx"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
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
    monkeypatch.setattr(get_settings(), "resume_upload_dir", str(tmp_path / "uploads"))
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _profile_id(client: TestClient) -> str:
    with FIXTURE_DOCX.open("rb") as fh:
        response = client.post(
            "/api/resumes", files={"file": ("resume.docx", fh.read(), DOCX_MIME)}
        )
    return response.json()["profile_id"]


# -- the model ----------------------------------------------------------------


def test_unanswered_and_declined_are_distinct():
    assert is_answered(None) is False
    assert is_answered(DECLINED) is True
    assert is_answered("Asian") is True


def test_eeo_never_appears_in_the_resume_read(api: TestClient) -> None:
    pid = _profile_id(api)
    api.put(
        f"/api/profiles/{pid}/eeo",
        json={"opt_in": True, "gender": DECLINED, "race_ethnicity": "Decline to self-identify"},
    )
    # The résumé profile read must not carry EEO data.
    profile = api.get(f"/api/resumes/{pid}").json()["profile"]
    assert "eeo" not in profile
    assert "gender" not in profile.get("application_profile", {})


def test_eeo_requires_opt_in(api: TestClient) -> None:
    pid = _profile_id(api)
    refused = api.put(f"/api/profiles/{pid}/eeo", json={"gender": "Woman", "opt_in": False})
    assert refused.status_code == 400


def test_eeo_round_trips_and_can_be_deleted(api: TestClient) -> None:
    pid = _profile_id(api)
    put = api.put(
        f"/api/profiles/{pid}/eeo", json={"opt_in": True, "veteran_status": "I am not a veteran"}
    )
    assert put.status_code == 200
    got = api.get(f"/api/profiles/{pid}/eeo").json()["eeo"]
    assert got["veteran_status"] == "I am not a veteran"

    assert api.delete(f"/api/profiles/{pid}/eeo").status_code == 204
    empty = api.get(f"/api/profiles/{pid}/eeo").json()["eeo"]
    assert empty["veteran_status"] is None


def test_eeo_is_owner_scoped(api: TestClient) -> None:
    pid = _profile_id(api)
    api.put(f"/api/profiles/{pid}/eeo", json={"opt_in": True, "gender": DECLINED})

    from src.auth.routes import current_active_user
    from src.db.users import UserDB

    intruder = UserDB(
        id="intruder",
        email="intruder@example.com",
        hashed_password="!",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    app.dependency_overrides[current_active_user] = lambda: intruder
    try:
        assert api.get(f"/api/profiles/{pid}/eeo").status_code == 404
        assert api.put(f"/api/profiles/{pid}/eeo", json={"opt_in": True}).status_code == 404
        assert api.delete(f"/api/profiles/{pid}/eeo").status_code == 404
    finally:
        app.dependency_overrides.pop(current_active_user, None)


# -- isolation from matching --------------------------------------------------


def test_eeo_fields_are_not_part_of_the_candidate_profile_facts() -> None:
    """EEO never reaches the fact table the matcher and the form layer read."""
    from src.applications.form import facts_from_profile
    from src.resume.profile import CandidateProfile, PersonalInformation

    profile = CandidateProfile(personal_information=PersonalInformation(name="Ada"))
    facts = facts_from_profile(profile)
    for leaked in ("race", "gender", "disability", "veteran", "race_ethnicity"):
        assert leaked not in facts


def test_matching_has_no_eeo_inputs() -> None:
    """The matcher's inputs are the listing and the profile — no EEO anywhere."""
    import inspect

    from src.matching import engine

    source = inspect.getsource(engine.calculate_match)
    for term in ("eeo", "race", "gender", "disability", "veteran"):
        assert term not in source.lower()


def test_eeo_profile_rejects_oversized_values():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EeoProfile(opt_in=True, gender="x" * 500)
