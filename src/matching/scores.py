"""Score states and the fixed-denominator blend (WS-20).

The WS-03 engine could not tell *earned* from *defaulted*: a component whose
inputs were unknown returned the neutral 70, and a missing embedding had its
weight redistributed onto the others. Both behaviours let a listing with less
evidence outrank one with more.

This module is the replacement, and it is deliberately small because it is a
*policy* module: one rule, applied everywhere.

The rule
--------

A component carries a :class:`ScoreState` — the **information situation**, not
the outcome:

- a **measured** component (``MATCHED`` / ``PARTIAL_MATCH`` / ``MISMATCH``)
  contributes ``weight * value`` to the numerator;
- an **unknown** component (``CANDIDATE_DATA_MISSING``,
  ``JOB_REQUIREMENT_MISSING``, ``EMBEDDING_PENDING``,
  ``EMBEDDING_UNAVAILABLE``) contributes **zero to the numerator and keeps its
  full weight in the denominator**. Unknown is never presented as a match, and
  a job is never rewarded for missing evidence.
- a genuinely **``NOT_APPLICABLE``** component is removed from numerator *and*
  denominator, and is reported so the exclusion is visible.

The denominator is therefore ``Σ weight`` over the counted components — the
configured weight set, never a function of how many factors happened to be
available. ``redistribute_without`` no longer exists on this path.

**Coverage** is the second half of the answer: ``Σ weight(measured) /
Σ weight(counted)``. A score and its coverage are always reportable together,
so ``71`` from six measured components is distinguishable from ``71`` from one
measured component and five unknowns.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

__all__ = [
    "EVIDENCE_STATES",
    "UNKNOWN_STATES",
    "ComponentScore",
    "ScoreState",
    "blend",
    "measured_state",
]


class ScoreState(StrEnum):
    """Why a component has the value it has (the information situation)."""

    MATCHED = "MATCHED"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    MISMATCH = "MISMATCH"
    CANDIDATE_DATA_MISSING = "CANDIDATE_DATA_MISSING"
    JOB_REQUIREMENT_MISSING = "JOB_REQUIREMENT_MISSING"
    EMBEDDING_PENDING = "EMBEDDING_PENDING"
    EMBEDDING_UNAVAILABLE = "EMBEDDING_UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


#: States backed by a real measurement (they count toward coverage).
EVIDENCE_STATES: frozenset[ScoreState] = frozenset(
    {ScoreState.MATCHED, ScoreState.PARTIAL_MATCH, ScoreState.MISMATCH}
)

#: States that mean "we do not know" (zero numerator, weight kept).
UNKNOWN_STATES: frozenset[ScoreState] = frozenset(
    {
        ScoreState.CANDIDATE_DATA_MISSING,
        ScoreState.JOB_REQUIREMENT_MISSING,
        ScoreState.EMBEDDING_PENDING,
        ScoreState.EMBEDDING_UNAVAILABLE,
    }
)


class ComponentScore(BaseModel):
    """One scored component: its value, its state, and its evidence.

    ``value`` is 0-100 and is only meaningful when ``state`` is a measured
    state; an unknown component carries ``value=0.0`` by construction, so it
    can never add to the numerator.
    """

    name: str
    value: float = Field(0.0, ge=0.0, le=100.0)
    state: ScoreState = ScoreState.NOT_APPLICABLE
    reason: str = ""
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)

    @property
    def counted(self) -> bool:
        """Whether this component takes part in the blend at all."""
        return self.state is not ScoreState.NOT_APPLICABLE

    @property
    def is_evidence(self) -> bool:
        """Whether the component is backed by a measured value."""
        return self.state in EVIDENCE_STATES


def measured_state(value: float, *, matched_at: float = 60.0) -> ScoreState:
    """Classify a measured 0-100 value into MATCHED / PARTIAL / MISMATCH.

    The thresholds are the *state* only; the numeric ``value`` is never
    altered by them, so no information is lost in the classification.
    """
    if value >= matched_at:
        return ScoreState.MATCHED
    if value > 0.0:
        return ScoreState.PARTIAL_MATCH
    return ScoreState.MISMATCH


class Blend(BaseModel):
    """The result of blending component scores with the fixed denominator."""

    overall_score: float = 0.0
    evidence_coverage: float = 0.0  # 0-100
    denominator: float = 0.0
    numerator: float = 0.0


def blend(weights: dict[str, float], components: dict[str, ComponentScore]) -> Blend:
    """Blend components over a **fixed** denominator.

    Every component named in *weights* is counted unless its state is
    ``NOT_APPLICABLE``. An unknown state contributes zero to the numerator but
    keeps its weight, so a missing component lowers the score instead of
    silently moving its weight elsewhere.
    """
    denominator = 0.0
    numerator = 0.0
    evidence_weight = 0.0
    for name, weight in weights.items():
        component = components.get(name)
        if component is None or not component.counted:
            continue
        denominator += weight
        numerator += weight * component.value
        if component.is_evidence:
            evidence_weight += weight
    # The values are already on the 0-100 scale, so the fixed-denominator mean
    # is the overall score directly; coverage is the measured share, as a
    # percentage of the counted weight.
    overall = (numerator / denominator) if denominator else 0.0
    coverage = (evidence_weight / denominator * 100.0) if denominator else 0.0
    return Blend(
        overall_score=max(0.0, min(100.0, overall)),
        evidence_coverage=max(0.0, min(100.0, coverage)),
        denominator=denominator,
        numerator=numerator,
    )
