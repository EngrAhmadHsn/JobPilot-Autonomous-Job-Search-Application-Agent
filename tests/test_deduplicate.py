"""Tests for Phase 4 deduplication logic."""

from src.jobs.contracts import JobListing
from src.jobs.deduplicate import deduplicate


def test_deduplicate_removes_duplicates():
    jobs = [
        JobListing(id="1", source="linkedin", title="Eng", company="A"),
        JobListing(id="2", source="linkedin", title="Eng", company="A"),
        JobListing(id="3", source="indeed", title="Dev", company="B"),
    ]
    result = deduplicate(jobs)
    assert len(result) == 2


def test_deduplicate_keeps_unique():
    jobs = [
        JobListing(id="1", source="linkedin", title="Eng", company="A"),
    ]
    result = deduplicate(jobs)
    assert len(result) == 1
    assert result[0].id == "1"
