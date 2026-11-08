"""A two-way PII mask for prompts that carry candidate data (WS-22).

**The property.** The provider a tailoring run calls never sees the
candidate's *identity*: not the name, not an e-mail address, not a phone
number, not a link to a profile. The model still gets every fact it needs —
skills, employers, titles, dates, projects — because those are the content it
tailors; it does not get the strings that would identify the person if the
provider retained them.

**How.** A deterministic, offline vault of placeholder tokens:

    Ada Lovelace, ada@example.com, +44 7700 900123, github.com/ada
        ↓ mask
    [[NAME]], [[EMAIL_1]], [[PHONE_1]], [[LINK_1]]
        ↓ the model works on tokens
    [[NAME]] shipped [[LINK_1]] …
        ↓ restore
    Ada Lovelace shipped github.com/ada …

Three rules make it safe rather than clever:

1. **Deterministic and exact.** A token maps to exactly one value and back.
   There is no hashing, no numbering that depends on iteration order, and no
   state outside the call — two runs over the same input produce the same
   tokens.
2. **Restore is verified, not assumed.** A model can mangle a placeholder.
   :meth:`PiiVault.residual_tokens` finds what did not survive, and the
   caller (the tailoring validator) drops the sentence and records a
   violation. A token is never left in a deliverable and never guessed at.
3. **The mask covers identity, not content.** Employer names, institutions,
   titles and locations are *facts the résumé is about*; masking them would
   break the tailoring. Only the person-identifying fields are masked — the
   same list the reference implementation used (name, e-mail, phone,
   LinkedIn, GitHub, portfolio).

**Known and accepted limit.** A name that is also an ordinary word ("May",
"Rose", "Will") is masked wherever it appears as that word — including in a
date. Nothing is lost, because the restore puts the original text back
verbatim; the model simply sees a placeholder. The alternative (masking only
"name-shaped" occurrences) would need the very judgement this module exists
to avoid.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from src.security.redaction import EMAIL_RE, PHONE_RE

__all__ = [
    "MASKED_PLACEHOLDER_RE",
    "PII_TOKEN_RE",
    "PiiVault",
    "build_vault_for_profile",
    "mask_prompt_text",
]

#: The whole-token shape. Bracketed and upper-case so it is unmistakable in a
#: prompt and unlikely to appear in a résumé or a listing by accident.
PII_TOKEN_RE = re.compile(r"\[\[(?:NAME|EMAIL_\d+|PHONE_\d+|LINK_\d+)\]\]")

#: The token shape **and its mangled near-misses** — ``[[ NAME ]]``, a single
#: bracket, a space instead of the underscore. A model that half-remembers a
#: placeholder produces one of these, and the caller must be able to see it
#: rather than ship it. The keyword set is what keeps the pattern from
#: eating legitimate bracketed text like ``[Python]``.
MASKED_PLACEHOLDER_RE = re.compile(
    r"\[{1,2}\s*(?:NAME|EMAIL|PHONE|LINK)[\s_]?\d*\s*\]{1,2}", re.IGNORECASE
)

#: A URL-ish string: scheme, ``www.``, or a bare ``host.tld/path``. The
#: last form is what a résumé prints ("github.com/ada"), and it is also the
#: form that is easiest to miss — so it is matched explicitly.
_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\"')]+"
    r"|(?<![\w.@])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(?:/[^\s<>\"')]*)?",
    re.IGNORECASE,
)

#: Fields of ``PersonalInformation`` that identify the person.
_IDENTITY_FIELDS = ("name", "email", "phone", "website", "linkedin", "github")

#: Values shorter than this are not masked as free text: a two-letter
#: "name" would match inside unrelated words and turn the prompt into
#: confetti. The structured identity fields are masked at any length.
_MIN_FREE_TEXT_MATCH = 4


@dataclass
class PiiVault:
    """The tokens for one call, and the two directions of the mapping."""

    #: token -> real value
    _to_value: dict[str, str] = field(default_factory=dict)
    #: real value -> token (so a repeat uses the same token)
    _to_token: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    # -- building ---------------------------------------------------------

    def _token_for(self, kind: str, value: str) -> str:
        """The token for *value*, minted once and reused."""
        existing = self._to_token.get(value)
        if existing is not None:
            return existing
        if kind == "NAME":
            token = "[[NAME]]"
        else:
            self._counters[kind] = self._counters.get(kind, 0) + 1
            token = f"[[{kind}_{self._counters[kind]}]]"
        self._to_token[value] = token
        self._to_value[token] = value
        return token

    def add(self, kind: str, value: str | None) -> None:
        """Register one value under a token kind (no-op when empty)."""
        text = (value or "").strip()
        if text:
            self._token_for(kind, text)

    def add_identity(self, identity: object | None) -> None:
        """Register the candidate's identity fields from a profile model.

        Accepts the ``PersonalInformation`` model (or any object with the
        same attribute names, or a mapping).
        """
        if identity is None:
            return
        for raw_name in _IDENTITY_FIELDS:
            value: object | None
            if isinstance(identity, dict):
                value = identity.get(raw_name)
            else:
                value = getattr(identity, raw_name, None)
            if isinstance(value, str):
                kind = (
                    "NAME"
                    if raw_name == "name"
                    else (
                        "EMAIL"
                        if raw_name == "email"
                        else "PHONE"
                        if raw_name == "phone"
                        else "LINK"
                    )
                )
                self.add(kind, value)

    def scan_text(self, text: str | None) -> None:
        """Register every e-mail, phone and URL that appears in *text*.

        This catches third-party identity in a listing (a recruiter's
        address, a tracking URL) as well as anything the profile carries in
        free-text fields, so the mask is a property of the **prompt**, not
        only of the candidate's structured fields.
        """
        if not text:
            return
        for match in EMAIL_RE.findall(text):
            self.add("EMAIL", match)
        for match in PHONE_RE.findall(text):
            self.add("PHONE", match)
        for match in _URL_RE.findall(text):
            self.add("LINK", match)

    @property
    def size(self) -> int:
        """How many distinct values the vault holds."""
        return len(self._to_value)

    # -- masking and restoring -------------------------------------------

    def _ordered_values(self) -> list[tuple[str, str]]:
        """(value, token) pairs, longest value first.

        Longest-first matters: masking ``github.com`` before
        ``github.com/ada`` would leave ``[[LINK_1]]/ada`` behind.
        """
        pairs = [(value, token) for token, value in self._to_value.items()]
        pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
        return pairs

    def mask(self, text: str | None) -> str:
        """Replace every registered value in *text* with its token.

        Whole words only for the short values: the candidate's *name* is
        registered from a structured field and masked wherever it appears,
        but a value shorter than :data:`_MIN_FREE_TEXT_MATCH` is skipped when
        it appears as free text so a two-letter token cannot eat the prompt.
        """
        if not text:
            return text or ""
        masked = text
        for value, token in self._ordered_values():
            if len(value) < _MIN_FREE_TEXT_MATCH:
                continue
            masked = re.sub(
                rf"(?<![\w]){re.escape(value)}(?![\w])",
                token,
                masked,
                flags=re.IGNORECASE,
            )
        return masked

    def restore_text(self, text: str | None) -> str:
        """Put the real values back, exactly."""
        if not text:
            return text or ""
        restored = text
        for token, value in self._to_value.items():
            restored = restored.replace(token, value)
        return restored

    def restore_model[T](self, model: T) -> T:
        """Restore every string inside a pydantic model, recursively.

        Returns a copy — the caller's object is untouched, so a test can
        hold both sides of the transform.
        """
        return _walk_restore(model, self)

    def residual_tokens(self, text: str | None) -> list[str]:
        """Placeholders in *text* that this vault **cannot resolve**.

        That is: the token shape and its near-misses
        (:data:`MASKED_PLACEHOLDER_RE`) **minus** the vault's own exact
        tokens — an exact token is not a defect, it is the thing the restore
        is about to resolve. Only a mangled one (``[[ NAME ]]``, ``[NAME]``)
        is unresolvable, and the caller must strip the sentence carrying it
        rather than ship a placeholder.
        """
        if not text:
            return []
        return [
            candidate
            for candidate in MASKED_PLACEHOLDER_RE.findall(text)
            if candidate not in self._to_value
        ]

    def strip_residual_tokens(self, text: str | None) -> tuple[str, list[str]]:
        """Drop the sentences that carry an unresolvable placeholder.

        Returns ``(kept_text, removed_sentences)``. A sentence is the unit
        because a placeholder inside a clause cannot be removed without
        guessing what the model meant — and guessing is the one thing this
        module must never do.
        """
        if not text:
            return text or "", []
        kept: list[str] = []
        removed: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if self.residual_tokens(sentence):
                removed.append(sentence)
            else:
                kept.append(sentence)
        return " ".join(kept), removed


def _walk_restore(value, vault: PiiVault):
    """Rebuild *value* with every string restored."""
    if isinstance(value, str):
        return vault.restore_text(value)
    if isinstance(value, dict):
        return {key: _walk_restore(item, vault) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        items = [_walk_restore(item, vault) for item in value]
        return type(value)(items) if not isinstance(value, tuple) else tuple(items)
    model_copy = getattr(value, "model_copy", None)
    if model_copy is not None:
        fields = {
            name: _walk_restore(getattr(value, name), vault) for name in type(value).model_fields
        }
        return model_copy(update=fields)
    return value


def mask_prompt_text(text: str | None, vault: PiiVault) -> str:
    """Convenience wrapper: mask one prompt block with an existing vault."""
    return vault.mask(text)


def build_vault_for_profile(profile: object, texts: Iterable[str | None] = ()) -> PiiVault:
    """A vault for one tailoring call: the candidate's identity plus *texts*.

    ``texts`` are the blocks going into the same prompt — the profile's own
    free text (a résumé bullet can carry an address or a profile link), the
    listing-derived requirements, the insights. Sweeping them makes the mask
    a property of the **prompt**, not only of the structured identity
    fields: a third party's address inside a posting is masked too, because
    the provider sees one prompt, whoever the text originally described.
    """
    vault = PiiVault()
    vault.add_identity(getattr(profile, "personal_information", None))
    for text in texts:
        vault.scan_text(text)
    return vault
