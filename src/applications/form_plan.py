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

WS-45 adds the fourth input: the answers the human saved for *this*
application (:func:`build_question_plan`'s ``answers`` argument). A saved
answer whose key (or normalized label, or category) matches a question
flips that question's ``needs_human`` verdict to ``answerable`` with
``answer_from="you"`` — the human's own answer, given in the console. A
question the profile already answers keeps its profile-derived source; a
``never_autofill`` verdict can never be flipped by a saved answer, because
the storage layer refuses such answers before one could exist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

__all__ = [
    "VERDICT_ANSWERABLE",
    "VERDICT_NEEDS_HUMAN",
    "VERDICT_NEVER_AUTOFILL",
    "VERDICT_OPTIONAL_UNANSWERED",
    "QuestionPlan",
    "SavedAnswer",
    "apply_saved_answers",
    "blocking_questions",
    "build_question_plan",
    "coerce_saved_answers",
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


class SavedAnswer(BaseModel):
    """One answer the human saved for this application (WS-45).

    The plan and the fact map both read this shape, and both accept it in
    three forms — a :class:`SavedAnswer`, a plain dict with these keys, or
    the stored row (``answer_text`` instead of ``answer``) — so a caller
    never needs a conversion layer. See :func:`coerce_saved_answers`.
    """

    question_key: str = ""
    label: str | None = None
    category: str | None = None
    answer: str = ""


def coerce_saved_answers(items: Any) -> list[SavedAnswer]:
    """The saved answers as :class:`SavedAnswer` items, whatever they arrived as.

    Accepts ``SavedAnswer`` instances, plain mappings, and the stored rows
    (which carry ``answer_text``). Items that are not answers are skipped,
    not raised: a merge must degrade to the un-merged plan, never fail a
    prepare because one saved row was odd.
    """
    if not items:
        return []
    resolved: list[SavedAnswer] = []
    for item in items:
        if isinstance(item, SavedAnswer):
            resolved.append(item)
        elif isinstance(item, dict):
            try:
                resolved.append(SavedAnswer.model_validate(item))
            except Exception as exc:  # noqa: BLE001 - one odd row must not stop the merge
                logger.debug("Skipping a saved answer that does not validate: %s", exc)
                continue
        else:
            answer = getattr(item, "answer", None) or getattr(item, "answer_text", "") or ""
            resolved.append(
                SavedAnswer(
                    question_key=str(getattr(item, "question_key", "") or ""),
                    label=getattr(item, "label", None),
                    category=getattr(item, "category", None),
                    answer=str(answer),
                )
            )
    return [item for item in resolved if (item.answer or "").strip()]


def _saved_answer_matches(answer: SavedAnswer, label: str, category: str) -> bool:
    """Whether a saved answer is an answer to *this* question.

    Three ways to match, tried in order — because the console may have
    saved under any of them:

    1. the saved ``question_key`` equals the question's **normalized
       label** (the canonical key :func:`normalize_label` produces, which
       strips the ``?``/``*``/``:`` decoration forms add to required
       fields);
    2. the saved row's own ``label`` equals the question's normalized
       label;
    3. the saved key, or the saved ``category``, equals the question's
       taxonomy category.
    """
    from src.applications.form import normalize_label

    normalized_question = normalize_label(label)
    saved_key = normalize_label(answer.question_key or "")
    saved_label = normalize_label(answer.label or "")
    if normalized_question and saved_key and saved_key == normalized_question:
        return True
    if normalized_question and saved_label and saved_label == normalized_question:
        return True
    if not category:
        return False
    category_text = category.strip().lower()
    saved_key_raw = (answer.question_key or "").strip().lower()
    saved_category = (answer.category or "").strip().lower()
    return (saved_key_raw == category_text) or (saved_category == category_text)


def _matching_saved_answer(
    answers: list[SavedAnswer], label: str, category: str
) -> SavedAnswer | None:
    """The saved answer that matches one question, if any."""
    for answer in answers:
        if _saved_answer_matches(answer, label, category):
            return answer
    return None


def build_question_plan(
    schema: Any,
    facts: dict[str, str] | None = None,
    answers: Any = None,
) -> list[QuestionPlan]:
    """Decide what the agent may do with every question on a form.

    Args:
        schema: A :class:`~src.applications.greenhouse_forms.FormSchema`.
        facts: The candidate's grounded profile facts (the only source an
            answer may come from).
        answers: The answers the human saved for this application
            (WS-45). A saved answer that matches a ``needs_human``
            question flips it to ``answerable`` with
            ``answer_from="you"``; a question the profile already answers
            keeps its profile-derived source, and a ``never_autofill``
            verdict can never be flipped (the storage layer refuses such
            answers before one could exist).

    Returns:
        One :class:`QuestionPlan` per question, in form order.
    """
    from src.applications.questions import NEVER_AUTOFILL, classify_text

    resolved_facts = {str(k): str(v) for k, v in (facts or {}).items() if v}
    saved = coerce_saved_answers(answers)
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
            # WS-45: the human may have answered this question in the
            # console. Their saved answer unblocks it — it is *their*
            # answer, grounded in nothing but themselves, and the plan
            # says so (``answer_from="you"``) instead of pretending it
            # came from the profile.
            if _matching_saved_answer(saved, question.label, category.value) is not None:
                verdict = VERDICT_ANSWERABLE
                answer_key = "you"
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


def apply_saved_answers(plan_dicts: list[dict[str, Any]], answers: Any) -> list[dict[str, Any]]:
    """The stored plan with the human's saved answers applied (WS-45).

    The approval row keeps the plan as it stood at prepare time, and a
    human may answer more questions afterwards (the per-application
    questions page saves through ``PUT .../answers``, which does not
    re-prepare). A read of that plan therefore folds the saved answers back
    in with the same rule the prepare-time merge uses: a matching answer
    flips the verdict to ``answerable`` with ``answer_from="you"`` and the
    question leaves the blocking set.

    A ``never_autofill`` verdict is never flipped — the storage layer
    refuses those answers before one could exist, and policy must not be
    reachable through a stale plan row.

    The input dicts are copied, never mutated: the stored plan is the
    approval's own record.
    """
    saved = coerce_saved_answers(answers)
    result: list[dict[str, Any]] = []
    for item in plan_dicts:
        current = dict(item)
        if current.get("verdict") != VERDICT_NEVER_AUTOFILL:
            match = _matching_saved_answer(
                saved,
                str(current.get("label") or ""),
                str(current.get("category") or ""),
            )
            if match is not None:
                current["verdict"] = VERDICT_ANSWERABLE
                current["answer_from"] = "you"
        result.append(current)
    return result


def plan_as_dicts(plans: list[QuestionPlan]) -> list[dict[str, Any]]:
    """The plan as plain data, for the prepare response and the approval row.

    WS-45: each item also carries ``question_key`` — the question's
    normalized label, the stable key the console saves a human answer
    under. The merge accepts that key, the raw label, or the category, so
    a client that echoes any of them matches; this key is the one the
    contract names.
    """
    from src.applications.form import normalize_label

    return [
        {
            "question_key": normalize_label(plan.label),
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
