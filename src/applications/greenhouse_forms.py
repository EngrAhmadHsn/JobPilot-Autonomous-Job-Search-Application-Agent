"""The Greenhouse application form schema (WS-25).

Greenhouse is the only one of the four providers that publishes its
**application form schema** over a public, key-less endpoint:

    GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}?questions=true

The response adds four keys to the ordinary job detail:
``questions``, ``location_questions``, ``compliance`` and
``demographic_questions``. Verified live (2026-11-09) against stripe,
anthropic and databricks: stripe's first job carries 13 questions, two
location questions, an empty ``compliance`` list and a null
``demographic_questions``.

Why this matters: the agent was preparing a payload from a **fixed**
field map. A Greenhouse form routinely asks questions the map has never
heard of — *"Will you require Stripe to sponsor you for a work permit
now or in the future?"*, *"Please select the country where you currently
reside"* — and a question the agent does not recognize is a question it
must not answer. With the schema, the prepare step can:

* show the operator the **exact** form, field by field;
* answer the questions the profile actually covers;
* and stop with ``blocked_human_review`` for the ones it cannot.

Two rules govern what the agent may do with the schema, and both come
from the shape of the data rather than from a preference:

**Consent and demographic questions are never answered by the agent.**
The ``compliance`` block carries EEO questions and the
``demographic_questions`` block carries the voluntary self-identification
questions; the ``data_compliance`` array states whether GDPR consent is
required. Ticking a consent box on the candidate's behalf is an
assertion the agent cannot make, and the demographic questions are
always optional by design. They are surfaced to the human at approval
time and nothing else.

**Location questions need the coordinates.** Greenhouse's hosted form
shows a location autocomplete, and the API documents that
``location``, ``latitude`` and ``longitude`` must **all** be sent — if
the coordinates are omitted, the location is ignored entirely. The
question schema names the fields (``location``, ``latitude``,
``longitude``), so the prepare step can detect that the form wants a
geocode and say so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "FormQuestion",
    "FormSchema",
    "build_form_schema",
    "human_fields",
    "is_consent_question",
]

logger = logging.getLogger(__name__)

#: The field types Greenhouse uses. ``input_file`` and ``input_text``
#: carry the resume and cover letter; the select types carry the
#: multiple-choice questions.
_TEXT_TYPES = frozenset({"input_text", "textarea", "input_hidden"})
_FILE_TYPES = frozenset({"input_file"})

#: The compliance and demographic blocks are surfaced to the human and
#: are never answered by the agent. The rules that identify them live in
#: ``src.applications.questions`` (the EEO categories and the
#: attestation rule); this module only needs to know that they arrive in
#: their own blocks.
_CONSENT_BLOCKS = ("compliance", "demographic_questions")


@dataclass
class FormQuestion:
    """One question on a Greenhouse application form."""

    #: The human label ("First Name", "Will you require sponsorship?").
    label: str
    #: Whether the form marks the question as required.
    required: bool
    #: The field names this question writes (``question_123``,
    #: ``question_123[]``, ``first_name``).
    field_names: list[str] = field(default_factory=list)
    #: The field types (``input_text``, ``multi_value_single_select``…).
    field_types: list[str] = field(default_factory=list)
    #: The offered choices, when the question is a select.
    options: list[dict[str, str]] = field(default_factory=list)
    #: Which block the question came from: ``questions``,
    #: ``location_questions``, ``compliance`` or ``demographic_questions``.
    block: str = "questions"
    #: The question's own description, when the board states one.
    description: str | None = None

    @property
    def is_file(self) -> bool:
        """Whether the question asks for a file (the résumé)."""
        return any(kind in _FILE_TYPES for kind in self.field_types)

    @property
    def is_location(self) -> bool:
        """Whether the question asks for a location or its coordinates."""
        return any(name in {"location", "latitude", "longitude"} for name in self.field_names)

    @property
    def needs_consent(self) -> bool:
        """Whether the question is a consent or demographic question.

        These are never answered by the agent. A consent box is an
        assertion the agent cannot make, and the demographic questions are
        voluntary by design.
        """
        return self.block in _CONSENT_BLOCKS


@dataclass
class FormSchema:
    """The full application form of one job."""

    #: The ordinary questions.
    questions: list[FormQuestion] = field(default_factory=list)
    #: The location questions (present when the job's location is asked).
    location_questions: list[FormQuestion] = field(default_factory=list)
    #: The EEO / compliance questions — surfaced, never answered.
    compliance: list[FormQuestion] = field(default_factory=list)
    #: The demographic questions — surfaced, never answered.
    demographic: list[FormQuestion] = field(default_factory=list)
    #: Whether the board states that GDPR consent is required.
    requires_gdpr_consent: bool = False
    #: The board's raw ``data_compliance`` array, kept for the record.
    data_compliance: list[dict[str, Any]] = field(default_factory=list)

    @property
    def all_questions(self) -> list[FormQuestion]:
        """Every question on the form, in every block."""
        return [*self.questions, *self.location_questions, *self.compliance, *self.demographic]

    @property
    def required_questions(self) -> list[FormQuestion]:
        """The questions the form marks as required."""
        return [question for question in self.all_questions if question.required]

    @property
    def unanswered_by_policy(self) -> list[FormQuestion]:
        """The questions the agent must never answer."""
        return [question for question in self.all_questions if question.needs_consent]


def _read_question(entry: Any, block: str) -> FormQuestion | None:
    """One question object out of a Greenhouse question list."""
    if not isinstance(entry, dict):
        return None
    label = entry.get("label")
    if not isinstance(label, str) or not label.strip():
        return None
    fields = entry.get("fields")
    names: list[str] = []
    types: list[str] = []
    options: list[dict[str, str]] = []
    if isinstance(fields, list):
        for field_entry in fields:
            if not isinstance(field_entry, dict):
                continue
            name = field_entry.get("name")
            if isinstance(name, str) and name:
                names.append(name)
            kind = field_entry.get("type")
            if isinstance(kind, str) and kind:
                types.append(kind)
            values = field_entry.get("values")
            if isinstance(values, list):
                for value in values:
                    if not isinstance(value, dict):
                        continue
                    entry_label = value.get("label")
                    entry_value = value.get("value")
                    options.append(
                        {
                            "label": str(entry_label) if entry_label is not None else "",
                            # Greenhouse returns the option value as a
                            # **string** ("3", "2", "1"), while the
                            # documentation's example shows integers. It
                            # is normalized to a string here so a caller
                            # never has to guess which it is.
                            "value": str(entry_value) if entry_value is not None else "",
                        }
                    )
    description = entry.get("description")
    return FormQuestion(
        label=label.strip(),
        required=bool(entry.get("required")),
        field_names=names,
        field_types=types,
        options=options,
        block=block,
        description=description.strip()
        if isinstance(description, str) and description.strip()
        else None,
    )


def build_form_schema(payload: dict[str, Any]) -> FormSchema:
    """Build the form schema from a ``?questions=true`` response.

    A response with no question keys is not an error: it means the board
    published no schema, and the caller falls back to the fixed field map.
    """
    schema = FormSchema()

    questions = payload.get("questions")
    if isinstance(questions, list):
        for entry in questions:
            question = _read_question(entry, "questions")
            if question is not None:
                schema.questions.append(question)

    location_questions = payload.get("location_questions")
    if isinstance(location_questions, list):
        for entry in location_questions:
            question = _read_question(entry, "location_questions")
            if question is not None:
                schema.location_questions.append(question)

    compliance = payload.get("compliance")
    if isinstance(compliance, list):
        for block in compliance:
            if not isinstance(block, dict):
                continue
            entries = block.get("questions")
            if not isinstance(entries, list):
                continue
            for entry in entries:
                question = _read_question(entry, "compliance")
                if question is not None:
                    schema.compliance.append(question)

    demographics = payload.get("demographic_questions")
    if isinstance(demographics, dict):
        entries = demographics.get("questions")
        if isinstance(entries, list):
            for entry in entries:
                question = _read_question(entry, "demographic_questions")
                if question is not None:
                    schema.demographic.append(question)

    data_compliance = payload.get("data_compliance")
    if isinstance(data_compliance, list):
        schema.data_compliance = [entry for entry in data_compliance if isinstance(entry, dict)]
        schema.requires_gdpr_consent = any(
            bool(entry.get("requires_consent"))
            or bool(entry.get("requires_processing_consent"))
            or bool(entry.get("requires_retention_consent"))
            for entry in schema.data_compliance
        )

    return schema


def human_fields(schema: FormSchema) -> list[dict[str, Any]]:
    """The schema as a plain, displayable list.

    The operator reads this at approval time, so the consent and
    demographic questions are included and clearly marked — they are
    shown to a human, not answered by the agent.
    """
    rows: list[dict[str, Any]] = []
    for question in schema.all_questions:
        rows.append(
            {
                "label": question.label,
                "required": question.required,
                "fields": question.field_names,
                "types": question.field_types,
                "options": question.options,
                "block": question.block,
                "agent_may_answer": not question.needs_consent,
                "description": question.description,
            }
        )
    return rows


def is_consent_question(label: str) -> bool:
    """Whether a label states a consent or attestation the agent must not give.

    The taxonomy in ``src.applications.questions`` classifies the label;
    this is the narrow wrapper the form-schema path uses so the rule
    lives in one place.
    """
    from src.applications.questions import NEVER_AUTOFILL, classify_text

    return classify_text(label).category in NEVER_AUTOFILL
