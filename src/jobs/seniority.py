"""Deterministic seniority classification (WS-23).

``JobListing.seniority`` was **never** written by any adapter: 0 of 6,696
rows in the live corpus carried a value, and the column has existed since
the initial schema. Because the matching layer blends over a fixed
denominator (``src/matching/scores.py``), a component whose inputs are
unknown contributes zero to the numerator and keeps its full weight — so
the seniority component (weight 0.08) was a flat 8-point penalty on every
listing in the corpus, and it never became a *measurement*.

No board publishes a reliable seniority field. Greenhouse carries
per-board metadata with names like ``"Employee Type"`` (which means
employment type, not level); Lever's ``categories`` has no level field at
all; Ashby has none. The level is in the **title**, and the title is the
one place every board states it.

So this is a classifier, and it is deliberately **deterministic** — a
regex ladder, no model. The project's rule is that business logic lives
in code, not in prompts, and a level is a fact, not a judgement.

Two properties matter more than coverage:

* **Conservative.** A title it does not recognize leaves the field
  ``None``. A wrong seniority is worse than an unknown one, because an
  unknown is visible in ``evidence_coverage`` and a wrong one is not.
* **Order-sensitive.** ``"Senior Backend Engineer"`` is senior;
  ``"Engineer II"`` is mid; ``"Director of Engineering"`` is a director
  even though it contains "engineering". The ladder is tried from the
  most senior to the least, and the first match wins, so a more specific
  signal always beats a more general one.
"""

from __future__ import annotations

import re

__all__ = ["SENIORITY_LEVELS", "classify_seniority", "normalize_seniority"]

#: The canonical levels, ordered from least to most senior. The order is
#: the contract: the matching layer's ``_seniority_rank`` maps these onto
#: numeric ranks, and a level outside this set is not used.
SENIORITY_LEVELS: tuple[str, ...] = (
    "intern",
    "entry",
    "junior",
    "mid",
    "senior",
    "staff",
    "principal",
    "lead",
    "manager",
    "director",
    "head",
    "vp",
    "cto",
)

#: The ladder, most senior first. The first pattern that matches wins, so
#: a director is never read as a senior engineer, and a senior engineer is
#: never read as a mid engineer.
#
#: Each entry is ``(level, pattern)``. The patterns are matched against a
#: lowercased title with punctuation collapsed to single spaces, so
#: ``"Sr. Engineer"``, ``"Sr Engineer"`` and ``"SR_ENGINEER"`` all reduce
#: to ``"sr engineer"``.
_LADDER: tuple[tuple[str, str], ...] = (
    # -- executive ---------------------------------------------------------
    ("cto", r"\bchief technology officer\b|\bcto\b"),
    ("vp", r"\bvice president\b|\bvp\b|\bhead of (?:product|technology|engineering)\b"),
    ("head", r"\bhead of\b|\bhead\b"),
    ("director", r"\bdirector\b|\bdir\b"),
    ("manager", r"\bmanager\b|\bmgr\b|\bteam lead\b|\bgroup lead\b"),
    # -- senior individual contributors ------------------------------------
    ("principal", r"\bprincipal\b|\bdistinguished\b|\bfellow\b|\barchitect\b"),
    ("staff", r"\bstaff\b"),
    ("lead", r"\blead\b|\bleading\b"),
    ("senior", r"\bsenior\b|\bsr\b|\bsr\.?\b|\bsn\b"),
    # -- junior ------------------------------------------------------------
    ("junior", r"\bjunior\b|\bjr\b|\bjr\.?\b"),
    ("intern", r"\bintern\b|\binternship\b|\bco-?op\b|\bapprentice\b"),
    # -- entry and mid -----------------------------------------------------
    ("entry", r"\bentry level\b|\bnew grad\b|\bgraduate\b|\bassociate\b"),
    ("mid", r"\bmid[- ]level\b|\bintermediate\b|\bii\b|\biii\b|\biv\b|\blevel 2\b|\blevel 3\b"),
)

#: The compiled ladder. It is a **tuple**, not a generator: a generator
#: would be consumed by the first call and every later call would find it
#: empty — which is exactly the bug this shape avoids.
_COMPILED_LADDER: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (level, re.compile(pattern)) for level, pattern in _LADDER
)

#: The title words that mean the role is not an individual-contributor
#: engineering role at all. The role classifier (WS-21) handles the
#: occupational family; this only keeps a non-IC title from being read as
#: a mid-level IC role.
_NON_IC_MARKERS: tuple[str, ...] = (
    "intern",
    "trainee",
    "apprentice",
)


def normalize_seniority(value: str | None) -> str | None:
    """Normalize a free-text level onto the canonical ladder.

    A board that *does* publish a level ("Full Time", "Senior", "Lead")
    gets it normalized rather than discarded. Anything that is not a level
    returns ``None`` — an employment type is not a seniority.
    """
    if not value or not isinstance(value, str):
        return None
    lowered = value.strip().casefold()
    if not lowered:
        return None
    for level, pattern in _COMPILED_LADDER:
        if pattern.search(lowered):
            return level
    return None


def classify_seniority(title: str | None) -> str | None:
    """Classify a job title onto the canonical seniority ladder.

    Returns ``None`` when the title states no level, which is the honest
    answer and leaves the field unknown rather than guessed.
    """
    if not title or not isinstance(title, str):
        return None
    lowered = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    if not lowered:
        return None

    # The ladder is ordered from most senior to least, so the first match
    # is the most senior signal present. ``"Senior Director"`` is a
    # director; ``"Director of Engineering"`` is a director, not a
    # principal architect, because "director" is tried first.
    for level, pattern in _COMPILED_LADDER:
        if pattern.search(lowered):
            # "Head of" beats "head" inside a phrase like "Head of Data" —
            # both map to the same level, so no special case is needed.
            return level
    return None


def is_non_ic(title: str | None) -> bool:
    """Whether a title names a non-IC position (an internship, a trainee)."""
    if not title:
        return False
    lowered = title.casefold()
    return any(marker in lowered for marker in _NON_IC_MARKERS)
