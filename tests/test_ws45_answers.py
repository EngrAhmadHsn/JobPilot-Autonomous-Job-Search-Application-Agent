"""WS-45 · the per-application answers: storage, routes, and the prepare merge.

The answering flow closes the one hole the Review screen had: a required
employer question blocked approval with nowhere to put a human's answer.
The properties under test here:

1. **Ownership** — answers belong to one application of one owner. A
   foreign application answers exactly like a missing one (404 over HTTP,
   ``None``/``[]`` at the accessor), and a superuser reads **no**
   cross-owner answers: they are personal data, under the same rule as
   the caller's own model credential.
2. **The route contract** — the shape the console (and its MSW mocks)
   builds against: ``GET``/``PUT /api/applications/{id}/answers`` with the
   same response body, upsert semantics, and the policy refusals (EEO and
   attestation answers are **never** stored — 422, not a bug).
3. **The merge** — a saved answer flips a ``needs_human`` verdict to
   ``answerable`` (``answer_from="you"``) on the *next* prepare for the
   same posting, so ``blocking_questions`` shrinks and the approval gate
   unlocks.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.applications.tracking import create_application
from src.auth.routes import current_active_user
from src.db import access
from src.db.access import UserScope
from src.db.applications import ApplicationEventDB
from src.db.audit import AuditEventDB
from src.db.base import Base
from src.db.session import get_db
from src.db.users import LEGACY_OWNER_ID, UserDB
from src.main import app

JOB_URL = "http://localhost:8000/jobs/1/apply"

#: The default suite caller is the legacy owner; this is its scope.
LEGACY_SCOPE = UserScope(user_id=LEGACY_OWNER_ID)

SPONSORSHIP_LABEL = "Will you now or in the future require sponsorship?"
SPONSORSHIP_ANSWER = {
    "question_key": SPONSORSHIP_LABEL,
    "label": SPONSORSHIP_LABEL,
    "category": "visa_sponsorship",
    "answer": "No",
}


def _track(
    factory,
    *,
    owner_id: str = LEGACY_OWNER_ID,
    job_url: str = JOB_URL,
) -> str:
    """One tracked application for *owner_id*, as the prepare flow leaves it."""
    with factory() as session:
        row = create_application(
            session,
            owner_id=owner_id,
            workflow_id=f"wf-{job_url}",
            adapter_name="fake-ats-playwright",
            job_url=job_url,
            job_title="Engineer",
            company_name="Acme Labs",
        )
        return row.id


# ---------------------------------------------------------------------------
# The fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An isolated database, with the suite's sessions pointed at it."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'answers.db').as_posix()}")
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


# ---------------------------------------------------------------------------
# The accessors — the ownership layer
# ---------------------------------------------------------------------------


class TestAnswerAccessors:
    """Every read and write goes through src.db.access, owner-fenced."""

    def test_an_application_with_no_answers_lists_none(self, session_factory) -> None:
        application_id = _track(session_factory)

        with session_factory() as db:
            assert access.list_application_answers(db, LEGACY_SCOPE, application_id) == []

    def test_upsert_inserts_then_updates_in_place(self, session_factory) -> None:
        application_id = _track(session_factory)

        with session_factory() as db:
            rows = access.upsert_application_answers(
                db, LEGACY_SCOPE, application_id, [dict(SPONSORSHIP_ANSWER)]
            )
            db.commit()
            assert len(rows) == 1
            first_id = rows[0].id
            first_answered_at = rows[0].answered_at

        time.sleep(0.002)  # the refresh must be observable on the clock
        with session_factory() as db:
            rows = access.upsert_application_answers(
                db,
                LEGACY_SCOPE,
                application_id,
                [{"question_key": SPONSORSHIP_LABEL, "answer": "Yes"}],
            )
            db.commit()
            stored = access.list_application_answers(db, LEGACY_SCOPE, application_id)

        assert len(stored) == 1, "a re-answered question updates its row, never a second one"
        assert stored[0].id == first_id
        assert stored[0].answer_text == "Yes"
        assert stored[0].category == "visa_sponsorship"
        assert stored[0].answered_at > first_answered_at, "answered_at is refreshed"
        assert stored[0].updated_at >= stored[0].answered_at

    def test_a_missing_application_answers_like_an_empty_one(self, session_factory) -> None:
        with session_factory() as db:
            assert access.list_application_answers(db, LEGACY_SCOPE, "no-such-app") == []
            assert (
                access.upsert_application_answers(
                    db, LEGACY_SCOPE, "no-such-app", [dict(SPONSORSHIP_ANSWER)]
                )
                is None
            )

    def test_a_foreign_application_is_not_readable_nor_writable(self, session_factory) -> None:
        alice_app = _track(session_factory, owner_id="alice", job_url=JOB_URL)
        bob = UserScope(user_id="bob")

        with session_factory() as db:
            assert access.list_application_answers(db, bob, alice_app) == []
            assert (
                access.upsert_application_answers(
                    db, bob, alice_app, [dict(SPONSORSHIP_ANSWER)]
                )
                is None
            )
            db.rollback()

    def test_a_superuser_gets_no_cross_owner_exception(self, session_factory) -> None:
        """Answers are personal data — the same rule as the stored credential."""
        alice_app = _track(session_factory, owner_id="alice", job_url=JOB_URL)
        auditor = UserScope(user_id="auditor", is_superuser=True)

        with session_factory() as db:
            assert access.list_application_answers(db, auditor, alice_app) == []
            assert (
                access.upsert_application_answers(
                    db, auditor, alice_app, [dict(SPONSORSHIP_ANSWER)]
                )
                is None
            )
            db.rollback()

        # On the auditor's OWN application the write and read both work.
        own_app = _track(session_factory, owner_id="auditor", job_url=JOB_URL + "-own")
        with session_factory() as db:
            rows = access.upsert_application_answers(
                db, auditor, own_app, [dict(SPONSORSHIP_ANSWER)]
            )
            db.commit()
            assert len(rows) == 1
            assert access.list_application_answers(db, auditor, own_app)

    def test_the_applications_of_a_job_are_listed_newest_first(self, session_factory) -> None:
        """The prepare merge walks a posting's prior applications, newest first."""
        _track(session_factory)
        second = _track(session_factory, job_url=JOB_URL + "-2")
        _track(session_factory, owner_id="someone-else", job_url=JOB_URL + "-2")

        with session_factory() as db:
            mine = access.list_applications_for_job(db, LEGACY_SCOPE, JOB_URL + "-2")
            assert [row.id for row in mine] == [second]
            assert access.list_applications_for_job(db, LEGACY_SCOPE, "https://elsewhere") == []


# ---------------------------------------------------------------------------
# The route contract
# ---------------------------------------------------------------------------


class TestAnswerRoutes:
    """GET/PUT /api/applications/{id}/answers — the contract the console mocks."""

    def test_get_on_a_fresh_application_returns_an_empty_list(
        self, client, session_factory
    ) -> None:
        application_id = _track(session_factory)

        response = client.get(f"/api/applications/{application_id}/answers")

        assert response.status_code == 200
        assert response.json() == {"application_id": application_id, "answers": []}

    def test_put_saves_and_get_returns_the_saved_answers(
        self, client, session_factory
    ) -> None:
        application_id = _track(session_factory)

        put = client.put(
            f"/api/applications/{application_id}/answers",
            json={"answers": [dict(SPONSORSHIP_ANSWER)]},
        )
        assert put.status_code == 200, put.text
        body = put.json()
        assert body["application_id"] == application_id
        assert len(body["answers"]) == 1
        answer = body["answers"][0]
        assert answer["question_key"] == SPONSORSHIP_LABEL
        assert answer["label"] == SPONSORSHIP_LABEL
        assert answer["category"] == "visa_sponsorship"
        assert answer["answer"] == "No"
        assert answer["answered_at"]

        got = client.get(f"/api/applications/{application_id}/answers")
        assert got.status_code == 200
        assert got.json()["answers"] == body["answers"]

    def test_put_upserts_an_existing_question_key(self, client, session_factory) -> None:
        application_id = _track(session_factory)
        client.put(
            f"/api/applications/{application_id}/answers",
            json={"answers": [dict(SPONSORSHIP_ANSWER)]},
        )

        put = client.put(
            f"/api/applications/{application_id}/answers",
            json={
                "answers": [
                    {
                        "question_key": SPONSORSHIP_LABEL,
                        "label": SPONSORSHIP_LABEL,
                        "category": "visa_sponsorship",
                        "answer": "Yes",
                    }
                ]
            },
        )

        assert put.status_code == 200
        assert len(put.json()["answers"]) == 1
        assert put.json()["answers"][0]["answer"] == "Yes"
        got = client.get(f"/api/applications/{application_id}/answers")
        assert len(got.json()["answers"]) == 1

    def test_put_on_an_unknown_application_is_a_404(self, client, session_factory) -> None:
        response = client.put(
            "/api/applications/no-such-app/answers",
            json={"answers": [dict(SPONSORSHIP_ANSWER)]},
        )
        assert response.status_code == 404

    def test_get_on_an_unknown_application_is_a_404(self, client, session_factory) -> None:
        assert client.get("/api/applications/no-such-app/answers").status_code == 404

    def test_a_foreign_application_answers_404_like_a_missing_one(
        self, client, session_factory, other_caller
    ) -> None:
        """The isolation matrix, over the answers route: not-yours is not-found."""
        application_id = _track(session_factory)  # owned by the suite's default caller

        foreign_put = client.put(
            f"/api/applications/{application_id}/answers",
            json={"answers": [dict(SPONSORSHIP_ANSWER)]},
        )
        missing_put = client.put(
            "/api/applications/no-such-app/answers",
            json={"answers": [dict(SPONSORSHIP_ANSWER)]},
        )
        foreign_get = client.get(f"/api/applications/{application_id}/answers")
        missing_get = client.get("/api/applications/no-such-app/answers")

        assert foreign_put.status_code == missing_put.status_code == 404
        assert foreign_get.status_code == missing_get.status_code == 404
        assert foreign_put.json()["detail"] == missing_put.json()["detail"]
        assert foreign_get.json()["detail"] == missing_get.json()["detail"]

    def test_put_with_an_empty_list_is_a_422(self, client, session_factory) -> None:
        application_id = _track(session_factory)
        response = client.put(
            f"/api/applications/{application_id}/answers", json={"answers": []}
        )
        assert response.status_code == 422

    def test_put_with_more_than_100_items_is_a_422(self, client, session_factory) -> None:
        application_id = _track(session_factory)
        answers = [
            {"question_key": f"Question {index}", "answer": "x"} for index in range(101)
        ]
        response = client.put(
            f"/api/applications/{application_id}/answers", json={"answers": answers}
        )
        assert response.status_code == 422

    def test_put_with_an_over_long_answer_is_a_422(self, client, session_factory) -> None:
        application_id = _track(session_factory)
        response = client.put(
            f"/api/applications/{application_id}/answers",
            json={
                "answers": [
                    {"question_key": "Tell us about a project", "answer": "x" * 501}
                ]
            },
        )
        assert response.status_code == 422

    def test_put_rejects_a_blank_answer(self, client, session_factory) -> None:
        application_id = _track(session_factory)
        response = client.put(
            f"/api/applications/{application_id}/answers",
            json={"answers": [{"question_key": "Q", "answer": "   "}]},
        )
        assert response.status_code == 422

    def test_put_rejects_a_never_autofill_category_with_a_helpful_detail(
        self, client, session_factory
    ) -> None:
        """EEO and attestation answers are never stored — policy, not a bug."""
        application_id = _track(session_factory)
        for category in ("eeo_race", "eeo_gender", "eeo_disability", "eeo_veteran", "attestation"):
            response = client.put(
                f"/api/applications/{application_id}/answers",
                json={
                    "answers": [
                        {"question_key": "Some question", "category": category, "answer": "Yes"}
                    ]
                },
            )
            assert response.status_code == 422, category
            detail = response.json()["detail"]
            assert "never" in detail.lower(), category
            assert category in detail, "the detail names the refused category"

    def test_put_rejects_a_label_that_classifies_as_never_autofill(
        self, client, session_factory
    ) -> None:
        """A client cannot smuggle an EEO answer in with no category given."""
        application_id = _track(session_factory)
        response = client.put(
            f"/api/applications/{application_id}/answers",
            json={
                "answers": [
                    {
                        "question_key": "I certify that the information provided is true",
                        "answer": "Yes",
                    }
                ]
            },
        )
        assert response.status_code == 422
        assert "never" in response.json()["detail"].lower()

    def test_put_rejects_an_unknown_category(self, client, session_factory) -> None:
        application_id = _track(session_factory)
        response = client.put(
            f"/api/applications/{application_id}/answers",
            json={
                "answers": [
                    {"question_key": "Q", "category": "handedness", "answer": "left"}
                ]
            },
        )
        assert response.status_code == 422

    def test_put_records_an_event_and_an_audit_row(self, client, session_factory) -> None:
        application_id = _track(session_factory)
        client.put(
            f"/api/applications/{application_id}/answers",
            json={"answers": [dict(SPONSORSHIP_ANSWER)]},
        )

        with session_factory() as db:
            events = list(
                db.scalars(
                    select(ApplicationEventDB).where(
                        ApplicationEventDB.application_id == application_id
                    )
                )
            )
            recorded = [event for event in events if event.event_type == "answers_recorded"]
            assert len(recorded) == 1, "one event per save"
            assert recorded[0].extra_metadata.get("count") == 1
            assert recorded[0].actor.startswith("human:"), "the save is a human act"

            audits = list(
                db.scalars(
                    select(AuditEventDB).where(AuditEventDB.action == "application.answers_recorded")
                )
            )
            assert len(audits) == 1
            assert audits[0].owner_id == LEGACY_OWNER_ID
            assert audits[0].resource == application_id
            assert audits[0].outcome == "success"


# ---------------------------------------------------------------------------
# The merge at prepare time — the flow that unblocks approval
# ---------------------------------------------------------------------------


class StubAdapter:
    """A minimal adapter for the prepare route (no browser)."""

    name = "fake-ats-playwright"

    def supports_url(self, url: str) -> bool:
        return url.startswith("http://localhost")

    def prepare(self, request):
        from src.applications.contracts import PreparedApplication

        return PreparedApplication(request=request, prepared_fields={})

    def submit(self, prepared):
        raise AssertionError("prepare never submits")

    def verify(self, result):
        return result


def _prepare_payload(job_url: str = JOB_URL) -> dict:
    return {
        "job_title": "Senior Python Engineer",
        "company_name": "Acme Labs",
        "job_url": job_url,
        "candidate_name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+1 555 0101",
    }


@pytest.fixture
def prepare_stack(session_factory, monkeypatch: pytest.MonkeyPatch):
    """The prepare route, with the board's form served from a fixed schema.

    The real schema fetch is a live HTTP call to the board; the merge under
    test is the plan that the schema feeds, so the tests pin the schema and
    let everything else run for real.
    """
    from src.applications.greenhouse_forms import FormQuestion, FormSchema
    from src.graph import executor as graph_executor

    schema = FormSchema(
        questions=[
            FormQuestion(
                label=SPONSORSHIP_LABEL,
                required=True,
                field_names=["question_1"],
            ),
            FormQuestion(label="Full name", required=True, field_names=["first_name"]),
        ]
    )

    def fake_form_plans(adapter, job_url, facts, *, answers=None):
        from src.applications.form_plan import build_question_plan

        return build_question_plan(schema, facts, answers=answers)

    adapter = StubAdapter()
    monkeypatch.setattr(graph_executor, "AVAILABLE_ADAPTERS", [adapter])
    monkeypatch.setattr("src.api.routes.applications._build_form_plans", fake_form_plans)
    return schema


class TestPrepareMerge:
    """A saved answer unblocks the next prepare for the same posting.

    The prepare payload carries no profile, so the schema's second question
    ("Full name") is also ``needs_human`` — which is what makes the shrink
    visible: the answered question leaves ``blocking_questions``, the
    unanswered one stays.
    """

    def test_a_saved_answer_shrinks_the_blocking_questions(
        self, client, session_factory, prepare_stack
    ) -> None:
        first = client.post("/api/applications/prepare", json=_prepare_payload())
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["status"] == "blocked_human_review"
        assert body["blocking_questions"] == [SPONSORSHIP_LABEL, "Full name"]
        assert body["application_id"]
        assert body["form_questions"][0]["question_key"] == "will you now or in the future require sponsorship"

        saved = client.put(
            f"/api/applications/{body['application_id']}/answers",
            json={"answers": [dict(SPONSORSHIP_ANSWER)]},
        )
        assert saved.status_code == 200, saved.text

        second = client.post("/api/applications/prepare", json=_prepare_payload())
        assert second.status_code == 200, second.text
        merged = second.json()
        # The answered question left the blockers; the unanswered one stayed.
        assert merged["blocking_questions"] == ["Full name"]
        sponsorship = next(
            question
            for question in merged["form_questions"]
            if question["label"] == SPONSORSHIP_LABEL
        )
        assert sponsorship["verdict"] == "answerable"
        assert sponsorship["answer_from"] == "you"

    def test_a_different_posting_inherits_no_answers(
        self, client, session_factory, prepare_stack
    ) -> None:
        first = client.post("/api/applications/prepare", json=_prepare_payload())
        client.put(
            f"/api/applications/{first.json()['application_id']}/answers",
            json={"answers": [dict(SPONSORSHIP_ANSWER)]},
        )

        other = client.post(
            "/api/applications/prepare", json=_prepare_payload(JOB_URL + "-other")
        )

        assert other.json()["blocking_questions"] == [SPONSORSHIP_LABEL, "Full name"]

    def test_a_re_prepare_carries_the_saved_answers_forward(
        self, client, session_factory, prepare_stack
    ) -> None:
        """The answers follow the posting: a re-prepare inherits them.

        The console reaches prepare with a fresh form each time, so the
        application it just created must already carry what the human
        answered against the previous one — both for the plan merge and
        for the Review screen that reads ``GET .../answers``.
        """
        first = client.post("/api/applications/prepare", json=_prepare_payload())
        first_app = first.json()["application_id"]
        client.put(
            f"/api/applications/{first_app}/answers",
            json={"answers": [dict(SPONSORSHIP_ANSWER)]},
        )

        second = client.post("/api/applications/prepare", json=_prepare_payload())
        second_app = second.json()["application_id"]
        assert second.json()["blocking_questions"] == ["Full name"]
        assert second_app != first_app

        inherited = client.get(f"/api/applications/{second_app}/answers")
        assert inherited.status_code == 200
        answers = inherited.json()["answers"]
        assert len(answers) == 1
        assert answers[0]["question_key"] == SPONSORSHIP_LABEL
        assert answers[0]["answer"] == "No"

        # And a third prepare cannot regress: the inheritance chains.
        third = client.post("/api/applications/prepare", json=_prepare_payload())
        assert third.json()["blocking_questions"] == ["Full name"]
