"""Job source contracts and normalization models.

WS-12: the :class:`JobListing` contract is where every listing from every
source enters the system, so it is where the **untrusted-text controls**
live. Two of them:

- **Neutralization.** A board's text is HTML (or claims to be plain text
  and is not). It is stored, returned by the API, put in front of the
  model, and written into the rendered resume. Neutralizing it here means
  no adapter can forget to, and no future adapter can introduce a hole:
  the markup is gone before the text is ever stored.
- **Length caps.** A listing is a job posting, not a document. A 50 MB
  description would be stored, embedded, and put in a prompt.

Both are applied in one place on purpose. A per-adapter sanitizer is a
control that has to be remembered at every call site; a contract-level one
is a control that cannot be forgotten.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from src.security.html import neutralize_html


class JobListing(BaseModel):
    """Normalized job listing from any source."""

    id: str
    source: str
    source_job_id: str | None = None
    title: str
    company: str
    description: str | None = None
    location: str | None = None
    remote_policy: str | None = None
    employment_type: str | None = None
    salary: str | None = None
    currency: str | None = None
    seniority: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    experience_requirements: str | None = None
    education_requirements: str | None = None
    application_url: str | None = None
    company_url: str | None = None
    posted_at: str | None = None
    metadata: dict = Field(default_factory=dict)

    # -- WS-12: the untrusted-text controls --------------------------------

    @field_validator("description", mode="before")
    @classmethod
    def _neutralize_description(cls, value: object) -> object:
        """Neutralize the description and cap its length.

        The cap is applied after neutralization, so the stored text is the
        text that was actually measured. A description that is mostly
        markup shrinks to something sensible before it is truncated.

        The whitespace is **preserved**: a board's plain-text field is
        stored as the board wrote it, line breaks and all, so the text the
        candidate reads is the text the employer published.
        """
        if not isinstance(value, str):
            return value
        from src.security.limits import get_limits

        limits = get_limits()
        text = neutralize_html(value, collapse_whitespace=False)
        if len(text) > limits.max_description_chars:
            text = text[: limits.max_description_chars]
        return text or None

    @field_validator("title", mode="before")
    @classmethod
    def _neutralize_title(cls, value: object) -> object:
        """Neutralize a board-supplied title and cap its length.

        A title of ``<script>…</script>`` is the same execution vector as
        a description, in a field that is more likely to be rendered in a
        list than a description is.
        """
        if not isinstance(value, str):
            return value
        from src.security.limits import get_limits

        limits = get_limits()
        text = neutralize_html(value)
        if len(text) > limits.max_title_chars:
            text = text[: limits.max_title_chars]
        return text

    @field_validator("company", mode="before")
    @classmethod
    def _neutralize_company(cls, value: object) -> object:
        """Neutralize a board-supplied company name and cap its length."""
        if not isinstance(value, str):
            return value
        from src.security.limits import get_limits

        limits = get_limits()
        text = neutralize_html(value)
        if len(text) > limits.max_company_chars:
            text = text[: limits.max_company_chars]
        return text

    @field_validator("application_url", "company_url", mode="before")
    @classmethod
    def _check_url_scheme(cls, value: object) -> object:
        """Keep only the URLs a browser may follow.

        WS-15: the application URL is the one field in a listing that the
        console turns into a **link**. A board that published
        ``javascript:…`` or ``data:text/html,…`` would be publishing an
        instruction to the operator's browser, and a hostile board that
        publishes ``https://attacker.example/phish`` is the ordinary
        phishing case that a scheme check cannot stop — but the scheme is
        the half that is cheap to close, and it is closed at the contract,
        so no adapter can forget it.

        A URL that is not ``http`` or ``https`` is **dropped**, not
        rewritten: a listing without an application link is a listing the
        operator cannot apply to from the console, which is a smaller
        problem than a link that runs code.
        """
        if not isinstance(value, str):
            return value
        from src.security.allowlist import has_allowed_scheme

        candidate = value.strip()
        if not candidate:
            return None
        if not has_allowed_scheme(candidate):
            return None
        return candidate


class JobSource(Protocol):
    """Abstract interface for job retrieval sources."""

    async def search(self, query: str, location: str | None = None) -> list[JobListing]: ...

    async def get_job(self, job_id: str) -> JobListing | None: ...
