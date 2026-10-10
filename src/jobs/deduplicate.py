"""Job deduplication logic."""

from __future__ import annotations

from src.jobs.contracts import JobListing


def _dedup_key(job: JobListing) -> tuple:
    """Build a deduplication key for a listing.

    Prefer stable identifiers when present (source job ID, then application
    URL, both scoped to the source). Listings without identifiers fall back
    to source + normalized title + company, so identical postings without
    IDs still collapse.
    """
    if job.source_job_id:
        return ("id", job.source, job.source_job_id)
    if job.application_url:
        return ("url", job.source, job.application_url)
    return (
        "content",
        job.source,
        (job.title or "").strip().lower(),
        (job.company or "").strip().lower(),
    )


def deduplicate(jobs: list[JobListing]) -> list[JobListing]:
    """Remove duplicate job listings.

    Listings are duplicates when they share (source, source_job_id), an
    application URL within the same source, or — when neither identifier
    exists — the same source, title, and company.
    """
    seen: set[tuple] = set()
    unique: list[JobListing] = []
    for job in jobs:
        key = _dedup_key(job)
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique
