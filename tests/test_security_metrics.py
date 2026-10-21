"""WS-14 · the security metric family.

**The property under test:** tenant isolation is a *measured* property,
not a claim. The four metrics turn it into numbers that join the
functional ones in the same report, against the same gate.

The metrics are measured by **probing the real application** — the real
routing, the real authentication and the real accessors — so a number
that comes out of the probe says something about the system.
"""

from __future__ import annotations

from pathlib import Path

from src.evaluation.security import (
    PROTECTED_ENDPOINTS,
    USER_SCOPED_ENDPOINTS,
    authorization_coverage,
    normalise_route,
    security_scores,
)


class TestTheSecurityMetrics:
    def test_every_metric_meets_its_target(self, tmp_path: Path) -> None:
        scores = security_scores(tmp_path)

        assert scores["security.unauthenticated_access_rate"] == 0.0, (
            "a protected endpoint answered an anonymous caller"
        )
        assert scores["security.cross_user_isolation_violations"] == 0, (
            "another account reached a resource it did not own"
        )
        assert scores["security.authorization_coverage"] == 1.0, (
            "a user-scoped endpoint has no isolation test"
        )
        assert scores["security.audit_attribution_rate"] == 1.0, (
            "an action was recorded without a resolvable principal"
        )

    def test_the_probe_covered_every_protected_endpoint(self, tmp_path: Path) -> None:
        scores = security_scores(tmp_path)
        assert scores["security.protected_endpoints"] == len(PROTECTED_ENDPOINTS)
        assert scores["security.isolation_endpoints"] == len(USER_SCOPED_ENDPOINTS)

    def test_the_coverage_is_measured_against_the_isolation_suite(self) -> None:
        assert authorization_coverage() == 1.0


class TestTheRouteNormalisation:
    def test_a_concrete_id_and_a_placeholder_are_the_same_route(self) -> None:
        assert normalise_route("/api/applications/whatever") == normalise_route(
            "/api/applications/{application_id}"
        )

    def test_a_literal_segment_is_not_collapsed(self) -> None:
        assert normalise_route("/api/applications/whatever/status") == (
            "/api/applications/{id}/status"
        )
        assert normalise_route("/api/applications") == "/api/applications"
