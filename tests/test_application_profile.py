"""WS-20 · the application-profile API, persistence and backwards compatibility."""

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
from src.db.profiles import CandidateProfileDB, application_profile_from_row
from src.db.session import get_db
from src.main import app
from src.resume.application_profile import ApplicationProfile
from src.resume.profile import CandidateProfile, PersonalInformation

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
    assert response.status_code == 200
    return response.json()["profile_id"]


def test_application_profile_is_empty_before_it_is_set(api: TestClient) -> None:
    pid = _profile_id(api)
    body = api.get(f"/api/profiles/{pid}/application-profile").json()
    assert body["profile_id"] == pid
    assert body["application_profile"]["professional"]["total_experience_years"] is None


def test_application_profile_round_trips(api: TestClient) -> None:
    pid = _profile_id(api)
    payload = {
        "professional": {"total_experience_years": 7, "seniority_level": "senior"},
        "preferences": {"remote_preference": "remote", "preferred_locations": ["Berlin"]},
        "answers": {
            "work_authorization": {"legally_authorized": True, "requires_sponsorship": False},
            "compensation": {
                "expected_salary": 120000,
                "expected_currency": "usd",
                "expected_period": "annual",
            },
            "notice": {"notice_days": 30},
        },
        "confirmed_fields": ["professional.seniority_level"],
    }
    put = api.put(f"/api/profiles/{pid}/application-profile", json=payload)
    assert put.status_code == 200

    got = api.get(f"/api/profiles/{pid}/application-profile").json()["application_profile"]
    assert got["professional"]["total_experience_years"] == 7
    assert got["answers"]["work_authorization"]["legally_authorized"] is True
    assert got["answers"]["compensation"]["expected_currency"] == "USD"
    assert got["answers"]["notice"]["notice_days"] == 30


def test_application_profile_rejects_invalid_values(api: TestClient) -> None:
    pid = _profile_id(api)
    bad = {"preferences": {"remote_preference": "teleport"}}
    assert api.put(f"/api/profiles/{pid}/application-profile", json=bad).status_code == 422


def test_application_profile_write_is_owner_scoped(api: TestClient) -> None:
    pid = _profile_id(api)
    # A different caller cannot see the profile, so both GET and PUT are 404.
    from src.auth.routes import current_active_user
    from src.db.users import UserDB

    intruder = UserDB(
        id="someone-else",
        email="intruder@example.com",
        hashed_password="!",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    app.dependency_overrides[current_active_user] = lambda: intruder
    try:
        assert api.get(f"/api/profiles/{pid}/application-profile").status_code == 404
        assert api.put(f"/api/profiles/{pid}/application-profile", json={}).status_code == 404
    finally:
        app.dependency_overrides.pop(current_active_user, None)


def test_older_profile_without_application_json_still_validates() -> None:
    """A pre-WS-20 row (NULL application_json) reads as an empty profile."""
    row = CandidateProfileDB(
        id="old",
        owner_id="legacy",
        profile_json=CandidateProfile(
            personal_information=PersonalInformation(name="Old")
        ).model_dump(mode="json"),
        application_json=None,
        file_path="x.docx",
    )
    from src.db.profiles import profile_from_row

    profile = profile_from_row(row)
    assert isinstance(profile.application_profile, ApplicationProfile)
    assert application_profile_from_row(row).professional.total_experience_years is None


def test_application_json_is_not_stored_inside_profile_json() -> None:
    """The résumé facts and the confirmed answers stay in separate columns."""
    from src.db.profiles import build_profile_row

    row = build_profile_row(CandidateProfile(), "x.docx", owner_id="legacy")
    assert "application_profile" not in row.profile_json
