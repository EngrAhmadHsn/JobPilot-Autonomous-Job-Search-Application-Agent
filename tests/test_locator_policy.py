"""WS-08 · Phase G — the locator policy of the browser layer.

The browser-automation skill requires **semantic** locators: a field is found
by the label a human reads, or by its role — never by an id, a class or a
coordinate. This is a source-level check, so it fails the moment somebody
reintroduces a fragile selector, whoever wrote it and however good the test
suite is.

The allowlist below is the whole of the CSS the browser layer may use. Every
entry has a reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# The browser layer: the adapter and the form contract it walks.
BROWSER_SOURCES = (
    REPO_ROOT / "src" / "applications" / "fake_ats_adapter.py",
    REPO_ROOT / "src" / "applications" / "form.py",
)

# Every CSS selector the browser layer may use, and why.
ALLOWED_CSS = {
    "input, select, textarea": (
        "the enumeration of the controls — the *set* of fields, not one field"
    ),
    "input[type='file']": "the documented file-input exception",
    ".error, [aria-invalid='true']": "the documented validation-error sweep",
    "body": "the visible text of the page (never a field)",
}

_LOCATOR_CALL = re.compile(r"\.locator\(\s*(?:\"([^\"]*)\"|'([^']*)')")
_GET_BY_CSS = re.compile(r"get_by_css\(\s*(?:\"([^\"]*)\"|'([^']*)')")

# The ways a coordinate-based interaction would show up.
_COORDINATE_PATTERNS = (
    re.compile(r"\bmouse\."),
    re.compile(r"position\s*="),
    re.compile(r"\.tap\("),
    re.compile(r"click\(\s*[\"']?\s*x\s*="),
)


def _sources() -> list[tuple[Path, str]]:
    return [(path, path.read_text(encoding="utf-8")) for path in BROWSER_SOURCES]


def _selectors(source: str) -> list[str]:
    """Every CSS selector the source hands to Playwright."""
    found: list[str] = []
    for pattern in (_LOCATOR_CALL, _GET_BY_CSS):
        for match in pattern.finditer(source):
            found.append(match.group(1) if match.group(1) is not None else match.group(2))
    return found


def test_every_css_selector_is_on_the_allowlist() -> None:
    offenders: list[str] = []
    for path, source in _sources():
        for selector in _selectors(source):
            if selector not in ALLOWED_CSS:
                offenders.append(f"{path.name}: {selector!r}")

    assert not offenders, "Unapproved CSS selectors in the browser layer:\n" + "\n".join(offenders)


def test_no_field_is_addressed_by_its_id() -> None:
    """An id selector is never allowed — not even on the allowlist."""
    offenders: list[str] = []
    for path, source in _sources():
        for selector in _selectors(source):
            if selector.startswith("#") or "[id=" in selector:
                offenders.append(f"{path.name}: {selector!r}")

    assert not offenders, "Id selectors in the browser layer:\n" + "\n".join(offenders)


@pytest.mark.parametrize("pattern", _COORDINATE_PATTERNS, ids=lambda p: p.pattern)
def test_no_coordinate_based_interaction(pattern: re.Pattern[str]) -> None:
    offenders: list[str] = []
    for path, source in _sources():
        for match in pattern.finditer(source):
            line = source[: match.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line}")

    assert not offenders, f"Coordinate-based interaction in the browser layer: {offenders}"


def test_the_browser_layer_uses_labels_and_roles() -> None:
    """The positive half of the rule: labels and roles are what is used."""
    source = (REPO_ROOT / "src" / "applications" / "fake_ats_adapter.py").read_text(
        encoding="utf-8"
    )

    assert "get_by_label" in source
    assert "get_by_role" in source
    # ...and the old CSS field selectors are gone.
    assert "#candidate-name" not in source
    assert "#email" not in source
    assert "#phone" not in source
