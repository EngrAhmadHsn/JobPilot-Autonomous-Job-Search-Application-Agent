"""EEO / voluntary self-identification data (WS-20) — sensitive, isolated.

Race/ethnicity, gender, disability and veteran status are the most sensitive
data this product holds. The rules, from the workstream spec, are hard
requirements, not guidelines:

1. Never inferred from a résumé, name, photograph, location, education, or any
   other information.
2. Never used for matching, ranking, eligibility scoring, or tailoring.
3. Collected only through explicit user input and opt-in.
4. "No answer", "unanswered" and "prefer not to answer" are three different
   states.
5. "Decline" is never selected automatically — only when the user chose it.
6. Kept logically separate from professional information and matching features.
7. Owner-only authorization; never in ordinary logs, audit metadata, analytics
   or LLM prompts.

This module only *models* the data. The isolation — a dedicated table, a
dedicated owner-scoped route, and the absence of any import into the matcher —
is what enforces the rest. The ``DISCLOSURE_*`` sentinels make rule 4 and 5
representable: an unanswered field is ``None``, and a chosen decline is
:data:`DECLINED`.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

__all__ = [
    "DECLINED",
    "EEO_FIELDS",
    "EeoProfile",
    "is_answered",
]

#: The sentinel a user picks to decline a question. Distinct from ``None``,
#: which means the question was never answered.
DECLINED = "prefer_not_to_answer"

EEO_FIELDS = ("race_ethnicity", "gender", "disability", "veteran_status")

_MAX_VALUE = 200


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > _MAX_VALUE:
        raise ValueError("EEO value is too long")
    return cleaned


class EeoProfile(BaseModel):
    """Owner-scoped voluntary self-identification data.

    Every field is ``None`` until the user answers. A field set to
    :data:`DECLINED` records an explicit "prefer not to answer" — which is
    **not** the same as leaving it unanswered, and is never auto-selected.
    ``opt_in`` must be true for the data to be stored at all.
    """

    opt_in: bool = False
    race_ethnicity: str | None = None
    gender: str | None = None
    disability: str | None = None
    veteran_status: str | None = None

    @field_validator(*EEO_FIELDS)
    @classmethod
    def _check_value(cls, value: str | None) -> str | None:
        return _clean(value)

    def is_empty(self) -> bool:
        """True when nothing at all has been answered."""
        return not any(getattr(self, field) for field in EEO_FIELDS)


def is_answered(value: str | None) -> bool:
    """Whether a field carries a real answer (a decline counts as an answer).

    ``None`` is *unanswered*; :data:`DECLINED` is an explicit choice. Both are
    distinct from a value, and neither may be invented by the system.
    """
    return value is not None
