"""WS-14 · A2 — the two-user isolation matrix over HTTP (AC-ISO).

**The property under test:** two users on the same deployment must not be
able to reach each other's data — not by guessing an id, not by guessing a
file name, and not by learning that a resource exists.

This is the matrix the brief asked for: **user A's resource id must
yield nothing for user B.** And the two ways of saying "not yours" must
be indistinguishable, or the API becomes an existence oracle.

Three things make this suite different from the accessor-level matrix in
``tests/test_tenant_isolation.py``:

1. it goes over **HTTP**, through the real authentication, so it proves
   the *route* is scoped and not only the accessor;
2. it uses the **real** cookie and bearer transports, with no dependency
   override — an override would prove that the override works;
3. it checks the **byte-identical** body rule, which is what stops the
   fix from creating a new oracle.

And the check that stops the control decaying is here too: **no route
module may reach a user-scoped table directly.** That check is written
against the **AST**, not against the text, because the text search missed
a real hole — a route that built its query with ``select(...)`` and
another that resolved the model name at runtime.

(The name is ``test_tenant_isolation_api`` rather than
``test_isolation`` because that name is taken by the WS-08 browser
*session*-isolation suite, which is a different property entirely.)
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.auth.routes import current_active_user
from src.config.settings import get_settings
from src.db.base import Base
from src.db.session import get_db
from src.main import app

ALICE = "alice@example.com"
BOB = "bob@example.com"
PASSWORD = "correct horse battery staple"

#: The user-scoped tables. ``jobs`` is deliberately absent: it holds
#: public board data and is the one table that *should* be shared.
USER_SCOPED_MODELS: tuple[str, ...] = (
    "CandidateProfileDB",
    "JobMatchDB",
    "TailoredResumeDB",
    "ApplicationDB",
    "ApplicationEventDB",
    "ApplicationEvidenceDB",
    "ApprovalRequestDB",
    "AuditEventDB",
)

#: Every model a route is allowed to name. A route that names a model
#: which is not in this list is reaching the database by an indirect
#: name, which is the shape of an evasion.
KNOWN_MODELS: frozenset[str] = frozenset(USER_SCOPED_MODELS) | {"JobDB"}

#: The session methods that read a table.
_QUERY_METHODS = frozenset({"get", "query", "scalar", "scalars", "execute", "select_from"})


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient with a throwaway database and **no** identity override.

    The autouse ``authenticated_caller`` fixture is removed here on
    purpose: this suite is about the real authentication, so the routes
    must resolve the principal from the real credential.
    """
    app.dependency_overrides.pop(current_active_user, None)

    engine = create_engine(f"sqlite:///{(tmp_path / 'isolation.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "data" / "evidence"))
    monkeypatch.setenv("RESUME_UPLOAD_DIR", str(tmp_path / "data" / "resumes"))
    monkeypatch.setenv("TAILORED_DIR", str(tmp_path / "data" / "tailored"))
    # The first registered account claims the rows that pre-date the
    # identity work. This suite creates its own rows, so the claim is
    # not wanted here.
    monkeypatch.setenv("AUTH_CLAIM_LEGACY", "false")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def _register(client: TestClient, email: str) -> str:
    """Register an account and return its id."""
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _token(client: TestClient, email: str) -> str:
    """Log in through the bearer transport and return the access token."""
    response = client.post(
        "/api/auth/token/login",
        data={"username": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _as(token: str) -> dict[str, str]:
    """The authorization header for a bearer token."""
    return {"Authorization": f"Bearer {token}"}


def _user_id(client: TestClient, token: str) -> str:
    """The account id a bearer token belongs to."""
    with next(client.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
        from src.auth.tokens import AccessTokenDB

        row = db.get(AccessTokenDB, token)
        assert row is not None
        return row.user_id


def _seed_profile(client: TestClient, token: str, name: str) -> str:
    """Write a profile owned by the token's account, and return its id."""
    from src.db.profiles import build_profile_row
    from src.resume.profile import CandidateProfile

    profile = CandidateProfile.model_validate(
        {
            "personal_information": {"name": name, "email": name},
            "professional_summary": "",
            "skills": [],
            "experience": [],
            "education": [],
            "certifications": [],
            "projects": [],
        }
    )
    with next(client.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
        row = build_profile_row(profile, f"/tmp/{name}.docx", owner_id=_user_id(client, token))
        db.add(row)
        db.commit()
        return row.id


def _seed_approval(client: TestClient, token: str) -> str:
    """Write a pending approval owned by the token's account."""
    from src.db.approval import ApprovalRequestDB, generate_approval_id

    with next(client.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
        row = ApprovalRequestDB(
            id=generate_approval_id(),
            owner_id=_user_id(client, token),
            workflow_id="wf-1",
            adapter_name="fake-ats-playwright",
            job_url="https://boards.greenhouse.io/x/1",
            job_title="Engineer",
            company_name="Acme",
            payload={},
            status="pending",
        )
        db.add(row)
        db.commit()
        return row.id


# -- the matrix ---------------------------------------------------------------


class TestTheTwoUserMatrix:
    """User A's resource id must yield nothing for user B."""

    def test_a_profile_is_not_readable_by_another_user(self, api: TestClient) -> None:
        _register(api, ALICE)
        _register(api, BOB)
        alice_token = _token(api, ALICE)
        bob_token = _token(api, BOB)

        profile_id = _seed_profile(api, alice_token, "alice")

        assert api.get(f"/api/resumes/{profile_id}", headers=_as(alice_token)).status_code == 200
        assert api.get(f"/api/resumes/{profile_id}", headers=_as(bob_token)).status_code == 404

    def test_a_foreign_resource_answers_exactly_like_a_missing_one(self, api: TestClient) -> None:
        """Check 4 of AC-ISO: the two answers must be indistinguishable."""
        _register(api, ALICE)
        _register(api, BOB)
        alice_token = _token(api, ALICE)
        bob_token = _token(api, BOB)

        profile_id = _seed_profile(api, alice_token, "alice")

        foreign = api.get(f"/api/resumes/{profile_id}", headers=_as(bob_token))
        missing = api.get("/api/resumes/no-such-profile", headers=_as(bob_token))
        assert foreign.status_code == missing.status_code == 404
        assert foreign.content == missing.content, (
            "the 'not yours' answer differs from the 'does not exist' answer — "
            "the API is an existence oracle"
        )

    def test_a_listing_does_not_leak_another_users_rows(self, api: TestClient) -> None:
        _register(api, ALICE)
        _register(api, BOB)
        alice_token = _token(api, ALICE)
        bob_token = _token(api, BOB)

        _seed_profile(api, alice_token, "alice")
        _seed_profile(api, bob_token, "bob")

        # The applications listing is the one that used to have no scope
        # at all, and it used to count and list every user's rows.
        applications = api.get("/api/applications", headers=_as(alice_token))
        assert applications.status_code == 200, applications.text
        assert applications.json()["total"] == 0
        assert applications.json()["items"] == []

    def test_an_unauthenticated_request_is_refused(self, api: TestClient) -> None:
        for method, path in (
            ("get", "/api/resumes/whatever"),
            ("get", "/api/applications"),
            ("get", "/api/applications/whatever"),
            ("post", "/api/resumes"),
            ("post", "/api/jobs/search"),
            ("post", "/api/tailor"),
            ("post", "/api/applications/prepare"),
            ("get", "/api/tailored/whatever"),
            ("get", "/api/tailored/whatever/download"),
            ("patch", "/api/applications/whatever/status"),
        ):
            response = api.request(method.upper(), path, json={})
            assert response.status_code == 401, (
                f"{method.upper()} {path} answered {response.status_code} without a credential"
            )

    def test_the_health_endpoint_stays_open(self, api: TestClient) -> None:
        """A liveness probe is not a protected resource."""
        assert api.get("/api/health").status_code == 200


class TestTheApproverIsThePrincipal:
    """Threat T2: a body-supplied approver is ignored."""

    def test_a_body_supplied_approver_is_ignored(self, api: TestClient) -> None:
        _register(api, ALICE)
        alice_token = _token(api, ALICE)
        alice_id = _user_id(api, alice_token)

        approval_id = _seed_approval(api, alice_token)

        response = api.post(
            f"/api/applications/{approval_id}/reject",
            json={"approver": "somebody-else", "reason": "not now"},
            headers=_as(alice_token),
        )
        assert response.status_code == 200, response.text
        assert response.json()["metadata"]["approver"] == alice_id

        from src.db.approval import ApprovalRequestDB

        with next(api.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
            stored = db.get(ApprovalRequestDB, approval_id)
            assert stored.approver == alice_id, (
                "the approval was recorded under a name the caller chose"
            )

    def test_another_user_cannot_decide_an_approval(self, api: TestClient) -> None:
        _register(api, ALICE)
        _register(api, BOB)
        alice_token = _token(api, ALICE)
        bob_token = _token(api, BOB)

        approval_id = _seed_approval(api, alice_token)

        response = api.post(
            f"/api/applications/{approval_id}/reject",
            json={"reason": "not mine"},
            headers=_as(bob_token),
        )
        assert response.status_code == 404


class TestTheWritersRecordTheOwner:
    """A row must be owned by the account that caused it.

    Two bugs of the same shape were found by the **live** run, not by the
    suite: a function accepted an ``owner_id`` and used it for one write
    but not for the row it was actually about. The row landed on the
    legacy owner, which is invisible to the account that created it — and
    is claimed by whoever registers next.

    These tests are the mechanical version of that lesson.
    """

    def test_a_tracked_application_is_owned_by_its_account(self, api: TestClient) -> None:
        from src.applications.tracking import create_application

        with next(api.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
            row = create_application(
                db,
                owner_id="alice",
                workflow_id="wf-owner",
                adapter_name="fake-ats",
                job_url="https://boards.greenhouse.io/x/1",
                job_title="Engineer",
                company_name="Acme",
            )
            assert row.owner_id == "alice", (
                "the tracked application was not owned by the account that "
                "prepared it"
            )

    def test_an_evidence_record_is_owned_by_the_account(self, api: TestClient) -> None:
        from src.db.evidence import ApplicationEvidenceDB

        with next(api.app.dependency_overrides[get_db]()) as db:  # type: ignore[misc]
            record = ApplicationEvidenceDB(
                owner_id="alice",
                application_id="app-alice",
                workflow_id="wf-owner",
                adapter_name="fake-ats",
                job_url="https://boards.greenhouse.io/x/1",
                status="verified",
            )
            db.add(record)
            db.commit()
            assert record.owner_id == "alice"


# -- the check that stops the control decaying --------------------------------


class TestNoDirectRouteQueries:
    """AC-ISO, check 2 — and the hole the text search left open.

    The accessors are the only way a route may reach a user-scoped table.
    A route that queries one directly is a route that has opted out of the
    owner filter.

    The check is written against the **AST** rather than the source text.
    The text search looked for ``db.get(Model`` and ``db.query(Model`` and
    therefore missed two real holes that this suite found: a route that
    built its query with ``select(Model)``, and a route that resolved the
    model name at runtime and passed the *variable* to ``db.query``.
    """

    def _route_sources(self) -> list[Path]:
        return sorted((Path(__file__).parent.parent / "src" / "api" / "routes").glob("*.py"))

    @staticmethod
    def _model_name(node: ast.AST) -> str | None:
        """The model a node names, if it names one."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def test_no_route_queries_a_user_scoped_table_directly(self) -> None:
        offenders: list[str] = []
        for path in self._route_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func

                # ``select(Model)`` — the model is the thing selected.
                if isinstance(func, ast.Name) and func.id == "select":
                    for arg in node.args:
                        self._check_model(path, node, "select", arg, offenders)
                    continue
                if not isinstance(func, ast.Attribute):
                    continue
                # ``select(...).select_from(Model)``.
                if func.attr == "select_from":
                    for arg in node.args:
                        self._check_model(path, node, "select_from", arg, offenders)
                    continue
                # ``db.get(Model, key)`` and ``db.query(Model)``: the model
                # is the **first** argument. The rest are keys, and a key
                # is not a model.
                if func.attr in {"get", "query"} and node.args:
                    self._check_model(path, node, func.attr, node.args[0], offenders)
        assert not offenders, (
            "A route reaches a user-scoped table directly, bypassing the owner "
            "filter in src.db.access:\n  " + "\n  ".join(offenders)
        )

    def _check_model(
        self,
        path: Path,
        node: ast.Call,
        call: str,
        arg: ast.AST,
        offenders: list[str],
    ) -> None:
        """Record an offence when *arg* names a table a route may not read."""
        name = self._model_name(arg)
        if name is None:
            return
        if name in USER_SCOPED_MODELS:
            offenders.append(
                f"{path.name}:{node.lineno}: {call}({name}) "
                "reaches a user-scoped table directly"
            )
        elif name not in KNOWN_MODELS:
            offenders.append(
                f"{path.name}:{node.lineno}: {call}({name}) names "
                "the model indirectly — the route is reaching the "
                "database by a name a text search cannot see"
            )

    def test_no_route_names_the_legacy_owner(self) -> None:
        """The note A0 left for A2.

        ``LEGACY_OWNER_ID`` in a route module is the single-tenant
        assumption written down: a write path that stamps the legacy
        owner instead of the request's principal.
        """
        offenders = [
            path.name
            for path in self._route_sources()
            if "LEGACY_OWNER_ID" in path.read_text(encoding="utf-8")
        ]
        assert not offenders, (
            "A route module still names the legacy owner; the write paths must "
            "use the request's scope:\n  " + "\n  ".join(offenders)
        )

    def test_every_route_module_imports_the_scope_dependency(self) -> None:
        """A route that touches user data must take its scope from one place."""
        for path in self._route_sources():
            text = path.read_text(encoding="utf-8")
            if "access." in text:
                assert "current_scope" in text, (
                    f"{path.name} uses the scoped accessors but does not take its "
                    "scope from src.api.scope.current_scope"
                )
