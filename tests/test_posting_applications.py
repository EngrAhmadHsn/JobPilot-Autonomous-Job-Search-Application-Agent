"""Real-listing preparation: public form reads and private, exact-question answers."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.applications.greenhouse_forms import build_form_schema
from src.auth.routes import current_active_user
from src.db.applications import ApplicationDB
from src.db.approval import ApprovalRequestDB
from src.db.base import Base
from src.db.jobs import JobDB
from src.db.profiles import build_profile_row
from src.db.runs import JobRunDB
from src.db.session import get_db
from src.db.users import LEGACY_OWNER_ID, UserDB
from src.main import app
from src.resume.profile import CandidateProfile

FIRST = "greenhouse:10"
OTHER_ROLE = "greenhouse:11"
OTHER_COMPANY = "greenhouse:12"
FORM = f"/api/jobs/{FIRST}/application-form"
LIBRARY = "/api/profiles/employer-answers"
WHY = "Why Acme?"
PARTNER = "Have you worked with any of our partners?"
CONSENT = "Confirm the company may process your personal information"


def _field(label, name, kind="input_text", *, required=True, values=None):
    return {
        "label": label,
        "required": required,
        "fields": [{"name": name, "type": kind, "values": values or []}],
    }


@pytest.fixture
def stack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_db():
        with factory() as db:
            yield db

    resume = tmp_path / "candidate.txt"
    resume.write_text("Original résumé", encoding="utf-8")
    payload = {
        "questions": [
            _field("First Name", "first_name"),
            _field("Resume/CV", "resume", "input_file"),
            _field(WHY, "question_1", "textarea"),
            _field(
                PARTNER,
                "question_2",
                "multi_value_single_select",
                values=[{"value": 1, "label": "Yes"}, {"value": 2, "label": "No"}],
            ),
        ],
        "compliance": [{"questions": [_field(CONSENT, "compliance_1")]}],
    }
    with factory() as db:
        db.add_all(
            JobDB(
                id=job_id,
                source="greenhouse",
                title=title,
                company="Acme" if job_id != OTHER_COMPANY else "Northstar",
                application_url=f"https://job-boards.greenhouse.io/acme/jobs/{job_id.split(':')[1]}",
            )
            for job_id, title in [
                (FIRST, "Engineer"),
                (OTHER_ROLE, "Designer"),
                (OTHER_COMPANY, "Writer"),
            ]
        )
        db.add(
            JobDB(
                id="ashby:42",
                source="ashby",
                title="Analyst",
                company="Other",
                application_url="https://jobs.ashbyhq.com/other/42",
            )
        )
        db.add(UserDB(id=LEGACY_OWNER_ID, email="fixture@example.invalid", hashed_password="!", is_active=True))
        row = build_profile_row(CandidateProfile(), str(resume))
        row.id = "cv"
        db.add(row)
        db.commit()

    async def read_schema(self, url, **_):
        return build_form_schema(payload)

    monkeypatch.setattr(
        "src.applications.greenhouse_adapter.GreenhouseAdapter.fetch_form_schema", read_schema
    )
    monkeypatch.setattr(
        "src.api.routes.documents.assert_within_owned_storage", lambda path, *_, **__: Path(path)
    )
    monkeypatch.setattr("src.db.session.SessionLocal", factory)
    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app), factory, payload, resume
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _questions(client: TestClient, job_id: str = FIRST):
    response = client.get(f"/api/jobs/{job_id}/application-form")
    assert response.status_code == 200, response.text
    return response.json()


def _save(client, question, answer):
    return client.put(
        f"{FORM}/answers",
        json={"answers": [{"question_key": question["question_key"], "answer": answer}]},
    )


def test_public_preview_has_typed_employer_questions_without_creating_a_packet(stack):
    client, factory, _, _ = stack
    form = _questions(client)
    assert form["state"] == "available"
    assert [(q["label"], q["kind"]) for q in form["questions"]] == [
        ("First Name", "contact"),
        ("Resume/CV", "resume"),
        (WHY, "textarea"),
        (PARTNER, "select"),
        (CONSENT, "employer"),
    ]
    assert form["questions"][3]["options"] == [
        {"value": "1", "label": "Yes"},
        {"value": "2", "label": "No"},
    ]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ApplicationDB)) == 0
        assert db.scalar(select(func.count()).select_from(ApprovalRequestDB)) == 0


def test_save_validates_against_the_current_question_and_its_published_choices(stack):
    client, _, payload, _ = stack
    _, _, why, partner, consent = _questions(client)["questions"]
    assert _save(client, consent, "Yes").status_code == 422
    assert _save(client, partner, "Maybe").status_code == 422
    assert _save(client, partner, "2").status_code == 200
    assert _save(client, why, "I am interested in the role.").status_code == 200
    payload["questions"][2]["label"] = "Why this team specifically?"
    assert _save(client, why, "A stale answer").status_code == 409
    assert "answer" in _questions(client)["questions"][2]
    assert _questions(client)["questions"][2]["answer"] is None


def test_profile_library_is_editable_but_never_reuses_an_answer_across_roles_or_owners(stack):
    client, _, _, _ = stack
    why = _questions(client)["questions"][2]
    assert _save(client, why, "My first answer").status_code == 200
    [entry] = client.get(LIBRARY).json()["items"]
    assert (entry["company_name"], entry["job_title"]) == ("Acme", "Engineer")
    url = f"{LIBRARY}/{entry['id']}"
    assert client.put(url, json={"answer": "My edited answer"}).status_code == 200
    assert _questions(client)["questions"][2]["answer"] == "My edited answer"
    for job_id in [OTHER_ROLE, OTHER_COMPANY]:
        assert _questions(client, job_id)["questions"][2]["answer"] is None
    owner = app.dependency_overrides[current_active_user]
    app.dependency_overrides[current_active_user] = lambda: UserDB(
        id="other",
        email="other@example.com",
        is_active=True,
        is_superuser=True,
        is_verified=True,
    )
    try:
        assert client.get(LIBRARY).json()["items"] == []
        assert _questions(client)["questions"][2]["answer"] is None
        assert client.put(url, json={"answer": "Never written"}).status_code == 404
        assert client.delete(url).status_code == 404
    finally:
        app.dependency_overrides[current_active_user] = owner
    assert client.delete(url).status_code == 204
    assert _questions(client)["questions"][2]["answer"] is None


def test_original_document_prepares_for_the_stored_posting_and_never_queues_real_submit(stack):
    client, factory, _, original = stack
    _, _, why, partner, _ = _questions(client)["questions"]
    assert _save(client, why, "My role-specific answer").status_code == 200
    assert _save(client, partner, "2").status_code == 200
    response = client.post(
        "/api/applications/prepare",
        json={
            "job_id": FIRST,
            "document_id": "profile-cv",
            "job_url": "https://outside.invalid/",
            "job_title": "Spoofed",
            "company_name": "Spoofed",
            "candidate_name": "Ada Lovelace",
            "email": "ada@example.com",
            "phone": "+1 555 0100",
        },
    )
    assert response.status_code == 200, response.text
    prepared = response.json()
    assert prepared["prepared_summary"]["job_title"] == "Engineer"
    assert prepared["prepared_summary"]["document_id"] == "profile-cv"
    assert prepared["blocking_questions"] == []
    assert (
        client.post(f"/api/applications/{prepared['approval_id']}/approve", json={}).status_code
        == 409
    )
    with factory() as db:
        row = db.get(ApprovalRequestDB, prepared["approval_id"])
        assert Path(row.payload["resume_path"]) == original
        assert (
            row.payload["posting_review"]["answers"][why["question_key"]]
            == "My role-specific answer"
        )
        tracked = db.get(ApplicationDB, prepared["application_id"])
        assert (
            tracked.owner_id,
            tracked.job_id,
            tracked.profile_id,
            tracked.tailored_resume_id,
        ) == (
            LEGACY_OWNER_ID,
            FIRST,
            "cv",
            None,
        )
        assert db.scalar(select(func.count()).select_from(JobRunDB)) == 0


def _prepare(client: TestClient, **overrides):
    body = {
        "job_id": FIRST,
        "document_id": "profile-cv",
        "job_url": "https://outside.invalid/",
        "job_title": "Spoofed",
        "company_name": "Spoofed",
        "candidate_name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+1 555 0100",
    }
    return client.post("/api/applications/prepare", json={**body, **overrides})


def test_review_is_reopenable_and_detects_edits_in_profile_and_to_the_file(stack):
    client, _, _, resume = stack
    why = _questions(client)["questions"][2]
    assert _save(client, why, "My first answer").status_code == 200
    response = _prepare(client)
    assert response.status_code == 200, response.text
    application_id = response.json()["application_id"]
    url = f"/api/applications/{application_id}/posting-review"
    first = client.get(url).json()
    assert first["document_current"] is True
    assert first["review_current"] is True
    assert first["posting_form"]["questions"][2]["answer"] == "My first answer"
    assert first["on_employer_site"] == [CONSENT]
    assert first["blocking_questions"] == [PARTNER]
    [entry] = client.get(LIBRARY).json()["items"]
    assert (
        client.put(f"{LIBRARY}/{entry['id']}", json={"answer": "My edited answer"}).status_code
        == 200
    )
    resume.write_text("Changed after the review", encoding="utf-8")
    revised = client.get(url).json()
    assert revised["review_current"] is False
    assert revised["document_current"] is False
    assert revised["posting_form"]["questions"][2]["answer"] == "My first answer"
    assert (
        client.patch(
            f"/api/applications/{application_id}/status", json={"status": "awaiting_approval"}
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"/api/applications/{application_id}/answers",
            json={
                "answers": [{"question_key": why["question_key"], "answer": "Unreviewed answer"}],
            },
        ).status_code
        == 409
    )


def test_assisted_fill_is_confirmed_scoped_single_use_and_never_submits(stack):
    client, factory, _, resume = stack
    _, _, why, partner, _ = _questions(client)["questions"]
    assert _save(client, why, "My answer").is_success
    assert _save(client, partner, "2").is_success
    packet = _prepare(client).json()
    app_id = packet["application_id"]
    route = f"/api/applications/{app_id}/authorize-fill"
    assert packet.get("assist_available") is True
    assert client.post(route, json={}).status_code == 422
    response = client.post(route, json={"purpose": "fill_only"})
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    code = response.json()["code"]
    assert code not in client.get(f"/api/applications/{app_id}/posting-review").text
    from src.api.posting_assist import FillRefused, claim_local_fill
    from src.db.audit import AuditEventDB
    from src.db.employer_answers import LocalFillGrantDB

    with factory() as db:
        row = db.get(LocalFillGrantDB, app_id)
        assert row.owner_id == LEGACY_OWNER_ID and row.code_digest != code
        grant = claim_local_fill(db, code)
        assert grant.resume_bytes == resume.read_bytes()
        assert grant.application_id == app_id and grant.email == "ada@example.com"
        assert grant.form.questions[2].answer == "My answer"
        with pytest.raises(FillRefused):
            claim_local_fill(db, code)
        assert db.scalar(select(func.count()).select_from(JobRunDB)) == 0
        assert db.get(ApplicationDB, app_id).submitted_at is None
        audited = [
            (event.action, event.extra_metadata) for event in db.scalars(select(AuditEventDB))
        ]
        assert code not in str(audited) and "My answer" not in str(audited)


def test_fill_refuses_missing_answers_changed_document_and_foreign_even_admin(stack):
    client, factory, _, resume = stack
    why, partner = _questions(client)["questions"][2:4]
    packet = _prepare(client).json()
    route = f"/api/applications/{packet['application_id']}/authorize-fill"
    assert client.post(route, json={"purpose": "fill_only"}).status_code == 409
    assert _save(client, why, "My answer").is_success
    assert _save(client, partner, "2").is_success
    packet = _prepare(client).json()
    route = f"/api/applications/{packet['application_id']}/authorize-fill"
    override = app.dependency_overrides[current_active_user]
    app.dependency_overrides[current_active_user] = lambda: UserDB(
        id="another",
        email="another@example.com",
        is_active=True,
        is_superuser=True,
    )
    try:
        assert client.post(route, json={"purpose": "fill_only"}).status_code == 404
    finally:
        app.dependency_overrides[current_active_user] = override
    first = client.post(route, json={"purpose": "fill_only"}).json()["code"]
    latest = client.post(route, json={"purpose": "fill_only"}).json()["code"]
    assert latest != first
    from src.api.posting_assist import FillRefused, claim_local_fill

    with factory() as db:
        with pytest.raises(FillRefused):
            claim_local_fill(db, first)
        resume.write_bytes(b"Changed since approval")
        with pytest.raises(FillRefused):
            claim_local_fill(db, latest)
    assert client.post(route, json={"purpose": "fill_only"}).status_code == 409
    unsupported = _prepare(client, job_id="ashby:42").json()
    assert unsupported["assist_available"] is False


def test_prepare_requires_an_owned_document_and_never_attaches_a_client_path(stack):
    client, _, _, _ = stack
    assert _prepare(client, document_id="profile-unknown").status_code == 404
    assert _prepare(client, resume_path="wrong.txt").status_code == 422
    assert _prepare(client, document_id="tailored-unknown").status_code == 404


def test_schema_unavailable_is_not_reported_as_zero_questions(stack, monkeypatch):
    client, _, _, _ = stack

    async def no_schema(self, url):
        return None

    monkeypatch.setattr(
        "src.applications.greenhouse_adapter.GreenhouseAdapter.fetch_form_schema", no_schema
    )
    assert _questions(client)["state"] == "unavailable"
    assert _questions(client, "ashby:42")["state"] == "unsupported"
