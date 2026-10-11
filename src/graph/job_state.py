"""LangGraph state for the job-search pipeline (WS-04).

Dedicated Pydantic state for the search→rank pipeline. It deliberately does
NOT reuse ``ApplicationWorkflowState`` — that state belongs to the submission
workflow (prepare→approval→submit→verify) and has no fields for jobs/matches.
LangGraph 1.x accepts a Pydantic model as the state schema; nodes return
partial dicts that are merged field-by-field.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.jobs.contracts import JobListing
from src.jobs.search_planner import SourceQuery
from src.matching.contracts import JobMatchResult
from src.resume.profile import CandidateProfile


class JobMatchPair(BaseModel):
    """One (listing, match result) pair flowing through match/rank."""

    job: JobListing
    match: JobMatchResult


class JobSearchState(BaseModel):
    """State passed through the job-search LangGraph pipeline.

    Field update order mirrors the pipeline: ``search`` fills ``queries`` and
    ``raw_jobs`` (plus ``source_errors``), ``normalize`` filters into ``jobs``
    (counting ``dropped``), ``deduplicate`` narrows ``jobs`` further,
    ``persist`` records ``persisted``, ``match`` fills ``matches`` (and
    ``degraded``), ``rank`` slices ``top``.
    """

    profile: CandidateProfile

    # Optional caller-supplied query/location overriding the planner-derived ones
    query: str | None = None
    location: str | None = None
    top_n: int = 10

    queries: list[SourceQuery] = Field(default_factory=list)
    raw_jobs: list[JobListing] = Field(default_factory=list)
    jobs: list[JobListing] = Field(default_factory=list)
    matches: list[JobMatchPair] = Field(default_factory=list)
    top: list[JobMatchPair] = Field(default_factory=list)

    # source -> error message; tolerated per plan §35 (a failing source
    # degrades the report, never fails the search)
    source_errors: dict[str, str] = Field(default_factory=dict)

    # Stats counters (surfaced on the JobSearchReport)
    dropped: int = 0  # listings dropped by the normalize node
    persisted: int = 0  # rows upserted by the persist node
    degraded: bool = False  # True when semantic scoring was unavailable
