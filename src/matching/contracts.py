"""Matching engine contracts (WS-03, extended WS-20)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobMatchResult(BaseModel):
    """Result of matching a candidate profile against a job listing.

    Every component score is 0-100 and, in the WS-20 policy, only meaningful
    when the corresponding entry in ``component_states`` is a *measured* state.
    An unknown component carries ``0.0`` — it is never presented as a match —
    and its reason appears in ``notes``. ``evidence_coverage`` says how much of
    the overall score rests on real information, so a score and its coverage
    are always readable together.
    """

    overall_score: float = Field(..., ge=0, le=100)
    semantic_score: float = Field(..., ge=0, le=100)
    lexical_score: float = Field(0.0, ge=0, le=100)
    skill_score: float = Field(..., ge=0, le=100)
    experience_score: float = Field(..., ge=0, le=100)
    seniority_score: float = Field(..., ge=0, le=100)
    location_score: float = Field(..., ge=0, le=100)
    preference_score: float = Field(..., ge=0, le=100)
    #: WS-21: relevance between the candidate's target roles and the
    #: listing's classified occupational family. 0 with an unknown state when
    #: either side is not known — never a silent default.
    role_score: float = Field(0.0, ge=0, le=100)
    #: WS-21 role evidence: the classified family (``None`` = unknown), how
    #: sure the classifier is, the candidate targets the comparison used
    #: (``user`` / ``inferred`` / ``cleared`` / ``none``), and whether the
    #: role mismatch capped the overall score.
    role_family: str | None = None
    role_family_confidence: float = Field(0.0, ge=0.0, le=1.0)
    role_targets: list[str] = Field(default_factory=list)
    role_target_source: str = "none"
    role_capped: bool = False
    #: 0-100: the share of the counted weight that is backed by a measurement.
    evidence_coverage: float = Field(0.0, ge=0, le=100)
    #: Per-component :class:`~src.matching.scores.ScoreState` values, by name.
    component_states: dict[str, str] = Field(default_factory=dict)
    #: Why a component is unknown / zero, in words.
    notes: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    matched_requirements: list[str] = Field(default_factory=list)
    #: Important keywords the job text mentions and the candidate does not.
    missing_keywords: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    explanation: str = ""
