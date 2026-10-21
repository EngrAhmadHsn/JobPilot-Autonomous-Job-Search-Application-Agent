"""Fake-job and spam screening for ingested listings (WS-12).

A job board is a write surface anyone can post to. A hostile or simply
degraded board can return thousands of machine-generated "listings" — SEO
filler, recruiting bait, or an attempt to exhaust this process's embedding
budget. Each *unique* listing is an embedding **cache miss**: it costs a
model call, a cache row, a vector, and a corpus slot, while being worth
nothing to a candidate who will never search for it.

That is the flood this module defends against. The attack is not a
crash — it is a **starvation**: the flood spends the provider's daily
quota and fills the cache, so the legitimate listings that arrive later
never get embedded, never get cached, and never become searchable. The
victim is cache *read* availability, not just write throughput.

The screen is deliberately **deterministic**, in the same spirit as
:mod:`src.security.injection`: a poisoned listing must not be able to argue
its way past the filter, and the decision must be reproducible and
explainable from the listing alone.

Three signals, in increasing order of confidence:

1. **Token stuffing** — one token occupies an implausible share of the
   description ("crypto crypto crypto ..."). Real postings are prose.
2. **Link farming** — a high density of URLs relative to the text.
3. **Body-fingerprint collision** — the *same* description text reappearing
   under a different title or company. This is the signature of a generated
   flood: the board serves one body under thousands of titles. The
   fingerprint is computed over the **description alone**, so a flood that
   varies the title and the company is still caught.

A listing is dropped only when a signal is unambiguous. Screening is
**advisory, not authoritative**: the caller decides what to admit, and every
drop is recorded with its reason so the decision is auditable. Nothing here
invents data — a screened listing is simply not admitted, and the listing
it was based on remains visible in the source.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlparse

from src.jobs.contracts import JobListing

__all__ = [
    "SpamVerdict",
    "body_fingerprint",
    "screen_listing",
    "screen_listings",
]

#: A single token occupying more than this share of the description's
#: tokens is stuffing rather than prose.
_STUFFING_RATIO = 0.25

#: The minimum number of tokens before the stuffing ratio means anything.
#: A short posting legitimately repeats a key term.
_STUFFING_MIN_TOKENS = 40

#: More than this many URLs in a description is a link farm.
_MAX_LINKS = 8

#: A description with fewer than this many words cannot be link-farmed.
_LINK_RATIO_MIN_WORDS = 60

#: The share of a description's words that may be links before the
#: description reads as a link farm rather than as prose with a link in
#: it. A real posting mentions a company site and maybe two postings; a
#: farm is links and little else.
_MAX_LINK_DENSITY = 0.15

#: A URL host appearing at least this many times in one description is a
#: link farm. Real postings link a company site and maybe two postings.
_MAX_HOST_REPEATS = 4

#: How many listings may share one description before the repeats are
#: treated as a flood. A board legitimately reuses boilerplate across a
#: handful of roles at the same company; a **generated** flood serves one
#: body under hundreds of titles. The threshold sits above the legitimate
#: case and far below the flood case.
_MAX_BODY_REPEATS = 10

#: How many **distinct companies** may share one description before the
#: repeats are treated as a flood. This is the discriminator that separates
#: the two cases: one company posting several similar roles is normal, and
#: the same body under a dozen unrelated company names is a generated
#: flood. A count of repeats alone cannot tell them apart — a company
#: with twenty openings would trip it.
_MAX_FLOOD_COMPANIES = 5

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9+#.]+")

#: Words that carry no signal when counting repetition.
_FILLER_WORDS = frozenset(
    {
        "and",
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "for",
        "with",
        "on",
        "at",
        "or",
        "is",
        "are",
        "we",
        "you",
        "our",
        "your",
        "will",
        "be",
        "as",
        "that",
        "this",
        "it",
        "from",
        "by",
        "all",
        "who",
        "join",
        "job",
        "jobs",
        "role",
        "work",
        "team",
    }
)


def _normalize_text(value: str) -> str:
    """Fold a text to its comparable form: case-folded, accent-free, spaced."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped.casefold()).strip()


def body_fingerprint(listing: JobListing) -> str:
    """A stable fingerprint of a listing's **description alone**.

    The title and the company are deliberately excluded. A generated flood
    serves one body under many different titles and company names, so the
    only field that stays constant across the flood is the body. Including
    the title would give every flooded listing its own fingerprint and the
    collision would never be detected.
    """
    body = _normalize_text(listing.description or "")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass
class SpamVerdict:
    """The screening outcome for one listing or one batch."""

    #: True when the subject is admissible.
    admitted: bool = True
    #: Why it was dropped (empty when admitted).
    reason: str = ""
    #: The signal that produced the verdict.
    signal: str = ""
    #: The body fingerprint of every listing considered.
    fingerprints: dict[str, str] = field(default_factory=dict)
    #: Every listing that was dropped, as ``(listing_id, reason)``.
    dropped: list[tuple[str, str]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.admitted


def _token_counts(text: str) -> dict[str, int]:
    """The count of each meaningful word in *text*."""
    counts: dict[str, int] = {}
    for word in _WORD_RE.findall(text.casefold()):
        if word in _FILLER_WORDS:
            continue
        counts[word] = counts.get(word, 0) + 1
    return counts


def _stuffing_signal(listing: JobListing) -> str:
    """The stuffing reason for *listing*, or '' when it looks like prose."""
    description = listing.description or ""
    tokens = _WORD_RE.findall(description.casefold())
    if len(tokens) < _STUFFING_MIN_TOKENS:
        return ""
    counts = _token_counts(description)
    if not counts:
        return ""
    worst_word, worst_count = max(counts.items(), key=lambda item: item[1])
    if worst_count / len(tokens) > _STUFFING_RATIO:
        return f"token stuffing: {worst_word!r} appears {worst_count} times in {len(tokens)} tokens"
    return ""


def _link_signal(listing: JobListing) -> str:
    """The link-farming reason for *listing*, or '' when it looks normal."""
    description = listing.description or ""
    urls = _URL_RE.findall(description)
    if len(urls) <= _MAX_LINKS:
        return ""
    words = _WORD_RE.findall(description)

    # The same host repeated is a farm whatever the text looks like.
    hosts: dict[str, int] = {}
    for url in urls:
        try:
            host = (urlparse(url).hostname or "").casefold()
        except ValueError:
            host = ""
        if host:
            hosts[host] = hosts.get(host, 0) + 1
    repeated = [(host, count) for host, count in hosts.items() if count > _MAX_HOST_REPEATS]
    if repeated:
        host, count = max(repeated, key=lambda item: item[1])
        return f"link farm: host {host!r} appears {count} times in {len(urls)} links"

    # Otherwise, judge the density: a posting that is mostly links is a
    # farm, and a posting that merely *contains* links is not. The ratio
    # is what separates them, so a long, real posting with a couple of
    # links is admitted.
    if not words:
        return f"link farm: {len(urls)} links and no text"
    if len(urls) / len(words) > _MAX_LINK_DENSITY:
        return f"link farm: {len(urls)} links in {len(words)} words"
    return ""


def screen_listing(listing: JobListing) -> SpamVerdict:
    """Screen one listing on its own content.

    Returns a verdict that admits the listing unless a signal is
    unambiguous. The fingerprint is always computed and returned, so the
    caller can compare listings against each other.
    """
    fingerprint = body_fingerprint(listing)

    reason = _stuffing_signal(listing)
    if reason:
        return SpamVerdict(
            admitted=False,
            reason=reason,
            signal="stuffing",
            fingerprints={listing.id: fingerprint},
        )

    reason = _link_signal(listing)
    if reason:
        return SpamVerdict(
            admitted=False,
            reason=reason,
            signal="links",
            fingerprints={listing.id: fingerprint},
        )

    return SpamVerdict(admitted=True, fingerprints={listing.id: fingerprint})


def screen_listings(listings: list[JobListing]) -> tuple[list[JobListing], SpamVerdict]:
    """Screen a batch of listings, including against each other.

    A batch is where the flood is visible: one description body served under
    hundreds of titles. The fingerprint check is therefore done across the
    whole batch.

    The duplicate rule has **two thresholds**, and that is the difference
    between a control and a bug. A board legitimately reuses boilerplate
    across a handful of roles — the same company posting five similar
    openings, each with the same company blurb. Dropping every repeat
    would delete real jobs on the strength of a coincidence.

    The two thresholds are what separate the legitimate case from the
    flood:

    - the body must repeat **more** than :data:`_MAX_BODY_REPEATS` times,
      and
    - it must repeat across **more** than
      :data:`_MAX_FLOOD_COMPANIES` distinct companies.

    One company posting many roles with the same blurb is normal. The same
    body under a dozen unrelated company names is a generated flood, and
    only then are the repeats dropped.

    Returns:
        The admitted listings and the batch verdict. The verdict's
        ``dropped`` list names every rejected listing and its reason.
    """
    kept: list[JobListing] = []
    verdict = SpamVerdict()

    # Pass one: how often does each body appear, and across how many
    # distinct companies?
    fingerprint_counts: dict[str, int] = {}
    fingerprint_companies: dict[str, set[str]] = {}
    for listing in listings:
        fingerprint = body_fingerprint(listing)
        verdict.fingerprints[listing.id] = fingerprint
        fingerprint_counts[fingerprint] = fingerprint_counts.get(fingerprint, 0) + 1
        fingerprint_companies.setdefault(fingerprint, set()).add(
            (listing.company or "").strip().lower()
        )

    fingerprint_seen: dict[str, int] = {}

    for listing in listings:
        single = screen_listing(listing)
        if not single.admitted:
            verdict.admitted = False
            verdict.signal = single.signal
            verdict.reason = single.reason
            verdict.dropped.append((listing.id, single.reason))
            continue

        fingerprint = verdict.fingerprints[listing.id]
        total = fingerprint_counts.get(fingerprint, 0)
        companies = len(fingerprint_companies.get(fingerprint, ()))
        seen = fingerprint_seen.get(fingerprint, 0)
        fingerprint_seen[fingerprint] = seen + 1

        is_flood = total > _MAX_BODY_REPEATS and companies > _MAX_FLOOD_COMPANIES
        if is_flood and seen >= _MAX_BODY_REPEATS:
            # The same body is being served under many unrelated company
            # names: this is the flood, and the repeats past the threshold
            # are dropped.
            reason = (
                f"the same description appears {total} times across {companies} "
                f"companies in this batch; only {_MAX_BODY_REPEATS} are admitted"
            )
            verdict.admitted = False
            verdict.signal = "duplicate_content"
            verdict.reason = reason
            verdict.dropped.append((listing.id, reason))
            continue

        kept.append(listing)

    return kept, verdict
