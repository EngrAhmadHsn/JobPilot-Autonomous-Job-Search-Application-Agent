"""The per-question answer plan for a prepared application (WS-25b §9.1).

WS-25 built the form schema and left it unwired. This module is the
bridge: it takes a schema and the candidate's grounded facts and decides,
**for every question on the board's real form**, what the agent may do.

Four verdicts, and the distinction between them is the point:

* **``answerable``** — the profile has a grounded fact for it. The agent
  may fill it.
* **``never_autofill``** — a consent, demographic or attestation
  question. The agent must **never** answer it; it is surfaced to the
  human at approval time. Ticking a consent box on the candidate's behalf
  is an assertion the agent cannot make.
* **``needs_human``** — the form marks it **required** and the profile
  does not answer it. This is the case that stops the flow.
* **``optional_unanswered``** — the profile does not answer it, and the
  form does not require it. Nothing to do.

The distinction between the last two is what makes this useful: a
required question the agent cannot answer is a reason to **stop and ask
a human**, while an optional one is not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "VERDICT_ANSWERABLE",
    "VERDICT_NEEDS_HUMAN",
    "VERDICT_NEVER_AUTOFILL",
    "VERDICT_OPTIONAL_UNANSWERED",
    "QuestionPlan",
    "blocking_questions",
    "build_question_plan",
    "plan_as_dicts",
]

logger = logging.getLogger(__name__)


#: The verdicts, in the order the console shows them.
VERDICT_ANSWERABLE = "answerable"
VERDICT_NEVER_AUTOFILL = "never_autofill"
VERDICT_NEEDS_HUMAN = "needs_human"
VERDICT_OPTIONAL_UNANSWERED = "optional_unanswered"


@dataclass
class QuestionPlan:
    """What the agent may do with one question on the form."""

    label: str
    required: bool
    block: str
    verdict: str
    #: The taxonomy category the label resolved to.
    category: str = "unknown"
    #: The grounded fact that answers it, when there is one.
    answer_from: str | None = None
    #: The form field names the answer would be submitted as.
    field_names: list[str] = field(default_factory=list)

    @property
    def blocks_submission(self) -> bool:
        """Whether this question stops the flow.

        Only a **required** question the agent cannot answer does — and a
        consent question never does, because a human answers those at the
        approval step by design.
        """
        return self.verdict == VERDICT_NEEDS_HUMAN


def _fact_for(category: str, facts: dict[str, str]) -> tuple[str, str] | None:
    """The grounded fact that answers a category, or ``None``.

    Returns ``(fact_key, value)``. The mapping is the taxonomy's own
    ``CATEGORY_FACT_KEYS``, so a category added there is answerable here
    without a second table.
    """
    from src.applications.questions import CATEGORY_FACT_KEYS, QuestionCategory

    try:
        resolved = QuestionCategory(category)
    except ValueError:
        return None
    for key in CATEGORY_FACT_KEYS.get(resolved, ()):
        value = facts.get(key)
        if value is not None and str(value).strip():
            return key, str(value).strip()
    return None


def build_question_plan(
    schema: Any,
    facts: dict[str, str] | None = None,
) -> list[QuestionPlan]:
    """Decide what the agent may do with every question on a form.

    Args:
        schema: A :class:`~src.applications.greenhouse_forms.FormSchema`.
        facts: The candidate's grounded profile facts (the only source an
            answer may come from).

    Returns:
        One :class:`QuestionPlan` per question, in form order.
    """
    from src.applications.questions import NEVER_AUTOFILL, classify_text

    resolved_facts = {str(k): str(v) for k, v in (facts or {}).items() if v}
    plans: list[QuestionPlan] = []

    for question in getattr(schema, "all_questions", []) or []:
        classification = classify_text(question.label)
        category = classification.category
        answer = _fact_for(category.value, resolved_facts)

        if question.needs_consent or category in NEVER_AUTOFILL:
            # The block the question arrived in, or the taxonomy, is
            # enough to know the agent must not answer it.
            verdict = VERDICT_NEVER_AUTOFILL
            answer_key = None
        elif answer is not None:
            verdict = VERDICT_ANSWERABLE
            answer_key = answer[0]
        elif question.required:
            verdict = VERDICT_NEEDS_HUMAN
            answer_key = None
        else:
            verdict = VERDICT_OPTIONAL_UNANSWERED
            answer_key = None

        plans.append(
            QuestionPlan(
                label=question.label,
                required=bool(question.required),
                block=question.block,
                verdict=verdict,
                category=category.value,
                answer_from=answer_key,
                field_names=list(question.field_names),
            )
        )
    return plans


def blocking_questions(plans: list[QuestionPlan]) -> list[QuestionPlan]:
    """The questions that stop the flow, if any."""
    return [plan for plan in plans if plan.blocks_submission]


def plan_as_dicts(plans: list[QuestionPlan]) -> list[dict[str, Any]]:
    """The plan as plain data, for the prepare response and the approval row."""
    return [
        {
            "label": plan.label,
            "required": plan.required,
            "block": plan.block,
            "verdict": plan.verdict,
            "category": plan.category,
            "answer_from": plan.answer_from,
            "fields": plan.field_names,
        }
        for plan in plans
    ]
