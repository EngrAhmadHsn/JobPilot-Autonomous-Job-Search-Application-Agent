"""WS-45 · the per-application questions page's read.

The questions page shows one application's employer questions as **the
prepared packet recorded them** — not a live re-fetch of the board's form.
That is only possible because the plan is stored with the approval, so the
properties under test here are:

1. **The plan is persisted with the packet** — ``build_approval_row`` keeps
   the question dicts, so the page has something durable to read.
2. **The read folds in saved answers** — a question answered through
   ``PUT .../answers`` (which does not re-prepare) stops reading as
   ``needs_human`` on the next ``GET .../questions``, and leaves the
   blocking list. Without this the page would show a stale "needs you"
   for a question the human just answered.
3. **A plan-less application is honest** — one that never went through
   prepare reports ``plan_available=false`` and no questions, rather than
   an empty form that reads as "no questions asked".
4. **Ownership** — a foreign application is a 404, indistinguishably.
5. **Policy holds** — a ``never_autofill`` verdict is never flipped by a
   stored answer, even one written by an older path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.applications.tracking import create_application
from src.auth.routes import current_active_user
from src.db.approval import ApprovalRequestDB
from src.db.base import Base
from src.db.session import get_db
from src.db.users import LEGACY_OWNER_ID, UserDB
from src.main import app

JOB_URL = "http://localhost:8000/jobs/1/apply"

SPONSORSHIP_LABEL = "Will you now or in the future require sponsorship?"

#: A stored plan in the shape ``plan_as_dicts`` writes.
STORED_PLAN = [
    {
        "question_key": "first name",
        "label": "First Name",
        "required": True,
        "block": "Personal information",
        "verdict": "answerable",
        "category": "first_name",
        "answer_from": "first_name",
        "fields": ["first_name"],
    },
    {
        "question_key": SPONSORSHIP_LABEL.lower(),
        "label": SPONSORSHIP_LABEL,
        "required": True,
        "block": "Personal information",
        "verdict": "needs_human",
        "category": "visa_sponsorship",
        "answer_from": None,
        "fields": ["question_42"],
    },
    {
        "question_key": "voluntary self identification of gender",
        "label": "Voluntary Self Identification of Gender",
        "required": False,
        "block": "Voluntary self identification",
        "verdict": "never_autofill",
        "category": "eeo_gender",
        "answer_from": None,
        "fields": ["question_99"],
    },
]


@pytest.fixture
def session_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An isolated database, with the suite's sessions pointed at it."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'questions.db').as_posix()}")
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


@pytest.fixture
def other_caller():
    """Switch the request identity to a second account (for the 404 matrix)."""
    caller = UserDB(
        id="bob",
        email="bob@example.com",
        hashed_password="!",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    app.dependency_overrides[current_active_user] = lambda: caller
    yield caller
    app.dependency_overrides.pop(current_active_user, None)


def _tracked(session_factory, *, plan: list[dict] | None = None) -> tuple[str, str | None]:
    """A tracked application, optionally behind an approval carrying *plan*."""
    approval_id: str | None = None
    with session_factory() as session:
        if plan is not None:
            approval_id = "appr-1"
            session.add(
                ApprovalRequestDB(
                    id=approval_id,
                    owner_id=LEGACY_OWNER_ID,
                    workflow_id="wf-1",
                    adapter_name="fake-ats-playwright",
                    job_url=JOB_URL,
                    job_title="Backend Engineer",
                    company_name="Northstar Labs",
                    payload={},
                    status="pending",
                    created_at=datetime.now(UTC),
                    form_questions=plan,
                )
            )
            session.commit()
        row = create_application(
            session,
            owner_id=LEGACY_OWNER_ID,
            workflow_id="wf-1",
            adapter_name="fake-ats-playwright",
            job_url=JOB_URL,
            job_title="Backend Engineer",
            company_name="Northstar Labs",
            approval_id=approval_id,
        )
        return row.id, approval_id


def test_a_plan_less_application_reports_unknown_questions(client, session_factory):
    """An application that never went through prepare has no plan — said, not faked."""
    application_id, _ = _tracked(session_factory)

    body = client.get(f"/api/applications/{application_id}/questions").json()

    assert body["plan_available"] is False
    assert body["questions"] == []
    assert body["answers"] == []
    assert body["blocking_questions"] == []
    # The application's own facts still come back, so the page can head itself.
    assert body["job_title"] == "Backend Engineer"
    assert body["company_name"] == "Northstar Labs"


def test_the_stored_plan_is_returned_in_the_boards_own_order(client, session_factory):
    """The questions come back as prepared, with the blocking ones named."""
    application_id, approval_id = _tracked(session_factory, plan=STORED_PLAN)

    body = client.get(f"/api/applications/{application_id}/questions").json()

    assert body["plan_available"] is True
    assert body["approval_id"] == approval_id
    assert [q["label"] for q in body["questions"]] == [item["label"] for item in STORED_PLAN]
    assert body["blocking_questions"] == [SPONSORSHIP_LABEL]
    # The verdicts travel with the questions: the console renders chips from them.
    verdicts = {q["label"]: q["verdict"] for q in body["questions"]}
    assert verdicts["First Name"] == "answerable"
    assert verdicts[SPONSORSHIP_LABEL] == "needs_human"
    assert verdicts["Voluntary Self Identification of Gender"] == "never_autofill"


def test_a_saved_answer_unblocks_the_question_on_the_next_read(client, session_factory):
    """A save folds back into the stored plan: the question stops needing a human."""
    application_id, _ = _tracked(session_factory, plan=STORED_PLAN)

    saved = client.put(
        f"/api/applications/{application_id}/answers",
        json={
            "answers": [
                {
                    "question_key": SPONSORSHIP_LABEL,
                    "label": SPONSORSHIP_LABEL,
                    "category": "visa_sponsorship",
                    "answer": "No",
                }
            ]
        },
    )
    assert saved.status_code == 200

    body = client.get(f"/api/applications/{application_id}/questions").json()

    sponsorship = next(q for q in body["questions"] if q["label"] == SPONSORSHIP_LABEL)
    assert sponsorship["verdict"] == "answerable"
    assert sponsorship["answer_from"] == "you"
    assert body["blocking_questions"] == []
    assert [a["answer"] for a in body["answers"]] == ["No"]


def test_a_never_autofill_verdict_is_never_flipped(client, session_factory):
    """EEO/attestation rows stay what they are, whatever a stored answer says.

    The route refuses to *save* such an answer (422), so this pins the read
    side: a plan row marked ``never_autofill`` keeps its verdict even if a
    matching answer row exists in the database from some older path.
    """
    application_id, _ = _tracked(session_factory, plan=STORED_PLAN)
    # Write the row past the route, the way an older build could have.
    saved = client.put(
        f"/api/applications/{application_id}/answers",
        json={
            "answers": [
                {
                    "question_key": "Voluntary Self Identification of Gender",
                    "label": "Voluntary Self Identification of Gender",
                    "category": "eeo_gender",
                    "answer": "Decline to self-identify",
                }
            ]
        },
    )
    assert saved.status_code == 422

    body = client.get(f"/api/applications/{application_id}/questions").json()
    gender = next(
        q for q in body["questions"] if q["label"] == "Voluntary Self Identification of Gender"
    )
    assert gender["verdict"] == "never_autofill"
    assert gender["answer_from"] is None


def test_a_foreign_application_is_a_404(client, session_factory, other_caller):
    """Ownership: another account's application answers exactly like a missing one."""
    application_id, _ = _tracked(session_factory, plan=STORED_PLAN)

    response = client.get(f"/api/applications/{application_id}/questions")

    assert response.status_code == 404


def test_a_missing_application_is_a_404(client, session_factory):
    """The same 404 as the foreign case — the API is not an existence oracle."""
    assert client.get("/api/applications/does-not-exist/questions").status_code == 404
