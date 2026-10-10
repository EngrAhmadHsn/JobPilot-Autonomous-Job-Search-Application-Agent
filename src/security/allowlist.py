"""Security controls: domain allowlist and permission registry."""

from __future__ import annotations

from enum import Enum


class CapabilityLevel(str, Enum):
    READ = "read"
    SEARCH = "search"
    PREPARE = "prepare"
    WRITE = "write"
    SUBMIT = "submit"


ALLOWED_DOMAINS = {
    "greenhouse.io",
    "lever.co",
    "workday.com",
    "ashbyhq.com",
    "smartrecruiters.com",
    "icims.com",
}


def is_domain_allowed(url: str) -> bool:
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    return any(d in host for d in ALLOWED_DOMAINS)
