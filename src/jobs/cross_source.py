"""Cross-source identity for a posting (WS-26 Phase 2).

``src/jobs/deduplicate.py`` answers "is this the same row?" and every one of
its keys includes ``job.source`` — which is exactly right, because a source's
own rows must never collapse into each other. It just does not answer "is this
the same *posting*?", and the registry's docstring claimed it did.

This module answers the second question. The same posting published by two
providers (a Greenhouse board and the company's Ashby board, most often) has
one identity here, and :func:`merge_cross_source` collapses those rows into
one — keeping the **first-seen** source's canonical id, because §3.4 makes the
per-source key the identity and this key only a merge key.

Two deliberate limits, both from the spec and both measured:

* **A fuzzy match is not attempted.** §3.2 proposes MinHash clustering for
  near-duplicates ("Senior Backend Engineer" vs "Sr. Backend Engineer"). On
  the live 8,558-listing corpus there are **zero** cross-source groups under
  three normalization strengths (exact, punctuation-stripped, and
  company-suffix/title-abbreviation normalized), so there is no duplicate for
  a fuzzy matcher to collapse — and merging two postings that are merely
  similar is a fabrication of identity. Unbuilt pending evidence.
* **Nothing is inferred.** A listing with no company or no title is unkeyable
  and is passed through untouched: a merge asserts two rows are one posting,
  and a listing that states neither cannot support that assertion.
"""

from __future__ import annotations

import hashlib
import re

from src.jobs.contracts import JobListing

__all__ = [
    "COMPLETENESS_FIELDS",
    "cross_source_key",
    "field_completeness",
    "merge_cross_source",
]

#: The fields that count toward a listing's completeness score (§3.3).
#: These are the WS-23 fields a board either publishes or does not, so the
#: score measures the same thing the corpus's field-population work does.
COMPLETENESS_FIELDS: tuple[str, ...] = (
    "description",
    "location",
    "remote_policy",
    "employment_type",
    "salary",
    "currency",
    "seniority",
    "experience_requirements",
    "education_requirements",
)

#: The keys of ``extra_metadata`` a cross-source merge may copy.
#:
#: WS-26 §3.1 says to merge ``extra_metadata``, and almost all of it is the
#: informational payload a board publishes (``team``, ``department``,
#: ``category``, ``salary_text``, ``secondary_locations``, ``country``,
#: ``all_locations``). **``updated_at`` is the exception, and it is not
#: negotiable.** It is not information about the posting; it is the gap's own
#: per-source change stamp, and ``registry._stored_update_stamps`` reads it
#: back per *source* to decide what the delta refresh must re-fetch. Copying
#: another provider's stamp into the survivor would make one source's bookkeeping
#: carry another's timestamp — so the owner's next refresh either re-fetches
#: every listing forever or, worse, reads a foreign stamp as "unchanged" and
#: silently misses a real edit. The stamp belongs to whoever owns the row id.
_MERGEABLE_METADATA_KEYS: tuple[str, ...] = (
    "team",
    "department",
    "category",
    "salary_text",
    "secondary_locations",
    "all_locations",
    "country",
)

#: Metadata keys a merge must never carry across sources.
_METADATA_STAMP_KEYS: frozenset[str] = frozenset({"updated_at"})

#: The order a merge copies fields in. Identity and provenance are excluded
#: on purpose: they belong to the survivor.
_MERGEABLE_FIELDS: tuple[str, ...] = COMPLETENESS_FIELDS + (
    "required_skills",
    "preferred_skills",
    "company_url",
    "posted_at",
)

#: A trailing legal-entity suffix is not part of a company's name. "Acme Inc."
#: and "Acme" are one employer publishing under two spellings.
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(inc|llc|ltd|limited|corp|corporation|gmbh|plc|co|company|holdings|group)\b\.?$"
)

#: Everything that is not a letter, a digit or a space.
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(value: str | None, *, strip_legal_suffix: bool = False) -> str:
    """The comparison form of a free-text field.

    Casefolded, punctuation removed, whitespace collapsed. A company name
    additionally loses a trailing legal-entity suffix, because the suffix is
    the publishing entity's paperwork rather than part of the name a reader
    recognizes.
    """
    if not value:
        return ""
    text = _NON_ALNUM_RE.sub(" ", str(value).casefold())
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if strip_legal_suffix:
        # Apply twice: "Acme Holdings Inc." carries two suffixes.
        for _ in range(2):
            stripped = _LEGAL_SUFFIX_RE.sub("", text).strip()
            if stripped == text:
                break
            text = stripped
    return text


def cross_source_key(job: JobListing) -> str | None:
    """The identity a posting has regardless of which provider published it.

    ``sha256(normalize(company) | normalize(title) | normalize(location))``
    per WS-26 §3.1. Returns ``None`` when the listing states no company or no
    title — an unkeyable listing is never merged.

    The location is a real part of the key, and a missing location is its own
    value: "no location stated" is not the same claim as "London", and
    collapsing the two would merge an on-site role with a remote one.
    """
    company = _normalize(job.company, strip_legal_suffix=True)
    title = _normalize(job.title)
    if not company or not title:
        return None
    location = _normalize(job.location)
    payload = f"{company}\x1f{title}\x1f{location}"
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def field_completeness(job: JobListing) -> int:
    """How many of the WS-23 fields this listing actually fills.

    §3.3's precedence rule needs a comparable number, and this is it: the
    count of populated fields plus the size of the skill lists. It is a
    *volume* measure on purpose — it says which of two rows carries more of
    what the corpus wants, and it does not try to judge which value is
    "right", because nothing in the data can answer that.
    """
    score = 0
    for name in COMPLETENESS_FIELDS:
        value = getattr(job, name, None)
        if isinstance(value, str):
            if value.strip():
                score += 1
        elif value:
            score += 1
    # Skills are a list, so their contribution is their size — a listing with
    # eight required skills tells the corpus more than one with a single tag.
    score += len(job.required_skills or [])
    score += len(job.preferred_skills or [])
    return score


def merge_cross_source(jobs: list[JobListing]) -> list[JobListing]:
    """Collapse the same posting published by different sources.

    The first listing of a group survives and keeps its ``id``, ``source``,
    ``source_job_id`` and position in the returned list. Its **data** fields
    are filled from any later listing of the group that scores strictly
    higher on :func:`field_completeness` (§3.3), and a tie keeps the
    first-seen row's value.

    A field the survivor already states is never blanked by a thinner
    listing: the merge fills gaps and upgrades the source of a value, it
    does not empty one.

    Listings from the **same** source are never merged, even when their
    cross-source keys match — the per-source identity is
    ``src/jobs/deduplicate.py``'s, and this function does not second-guess
    it.

    The input listings are not mutated.
    """
    survivors: list[JobListing] = []
    #: key -> index in ``survivors``.
    positions: dict[str, int] = {}
    #: key -> the completeness score of the row currently holding the slot.
    scores: dict[str, int] = {}
    #: key -> the source that owns the slot (same-source rows never merge).
    owners: dict[str, str] = {}

    for job in jobs:
        key = cross_source_key(job)
        if key is None:
            # Unkeyable: it cannot be asserted to be the same posting as
            # anything, so it is always its own row.
            survivors.append(job)
            continue

        index = positions.get(key)
        if index is not None and owners.get(key) != job.source:
            # Two rules, in this order, because they answer different
            # questions. §3.3 decides **which value wins where both state
            # one**: the richer listing's. But a field only one of them
            # states is not a disagreement at all — it is a gap, and filling
            # it is free and correct regardless of which row is richer.
            richer = field_completeness(job) > scores.get(key, -1)
            survivors[index] = _merge_into(
                survivors[index],
                job,
                overwrite=richer,
            )
            scores[key] = max(scores.get(key, -1), field_completeness(job))
            continue

        if index is not None:
            # Same source, same key: a per-source duplicate. It keeps its own
            # row here and `deduplicate` is what collapses it.
            survivors.append(job)
            continue

        positions[key] = len(survivors)
        scores[key] = field_completeness(job)
        owners[key] = job.source
        survivors.append(job)

    return survivors


def _merge_into(identity: JobListing, data: JobListing, *, overwrite: bool) -> JobListing:
    """``identity``'s id and provenance, carrying ``data``'s values.

    A string field is copied when ``data`` states one and the identity row
    does not — a gap is filled whatever the completeness scores say. When
    *both* state one, ``overwrite`` decides whether ``data``'s wins: that is
    §3.3's precedence rule, and it is only consulted for a real disagreement.

    A value is never cleared. A list (the skills) is replaced only when the
    identity's is empty, or when ``overwrite`` is set and ``data`` states one
    — and even then only with a list that is actually longer, because
    replacing the survivor's own eight skills with the other row's one tag is
    a downgrade dressed as a precedence rule.

    ``extra_metadata`` is merged by **known informational key**, and the
    per-source change stamp is excluded (see :data:`_MERGEABLE_METADATA_KEYS`).
    """
    merged = identity.model_copy(deep=True)
    for name in _MERGEABLE_FIELDS:
        incoming = getattr(data, name, None)
        current = getattr(merged, name, None)
        if isinstance(incoming, str):
            if not incoming.strip():
                continue
            current_stated = isinstance(current, str) and bool(current.strip())
            if not current_stated or overwrite:
                setattr(merged, name, incoming)
        elif incoming:
            current_size = len(current) if current else 0
            if len(incoming) > current_size and (not current or overwrite):
                setattr(merged, name, incoming)

    merged.metadata = _merged_metadata(identity.metadata, data.metadata, overwrite=overwrite)
    return merged


def _merged_metadata(
    current: dict | None,
    incoming: dict | None,
    *,
    overwrite: bool,
) -> dict:
    """The survivor's metadata, filled from the other rows of its group.

    Only the known informational keys travel, and a key the survivor already
    carries is kept unless ``overwrite`` says the incoming row is the richer
    one — the same rule the ordinary fields follow. Everything else in
    ``extra_metadata`` (including the change stamp, and anything a future
    adapter adds for its own bookkeeping) stays with the row that owns it.
    """
    merged = dict(current or {})
    source = incoming or {}
    for key in _MERGEABLE_METADATA_KEYS:
        if key in _METADATA_STAMP_KEYS:  # defensive: the two sets must not overlap
            continue
        value = source.get(key)
        if value is None or value == "" or value == []:
            continue
        if key not in merged or merged.get(key) in (None, "", []) or overwrite:
            merged[key] = value
    return merged
