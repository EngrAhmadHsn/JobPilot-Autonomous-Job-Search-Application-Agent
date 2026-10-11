"""Deterministic in-memory JobSource fixture (WS-04).

Used by the pipeline tests, the API tests, and the offline milestone demo so
the First-Milestone path runs without a network. ``FakeJobSource.search``
returns its canned listings verbatim (deterministic: same calls, same
results); ``FailingJobSource`` always raises so tests can exercise the
per-source degradation path (plan §35).
"""

from __future__ import annotations

from src.jobs.contracts import JobListing


def make_listing(
    listing_id: str,
    title: str,
    company: str,
    *,
    source: str = "fixture",
    description: str = "Build backend services with Python.",
    required_skills: list[str] | None = None,
    preferred_skills: list[str] | None = None,
    location: str | None = "Remote",
    remote_policy: str | None = "remote",
    seniority: str | None = None,
    employment_type: str | None = "full-time",
    salary: str | None = None,
) -> JobListing:
    """Build one normalized fixture listing with a canonical ``source:id`` key."""
    return JobListing(
        id=f"{source}:{listing_id}",
        source=source,
        source_job_id=listing_id,
        title=title,
        company=company,
        description=description,
        required_skills=required_skills or [],
        preferred_skills=preferred_skills or [],
        location=location,
        remote_policy=remote_policy,
        seniority=seniority,
        employment_type=employment_type,
        salary=salary,
    )


FIXTURE_JOBS: list[JobListing] = [
    make_listing(
        "1",
        "Senior Python Engineer",
        "Acme",
        required_skills=["Python", "FastAPI", "SQL"],
        preferred_skills=["AWS"],
        salary="$140,000",
        seniority="senior",
    ),
    make_listing(
        "2",
        "Machine Learning Engineer",
        "Globex",
        required_skills=["Python", "PyTorch"],
        preferred_skills=["Docker"],
        salary="$150,000",
    ),
    make_listing(
        "3",
        "DevOps Engineer",
        "Initech",
        required_skills=["Kubernetes", "AWS", "Terraform"],
        salary="$130,000",
    ),
    make_listing(
        "4",
        "Backend Python Engineer",
        "Umbrella",
        required_skills=["Python", "PostgreSQL"],
        preferred_skills=["FastAPI", "AWS"],
        salary="$145,000",
    ),
    make_listing(
        "5",
        "Data Engineer",
        "Hooli",
        required_skills=["Python", "SQL", "Airflow"],
        salary="$135,000",
    ),
]


class FakeJobSource:
    """JobSource double returning the same canned listings on every call."""

    def __init__(self, listings: list[JobListing] | None = None) -> None:
        self.listings = listings if listings is not None else FIXTURE_JOBS
        self.search_calls = 0
        self.last_query: str | None = None
        self.last_location: str | None = None

    async def search(self, query: str, location: str | None = None) -> list[JobListing]:
        self.search_calls += 1
        self.last_query = query
        self.last_location = location
        return list(self.listings)

    async def get_job(self, job_id: str) -> JobListing | None:
        for listing in self.listings:
            if listing.id == job_id:
                return listing
        return None


class FailingJobSource:
    """JobSource double whose search always raises (degradation path)."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error or RuntimeError("fixture source unavailable")
        self.search_calls = 0

    async def search(self, query: str, location: str | None = None) -> list[JobListing]:
        self.search_calls += 1
        raise self._error

    async def get_job(self, job_id: str) -> JobListing | None:
        return None
