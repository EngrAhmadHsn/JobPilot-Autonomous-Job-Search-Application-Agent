"""Job source abstraction layer."""

from src.jobs.contracts import JobListing, JobSource
from src.jobs.deduplicate import deduplicate
from src.jobs.greenhouse_adapter import GreenhouseJobAdapter
from src.jobs.lever_adapter import LeverJobAdapter
from src.jobs.remotive_adapter import RemotiveJobAdapter
from src.jobs.search_planner import SourceQuery, plan_queries

__all__ = [
    "GreenhouseJobAdapter",
    "JobListing",
    "JobSource",
    "LeverJobAdapter",
    "RemotiveJobAdapter",
    "SourceQuery",
    "deduplicate",
    "plan_queries",
]
