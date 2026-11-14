"""The provider's own application contract, as data (WS-32).

Greenhouse documents the application submission endpoint and its field names
in its own published documentation
(https://docs.greenhouse.io/job-board.html, "Application submission"; the
source of record is ``grnhse/greenhouse-api-docs``,
``source/includes/job-board/_applications.md``):

    POST https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{id}
    Authorization: Basic <API_KEY>        # the username IS the key; no password

Two verified facts about that endpoint decide how this module is used.

**The provider does not validate the payload.** Greenhouse says so verbatim:
"Validation for required fields must be done on the client side, as Greenhouse
will not reject applications that are missing required fields." An application
missing a required answer therefore **submits successfully and incompletely**:
the candidate believes they applied, the employer receives a blank, and nothing
anywhere reports an error. That is the failure this module catches, in *our*
payload, before the submit node calls an adapter.

**The credential is the employer's, not ours.** The Basic Auth username is the
hiring company's API key (the endpoint answers 401 without it), so a
third-party agent cannot post an application to a company's board without that
company's cooperation. The field names below are therefore used to *validate
ours*, never to submit. The submission path stays where the project put it:
the browser, with a human in the loop.

The names are a policy table rather than logic, in the shape
``src/jobs/board_metadata.py`` uses: they come from the provider's
documentation, the provider may rename them, and a table is what can be
reviewed and corrected in one place.

**Which adapters the gate covers.** :data:`CONTRACT_ADAPTERS` names the
adapters whose payloads follow the documented names. The local fake ATS is
deliberately **not** among them: its payload is a form-walk summary
(``candidate_name``, not ``first_name``/``last_name``), and its completeness
protection is its own WS-08 form walker, which stops on an unanswered required
question before anything is submitted. An unconditional gate would refuse the
only live submission path. An adapter for a further provider must add one row
to :data:`CONTRACT_ADAPTERS` to be covered.

**Consent is the caller's to supply.** :func:`validate_against_contract`
reports unanswered consent fields only when the caller names them — through
``consent_required``, or by handing over the board's ``schema``, whose own
consent questions are what the operator answers at approval time. The submit
node passes neither, because the form plan that knows the board's questions is
computed at prepare time and is not persisted on the approval row: **consent
reporting is inert in the node** and belongs to callers that hold a schema (the
WS-32 assist pilot fetches one). A missing consent is never reported as a
*missing* field — it is a human's to give, not a defect in the agent's work.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from src.applications.contracts import PreparedApplication

__all__ = [
    "CONSENT_FIELDS",
    "CONTRACT_ADAPTERS",
    "GREENHOUSE_APPLICATION_FIELDS",
    "REQUIRED_FIELDS",
    "RESUME_FIELDS",
    "ContractReport",
    "consent_fields_from_schema",
    "custom_question_fields",
    "validate_against_contract",
]

#: Every field group Greenhouse documents for an application, as data.
#: The address group needs its coordinates as well as the name (the board
#: ignores a location whose ``latitude``/``longitude`` are absent) and the
#: custom questions are named ``question_{id}`` — the shapes a payload has to
#: use, not decoration.
GREENHOUSE_APPLICATION_FIELDS: dict[str, tuple[str, ...]] = {
    "identity": ("first_name", "last_name", "email", "phone"),
    "documents": ("resume", "resume_text", "cover_letter", "cover_letter_text"),
    "address": ("location", "latitude", "longitude", "country_short_name"),
    "consent": (
        "data_compliance[gdpr_processing_consent_given]",
        "data_compliance[gdpr_retention_consent_given]",
        "data_compliance[gdpr_demographic_data_consent_given]",
    ),
    "provenance": ("mapped_url_token", "applicant_ip"),
}

#: The identity fields. Greenhouse does not reject an application that is
#: missing them; we do, before it is submitted.
REQUIRED_FIELDS: tuple[str, ...] = GREENHOUSE_APPLICATION_FIELDS["identity"]

#: The document group's resume requirement: a **file or a text body** is
#: accepted, and the name reported when neither is present is the first of
#: them — the contract's own name for the uploaded document.
RESUME_FIELDS: tuple[str, ...] = ("resume", "resume_text")

#: The documented consent fields. A caller that knows the board requires
#: GDPR consent passes these (or the schema's own consent questions are read
#: instead); the validator answers for whichever it is given.
CONSENT_FIELDS: tuple[str, ...] = GREENHOUSE_APPLICATION_FIELDS["consent"]

#: The adapters whose payloads follow the documented contract, so the submit
#: node may check the assembled payload against it. ``assist-playwright``
#: (WS-32 · Task 5) is listed ahead of its implementation on purpose: it
#: submits to a real board, which is exactly where an incomplete payload is
#: invisible. The local fake ATS is excluded — see the module docstring.
CONTRACT_ADAPTERS: frozenset[str] = frozenset({"greenhouse", "assist-playwright"})

#: The shape of a custom question's field name: ``question_5555``,
#: ``question_2222[]`` (the multipart bracket convention), and the file
#: variants ``question_12349_url`` + ``_filename`` and
#: ``question_12350_content`` + ``_filename``.
_CUSTOM_QUESTION_RE = re.compile(
    r"^question_\d+(?:\[\])?(?:_(?:url|content)(?:_filename)?)?$"
)

#: The label used in the report for the resume requirement. The contract
#: accepts ``resume`` *or* ``resume_text``, and the report names the field the
#: payload would have carried.
_RESUME_FIELD = RESUME_FIELDS[0]


@dataclass(frozen=True)
class ContractReport:
    """What the contract check found in one assembled payload.

    Readable in a log line and assertable in a test, which is why it is a
    dataclass and not a bare tuple.

    ``missing`` is about the payload the provider would *accept anyway*:
    the documented fields it does not answer. ``consent_unanswered`` is a
    different thing and is deliberately not part of ``is_complete`` — an
    unanswered consent is a human's to give at approval time, not a bug the
    agent should fix.
    """

    #: The documented fields the payload does not answer.
    missing: list[str] = field(default_factory=list)
    #: The consent fields the caller named that the payload does not answer.
    consent_unanswered: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Whether the payload answers every documented required field."""
        return not self.missing


def _is_answered(value: Any) -> bool:
    """Whether a value is a real answer rather than a blank.

    Whitespace is not an answer: ``first_name="  "`` is exactly the
    silent-incompleteness the provider permits, so it must read as missing
    here. An absent key and a blank value are the same finding.
    """
    return value is not None and str(value).strip() != ""


def _resume_is_answered(prepared: PreparedApplication) -> bool:
    """Whether the payload carries the resume, as a file or as text."""
    if _is_answered(prepared.resume_path):
        return True
    fields = prepared.prepared_fields or {}
    return any(_is_answered(fields.get(name)) for name in RESUME_FIELDS)


def consent_fields_from_schema(schema: Any | None) -> list[str]:
    """The consent field names the board's own form publishes, in form order.

    Only the questions the schema marks as consent are read
    (:attr:`~src.applications.greenhouse_forms.FormQuestion.needs_consent`):
    an EEO or demographic question arrives in its own block, and the agent
    never answers one. They are the fields a human fills in at approval time,
    so the report says which of them the payload leaves unanswered.

    Returns an empty list when no schema is given.
    """
    if schema is None:
        return []
    fields: list[str] = []
    for question in getattr(schema, "all_questions", None) or []:
        if not getattr(question, "needs_consent", False):
            continue
        for name in getattr(question, "field_names", None) or []:
            text = str(name)
            if text and text not in fields:
                fields.append(text)
    return fields


def custom_question_fields(schema: Any | None) -> dict[str, str]:
    """The form's custom questions, as the contract names them.

    Every question a Greenhouse board publishes carries its own field names,
    and a custom question's name **is** the contract's ``question_{id}`` form
    (``question_69650990``, ``question_69650991[]``). So the mapping announces
    *which* of the form's fields are custom questions — the ones the fixed
    field map has never heard of — and it maps each to itself rather than
    renaming it: the bracket suffix of a multi-select is part of the name the
    POST encoding uses, so stripping it would invent a field the board does
    not publish.

    Returns an empty mapping when no schema is given.
    """
    mapping: dict[str, str] = {}
    if schema is None:
        return mapping
    for question in getattr(schema, "all_questions", None) or []:
        for name in getattr(question, "field_names", None) or []:
            text = str(name)
            if text and _CUSTOM_QUESTION_RE.match(text):
                mapping[text] = text
    return mapping


def validate_against_contract(
    prepared: PreparedApplication,
    *,
    schema: Any | None = None,
    consent_required: Iterable[str] = (),
) -> ContractReport:
    """Check an assembled payload against the provider's documented contract.

    The check is on the payload **as it is**: a documented name the payload
    does not carry is reported by that name, and nothing is derived from
    anything else. Splitting a full name into ``first_name``/``last_name``
    would be inventing candidate data, which the project forbids — an
    incomplete payload is reported, not repaired.

    Args:
        prepared: The payload the adapter would submit.
        schema: The board's published form schema, when the caller has one.
            Its own consent questions are added to the consent list.
        consent_required: The consent fields the caller knows the board asks
            for. These are reported separately from ``missing`` and never
            make the payload incomplete.

    Returns:
        A :class:`ContractReport`. ``is_complete`` is about the documented
        required fields only.
    """
    fields = prepared.prepared_fields or {}

    missing = [name for name in REQUIRED_FIELDS if not _is_answered(fields.get(name))]
    if not _resume_is_answered(prepared):
        missing.append(_RESUME_FIELD)

    required_consent = [str(name) for name in consent_required if str(name)]
    for name in consent_fields_from_schema(schema):
        if name not in required_consent:
            required_consent.append(name)
    consent_unanswered = [name for name in required_consent if not _is_answered(fields.get(name))]

    return ContractReport(missing=missing, consent_unanswered=consent_unanswered)
