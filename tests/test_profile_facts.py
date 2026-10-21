"""WS-08 · Phase D — the profile facts reach the prepared payload.

The facts an application may answer a form question with come from the
candidate's **own document**: the stored profile. They are never taken from
the request body, and a profile that does not exist yields no facts rather
than invented ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.db.approval import ApprovalRequestDB
from src.db.base import Base
from src.db.profiles import CandidateProfileDB
from src.db.session import get_db
from src.main import app
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
    WorkPreferences,
)


@pytest.fixture
def session_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An isolated database for the profiles, the approvals and the audit trail."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'facts.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("src.db.session.SessionLocal", factory)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _profile() -> CandidateProfile:
    return CandidateProfile(
        personal_information=PersonalInformation(
            name="Ada Lovelace",
            email="ada@example.com",
            phone="+1 555 0101",
            location="Berlin, Germany",
        ),
        skills=["Python"],
        experience=[ExperienceEntry(title="Engineer", company="Acme", years=4)],
        work_preferences=WorkPreferences(
            remote_preference="remote",
            work_authorization="authorized",
        ),
    )


def _store_profile(factory) -> str:
    """A stored candidate profile."""
    with factory() as session:
        row = CandidateProfileDB(
            id="profile-1",
            name="Ada Lovelace",
            email="ada@example.com",
            phone="+1 555 0101",
            location="Berlin, Germany",
            title="",
            profile_json=_profile().model_dump(mode="json"),
            file_path="/tmp/resume.txt",
        )
        session.add(row)
        session.commit()
        return row.id


def _payload(profile_id: str | None = None) -> dict:
    payload = {
        "job_title": "Senior Python Engineer",
        "company_name": "Acme Labs",
        "job_url": "http://127.0.0.1:8123/jobs/123/apply",
        "candidate_name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+1 555 0101",
    }
    if profile_id is not None:
        payload["profile_id"] = profile_id
    return payload


def test_prepare_derives_the_facts_from_the_stored_profile(client, session_factory) -> None:
    profile_id = _store_profile(session_factory)

    response = client.post("/api/applications/prepare", json=_payload(profile_id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["prepared_summary"]["profile_fact_names"] == [
        "email",
        "location",
        "name",
        "phone",
        "remote_preference",
        "skills",
        "work_authorization",
        "years_of_experience",
    ]

    with session_factory() as session:
        row = session.scalars(select(ApprovalRequestDB)).one()
        facts = row.payload["profile_facts"]
        assert facts["years_of_experience"] == "4"
        assert facts["work_authorization"] == "authorized"
        assert facts["remote_preference"] == "remote"
        # The values are not echoed back to the caller.
        assert "authorized" not in response.text


def test_prepare_without_a_profile_carries_no_facts(client, session_factory) -> None:
    response = client.post("/api/applications/prepare", json=_payload())

    assert response.status_code == 200, response.text
    assert response.json()["prepared_summary"]["profile_fact_names"] == []

    with session_factory() as session:
        row = session.scalars(select(ApprovalRequestDB)).one()
        assert row.payload["profile_facts"] == {}


def test_prepare_with_an_unknown_profile_carries_no_facts(client, session_factory) -> None:
    response = client.post("/api/applications/prepare", json=_payload("does-not-exist"))

    assert response.status_code == 200, response.text
    assert response.json()["prepared_summary"]["profile_fact_names"] == []

    with session_factory() as session:
        row = session.scalars(select(ApprovalRequestDB)).one()
        assert row.payload["profile_facts"] == {}
