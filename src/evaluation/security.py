"""The security metric family (WS-14 · Phase G).

**What this measures.** Tenant isolation is a property of the system, and
a property that is only *asserted* decays. These four metrics turn it
into a number in the same report as the functional ones, so the FYP's
security contribution is reported next to its functional contribution,
against the same gate.

===========================================  ======  =========================
Metric                                       Target  Meaning
===========================================  ======  =========================
``security.unauthenticated_access_rate``     0      protected endpoints
                                                      reachable without a
                                                      credential
``security.cross_user_isolation_violations`` 0      cross-user accesses that
                                                      succeeded
``security.authorization_coverage``          1.0    fraction of user-scoped
                                                      endpoints with an
                                                      isolation test
``security.audit_attribution_rate``          1.0    actions with a resolvable
                                                      principal
===========================================  ======  =========================

**How they are measured.** The first two are measured by *probing the
real application*: the probe registers two accounts, gives the first a
resource, and then asks for it the way a second account would. The third
is measured against the isolation suite's source, because a coverage
number that is computed from the same code that does the work would be
circular. The fourth is measured on the audit rows the probe itself
wrote.

The probe runs against an in-process client with a throwaway database, so
it needs no network and no running server, and it exercises the **real**
routing, the **real** authentication and the **real** accessors.
"""

from __future__ import annotations

import logging
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.audit import AuditEventDB
from src.db.base import Base
from src.db.session import get_db

logger = logging.getLogger(__name__)

__all__ = [
    "PROTECTED_ENDPOINTS",
    "USER_SCOPED_ENDPOINTS",
    "security_scores",
]

#: The endpoints that must refuse an anonymous caller. Every one of them
#: reaches a user-scoped resource, so every one of them needs a
#: credential.
#:
#: WS-15: the last two are the ``/api/jobs`` routes. The corpus is shared
#: board data, so they do not reach a *user-scoped* resource — but the
#: refresh is the most expensive operation in the system and the job read
#: enumerates the whole corpus, so both need a credential. A metric that
#: only covers the easy endpoints is a metric that says "0.0" about the
#: part of the surface nobody tested.
PROTECTED_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("GET", "/api/resumes/{profile_id}"),
    ("POST", "/api/resumes"),
    ("GET", "/api/profiles/{profile_id}/matches"),
    ("GET", "/api/applications"),
    ("GET", "/api/applications/{application_id}"),
    ("PATCH", "/api/applications/{application_id}/status"),
    ("GET", "/api/applications/{application_id}/evidence"),
    ("GET", "/api/applications/{application_id}/evidence/{filename}"),
    ("POST", "/api/applications/prepare"),
    ("GET", "/api/tailored/{tailoring_id}"),
    ("GET", "/api/tailored/{tailoring_id}/download"),
    ("GET", "/api/audit"),
    ("GET", "/api/auth/me"),
    ("POST", "/api/jobs/refresh"),
    ("GET", "/api/jobs/{job_id}"),
)

#: The endpoints that reach a user-scoped resource, and therefore need an
#: isolation test. The coverage metric is the fraction of these the
#: isolation suite exercises.
USER_SCOPED_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("GET", "/api/resumes/{profile_id}"),
    ("GET", "/api/profiles/{profile_id}/matches"),
    ("GET", "/api/applications"),
    ("GET", "/api/applications/{application_id}"),
    ("GET", "/api/applications/{application_id}/evidence"),
    ("GET", "/api/applications/{application_id}/evidence/{filename}"),
    ("GET", "/api/tailored/{tailoring_id}"),
    ("GET", "/api/tailored/{tailoring_id}/download"),
    ("GET", "/api/audit"),
)

#: The isolation suite that the coverage metric is measured against.
ISOLATION_SUITE = Path(__file__).resolve().parents[2] / "tests" / "test_tenant_isolation_api.py"

#: The placeholders a probe fills in when it asks for a resource.
_PROBE_VALUES = {
    "profile_id": "no-such-profile",
    "application_id": "no-such-application",
    "tailoring_id": "no-such-tailoring",
    "filename": "no-such-file.png",
    # WS-15: the job probe. The route answers 404 for an unknown listing,
    # but it must answer 401 for an anonymous one — the credential is
    # checked before the listing is looked up.
    "job_id": "no-such-job",
}


def _fill(path: str) -> str:
    """A concrete path for a route template."""
    filled = path
    for name, value in _PROBE_VALUES.items():
        filled = filled.replace("{" + name + "}", value)
    return filled


#: A route path as it appears in a source file.
_ROUTE_IN_SOURCE = re.compile(r'"(/api/[-A-Za-z0-9/_{}.]*)"')

#: The path segments that are **route literals** rather than resource
#: ids. A segment that is not one of these, and that is not the
#: ``{name}`` form, names a resource.
ROUTE_LITERALS = frozenset(
    {
        "api",
        "applications",
        "approvals",
        "approve",
        "audit",
        "download",
        "evidence",
        "health",
        "jobs",
        "login",
        "logout",
        "matches",
        "me",
        "prepare",
        "profiles",
        "refresh",
        "register",
        "reject",
        "resumes",
        "search",
        "sessions",
        "status",
        "tailor",
        "tailored",
    }
)


def normalise_route(path: str) -> str:
    """The shape of a route, with the resource ids collapsed.

    ``/api/applications/whatever`` and ``/api/applications/{id}`` are the
    same route, and so is ``/api/applications/{application_id}``. The
    coverage metric compares shapes, so a suite may name a resource by a
    concrete id or by a placeholder and still count.
    """
    segments = path.split("/")
    collapsed: list[str] = []
    for index, segment in enumerate(segments):
        literal = segment in ROUTE_LITERALS
        braced = segment.startswith("{") and segment.endswith("}")
        if index and not literal and (braced or segment):
            collapsed.append("{id}")
        else:
            collapsed.append(segment)
    return "/".join(collapsed)


def routes_in(source: str) -> set[str]:
    """The route shapes a source file exercises."""
    return {normalise_route(match.group(1)) for match in _ROUTE_IN_SOURCE.finditer(source)}


def authorization_coverage(suite_path: Path = ISOLATION_SUITE) -> float:
    """The fraction of user-scoped endpoints the isolation suite exercises.

    Measured against the suite's **source**, not against the code that
    does the work: a coverage number computed from the same code that
    does the measuring would be circular.
    """
    if not suite_path.is_file():
        return 0.0
    exercised = routes_in(suite_path.read_text(encoding="utf-8"))
    covered = sum(1 for _, path in USER_SCOPED_ENDPOINTS if normalise_route(path) in exercised)
    return round(covered / len(USER_SCOPED_ENDPOINTS), 4)


def _audit_attribution_rate(session) -> float:
    """The fraction of the audit rows with a resolvable principal.

    A row is attributable when it names a kind, and either an id (a
    user, an agent) or nothing at all (the system, which is honest about
    being the system).
    """
    rows = session.query(AuditEventDB).all()
    if not rows:
        return 1.0
    attributable = sum(
        1
        for row in rows
        if row.actor_kind in {"user", "agent", "system"}
        and (row.actor_id or row.actor_kind == "system")
    )
    return round(attributable / len(rows), 4)


def security_scores(tmp_path: Path | None = None) -> dict[str, float | int]:
    """Measure the four security metrics against the real application.

    The probe registers two accounts, gives the first one a profile, and
    then asks for that profile the way the second account would. It
    writes nothing outside a throwaway database.
    """
    from fastapi.testclient import TestClient

    from src.db.profiles import build_profile_row
    from src.main import app
    from src.resume.profile import CandidateProfile

    # The probe's database is **temporary**: it must not write into the
    # repository, and it must not be able to see the deployment's rows.
    if tmp_path is not None:
        work = Path(tmp_path)
    else:
        work = Path(tempfile.mkdtemp(prefix="ws14-probe-"))
    work.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{(work / 'probe.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # The suite's autouse fixture gives every test an identity. The probe
    # is measuring what an **anonymous** caller gets, so the override is
    # lifted for the duration of the probe and restored afterwards.
    from src.auth.routes import current_active_user

    previous_identity = app.dependency_overrides.pop(current_active_user, None)
    try:
        with TestClient(app) as client:
            unauthenticated_violations, probed = _probe_unauthenticated(client)
            cross_user_violations, isolation_probed = _probe_isolation(
                client, factory, build_profile_row, CandidateProfile
            )
            with factory() as db:
                attribution = _audit_attribution_rate(db)
    finally:
        app.dependency_overrides.clear()
        if previous_identity is not None:
            app.dependency_overrides[current_active_user] = previous_identity
        engine.dispose()

    return {
        "security.unauthenticated_access_rate": round(
            unauthenticated_violations / len(PROTECTED_ENDPOINTS), 4
        ),
        "security.cross_user_isolation_violations": cross_user_violations,
        "security.authorization_coverage": authorization_coverage(),
        "security.audit_attribution_rate": attribution,
        "security.protected_endpoints": probed,
        "security.isolation_endpoints": isolation_probed,
    }


def _probe_unauthenticated(client) -> tuple[int, int]:
    """How many protected endpoints answer an anonymous caller.

    Returns:
        The number of endpoints that answered something other than 401,
        and how many were probed.
    """
    violations = 0
    for method, path in PROTECTED_ENDPOINTS:
        response = client.request(method, _fill(path), json={})
        if response.status_code != 401:
            violations += 1
            logger.warning(
                "%s %s answered %s to an anonymous caller",
                method,
                path,
                response.status_code,
            )
    return violations, len(PROTECTED_ENDPOINTS)


def _probe_isolation(client, factory, build_profile_row, CandidateProfile) -> tuple[int, int]:
    """How many of user A's resources user B could reach.

    Returns:
        The number of cross-user accesses that succeeded, and how many
        endpoints were probed.
    """
    password = "correct horse battery staple"
    # A **fresh** account per run: the probe is repeatable, and it never
    # depends on the state a previous run left behind.
    stamp = uuid.uuid4().hex[:8]

    def register(email: str) -> str:
        response = client.post("/api/auth/register", json={"email": email, "password": password})
        if response.status_code != 201:
            raise RuntimeError(f"the probe could not register {email}: {response.text}")
        return response.json()["id"]

    def sign_in(email: str) -> str:
        response = client.post(
            "/api/auth/token/login", data={"username": email, "password": password}
        )
        if response.status_code != 200:
            raise RuntimeError(f"the probe could not sign in as {email}: {response.text}")
        return response.json()["access_token"]

    alice = register(f"probe-alice-{stamp}@example.com")
    register(f"probe-bob-{stamp}@example.com")
    alice_token = sign_in(f"probe-alice-{stamp}@example.com")
    bob_token = sign_in(f"probe-bob-{stamp}@example.com")

    # A profile that belongs to Alice.
    profile = CandidateProfile.model_validate(
        {
            "personal_information": {"name": "Alice", "email": "alice@example.com"},
            "professional_summary": "",
            "skills": [],
            "experience": [],
            "education": [],
            "certifications": [],
            "projects": [],
        }
    )
    with factory() as db:
        row = build_profile_row(profile, "/tmp/probe-alice.docx", owner_id=alice)
        db.add(row)
        db.commit()
        profile_id = row.id

    # The endpoints that **list** the caller's own resources are not
    # cross-user accesses: a listing that shows Bob his own (empty) list
    # is the correct answer. The check there is that Alice's resources
    # do not appear in it.
    listing_endpoints = {"/api/applications", "/api/audit"}

    violations = 0
    probed = 0
    for method, path in USER_SCOPED_ENDPOINTS:
        concrete = path.replace("{profile_id}", profile_id)
        response = client.request(
            method,
            concrete,
            json={"status": "interview", "actor": "human:someone"},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        probed += 1
        if path in listing_endpoints:
            leaked = profile_id in response.text
            if leaked:
                violations += 1
                logger.warning("%s %s leaked another account's rows", method, path)
            continue
        if response.status_code not in (403, 404):
            violations += 1
            logger.warning(
                "%s %s answered %s to another account",
                method,
                path,
                response.status_code,
            )
    # Alice may read her own.
    own = client.get(
        f"/api/resumes/{profile_id}", headers={"Authorization": f"Bearer {alice_token}"}
    )
    if own.status_code != 200:
        logger.warning("the owner could not read her own profile: %s", own.status_code)
    return violations, probed


def _unused(*args: Any) -> None:  # pragma: no cover - keeps the linter quiet
    return None
