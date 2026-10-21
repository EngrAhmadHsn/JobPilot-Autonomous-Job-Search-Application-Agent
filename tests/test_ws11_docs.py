"""WS-11 · The browser's visibility is a documented, configurable fact.

``.env.example`` documents ``PLAYWRIGHT_HEADLESS``. A documented variable
that the code ignores is worse than an undocumented one: the operator sets
it, sees no effect, and concludes the browser layer is broken.

These tests pin the behaviour of the flag: the default is headless (what a
server wants), an explicit ``false`` shows the window, and the value is read
at launch time rather than frozen at import time — so a test or a script can
change it without reloading the module.
"""

from __future__ import annotations

import pytest

from src.applications.fake_ats_adapter import launch_options


def test_the_default_is_headless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the variable, the browser runs without a window."""
    monkeypatch.delenv("PLAYWRIGHT_HEADLESS", raising=False)

    assert launch_options() == {"headless": True}


@pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "off"])
def test_an_explicit_false_shows_the_window(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """A workstation can watch the form being filled."""
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", value)

    assert launch_options() == {"headless": False}


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", "on", ""])
def test_anything_else_stays_headless(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """The flag fails safe: anything unrecognised keeps the window closed."""
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", value)

    assert launch_options() == {"headless": True}


def test_the_value_is_read_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag is not frozen at import time.

    The adapter reads the environment when it launches a browser, so a test
    (or an operator changing the variable) does not need a reimport.
    """
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "false")
    assert launch_options()["headless"] is False

    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "true")
    assert launch_options()["headless"] is True
