"""Fill native fields of one prepared Greenhouse review. No submit-capable walker."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

from playwright.sync_api import ElementHandle, Locator, Page

from src.applications.assist_adapter import AssistAdapter, split_candidate_name
from src.applications.greenhouse_adapter import parse_greenhouse_job_url
from src.applications.posting_form import PostingForm, PostingQuestion, validated_answer
from src.security.allowlist import assert_job_url_allowed
from src.security.page_guards import inspect_page
from src.security.permissions import CapabilityLevel


class FillGrant(Protocol):
    """Only the claimed, same-revision snapshot; never a path or a CLI-supplied identity."""

    owner_id: str
    application_id: str
    job_url: str
    full_name: str | None
    email: str | None
    phone: str | None
    resume_name: str
    resume_bytes: bytes
    form: PostingForm


FillStatus = Literal[
    "handoff",
    "declined",
    "unsafe_page",
    "challenge",
    "closed",
    "no_form",
    "no_supported_fields",
    "stopped",
]


@dataclass(frozen=True)
class FillOutcome:
    """Confirmed fills and remaining review questions, not a submission result."""

    status: FillStatus
    filled: int
    skipped: int


_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}
_APPLICATION_FORM = "form:is(#application-form, #application_form, #job-application-form)"
_RESUME_LABEL = re.compile(
    r"^(?:(?:upload|attach) (?:your )?)?(?:r[eé]sum[eé](?:\s*/\s*cv)?|cv(?:\s*/\s*r[eé]sum[eé])?"
    r"|curriculum vitae)\s*\*?$",
    re.IGNORECASE,
)
_MIME = {
    "pdf": "application/pdf",
    "txt": "text/plain",
    "md": "text/markdown",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_TIMEOUT = 1500  # A disappearing field stops the run. Never retry on another element.


def _target(url: str) -> tuple[str, str, str]:
    try:
        parts = urlsplit(url)
        ids = parse_greenhouse_job_url(url)
        if (
            not ids
            or not ids[1].isascii()
            or parts.scheme != "https"
            or parts.netloc not in _HOSTS
            or parts.path not in {f"/{ids[0]}/jobs/{ids[1]}", f"/{ids[0]}/jobs/{ids[1]}/"}
            or "\\" in url
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url)
        ):
            raise ValueError
        assert_job_url_allowed(url)
        return parts.netloc, *ids
    except (ValueError, TypeError, PermissionError):
        raise ValueError("Not a supported Greenhouse job URL.") from None


def review_domain(job_url: str) -> str:
    """Only a validated canonical hostname is suitable for the operator prompt."""
    return _target(job_url)[0]


def same_review_posting(url: str, review_url: str) -> bool:
    """True only for the reviewed board token and job id, on a canonical host.

    The helper's network guard uses this to block navigation to a different
    posting, a look-alike host, or a path that merely prefixes the reviewed id.
    """
    try:
        return _target(url) == _target(review_url)
    except ValueError:
        return False


def _wording(label: str) -> str:
    return " ".join(label.split()).removesuffix("*").strip()


def _field(form: Locator, question: PostingQuestion) -> ElementHandle | None:
    words = _wording(question.label).split()
    name = re.compile(r"^\s*" + r"\s+".join(map(re.escape, words)) + r"\s*\*?\s*$")
    # Count BEFORE filtering by kind/visibility: duplicate labels aren't a mapping.
    matches = form.get_by_label(name).element_handles()
    if len(matches) != 1:
        return None
    field = matches[0]
    if not field.is_visible() or not field.is_enabled():
        return None
    if not field.evaluate("""e => e.form === e.closest('form') && !e.readOnly &&
        !e.closest('[inert], [role=combobox], [aria-haspopup], [aria-autocomplete], '
        + '[aria-controls], [aria-disabled=true], [aria-readonly=true], [aria-hidden=true]') &&
        !e.hasAttribute('role') && !e.hasAttribute('list')"""):
        return None
    return field


def _select(field: ElementHandle, question: PostingQuestion) -> bool:
    answer = validated_answer(question, question.answer)
    values = [answer] if isinstance(answer, str) else answer
    published = {o.value: o.label for o in question.options}
    labels = [published[value] for value in values]
    options = field.evaluate("""e => Array.from(e.options, o => ({label: o.label,
        value: o.value, unavailable: o.matches(':disabled') || !!o.closest('[hidden]')}))""")
    actual = [o["label"] for o in options if o["value"] or o["label"] in published.values()]
    if (
        len(set(published.values())) != len(question.options)
        or Counter(actual) != Counter(published.values())
        or any(o["unavailable"] and o["label"] in labels for o in options)
    ):
        return False
    field.select_option(label=labels, timeout=_TIMEOUT)
    return True


def _write_field(
    form: Locator, question: PostingQuestion, grant: FillGrant, contact: dict[str, str | None]
) -> bool:
    kind = question.kind
    if kind == "employer" or (kind not in {"resume", "contact"} and question.answer is None):
        return False
    field = _field(form, question)
    if field is None:
        return False
    tag, input_type = field.evaluate("e => [e.localName, e.type]")
    if kind == "resume":
        if (
            tag != "input"
            or input_type != "file"
            or not _RESUME_LABEL.fullmatch(question.label)
            or form.get_by_label(_RESUME_LABEL).and_(form.locator("input[type=file]")).count() != 1
            or not isinstance(grant.resume_bytes, bytes)
            or not grant.resume_bytes
        ):
            return False
        ext = grant.resume_name.rpartition(".")[2].lower()
        if ext not in _MIME or any(c in grant.resume_name for c in "\\/:"):
            return False
        # FilePayload, never a filesystem path; don't transmit a private local filename.
        field.set_input_files(
            {"name": f"resume.{ext}", "mimeType": _MIME[ext], "buffer": grant.resume_bytes},
            timeout=_TIMEOUT,
        )
        return True
    if kind in {"select", "multiselect"}:
        if tag != "select" or input_type != (
            "select-one" if kind == "select" else "select-multiple"
        ):
            return False
        return _select(field, question)
    if kind == "contact":
        key = question.field_name
        allowed = {"text", {"email": "email", "phone": "tel"}.get(key, "text")}
        if tag != "input" or input_type not in allowed:
            return False
        text = contact.get(key)
    else:
        if (kind, tag, input_type) not in {
            ("text", "input", "text"),
            ("textarea", "textarea", "textarea"),
        }:
            return False
        text = validated_answer(question, question.answer)
    if not isinstance(text, str) or not text.strip():
        return False
    field.fill(text, timeout=_TIMEOUT)
    return True


def fill_review_page(page: Page, grant: FillGrant, *, confirmed: bool) -> FillOutcome:
    """Use an already-open page after explicit human confirmation. Never navigate or click.

    Only ``handoff`` means the current page is suitable for a person to finish.
    The caller owns this page and must close it for every other outcome.
    """
    questions = grant.form.questions
    filled = 0

    def result(status: FillStatus) -> FillOutcome:
        return FillOutcome(status, filled, len(questions) - filled)

    if confirmed is not True:
        return result("declined")
    try:
        AssistAdapter().require_capability(CapabilityLevel.PREPARE)
        expected = _target(grant.job_url)
        if grant.form.state != "available":
            return result("no_form")
        parts = split_candidate_name(grant.full_name)
        contact = {
            "name": grant.full_name,
            "first_name": parts[0] if parts else None,
            "last_name": parts[1] if parts else None,
            "email": grant.email,
            "phone": grant.phone,
        }
        labels = Counter(_wording(q.label) for q in questions)
        form = page.locator(f"{_APPLICATION_FORM}:visible")
        for question in questions:
            if _target(page.url) != expected:
                return result("unsafe_page")
            if inspect_page(page):
                return result("challenge")
            if form.count() != 1 or page.locator("form:visible").count() != 1:
                return result("no_form")
            if labels[_wording(question.label)] == 1 and _write_field(
                form, question, grant, contact
            ):
                filled += 1
        return result("handoff" if filled else "no_supported_fields")
    except Exception:  # noqa: BLE001 - browser/locator failures can contain private DOM or values; show only a safe status
        return result("stopped")
