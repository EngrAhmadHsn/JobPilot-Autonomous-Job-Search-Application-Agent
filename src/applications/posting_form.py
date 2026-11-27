"""Read-only employer forms and exact, human-entered answers for one posting."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Literal

from anyio import from_thread
from pydantic import BaseModel, Field

from src.applications.greenhouse_adapter import parse_greenhouse_job_url
from src.applications.greenhouse_forms import FormQuestion, FormSchema
from src.applications.questions import NEVER_AUTOFILL, classify_text
from src.graph.executor import select_adapter_for_url
from src.security.allowlist import DisallowedDomainError, assert_job_url_allowed

logger = logging.getLogger(__name__)

FormState = Literal["available", "unavailable", "unsupported"]
QuestionKind = Literal["text", "textarea", "select", "multiselect", "contact", "resume", "employer"]
AnswerValue = str | list[str]
MAX_ANSWER_LENGTH = 4000
MAX_QUESTIONS = 150
MAX_OPTIONS = 500
CONTACT_FIELDS = frozenset({"first_name", "last_name", "name", "email", "phone"})
RESUME_FIELDS = frozenset({"resume", "resume_text"})
SELECT_ONE = frozenset({"multi_value_single_select", "select", "radio"})
SELECT_MANY = frozenset({"multi_value_multi_select"})


class Choice(BaseModel):
    value: str
    label: str


class PostingQuestion(BaseModel):
    question_key: str
    label: str
    kind: QuestionKind
    required: bool
    description: str | None = None
    options: list[Choice] = Field(default_factory=list)
    answer: AnswerValue | None = None
    field_name: str | None = None


class PostingForm(BaseModel):
    state: FormState
    questions: list[PostingQuestion] = Field(default_factory=list)


@dataclass(frozen=True)
class LoadedForm:
    form: PostingForm
    # A verified provider posting identity, not display company text or a guessed hostname.
    provider_posting: str | None = None


def _question(posting: str, question: FormQuestion) -> PostingQuestion | None:
    names = frozenset(question.field_names)
    types = frozenset(question.field_types)
    if types == {"input_hidden"}:
        return None
    label = question.label.strip()
    if not label or len(label) > 1500:
        raise ValueError("Invalid employer question label")
    if len(question.options) > MAX_OPTIONS:
        raise ValueError("Too many employer options")
    options = [Choice.model_validate(option) for option in question.options]
    if any(not o.value or len(o.value) > 200 or not o.label or len(o.label) > 500 for o in options):
        raise ValueError("Invalid employer option")
    if len({o.value for o in options}) != len(options):
        raise ValueError("Ambiguous employer options")

    category = classify_text(label).category
    description = (question.description or "").strip() or None
    private = (
        question.needs_consent
        or category in NEVER_AUTOFILL
        or (description is not None and classify_text(description).category in NEVER_AUTOFILL)
    )
    field_name = next(iter(names)) if len(names) == 1 else None
    kind: QuestionKind
    if private or question.is_location:
        kind = "employer"
    elif names and names <= RESUME_FIELDS and types <= {"input_text", "input_file", "textarea"}:
        kind = "resume"
    elif field_name in CONTACT_FIELDS and types == {"input_text"}:
        kind = "contact"
    elif not field_name or question.is_file or len(types) != 1:
        kind = "employer"
    elif types <= SELECT_ONE and options:
        kind = "select"
    elif types <= SELECT_MANY and options:
        kind = "multiselect"
    elif types == {"textarea"}:
        kind = "textarea"
    elif types == {"input_text"}:
        kind = "text"
    else:
        kind = "employer"

    # The revision includes the prompt and option meanings, not just an ATS field id.
    # Re-ordering unchanged choices is safe; a repurposed field id is not.
    identity = [
        posting,
        question.block,
        sorted(names),
        sorted(types),
        label,
        description,
        question.required,
        kind,
        sorted((option.value, option.label) for option in options),
    ]
    key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
    return PostingQuestion(
        question_key=key,
        label=label,
        kind=kind,
        required=question.required,
        description=description[:1500] if description else None,
        options=options if kind in {"select", "multiselect"} else [],
        field_name=field_name if kind == "contact" else None,
    )


def read_posting_form(job_id: str, url: str | None, *, local: bool = False) -> LoadedForm:
    """Read only public form metadata; never send contact data or uploaded files."""
    fallback = LoadedForm(PostingForm(state="unsupported"))
    if not url:
        return fallback
    try:
        assert_job_url_allowed(url)
        adapter = select_adapter_for_url(url)
    except (DisallowedDomainError, RuntimeError, ValueError):
        return fallback
    provider_ids = parse_greenhouse_job_url(url)
    fetch = getattr(adapter, "fetch_form_schema", None)
    if not provider_ids or not callable(fetch):
        return fallback
    provider_key = f"greenhouse:{provider_ids[0].lower()}:{provider_ids[1]}"

    async def fetch_bounded() -> FormSchema | None:
        return await asyncio.wait_for(fetch(url), timeout=8)

    try:
        # FastAPI sync handlers run in AnyIO worker threads. Keep HTTP on the
        # server loop so the process-wide source limiter can share its lock.
        schema = asyncio.run(fetch_bounded()) if local else from_thread.run(fetch_bounded)
        if schema is None or not schema.schema_published:
            return LoadedForm(PostingForm(state="unavailable"))
        if len(schema.all_questions) > MAX_QUESTIONS:
            raise ValueError("Too many employer questions")
        questions = [
            view
            for item in schema.all_questions
            if (view := _question(f"{job_id}:{provider_key}", item)) is not None
        ]
        if len({question.question_key for question in questions}) != len(questions):
            raise ValueError("Ambiguous employer questions")
        return LoadedForm(PostingForm(state="available", questions=questions), provider_key)
    except Exception:  # noqa: BLE001 - A provider outage must not stop local preparation.
        logger.info("Could not read a usable application form for the stored posting")
        return LoadedForm(PostingForm(state="unavailable"))


def validated_answer(question: PostingQuestion, value: AnswerValue) -> AnswerValue:
    """Validate at the server against the displayable, revision-bound control."""
    if question.kind not in {"text", "textarea", "select", "multiselect"}:
        raise ValueError(
            "Answer this field in Contact details, Documents, or on the employer site."
        )
    if question.kind == "multiselect":
        options = {option.value for option in question.options}
        if (
            not isinstance(value, list)
            or not value
            or len(value) > 100
            or len(set(value)) != len(value)
            or any(item not in options for item in value)
        ):
            raise ValueError("Select one or more of the employer's published options.")
        return value
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > MAX_ANSWER_LENGTH:
        raise ValueError(f"Enter an answer of 1 to {MAX_ANSWER_LENGTH} characters.")
    if question.kind == "select" and value not in {option.value for option in question.options}:
        raise ValueError("Select one of the employer's published options.")
    return value if question.kind == "select" else value.strip()
