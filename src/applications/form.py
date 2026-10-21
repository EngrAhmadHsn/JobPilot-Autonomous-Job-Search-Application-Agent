"""The application-form contract (WS-08).

This module is the *pure* half of the browser layer. It knows what a form is,
what a question is, and — above all — **what may be answered**.

The rule it exists to enforce is plan §24: when a form asks something the
candidate's evidence does not cover, the agent says *UNKNOWN* and asks a human.
It never guesses, and it never turns uncertainty into false confidence.

Three parts:

* the **models** — :class:`FormControl`, :class:`FormQuestion`, :class:`FormPlan`;
* the **field map** — the labels a form may use and the candidate fact each one
  asks for (:data:`FIELD_MAP`);
* the **reader** — :func:`read_controls`, which turns a page into controls using
  the browser's own accessibility information, and :func:`build_form_plan`,
  which turns controls plus grounded facts into a plan.

The page reader is duck-typed on purpose (the same choice
``src/security/page_guards.py`` makes): the module must not depend on
Playwright, so the whole of it is unit-testable with plain data — including
from the saved page snapshots under ``tests/fixtures/fake_ats/snapshots``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.applications.contracts import PreparedApplication
    from src.resume.profile import CandidateProfile

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# The models
# --------------------------------------------------------------------------


class FormControl(BaseModel):
    """One control on a page, as read from the accessibility tree.

    The control is described by what a *person* would call it — its label —
    and not by the implementation detail that carries it (the ``id``). That
    distinction is the whole point: the adapter addresses a control by the
    name a human reads.
    """

    label: str
    kind: str = "text"
    required: bool = False
    options: list[str] = Field(default_factory=list)
    name: str = ""


class FormQuestion(BaseModel):
    """One question the page asks.

    ``classification`` records *why* a question is or is not answerable:

    ``known``
        the label is in the field map and a grounded value exists.
    ``mappable``
        the label is in the field map, but no grounded value exists. The
        question is left alone unless it is required.
    ``unknown``
        the label is not in the field map at all. Nothing may be typed into
        it — the run stops and asks a human.
    """

    label: str
    kind: str = "text"
    required: bool = False
    options: list[str] = Field(default_factory=list)
    classification: str = "unknown"


class FormPlan(BaseModel):
    """The plan for one page: what it asks, what we answer, what we cannot.

    ``answers`` is keyed by the **label as it appears on the page** — that is
    what the adapter needs to find the control again. The value always comes
    from the candidate's own evidence.
    """

    questions: list[FormQuestion] = Field(default_factory=list)
    answers: dict[str, str] = Field(default_factory=dict)
    unresolved: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


class ProfileFacts(BaseModel):
    """The grounded facts available to answer a form.

    A fact is present only when it exists. An absent key means *no evidence*,
    which is a different thing from "the answer is no" — and the difference is
    what keeps the agent from answering a question it cannot ground.
    """

    values: dict[str, str] = Field(default_factory=dict)

    def get(self, key: str) -> str | None:
        """The value of *key*, or ``None`` when there is no evidence for it."""
        value = self.values.get(key)
        if value is None:
            return None
        value = value.strip()
        return value or None

    def has(self, key: str) -> bool:
        """True when a non-empty value exists for *key*."""
        return self.get(key) is not None

    @classmethod
    def from_prepared(cls, prepared: PreparedApplication) -> ProfileFacts:
        """The facts of a prepared application.

        The prepared fields, the profile facts and the two artifacts that are
        not fields (the cover letter and the resume file) in one table.
        """
        values: dict[str, str] = {}
        for source in (prepared.prepared_fields, prepared.profile_facts):
            for key, value in source.items():
                if isinstance(value, str) and value.strip():
                    values.setdefault(key, value)
        if prepared.cover_letter and prepared.cover_letter.strip():
            values.setdefault("cover_letter", prepared.cover_letter)
        if prepared.resume_path and str(prepared.resume_path).strip():
            values.setdefault("resume", str(prepared.resume_path))
        return cls(values=values)


# --------------------------------------------------------------------------
# The field map
# --------------------------------------------------------------------------

# The labels a form may use, and the candidate fact each one asks for. The
# keys are normalized labels (see :func:`normalize_label`).
FIELD_MAP: dict[str, str] = {
    # identity
    "full name": "candidate_name",
    "candidate name": "candidate_name",
    "name": "candidate_name",
    "email": "email",
    "email address": "email",
    "phone": "phone",
    "phone number": "phone",
    "telephone": "phone",
    # documents
    "cover letter": "cover_letter",
    "resume": "resume",
    "resume cv": "resume",
    # eligibility
    "country": "country",
    "country of residence": "country",
    "location": "location",
    "current location": "location",
    "years of experience": "years_of_experience",
    "years of professional experience": "years_of_experience",
    "work authorization": "work_authorization",
    "i am authorized to work": "work_authorization",
    "authorized to work": "work_authorization",
    "work mode": "work_mode",
    "preferred work mode": "work_mode",
    "work arrangement": "work_mode",
    # background
    "linkedin": "linkedin",
    "linkedin profile": "linkedin",
    "github": "github",
    "website": "website",
    "portfolio": "website",
    "desired salary": "min_salary",
    "salary expectation": "min_salary",
    "employment type": "employment_types",
    "skills": "skills",
}

# Some facts are called different things by different forms. The first source
# key that carries a value wins.
FACT_SOURCES: dict[str, tuple[str, ...]] = {
    "candidate_name": ("candidate_name", "name"),
    "email": ("email",),
    "phone": ("phone",),
    "cover_letter": ("cover_letter",),
    "resume": ("resume",),
    "country": ("country",),
    "location": ("location",),
    "years_of_experience": ("years_of_experience",),
    "work_authorization": ("work_authorization", "eligibility"),
    "work_mode": ("work_mode", "remote_preference"),
    "linkedin": ("linkedin",),
    "github": ("github",),
    "website": ("website", "portfolio"),
    "min_salary": ("min_salary", "desired_salary"),
    "employment_types": ("employment_types",),
    "skills": ("skills",),
}

# Only long labels take part in the fuzzy second pass (S1.2). A short key such
# as "name" would match "company name" — the wrong field, confidently filled.
_FUZZY_MIN_LENGTH = 8

# The truth values a boolean checkbox understands. Anything else is not a
# value we are willing to interpret as yes or no.
_TRUTHY = frozenset(
    {
        "yes",
        "y",
        "true",
        "1",
        "authorized",
        "eligible",
        "citizen",
        "permanent resident",
        "able to work",
    }
)
_FALSY = frozenset(
    {
        "no",
        "n",
        "false",
        "0",
        "not authorized",
        "not eligible",
        "unable to work",
        "require sponsorship",
        "requires sponsorship",
    }
)

_LABEL_STRIP = re.compile(r"[\s?:*]+$")
_LABEL_TRIM = re.compile(r"^[\s?:*]+")


def normalize_label(label: str) -> str:
    """The canonical form of a label, used for every field-map lookup.

    Lowercased, whitespace collapsed, and stripped of the decoration a form
    adds to a required field (``Full name:``, ``Full name *``).
    """
    if not label:
        return ""
    collapsed = " ".join(label.split())
    collapsed = _LABEL_TRIM.sub("", collapsed)
    collapsed = _LABEL_STRIP.sub("", collapsed)
    return collapsed.lower()


def lookup_fact_key(label: str) -> str | None:
    """The fact key a label asks for, or ``None`` when it asks for nothing known.

    The lookup has two passes. The first is exact: the normalized label is a
    key of :data:`FIELD_MAP`. The second is a fuzzy pass over the *long* keys
    only, and it fires only when it is unambiguous — the longest matching key
    wins, and a tie means no match at all. A tie is treated as "unknown"
    because a wrong match is a wrong answer, and an unknown question is
    recoverable while a wrong answer is not.
    """
    normalized = normalize_label(label)
    if not normalized:
        return None
    exact = FIELD_MAP.get(normalized)
    if exact is not None:
        return exact

    matches = [key for key in FIELD_MAP if len(key) >= _FUZZY_MIN_LENGTH and key in normalized]
    if not matches:
        return None
    longest = max(len(key) for key in matches)
    winners = [key for key in matches if len(key) == longest]
    if len(winners) != 1:
        return None
    return FIELD_MAP[winners[0]]


def facts_from_profile(profile: CandidateProfile) -> dict[str, str]:
    """The facts a parsed candidate profile actually states.

    The derivation is deterministic and additive. It never infers a fact the
    document does not state: a profile that lists no dates yields no
    ``years_of_experience`` fact, and the question that asks for it becomes
    unresolved rather than "0".
    """
    info = profile.personal_information
    prefs = profile.work_preferences

    facts: dict[str, str] = {}
    for key, value in (
        ("name", info.name),
        ("email", info.email),
        ("phone", info.phone),
        ("location", info.location),
        ("title", info.title),
        ("remote_preference", prefs.remote_preference),
        ("work_authorization", prefs.work_authorization),
        ("min_salary", prefs.min_salary),
    ):
        if value and value.strip():
            facts[key] = value.strip()

    if prefs.employment_types:
        facts["employment_types"] = ", ".join(prefs.employment_types)
    if profile.skills:
        facts["skills"] = ", ".join(profile.skills)

    stated_years = [entry.years for entry in profile.experience if entry.years is not None]
    if stated_years:
        facts["years_of_experience"] = str(sum(stated_years))

    return facts


# --------------------------------------------------------------------------
# The answer rule
# --------------------------------------------------------------------------


class FieldLookup:
    """The field map, as one reviewed namespace.

    The map is the statement of *which questions this agent knows how to
    answer*. It is exposed as a namespace rather than as loose module
    constants so that a reviewer reads it in one place — and so that a test
    can assert on it without reaching into the module internals.
    """

    FIELD_MAP = FIELD_MAP
    FACT_SOURCES = FACT_SOURCES


def _as_facts(profile: ProfileFacts | Mapping[str, str] | None) -> ProfileFacts:
    """Coerce the grounding source into a :class:`ProfileFacts`."""
    if profile is None:
        return ProfileFacts()
    if isinstance(profile, ProfileFacts):
        return profile
    values = {key: value for key, value in profile.items() if isinstance(value, str)}
    return ProfileFacts(values=values)


def _option_match(value: str, options: Sequence[str]) -> str | None:
    """The option that matches *value*, or ``None`` when none does.

    A select or a radio group may only be given a value the page itself
    offers. Choosing a different option would be a fabrication, so a value
    that matches nothing yields no answer at all.
    """
    wanted = normalize_label(value)
    if not wanted:
        return None
    for option in options:
        if normalize_label(option) == wanted:
            return option
    return None


def checkbox_truth(value: str) -> bool | None:
    """Whether *value* means yes or no — ``None`` when it means neither.

    An unrecognized token is not interpreted. "Maybe" is not a "no", and a
    checkbox left in an unknown state is a wrong answer.
    """
    token = normalize_label(value)
    if token in _TRUTHY:
        return True
    if token in _FALSY:
        return False
    return None


def answer_question(
    question: FormQuestion, profile: ProfileFacts | Mapping[str, str] | None
) -> str | None:
    """The grounded answer to *question*, or ``None`` when there is none.

    The answer comes from the candidate's own evidence and nowhere else. A
    question whose label is not in the field map, whose fact has no value, or
    whose value cannot be used by the control (an option that does not exist,
    a checkbox token that is neither yes nor no) is **not** answered.
    """
    key = lookup_fact_key(question.label)
    if key is None:
        return None

    facts = _as_facts(profile)
    value: str | None = None
    for source_key in FACT_SOURCES.get(key, (key,)):
        candidate = facts.get(source_key)
        if candidate:
            value = candidate
            break
    if value is None:
        return None

    if question.kind in {"select", "radio"}:
        if not question.options:
            # A group without options cannot be matched against anything.
            return None
        return _option_match(value, question.options)

    if question.kind == "checkbox":
        if question.options:
            # A checkbox group: the value names the option to tick.
            return _option_match(value, question.options)
        if checkbox_truth(value) is None:
            return None
        return value

    return value


def classify_question(
    question: FormQuestion, profile: ProfileFacts | Mapping[str, str] | None
) -> str:
    """The class of *question*: ``known``, ``mappable`` or ``unknown``."""
    if answer_question(question, profile) is not None:
        return "known"
    if lookup_fact_key(question.label) is None:
        return "unknown"
    return "mappable"


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


def build_form_plan(
    source: Sequence[FormControl] | Iterable[FormControl] | Any,
    facts: ProfileFacts | Mapping[str, str] | None = None,
) -> FormPlan:
    """The plan for one page.

    Args:
        source: The controls of the page. A list of :class:`FormControl` is
            the pure path (unit tests, saved snapshots); anything with a
            ``locator`` attribute is read as a page.
        facts: The grounded facts the answers come from.

    Returns:
        The plan: every question with its class, the answers, the questions
        that must go to a human, and the ones that are simply left alone.
    """
    controls = read_controls(source) if hasattr(source, "locator") else list(source)
    profile = _as_facts(facts)

    questions: list[FormQuestion] = []
    answers: dict[str, str] = {}
    unresolved: list[str] = []
    skipped: list[str] = []

    for control in controls:
        question = FormQuestion(
            label=control.label,
            kind=control.kind,
            required=control.required,
            options=list(control.options),
        )
        value = answer_question(question, profile)
        if value is not None:
            question.classification = "known"
            answers[question.label] = value
        elif lookup_fact_key(question.label) is None:
            question.classification = "unknown"
            unresolved.append(question.label)
        else:
            question.classification = "mappable"
            if question.required:
                # A required field we cannot ground would be a guess.
                unresolved.append(question.label)
            else:
                skipped.append(question.label)
        questions.append(question)

    return FormPlan(
        questions=questions,
        answers=answers,
        unresolved=unresolved,
        skipped=skipped,
    )


# --------------------------------------------------------------------------
# The page reader
# --------------------------------------------------------------------------

# The script that reads one control's accessibility information. It uses the
# DOM's own label association (``element.labels``) — the same relation a
# screen reader uses — and never an id.
_CONTROL_SNAPSHOT_JS = """
(el) => {
  const text = (node) => {
    if (!node) { return ''; }
    const value = node.innerText || node.textContent || '';
    return value.trim();
  };
  const labels = el.labels ? Array.from(el.labels).map(text) : [];
  let groupLabel = '';
  if (el.closest) {
    const fieldset = el.closest('fieldset');
    const legend = fieldset ? fieldset.querySelector('legend') : null;
    groupLabel = legend ? text(legend) : '';
  }
  const options = [];
  if (el.tagName.toLowerCase() === 'select' && el.options) {
    for (const option of Array.from(el.options)) { options.push(text(option)); }
  }
  return {
    labels: labels,
    aria: el.getAttribute('aria-label') || '',
    tag: el.tagName.toLowerCase(),
    type: (el.getAttribute('type') || '').toLowerCase(),
    name: el.name || '',
    required: !!el.required,
    groupLabel: groupLabel,
    options: options,
  };
}
"""

# The input types that are not questions.
_NON_QUESTION_TYPES = frozenset({"hidden", "submit", "button", "image", "reset"})

_INPUT_KINDS = {
    "": "text",
    "text": "text",
    "email": "email",
    "tel": "tel",
    "number": "number",
    "url": "url",
    "password": "password",
    "search": "search",
    "date": "date",
    "file": "file",
    "checkbox": "checkbox",
    "radio": "radio",
}


def _control_kind(tag: str, input_type: str) -> str:
    """The kind of a control, from its tag and type."""
    if tag == "textarea":
        return "textarea"
    if tag == "select":
        return "select"
    return _INPUT_KINDS.get(input_type, "text")


def _own_label(data: Mapping[str, Any]) -> str:
    """The label that belongs to the control itself (not to its group)."""
    labels = data.get("labels") or []
    for label in labels:
        if label and label.strip():
            return label.strip()
    aria = data.get("aria") or ""
    if aria.strip():
        return aria.strip()
    return ""


def read_controls(page: Any) -> list[FormControl]:
    """The visible, answerable controls of a page.

    The page is enumerated structurally — the *set* of controls is found with
    a type selector — but each control is then described by the browser's own
    accessibility information: the DOM's label association, the ``<legend>``
    of its fieldset, the ``<option>`` texts of a select, the ``required``
    attribute. That information is what a person reads, and it is what the
    adapter will use to find the control again.

    Radio buttons and checkboxes that share a ``name`` are one question, not
    several: they are grouped into a single control whose options are the
    individual labels.

    Args:
        page: The page to read. Duck-typed — it needs ``locator``,
            ``count``, ``nth``, ``is_visible`` and ``evaluate``.

    Returns:
        The controls, in document order.
    """
    raw: list[dict[str, Any]] = []
    try:
        locator = page.locator("input, select, textarea")
        for index in range(locator.count()):
            element = locator.nth(index)
            try:
                if not element.is_visible():
                    continue
            except Exception as exc:  # noqa: BLE001 - an unreadable control is skipped
                logger.debug("Control %d could not be checked for visibility: %s", index, exc)
                continue
            try:
                data = element.evaluate(_CONTROL_SNAPSHOT_JS)
            except Exception as exc:  # noqa: BLE001 - an unreadable control is skipped
                logger.debug("Control %d could not be read: %s", index, exc)
                continue
            if not isinstance(data, dict):
                continue
            raw.append(data)
    except Exception as exc:  # noqa: BLE001 - an unreadable page yields no controls
        logger.warning("The page could not be read for form controls: %s", exc)
        return []

    return _group_controls(raw)


def _group_controls(raw: list[dict[str, Any]]) -> list[FormControl]:
    """Turn the raw control snapshots into the controls of the form."""
    controls: list[FormControl] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for data in raw:
        tag = str(data.get("tag") or "")
        input_type = str(data.get("type") or "")
        if tag == "input" and input_type in _NON_QUESTION_TYPES:
            continue

        kind = _control_kind(tag, input_type)
        if kind in {"radio", "checkbox"}:
            name = str(data.get("name") or "")
            groups.setdefault((kind, name), []).append(data)
            continue

        label = _own_label(data)
        options = [str(option) for option in (data.get("options") or [])]
        controls.append(
            FormControl(
                label=label,
                kind=kind,
                required=bool(data.get("required")),
                options=options,
                name=str(data.get("name") or ""),
            )
        )

    for (kind, name), members in groups.items():
        controls.append(_group_control(kind, name, members))

    return controls


def _group_control(kind: str, name: str, members: list[dict[str, Any]]) -> FormControl:
    """One control for a group of radio buttons or checkboxes."""
    own_labels = [_own_label(member) for member in members]
    options = [label for label in own_labels if label]
    group_label = ""
    for member in members:
        candidate = str(member.get("groupLabel") or "").strip()
        if candidate:
            group_label = candidate
            break

    required = any(bool(member.get("required")) for member in members)

    if kind == "radio":
        # A radio group is always a choice between options, so the group's
        # label is the legend; without one, the first option's own label is
        # used and the group is (correctly) not recognisable.
        return FormControl(
            label=group_label or (options[0] if options else ""),
            kind="radio",
            required=required,
            options=options,
            name=name,
        )

    if len(members) > 1:
        # A group of checkboxes: the value names the option to tick.
        return FormControl(
            label=group_label or (options[0] if options else ""),
            kind="checkbox",
            required=required,
            options=options,
            name=name,
        )

    # A single checkbox is a yes/no question about itself.
    return FormControl(
        label=options[0] if options else group_label,
        kind="checkbox",
        required=required,
        options=[],
        name=name,
    )
