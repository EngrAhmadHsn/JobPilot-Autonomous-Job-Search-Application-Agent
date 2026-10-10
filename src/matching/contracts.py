"""Matching engine contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobMatchResult(BaseModel):
    """Result of matching a candidate profile against a job listing."""

    overall_score: float = Field(..., ge=0, le=100)
    semantic_score: float = Field(..., ge=0, le=100)
    skill_score: float = Field(..., ge=0, le=100)
    experience_score: float = Field(..., ge=0, le=100)
    seniority_score: float = Field(..., ge=0, le=100)
    location_score: float = Field(..., ge=0, le=100)
    preference_score: float = Field(..., ge=0, le=100)
    missing_requirements: list[str] = Field(default_factory=list)
    matched_requirements: list[str] = Field(default_factory=list)
    explanation: str = ""
