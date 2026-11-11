"""Per-board metadata key mapping (WS-23).

Greenhouse's ``metadata[]`` is a list of ``{id, name, value, value_type}``
entries, and **the key names are not standardized across boards**. The
adapter used to look for a key called ``"employmentType"`` — and that key
appears **zero** times across the 11 boards and 4,406 jobs in the registry
(measured live, 2026-11-09). The data was in the payload the whole time;
the lookup was looking for the wrong name.

What the boards actually publish (measured live):

=========================  ==================================================
board                      metadata keys present
=========================  ==================================================
airbnb                     ``Workplace Type``, ``Is this job part of ACC?``
block                      ``Position open to remote``, ``Employee Type``
anthropic                  ``Location Type``
cloudflare                 ``Job Posting Location``
asana                      ``Careers Page: Location``, ``Careers Page: Team``
databricks                 ``Company Assignment``, ``Career Page Posting Category``
coinbase                   ``Team``, ``Careersite Department (for job postings)``
gitlab                     ``Quota Coverage Type``
adyen, figma, stripe       *(none)*
=========================  ==================================================

So the mapping is **per board**, and this module is where it lives. It is
a policy table, not code: the keys change without notice, and a board
that publishes nothing must leave the fields honestly unknown rather than
inherit another board's semantics.

The resolution order for a board is:

1. the board's own configured key, if it has one;
2. the **aliases** — the set of key names observed across boards, tried in
   a fixed order;
3. nothing, and the field stays ``None``.

The aliases are a fallback, not a shortcut: a board that has an explicit
entry always uses it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "GREENHOUSE_BOARD_METADATA",
    "BoardMetadataMap",
    "extract_metadata_value",
    "metadata_value",
    "remote_policy_from_metadata",
]


@dataclass(frozen=True)
class BoardMetadataMap:
    """The metadata keys one board uses for each concept."""

    #: The key whose value states whether the role is remote.
    remote_policy_key: str | None = None
    #: The key whose value states the employment type.
    employment_type_key: str | None = None
    #: The key whose value states the department or team.
    department_key: str | None = None
    #: Extra keys to try, in order, when the board's own key is absent.
    remote_policy_aliases: tuple[str, ...] = field(default_factory=tuple)
    employment_type_aliases: tuple[str, ...] = field(default_factory=tuple)

    def remote_key(self) -> str | None:
        """The board's own remote key, or the first alias."""
        return self.remote_policy_key or (
            self.remote_policy_aliases[0] if self.remote_policy_aliases else None
        )

    def employment_key(self) -> str | None:
        """The board's own employment key, or the first alias."""
        return self.employment_type_key or (
            self.employment_type_aliases[0] if self.employment_type_aliases else None
        )


#: The alias sets, tried when a board has no explicit entry. These are the
#: key names observed across the registry's boards (measured 2026-11-09).
_REMOTE_ALIASES: tuple[str, ...] = (
    "Workplace Type",
    "Position open to remote",
    "Location Type",
    "Job Posting Location",
    "Careers Page: Location",
)

_EMPLOYMENT_ALIASES: tuple[str, ...] = (
    "Employee Type",
    "Employment Type",
    "Careers Page: Employment Type",
)

_DEPARTMENT_ALIASES: tuple[str, ...] = (
    "Career Page Posting Category",
    "Careersite Department (for job postings)",
    "Department",
    "Team",
    "Careers Page: Team",
)


#: The per-board table. A board that appears here with only a couple of
#: keys is a board that publishes only those concepts.
GREENHOUSE_BOARD_METADATA: dict[str, BoardMetadataMap] = {
    "airbnb": BoardMetadataMap(
        remote_policy_key="Workplace Type",
        department_key=None,
    ),
    "block": BoardMetadataMap(
        remote_policy_key="Position open to remote",
        employment_type_key="Employee Type",
        department_key="Career Site Function",
    ),
    "anthropic": BoardMetadataMap(
        remote_policy_key="Location Type",
    ),
    "cloudflare": BoardMetadataMap(
        remote_policy_key="Job Posting Location",
        department_key="Career Site Department",
    ),
    "asana": BoardMetadataMap(
        remote_policy_key="Careers Page: Location",
        department_key="Careers Page: Team",
    ),
    "databricks": BoardMetadataMap(
        department_key="Career Page Posting Category",
    ),
    "coinbase": BoardMetadataMap(
        department_key="Careersite Department (for job postings)",
    ),
    "gitlab": BoardMetadataMap(),
    "adyen": BoardMetadataMap(),
    "figma": BoardMetadataMap(),
    "stripe": BoardMetadataMap(),
}


def _normalize_key(label: str) -> str:
    """The comparison form of a metadata key.

    Greenhouse keys are free text: ``"Workplace Type"``, ``"workplace
    type"`` and ``"workplace_type"`` are the same key. Comparing on a
    punctuation-free, lowercased form makes the lookup robust to the
    spelling a board chooses.
    """
    return "".join(ch for ch in label.casefold() if ch.isalnum())


def _iter_metadata(metadata: Any):
    """Yield ``(label, value)`` pairs from a Greenhouse metadata list."""
    if not isinstance(metadata, list):
        return
    for entry in metadata:
        if not isinstance(entry, dict):
            continue
        label = entry.get("name") or entry.get("key") or ""
        if not isinstance(label, str) or not label.strip():
            continue
        yield label.strip(), entry.get("value")


def metadata_value(metadata: Any, keys: tuple[str, ...] | list[str]) -> str | None:
    """The value of the first key that is present in the metadata.

    The comparison is on the normalized key, so the caller's key spelling
    does not have to match the board's exactly. The **board's own
    spelling** is preserved in the lookup, not in the result — the result
    is the value.
    """
    if not keys:
        return None
    wanted = {_normalize_key(key) for key in keys if key}
    if not wanted:
        return None
    for label, value in _iter_metadata(metadata):
        if _normalize_key(label) not in wanted:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def extract_metadata_value(metadata: Any, key: str | None) -> str | None:
    """The value of one named metadata key, or None."""
    if not key:
        return None
    return metadata_value(metadata, (key,))


def remote_policy_from_metadata(metadata: Any, board: str | None) -> str | None:
    """The remote policy a board's metadata states, or ``None``.

    The values are free text and each board words them differently
    (``"Remote"``, ``"Hybrid"``, ``"On-site"``, ``"Remote - US"``). The
    mapping is deliberately narrow: only a value that **states** a policy
    is read, and a value that says nothing about remoteness is left
    unknown. A wrong remote policy is worse than a missing one, because
    the location component asserts a measured value when it has one.

    Two shapes are handled, because the boards use both:

    * the **value** states the policy — ``"Workplace Type": "Remote"``;
    * the **key** states the policy and the value is a yes/no — block
      publishes ``"Position open to remote": "Yes"``, and the key's own
      wording is the fact.
    """
    board_map = GREENHOUSE_BOARD_METADATA.get(board or "", BoardMetadataMap())
    keys: list[str] = []
    if board_map.remote_policy_key:
        keys.append(board_map.remote_policy_key)
    keys.extend(board_map.remote_policy_aliases)
    if not keys:
        keys.extend(_REMOTE_ALIASES)

    lookup = tuple(dict.fromkeys(keys))
    raw = metadata_value(metadata, lookup)
    if raw is None:
        return None

    policy = _remote_policy_from_text(raw)
    if policy is not None:
        return policy

    # The value did not state a policy; the key may have.
    key_policy = _remote_policy_from_key(lookup)
    if key_policy is None:
        return None
    answer = _remote_policy_from_yes_no(raw)
    if answer is None:
        return None
    if key_policy == "remote":
        return "remote" if answer else "onsite"
    return key_policy


def _remote_policy_from_key(keys: tuple[str, ...]) -> str | None:
    """The policy a metadata **key** names, or ``None``."""
    for key in keys:
        lowered = key.casefold()
        if "remote" in lowered:
            return "remote"
        if "hybrid" in lowered:
            return "hybrid"
        if "on-site" in lowered or "onsite" in lowered:
            return "onsite"
    return None


def _remote_policy_from_yes_no(value: str) -> bool | None:
    """Whether a yes/no value is a yes, a no, or neither."""
    lowered = value.strip().casefold()
    if lowered in {"yes", "true", "y", "1"}:
        return True
    if lowered in {"no", "false", "n", "0"}:
        return False
    return None


def _remote_policy_from_text(raw: str) -> str | None:
    """Read a remote policy out of a board's free text.

    The order matters: a value mentioning both remote and hybrid
    (``"Remote"`` on a board whose key is ``"Location Type"`` and whose
    value is ``"Remote - San Francisco"``) is remote, but a value that
    says ``"Hybrid"`` is hybrid even if it also contains the word
    "remote" in a location name.
    """
    lowered = raw.casefold()

    if "hybrid" in lowered:
        return "hybrid"
    if "on-site" in lowered or "onsite" in lowered or "in-office" in lowered:
        return "onsite"
    if "remote" in lowered:
        return "remote"
    return None
