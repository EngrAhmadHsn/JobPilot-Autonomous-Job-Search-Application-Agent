"""WS-06 · Phase A — domain allowlist v2 and blocked-host rules (SEC-06 / SEC-11).

The old implementation matched domains with a substring test (``d in host``),
which let ``evil-greenhouse.io.attacker.com`` pass a check for
``greenhouse.io``. These tests pin the exact-match rule, the internal-host
block list, and the dev-scoped local exception used by the fake ATS.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.applications.greenhouse_adapter import GreenhouseAdapter
from src.applications.lever_adapter import LeverAdapter
from src.security import allowlist
from src.security.allowlist import (
    DisallowedDomainError,
    assert_job_url_allowed,
    assert_navigation_allowed,
    host_matches_domain,
    is_blocked_host,
    is_domain_allowed,
    is_local_host,
)


@dataclass
class _FakeSettings:
    """Minimal stand-in for the settings object (only what the guard reads)."""

    app_env: str = "development"
    allowed_domains: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.allowed_domains is None:
            self.allowed_domains = [
                "greenhouse.io",
                "lever.co",
                "workday.com",
                "ashbyhq.com",
                "smartrecruiters.com",
                "icims.com",
            ]


def _use_settings(monkeypatch: pytest.MonkeyPatch, settings: _FakeSettings) -> None:
    monkeypatch.setattr(allowlist, "get_settings", lambda: settings)


class TestExactHostMatching:
    """A host is allowed when it is the domain or a sub-domain of it."""

    def test_exact_domain_is_allowed(self) -> None:
        assert is_domain_allowed("https://greenhouse.io/jobs/1") is True

    def test_subdomain_is_allowed(self) -> None:
        assert is_domain_allowed("https://boards.greenhouse.io/acme/jobs/1") is True

    def test_spoofed_prefix_domain_is_rejected(self) -> None:
        # The regression the substring matcher got wrong.
        assert is_domain_allowed("https://evil-greenhouse.io.attacker.com/jobs/1") is False

    def test_domain_embedded_in_a_longer_name_is_rejected(self) -> None:
        assert is_domain_allowed("https://notgreenhouse.io/jobs/1") is False
        assert is_domain_allowed("https://greenhouse.io.attacker.com/jobs/1") is False

    def test_port_does_not_affect_matching(self) -> None:
        assert is_domain_allowed("https://greenhouse.io:8443/jobs/1") is True

    def test_ip_literal_is_never_domain_allowed(self) -> None:
        assert is_domain_allowed("https://127.0.0.1/jobs/1") is False

    def test_unparseable_url_is_not_allowed(self) -> None:
        assert is_domain_allowed("not a url") is False
        assert is_domain_allowed("") is False

    def test_host_matches_domain_helper(self) -> None:
        assert host_matches_domain("https://boards.greenhouse.io/x", "greenhouse.io") is True
        assert host_matches_domain("https://greenhouse.io/x", "greenhouse.io") is True
        assert host_matches_domain("https://xgreenhouse.io/x", "greenhouse.io") is False
        assert host_matches_domain("https://greenhouse.io/x", "lever.co") is False


class TestBlockedHosts:
    """Internal, loopback and metadata addresses are refused (SEC-11)."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:8000/apply",
            "http://127.0.0.1:8000/apply",
            "http://[::1]:8000/apply",
            "http://0.0.0.0/apply",
            "http://10.0.0.5/apply",
            "http://172.16.4.4/apply",
            "http://192.168.1.10/apply",
            "http://169.254.169.254/latest/meta-data/",
            "http://100.100.100.200/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://foo.localhost/apply",
        ],
    )
    def test_internal_hosts_are_blocked(self, url: str) -> None:
        assert is_blocked_host(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://greenhouse.io/jobs/1",
            "https://boards.greenhouse.io/acme/jobs/1",
            "https://example.com/",
        ],
    )
    def test_public_hosts_are_not_blocked(self, url: str) -> None:
        assert is_blocked_host(url) is False

    def test_url_without_host_is_blocked(self) -> None:
        assert is_blocked_host("not a url") is True

    def test_is_local_host_is_narrow(self) -> None:
        assert is_local_host("http://localhost:8000/x") is True
        assert is_local_host("http://127.0.0.1:8000/x") is True
        assert is_local_host("https://greenhouse.io/x") is False


class TestAssertNavigationAllowed:
    """The guard raises for anything that must not be visited."""

    def test_allowlisted_host_passes(self) -> None:
        assert_navigation_allowed("https://boards.greenhouse.io/acme/jobs/1")

    def test_non_allowlisted_host_raises(self) -> None:
        with pytest.raises(DisallowedDomainError):
            assert_navigation_allowed("https://evil-greenhouse.io.attacker.com/jobs/1")

    def test_internal_host_raises(self) -> None:
        with pytest.raises(DisallowedDomainError):
            assert_navigation_allowed("http://169.254.169.254/latest/meta-data/")

    def test_non_http_scheme_raises(self) -> None:
        with pytest.raises(DisallowedDomainError):
            assert_navigation_allowed("file:///etc/passwd")
        with pytest.raises(DisallowedDomainError):
            assert_navigation_allowed("javascript:alert(1)")

    def test_empty_url_raises(self) -> None:
        with pytest.raises(DisallowedDomainError):
            assert_navigation_allowed("")

    def test_local_host_needs_the_explicit_exception(self) -> None:
        with pytest.raises(DisallowedDomainError):
            assert_navigation_allowed("http://localhost:8000/apply")
        # The exception is never implicit: the caller has to ask for it.
        assert_navigation_allowed("http://localhost:8000/apply", allow_localhost=True)

    def test_localhost_exception_does_not_open_the_metadata_service(self) -> None:
        with pytest.raises(DisallowedDomainError):
            assert_navigation_allowed("http://169.254.169.254/", allow_localhost=True)


class TestJobUrlGuard:
    """The API-boundary guard applies the dev-scoped local exception."""

    def test_local_host_allowed_in_development(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_settings(monkeypatch, _FakeSettings(app_env="development"))
        assert_job_url_allowed("http://localhost:8000/apply")

    def test_local_host_blocked_outside_development(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_settings(monkeypatch, _FakeSettings(app_env="production"))
        with pytest.raises(DisallowedDomainError):
            assert_job_url_allowed("http://localhost:8000/apply")

    def test_non_allowlisted_host_blocked_in_development(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_settings(monkeypatch, _FakeSettings(app_env="development"))
        with pytest.raises(DisallowedDomainError):
            assert_job_url_allowed("https://evil-greenhouse.io.attacker.com/jobs/1")

    def test_empty_allowlist_blocks_every_domain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_settings(monkeypatch, _FakeSettings(allowed_domains=[]))
        with pytest.raises(DisallowedDomainError):
            assert_job_url_allowed("https://boards.greenhouse.io/acme/jobs/1")


class TestAdapterHostSelection:
    """Adapter selection must not be spoofable by a substring (SEC-06)."""

    def test_greenhouse_adapter_matches_real_hosts(self) -> None:
        adapter = GreenhouseAdapter()
        assert adapter.supports_url("https://boards.greenhouse.io/acme/jobs/1") is True
        assert adapter.supports_url("https://job-boards.greenhouse.io/acme/jobs/1") is True

    def test_greenhouse_adapter_rejects_spoofed_hosts(self) -> None:
        adapter = GreenhouseAdapter()
        assert adapter.supports_url("https://evil-greenhouse.io.attacker.com/x") is False
        assert adapter.supports_url("https://notgreenhouse.io/x") is False

    def test_lever_adapter_rejects_spoofed_hosts(self) -> None:
        adapter = LeverAdapter()
        assert adapter.supports_url("https://jobs.lever.co/acme/uuid") is True
        assert adapter.supports_url("https://notlever.co.attacker.com/x") is False
