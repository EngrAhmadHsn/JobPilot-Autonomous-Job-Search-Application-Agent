"""Domain allowlist and blocked-host rules (WS-06 · SEC-06 / SEC-11).

The allowlist is the runtime enforcement point for "web content is data, never
instruction" (SEC-01) and "browser automation is only allowed for approved
domains" (SEC-06): a URL whose host is not explicitly approved never reaches
a page, and an internal host is refused outright.

Two rules replace the original substring matching (``d in host``), which let
``evil-greenhouse.io.attacker.com`` pass a check for ``greenhouse.io``:

1. **Exact host matching** — a host is allowed for a domain when it *is* the
   domain or is a sub-domain of it (``host == domain`` or
   ``host.endswith("." + domain)``). Ports are ignored; an IP literal never
   matches a domain.
2. **Blocked hosts** — loopback, private, link-local, CGNAT and cloud-metadata
   addresses are refused, so a redirect to ``169.254.169.254`` cannot reach the
   instance metadata service.

The checks are **literal only**: no DNS resolution happens here. Resolving a
hostname is the job-source HTTP client's job (``src/jobs/http_client.py``);
the browser layer must be able to make a decision without a resolver. The
allowlist itself bounds the reachable hosts to a small, operator-chosen set.

The fake ATS runs on localhost. That exception is **explicit and dev-scoped**:
``assert_navigation_allowed`` only admits a local host when the caller passes
``allow_localhost=True`` (only the fake-ATS adapter does, behind its own
``supports_url`` gate), and the API boundary guard only grants it when
``APP_ENV=development``.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from src.config.settings import get_settings

# The fallback list is the one the settings module already carries; it is
# duplicated here only so this module stays importable without a settings
# instance (the settings value always wins).
DEFAULT_ALLOWED_DOMAINS = frozenset(
    {
        "greenhouse.io",
        "lever.co",
        "workday.com",
        "ashbyhq.com",
        "smartrecruiters.com",
        "icims.com",
    }
)

# Host names that resolve to internal services on the common clouds.
BLOCKED_HOSTNAMES = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)

# Literal addresses that must never be contacted (SEC-11).
BLOCKED_IP_LITERALS = frozenset(
    {
        "169.254.169.254",  # AWS / Azure / GCP / DigitalOcean metadata
        "169.254.170.2",  # AWS ECS task metadata
        "100.100.100.200",  # Alibaba Cloud metadata
    }
)

# Carrier-grade NAT range (RFC 6598) — not covered by ``ipaddress.is_private``.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")

# Literal loopback hosts, used for the dev-scoped fake-ATS exception.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class DisallowedDomainError(PermissionError):
    """Raised when a URL's host may not be navigated to or fetched."""


def _normalize_domain(domain: str) -> str:
    """Lowercase a domain entry and drop a leading dot."""
    return domain.strip().lower().lstrip(".")


def host_of(url: str) -> str:
    """The lowercased hostname of *url* ('' when there is none)."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    return (parsed.hostname or "").lower()


def allowed_domains() -> frozenset[str]:
    """The configured allowlist, normalized.

    An empty configuration yields an empty allowlist: nothing is allowed. That
    is the fail-closed reading of "no domains configured".
    """
    configured = get_settings().allowed_domains
    domains = {_normalize_domain(domain) for domain in configured if domain and domain.strip()}
    return frozenset(domains)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def host_matches_domain(url: str, domain: str) -> bool:
    """True when *url*'s host is *domain* or a sub-domain of it.

    Exact matching only: ``evil-greenhouse.io.attacker.com`` does not match
    ``greenhouse.io``, while ``boards.greenhouse.io`` does.
    """
    host = host_of(url)
    target = _normalize_domain(domain)
    if not host or not target:
        return False
    if _is_ip_literal(host):
        return False
    return host == target or host.endswith("." + target)


def is_domain_allowed(url: str) -> bool:
    """True when the URL's host is on the configured allowlist."""
    host = host_of(url)
    if not host or _is_ip_literal(host):
        return False
    return any(host_matches_domain(url, domain) for domain in allowed_domains())


def is_local_host(url: str) -> bool:
    """True when the URL points at a literal loopback host."""
    host = host_of(url)
    if not host:
        return False
    return host in _LOCAL_HOSTS or host.endswith(".localhost")


def _is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when the address must never be contacted."""
    # An IPv4-mapped IPv6 address (::ffff:10.0.0.1) is judged by its embedded
    # IPv4 address, or the private v4 ranges could be smuggled in.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_forbidden_ip(ip.ipv4_mapped)
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_reserved:
        return True
    if ip.is_multicast:
        return True
    if isinstance(ip, ipaddress.IPv4Address):
        if ip in _CGNAT:
            return True
        return ip.is_private  # RFC 1918: 10/8, 172.16/12, 192.168/16
    return ip.is_private  # IPv6 unique-local fc00::/7 and friends


def is_blocked_host(url: str) -> bool:
    """True when the URL points at an internal or metadata address.

    A URL without a hostname is blocked: there is nothing to allow.
    """
    host = host_of(url)
    if not host:
        return True
    if host in BLOCKED_HOSTNAMES:
        return True
    if host == "localhost" or host.endswith(".localhost"):
        return True
    if host in BLOCKED_IP_LITERALS:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return _is_forbidden_ip(ip)


def assert_navigation_allowed(url: str, *, allow_localhost: bool = False) -> None:
    """Raise :class:`DisallowedDomainError` unless *url* may be visited.

    Args:
        url: The URL about to be opened.
        allow_localhost: Opt-in exception for the local fake ATS. It is never
            granted implicitly: a local host is refused unless the caller
            passes this flag.

    Raises:
        DisallowedDomainError: The URL is empty, uses a scheme other than
            http/https, has no host, points at an internal address, or its
            host is not on the allowlist.
    """
    if not url or not url.strip():
        raise DisallowedDomainError("An empty URL is not navigable")

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise DisallowedDomainError(f"URL could not be parsed: {url!r}") from exc

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise DisallowedDomainError(
            f"Scheme {parsed.scheme!r} is not allowed (only http/https): {url!r}"
        )

    host = host_of(url)
    if not host:
        raise DisallowedDomainError(f"URL has no hostname: {url!r}")

    if is_local_host(url):
        if allow_localhost:
            return
        raise DisallowedDomainError(
            f"Host {host!r} is a local address; navigation to it is not allowed here"
        )

    if is_blocked_host(url):
        raise DisallowedDomainError(
            f"Host {host!r} is an internal or metadata address and is blocked"
        )

    if not is_domain_allowed(url):
        raise DisallowedDomainError(
            f"Host {host!r} is not on the domain allowlist "
            f"({', '.join(sorted(allowed_domains())) or 'empty'})"
        )


def assert_job_url_allowed(url: str) -> None:
    """API-boundary guard for a job URL.

    Identical to :func:`assert_navigation_allowed` except that the local fake
    ATS is admitted **only** outside production, i.e. when
    ``APP_ENV=development``. A production deployment can therefore never
    submit to a loopback address.
    """
    allow_local = get_settings().app_env == "development"
    assert_navigation_allowed(url, allow_localhost=allow_local)
