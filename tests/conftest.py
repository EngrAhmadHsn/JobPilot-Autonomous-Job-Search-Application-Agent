"""Shared test-suite fixtures.

The autouse ``fast_rate_limiter`` fixture replaces the process-wide job-source
rate limiter with a zero-interval one: politeness spacing (1 s/host by
default) is a live-network concern, and no test talks to a live network. Tests
that exercise the limiter itself inject their own explicit limiter.

The autouse ``generous_api_rate_limit`` fixture does the same for the **API**
rate limiter (WS-12): every test in the suite shares one client address
(``testclient``), so the per-client request budget — a real control, and one
that the suite duly trips — would refuse the hundredth request of a test
module. The budget is raised out of the way here, and the tests that verify
the limiter itself build their own instance and assert against it directly.

The autouse ``isolated_session_local`` fixture points the module-level
session factory at a throwaway database. Several code paths open their **own**
session when the caller hands over none — the workflow nodes write their
evidence that way, and the audit writer falls back to ``SessionLocal``. Without
this guard the suite writes into the developer's real database, which is a
data leak into a working environment and not something a test may ever do.

The autouse ``authenticated_caller`` fixture gives every test an
**identity** (WS-14 · A2). Since the API now refuses a caller it cannot
identify, a test that calls a protected endpoint needs a principal. The
identity it installs is the **legacy owner** — the account the ownership
migration backfilled the pre-existing rows to — because that is the owner
the test fixtures write their rows under (``build_profile_row`` and its
siblings default to it). The scope is deliberately **not** a superuser
scope: a superuser scope bypasses the owner filter, and a suite that
always bypassed it would prove nothing about the filter.

The identity is injected through FastAPI's dependency override rather
than by logging in, because logging in for every test would make the
suite slow and would test the *login* rather than the thing under test.
The tests that are **about** the identity — ``tests/test_auth.py`` and
``tests/test_isolation.py`` — remove the override and use the real
cookie and bearer transports, so the real path is proved where it
matters.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Every model is imported here, not left to the test modules. The suite
# database is created from the metadata, and a model that no collected test
# module happens to import is a table that never gets created — so running
# one test file on its own would fail with "no such table" while the full
# suite passed. The import list is the fix, not the collection order.
from src.db import (  # noqa: F401  (imported for the model registration)
    applications,
    approval,
    audit,
    evidence,
    jobs,
    matches,
    profiles,
    tailored,
)
from src.db.base import Base
from src.jobs.http_client import HostRateLimiter, get_default_limiter, reset_default_limiter


@pytest.fixture(autouse=True)
def fast_rate_limiter(monkeypatch):
    monkeypatch.setattr(
        "src.jobs.http_client.get_default_limiter", lambda: HostRateLimiter(min_interval=0.0)
    )
    yield
    reset_default_limiter()
    assert get_default_limiter() is not None  # rebuildable after reset


@pytest.fixture(autouse=True)
def generous_api_rate_limit(monkeypatch):
    """Keep the API rate limiter from refusing the suite's own requests.

    The limiter is a real control and it is not disabled — the budget is
    raised so the suite's shared client address is never throttled. The
    tests that cover the limiter build their own instance and assert
    against it directly, so the control itself is still verified.
    """
    from src.api.middleware import reset_rate_limiter

    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "100000")
    from src.security.limits import reset_limits

    reset_limits()
    reset_rate_limiter()
    yield
    reset_limits()
    reset_rate_limiter()


@pytest.fixture(scope="session")
def _suite_database(tmp_path_factory):
    """The throwaway database the suite's own sessions write to."""
    db_path = tmp_path_factory.mktemp("suite-db") / "app.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    # Every model is registered on the metadata by the imports above, so the
    # throwaway database has every table the suite writes to.
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def isolated_session_local(_suite_database, monkeypatch: pytest.MonkeyPatch):
    """Keep the suite out of the developer's database.

    A test that needs to assert on what a code path wrote points
    ``SessionLocal`` at its own database (it has the last word — it patches
    after this fixture). This is the safety net for the paths that do not.
    """
    monkeypatch.setattr(
        "src.db.session.SessionLocal",
        sessionmaker(bind=_suite_database, autoflush=False),
    )


@pytest.fixture(autouse=True)
def authenticated_caller():
    """Give every test an identity (WS-14 · A2).

    The API refuses a caller it cannot identify, so a test that calls a
    protected endpoint needs a principal. The one installed here is the
    **legacy owner** — the account the ownership migration backfilled the
    pre-existing rows to, and the owner the test fixtures write their rows
    under.

    The scope is deliberately **not** a superuser scope. A superuser
    scope bypasses the owner filter by design (it is the platform's audit
    view), and a suite that always bypassed it would prove nothing about
    the filter it is supposed to be exercising.

    The identity is injected through FastAPI's dependency override rather
    than by logging in: logging in for every test would make the suite
    slow and would test the login rather than the thing under test. The
    tests that are *about* the identity — ``tests/test_auth.py`` and
    ``tests/test_isolation.py`` — remove this override and use the real
    cookie and bearer transports.
    """
    from src.auth.routes import current_active_user
    from src.db.users import LEGACY_OWNER_ID, UserDB
    from src.main import app

    caller = UserDB(
        id=LEGACY_OWNER_ID,
        email="test-caller@example.com",
        # The suite never authenticates with this account, so the value
        # is irrelevant; it is not a password hash and never is verified.
        hashed_password="!",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    app.dependency_overrides[current_active_user] = lambda: caller
    try:
        yield caller
    finally:
        app.dependency_overrides.pop(current_active_user, None)
