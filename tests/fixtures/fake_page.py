"""A fake Playwright page for the browser-layer unit tests (WS-08).

The adapter addresses a page through the **accessibility tree**: it reads the
controls' labels, roles and validity, and it finds them again by label or by
role. This fake models exactly that surface — the same slice of the Playwright
API the adapter uses — so the unit tests stay fast and browser-free while
still exercising the real locator strategy.

The real browser is exercised separately, in ``tests/test_browser_variants.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FakeControl:
    """One control of the fake page."""

    label: str
    kind: str = "text"
    required: bool = False
    options: list[str] = field(default_factory=list)
    name: str = ""
    group_label: str = ""

    @property
    def tag(self) -> str:
        """The HTML tag the control would have."""
        if self.kind == "select":
            return "select"
        if self.kind == "textarea":
            return "textarea"
        return "input"

    @property
    def type(self) -> str:
        """The input type the control would have."""
        if self.kind in {"text", "textarea", "select"}:
            return ""
        if self.kind == "email":
            return "email"
        if self.kind == "tel":
            return "tel"
        if self.kind == "number":
            return "number"
        return self.kind

    def snapshot(self) -> dict[str, Any]:
        """The accessibility snapshot the browser would hand back."""
        return {
            "labels": [self.label] if self.label else [],
            "aria": "",
            "tag": self.tag,
            "type": self.type,
            "name": self.name,
            "required": self.required,
            "groupLabel": self.group_label,
            "options": list(self.options),
        }


class FakeTracing:
    """The Playwright tracing API, reduced to what the adapter uses."""

    def __init__(self) -> None:
        self.started_with: dict | None = None
        self.stopped_at: str | None = None

    def start(self, **kwargs) -> None:
        self.started_with = kwargs

    def stop(self, path: str | None = None) -> None:
        self.stopped_at = path
        if path:
            Path(path).write_bytes(b"fake-trace")


class FakeContext:
    """The browser context of the fake page."""

    def __init__(self) -> None:
        self.tracing = FakeTracing()
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeLocator:
    """A locator over a list of fake targets."""

    def __init__(self, page: FakePage, targets: list[dict[str, Any]]) -> None:
        self.page = page
        self.targets = targets

    # -- the Playwright surface -----------------------------------------

    def count(self) -> int:
        return len(self.targets)

    def nth(self, index: int) -> FakeLocator:
        if index >= len(self.targets):
            return FakeLocator(self.page, [])
        return FakeLocator(self.page, [self.targets[index]])

    @property
    def first(self) -> FakeLocator:
        return self.nth(0)

    def is_visible(self) -> bool:
        return bool(self.targets)

    def evaluate(self, _expression: str) -> Any:
        target = self.targets[0] if self.targets else None
        if target is None:
            return None
        return target["control"].snapshot()

    def evaluate_all(self, _expression: str) -> list[str]:
        return list(self.page.native_validation_messages)

    def inner_text(self) -> str:
        target = self.targets[0] if self.targets else None
        if target is None:
            return ""
        return target.get("text", "")

    def fill(self, value: str) -> None:
        target = self.targets[0] if self.targets else None
        if target is None:
            return
        self.page.filled[target["control"].label] = value

    def select_option(self, label: str) -> None:
        target = self.targets[0] if self.targets else None
        if target is None:
            return
        self.page.selected[target["control"].label] = label

    def check(self) -> None:
        target = self.targets[0] if self.targets else None
        if target is None:
            return
        self.page.checked.append(target["control"].label)

    def uncheck(self) -> None:
        target = self.targets[0] if self.targets else None
        if target is None:
            return
        self.page.unchecked.append(target["control"].label)

    def set_input_files(self, path: str) -> None:
        self.page.uploaded = path

    def click(self) -> None:
        target = self.targets[0] if self.targets else None
        if target is None:
            return
        self.page.clicked.append(target.get("name", ""))


class FakePage:
    """A page with the slice of the Playwright API the adapter uses."""

    def __init__(
        self,
        url: str = "http://localhost:8000/apply/confirm",
        body: str = "Application Submitted. Thanks for applying.",
        title: str = "Application received",
        controls: list[FakeControl] | None = None,
        buttons: list[str] | None = None,
        alerts: list[str] | None = None,
        errors: list[str] | None = None,
        native_validation_messages: list[str] | None = None,
    ) -> None:
        self.context = FakeContext()
        self.url = url
        self.body = body
        self._title = title
        self.controls = list(controls if controls is not None else default_controls())
        self.buttons = list(buttons if buttons is not None else ["Submit application"])
        self.alerts = list(alerts or [])
        self.errors = list(errors or [])
        self.native_validation_messages = list(native_validation_messages or [])
        self.filled: dict[str, str] = {}
        self.selected: dict[str, str] = {}
        self.checked: list[str] = []
        self.unchecked: list[str] = []
        self.clicked: list[str] = []
        self.uploaded: str | None = None
        self.screenshot_path: str | None = None
        self.screenshot_fails = False

    # -- the Playwright surface -----------------------------------------

    def title(self) -> str:
        return self._title

    def locator(self, selector: str) -> FakeLocator:
        if selector == "input, select, textarea":
            return FakeLocator(self, [{"control": c} for c in self.controls])
        if selector == "input[type='file']":
            return FakeLocator(self, [{"control": c} for c in self.controls if c.kind == "file"])
        if selector == "body":
            return FakeLocator(self, [{"text": self.body}])
        if selector.startswith("."):
            return FakeLocator(self, [{"text": message} for message in self.errors])
        return FakeLocator(self, [])

    def get_by_label(self, label: str | re.Pattern[str], exact: bool = False) -> FakeLocator:
        matches = [
            {"control": control}
            for control in self.controls
            if _label_matches(control.label, label, exact)
        ]
        return FakeLocator(self, matches)

    def get_by_role(self, role: str, name: str | re.Pattern[str] | None = None) -> FakeLocator:
        if role == "button":
            return FakeLocator(self, [{"name": button} for button in self.buttons])
        if role == "alert":
            return FakeLocator(self, [{"text": message} for message in self.alerts])
        if role in {"checkbox", "radio"}:
            return FakeLocator(
                self,
                [
                    {"control": control}
                    for control in self.controls
                    if control.kind == role and _name_matches(control.label, name)
                ],
            )
        return FakeLocator(self, [])

    def wait_for_load_state(self, *args, **kwargs) -> None:
        return None

    def screenshot(self, path: str | None = None) -> None:
        if self.screenshot_fails:
            raise RuntimeError("screenshot failed")
        self.screenshot_path = path
        if path:
            Path(path).write_bytes(b"fake-png")

    def close(self) -> None:
        return None


def _label_matches(label: str, wanted: str | re.Pattern[str], exact: bool) -> bool:
    """Whether a control's label is the one that was asked for."""
    if isinstance(wanted, re.Pattern):
        return bool(wanted.search(label))
    if exact:
        return label == wanted
    return wanted.lower() in label.lower()


def _name_matches(label: str, wanted: str | re.Pattern[str] | None) -> bool:
    """Whether a control's accessible name is the one that was asked for."""
    if wanted is None:
        return True
    if isinstance(wanted, re.Pattern):
        return bool(wanted.search(label))
    return wanted.lower() in label.lower()


def default_controls() -> list[FakeControl]:
    """The controls of the standard fake-ATS form."""
    return [
        FakeControl(label="Full name", kind="text", required=True, name="candidate_name"),
        FakeControl(label="Email address", kind="email", required=True, name="email"),
        FakeControl(label="Phone number", kind="tel", name="phone"),
        FakeControl(label="Cover letter", kind="textarea", name="cover_letter"),
        FakeControl(label="Resume", kind="file", name="resume"),
    ]
