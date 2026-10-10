"""WS-02 tests: guarded HTTP client (src/jobs/http_client.py).

Covers the SSRF spoof matrix (acceptance: localhost, 127.0.0.1,
169.254.169.254, 10.x, 192.168.x, file:// targets are rejected), retry
behavior on 429/5xx/transport errors, immediate failure on other 4xx and on
redirects, and the per-host rate limiter. No test touches a live network —
``httpx.MockTransport`` simulates every HTTP interaction.
"""

from __future__ import annotations

import socket
import time

import httpx
import pytest

from src.jobs.http_client import (
    HostRateLimiter,
    SourceError,
    SSRFBlockedError,
    assert_url_allowed,
    create_client,
    guarded_get,
)

FAST = {"backoff_base": 0.001}


# ---------------------------------------------------------------- SSRF guard


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/x",
        "http://LOCALHOST:8000/x",
        "http://127.0.0.1/x",
        "http://127.9.9.9/x",
        "http://[::1]/x",
        "http://169.254.169.254/latest/meta-data",
        "http://169.254.1.1/x",
        "http://10.0.0.1/x",
        "http://10.255.255.255/x",
        "http://172.16.0.1/x",
        "http://172.31.255.255/x",
        "http://192.168.1.1/x",
        "http://192.168.0.0/x",
        "http://0.0.0.0/x",
        "http://[fe80::1]/x",  # IPv6 link-local
        "http://[fc00::1]/x",  # IPv6 unique-local
        "http://[::ffff:10.0.0.1]/x",  # IPv4-mapped private smuggled as IPv6
        "http://[::ffff:169.254.169.254]/x",  # metadata via IPv4-mapped
        "http://240.0.0.1/x",  # reserved class E
        "file:///etc/passwd",
        "ftp://example.com/file",
        "javascript:alert(1)",
    ],
)
def test_ssrf_matrix_rejects_forbidden_targets(url):
    with pytest.raises(SSRFBlockedError):
        assert_url_allowed(url)


def test_ssrf_rejects_unresolvable_host_fail_closed(monkeypatch):
    """gaierror must fail closed — the guard never assumes a host is safe."""

    def failing_getaddrinfo(host, *args, **kwargs):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr("src.jobs.http_client._getaddrinfo", failing_getaddrinfo)
    with pytest.raises(SSRFBlockedError, match="does not resolve"):
        assert_url_allowed("http://this-host-does-not-exist.invalid/x")


@pytest.mark.parametrize(
    "url",
    [
        "https://boards-api.greenhouse.io/v1/boards/x/jobs",
        "http://example.com/",
        "https://remotive.com/api/remote-jobs?search=python",
    ],
)
def test_ssrf_allows_public_http_urls(url, monkeypatch):
    # Subject is the guard's acceptance logic, not the resolver: stub DNS to
    # a public address so the test is hermetic (no live resolution, which is
    # environment-dependent and flaky in sandboxed networks).
    _stub_dns(monkeypatch, "93.184.216.34")
    assert_url_allowed(url)  # must not raise


def test_ssrf_guard_runs_before_any_request():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(SSRFBlockedError):
        import asyncio

        asyncio.run(guarded_get(client, "http://127.0.0.1/secret"))
    assert calls == 0  # nothing was ever requested


# ------------------------------------------------------------------- retries


class CountingTransport(httpx.MockTransport):
    """MockTransport that records how many requests it handled (async path)."""

    def __init__(self, handler):
        super().__init__(handler)
        self.calls = 0

    async def handle_async_request(self, request):
        self.calls += 1
        return await super().handle_async_request(request)


def test_retry_on_5xx_then_success():
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    transport = CountingTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    async def run():
        return await guarded_get(client, "https://example.com/api", **FAST)

    import asyncio

    response = asyncio.run(run())
    assert response.status_code == 200
    assert transport.calls == 3  # 2 failures + success, within max_retries=2


def test_retry_on_429_then_success():
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=CountingTransport(handler))

    import asyncio

    response = asyncio.run(guarded_get(client, "https://example.com/api", **FAST))
    assert response.status_code == 200


def test_5xx_exhausting_retries_raises_source_error():
    client = httpx.AsyncClient(transport=CountingTransport(lambda request: httpx.Response(503)))

    import asyncio

    with pytest.raises(SourceError, match="503"):
        asyncio.run(guarded_get(client, "https://example.com/api", **FAST))


def test_4xx_raises_immediately_without_retry():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    transport = CountingTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    import asyncio

    with pytest.raises(SourceError, match="404"):
        asyncio.run(guarded_get(client, "https://example.com/api", **FAST))
    assert transport.calls == 1  # no retry on plain 4xx


def test_redirect_raises_source_error_and_is_not_followed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"Location": "https://evil.example.com/redirected"})

    client = httpx.AsyncClient(transport=CountingTransport(handler))

    import asyncio

    with pytest.raises(SourceError, match="301"):
        asyncio.run(guarded_get(client, "https://example.com/api", **FAST))


def test_transport_error_retries_then_raises_source_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.AsyncClient(transport=CountingTransport(handler))

    import asyncio

    with pytest.raises(SourceError, match="connection refused"):
        asyncio.run(guarded_get(client, "https://example.com/api", **FAST))


def test_timeout_is_wrapped_as_source_error():
    """ReadTimeout (a TransportError) exhausts retries into SourceError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    client = httpx.AsyncClient(transport=CountingTransport(handler))

    import asyncio

    with pytest.raises(SourceError, match="timed out"):
        asyncio.run(guarded_get(client, "https://example.com/api", max_retries=1, **FAST))


# -------------------------------------------------------------- rate limiting


def _stub_dns(monkeypatch, ip: str) -> None:
    """Make assert_url_allowed resolve instantly to a public IP (no network)."""

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(2, 1, 6, "", (ip, 0))]

    monkeypatch.setattr("src.jobs.http_client._getaddrinfo", fake_getaddrinfo)


def test_rate_limiter_spaces_same_host_requests(monkeypatch):
    _stub_dns(monkeypatch, "93.184.216.34")
    interval = 0.05
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(time.monotonic())
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    limiter = HostRateLimiter(min_interval=interval)

    import asyncio

    async def run():
        await guarded_get(client, "https://example.com/a", limiter=limiter)
        await guarded_get(client, "https://example.com/b", limiter=limiter)

    asyncio.run(run())
    assert len(seen) == 2
    assert seen[1] - seen[0] >= interval * 0.9  # allow tiny clock slop


def test_rate_limiter_does_not_delay_different_hosts(monkeypatch):
    _stub_dns(monkeypatch, "93.184.216.34")
    interval = 0.2
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(time.monotonic())
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    limiter = HostRateLimiter(min_interval=interval)

    import asyncio

    async def run():
        await guarded_get(client, "https://a.example.com/x", limiter=limiter)
        await guarded_get(client, "https://b.example.com/x", limiter=limiter)

    start = time.monotonic()
    asyncio.run(run())
    assert time.monotonic() - start < interval  # no cross-host wait


def test_rate_limiter_serializes_concurrent_same_host_callers(monkeypatch):
    _stub_dns(monkeypatch, "93.184.216.34")
    interval = 0.05
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(time.monotonic())
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    limiter = HostRateLimiter(min_interval=interval)

    import asyncio

    async def run():
        await asyncio.gather(
            guarded_get(client, "https://example.com/1", limiter=limiter),
            guarded_get(client, "https://example.com/2", limiter=limiter),
        )

    asyncio.run(run())
    seen.sort()
    assert seen[1] - seen[0] >= interval * 0.9


# ------------------------------------------------------------- create_client


def test_create_client_configuration():
    client = create_client(timeout=3.5)
    try:
        assert client.timeout.connect == 3.5
        assert client._transport is not None
        # httpx Headers lookups are case-insensitive.
        assert "agentic-job-applier" in client.headers.get("user-agent", "")
        assert client.headers.get("accept") == "application/json"
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_create_client_follows_no_redirects():
    client = create_client(timeout=1.0)
    try:
        assert client.follow_redirects is False
    finally:
        import asyncio

        asyncio.run(client.aclose())
