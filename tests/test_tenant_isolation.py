"""WS-13 · A0 — the two-user isolation matrix (AC-ISO).

**The property under test:** two users on the same deployment must not be
able to reach each other's data — not by guessing an id, not by guessing a
file name, and not by learning that a resource exists.

These tests are the *mechanical* half of AC-ISO (the other half is
``TestNoDirectRouteQueries``). They are written against the accessors
rather than over HTTP because that is where the control lives: the
accessors are the only way a route reaches a user-scoped row, so proving
they filter is proving the control.

The matrix is the shape the brief asked for: **user A's resource id must
yield nothing for user B.** And the two ways of saying "not yours" must
be indistinguishable, or the API becomes an existence oracle.

(This is the tenant-isolation matrix. The browser *session* isolation of
WS-08 — two runs sharing no cookie — lives in ``test_isolation.py``.)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db import access
from src.db.access import UserScope
from src.db.applications import ApplicationDB, ApplicationEventDB
from src.db.approval import ApprovalRequestDB
from src.db.audit import AuditEventDB
from src.db.base import Base
from src.db.evidence import ApplicationEvidenceDB
from src.db.matches import JobMatchDB
from src.db.profiles import CandidateProfileDB
from src.db.tailored import TailoredResumeDB

#: The two principals. Neither is a superuser: a superuser scope may read
#: across owners, and a test that used one would prove nothing.
ALICE = UserScope(user_id="alice")
BOB = UserScope(user_id="bob")


@pytest.fixture
def session(tmp_path: Path):
    """A throwaway database with one row per user-scoped table."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'isolation.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add(
            CandidateProfileDB(
                id="profile-alice",
                owner_id=ALICE.user_id,
                name="Alice",
                profile_json={},
                file_path="/tmp/alice.docx",
            )
        )
        db.add(
            CandidateProfileDB(
                id="profile-bob",
                owner_id=BOB.user_id,
                name="Bob",
                profile_json={},
                file_path="/tmp/bob.docx",
            )
        )
        db.add(
            JobMatchDB(
                owner_id=ALICE.user_id,
                profile_id="profile-alice",
                job_id="job-1",
                scores={},
            )
        )
        db.add(
            TailoredResumeDB(
                id="tailored-alice",
                owner_id=ALICE.user_id,
                profile_id="profile-alice",
                job_id="job-1",
                tailored={},
                factuality={},
                ats_report={},
                docx_path="/tmp/alice.docx",
            )
        )
        db.add(
            ApplicationDB(
                id="app-alice",
                owner_id=ALICE.user_id,
                job_id="job-1",
                workflow_id="wf-1",
                adapter_name="fake-ats-playwright",
                job_url="https://boards.greenhouse.io/x/1",
                job_title="Engineer",
                company_name="Acme",
                status="prepared",
            )
        )
        db.add(
            ApplicationEventDB(
                owner_id=ALICE.user_id,
                application_id="app-alice",
                event_type="application.created",
                actor="agent",
            )
        )
        db.add(
            ApplicationEvidenceDB(
                owner_id=ALICE.user_id,
                application_id="app-alice",
                workflow_id="wf-1",
                adapter_name="fake-ats-playwright",
                job_url="https://boards.greenhouse.io/x/1",
                status="verified",
            )
        )
        db.add(
            ApprovalRequestDB(
                id="approval-alice",
                owner_id=ALICE.user_id,
                workflow_id="wf-1",
                adapter_name="fake-ats-playwright",
                job_url="https://boards.greenhouse.io/x/1",
                job_title="Engineer",
                company_name="Acme",
                payload={},
                status="pending",
            )
        )
        db.add(
            AuditEventDB(
                owner_id=ALICE.user_id,
                actor="user:alice",
                action="application.prepare",
                resource="app-alice",
                outcome="success",
            )
        )
        db.commit()
        yield db


# -- the matrix ---------------------------------------------------------------


class TestCrossUserAccess:
    """User B must not reach user A's rows by naming them."""

    def test_a_profile_is_not_readable_by_another_user(self, session):
        assert access.get_profile(session, ALICE, "profile-alice") is not None
        assert access.get_profile(session, BOB, "profile-alice") is None

    def test_a_tailored_resume_is_not_readable_by_another_user(self, session):
        assert access.get_tailored(session, ALICE, "tailored-alice") is not None
        assert access.get_tailored(session, BOB, "tailored-alice") is None

    def test_an_application_is_not_readable_by_another_user(self, session):
        """The IDOR the brief named: /api/applications/123 vs /124."""
        assert access.get_application(session, ALICE, "app-alice") is not None
        assert access.get_application(session, BOB, "app-alice") is None

    def test_an_approval_is_not_readable_by_another_user(self, session):
        assert access.get_approval(session, ALICE, "approval-alice") is not None
        assert access.get_approval(session, BOB, "approval-alice") is None

    def test_the_application_history_is_not_readable_by_another_user(self, session):
        assert access.list_application_events(session, ALICE, "app-alice")
        assert access.list_application_events(session, BOB, "app-alice") == []

    def test_the_match_history_is_not_readable_by_another_user(self, session):
        assert access.list_job_matches(session, ALICE, "profile-alice")
        assert access.list_job_matches(session, BOB, "profile-alice") == []

    def test_the_evidence_is_not_readable_by_another_user(self, session):
        assert access.list_evidence(session, ALICE, "wf-1")
        assert access.list_evidence(session, BOB, "wf-1") == []

    def test_the_audit_trail_is_not_readable_by_another_user(self, session):
        assert access.list_audit_events(session, ALICE)
        assert access.list_audit_events(session, BOB) == []

    def test_a_listing_does_not_leak_another_users_rows(self, session):
        assert [p.id for p in access.list_profiles(session, ALICE)] == ["profile-alice"]
        assert [p.id for p in access.list_profiles(session, BOB)] == ["profile-bob"]

    def test_an_application_listing_does_not_leak_another_users_rows(self, session):
        assert [a.id for a in access.list_applications(session, ALICE)] == ["app-alice"]
        assert access.list_applications(session, BOB) == []


class TestExistenceIsNotAnOracle:
    """A foreign resource and a missing one must look identical."""

    def test_a_foreign_id_and_a_missing_id_are_both_not_found(self, session):
        foreign = access.get_application(session, BOB, "app-alice")
        missing = access.get_application(session, BOB, "app-does-not-exist")
        assert foreign is None
        assert missing is None

    def test_the_two_answers_are_the_same_thing(self, session):
        """Not merely equal in value — the caller cannot tell them apart."""
        for accessor, args in (
            (access.get_application, ("app-alice",)),
            (access.get_profile, ("profile-alice",)),
            (access.get_tailored, ("tailored-alice",)),
            (access.get_approval, ("approval-alice",)),
        ):
            foreign = accessor(session, BOB, *args)
            missing = accessor(session, BOB, "no-such-thing")
            assert foreign is missing


class TestScopeSemantics:
    def test_a_superuser_may_read_across_owners(self, session):
        """The platform's audit view. It is the one deliberate exception."""
        auditor = UserScope(user_id="auditor", is_superuser=True)
        assert access.get_application(session, auditor, "app-alice") is not None

    def test_a_scope_owns_only_its_own_rows(self):
        assert ALICE.owns("alice") is True
        assert ALICE.owns("bob") is False
        assert ALICE.owns(None) is False

    def test_the_legacy_scope_sees_the_backfilled_rows(self, session):
        """The rows the migration backfilled belong to the legacy owner."""
        legacy = access.LEGACY_SCOPE
        assert access.get_profile(session, legacy, "profile-alice") is not None


class TestNoDirectRouteQueries:
    """AC-ISO, check 2: the control must not be able to decay.

    The accessors are the only way a route may reach a user-scoped table.
    A route that queries one directly is a route that has opted out of the
    owner filter, and this test fails if one appears.
    """

    #: The tables that carry an owner.
    OWNED_MODELS = (
        "CandidateProfileDB",
        "JobMatchDB",
        "TailoredResumeDB",
        "ApplicationDB",
        "ApplicationEventDB",
        "ApplicationEvidenceDB",
        "ApprovalRequestDB",
        "AuditEventDB",
    )

    def _route_sources(self) -> list[Path]:
        return sorted((Path(__file__).parent.parent / "src" / "api" / "routes").glob("*.py"))

    def test_no_route_queries_a_user_scoped_table_directly(self):
        offenders: list[str] = []
        for path in self._route_sources():
            text = path.read_text(encoding="utf-8")
            for model in self.OWNED_MODELS:
                for pattern in (
                    f"db.get({model}",
                    f"db.query({model}",
                    f"session.get({model}",
                    f"session.query({model}",
                ):
                    if pattern in text:
                        offenders.append(f"{path.name}: {pattern}")
        assert not offenders, (
            "A route queries a user-scoped table directly, bypassing the owner "
            "filter in src.db.access:\n  " + "\n  ".join(offenders)
        )

    def test_every_route_module_imports_the_scope_dependency(self):
        """A route that touches user data must take its scope from one place."""
        for path in self._route_sources():
            text = path.read_text(encoding="utf-8")
            if "access." in text:
                assert "current_scope" in text, (
                    f"{path.name} uses the scoped accessors but does not take its "
                    "scope from src.api.scope.current_scope"
                )
