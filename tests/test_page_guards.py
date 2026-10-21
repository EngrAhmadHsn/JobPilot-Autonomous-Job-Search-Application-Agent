"""WS-06 · Phase F — CAPTCHA / MFA detection (SEC-09).

A challenge must stop the flow. It must never be solved, clicked through, or
retried. The detection is deterministic: a pattern match on the page's own
text, with no model involved.
"""

from __future__ import annotations

import pytest

from src.security.page_guards import (
    CHALLENGE_PATTERNS,
    detect_challenge,
    inspect_page,
    page_text,
)


class FakeLocator:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def inner_text(self) -> str:
        return self.value


class FakeFrame:
    def __init__(self, url: str) -> None:
        self.url = url


class FakePage:
    """A page with just enough of the Playwright surface for the guard."""

    def __init__(
        self, title: str = "Apply", body: str = "", frames: list[str] | None = None
    ) -> None:
        self._title = title
        self._body = body
        self.frames = [FakeFrame(url) for url in (frames or [])]

    def title(self) -> str:
        return self._title

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self._body)


@pytest.mark.parametrize(
    "text",
    [
        "Please complete the CAPTCHA to continue",
        "recaptcha challenge",
        "hCaptcha",
        "Multi-factor authentication required",
        "two-factor code",
        "Enter your 2FA code",
        "We sent an OTP to your phone",
        "Enter the verification code we sent you",
        "Security question: your first pet",
        "Verify you are human",
        "Just a moment...",
        "Checking your browser before accessing",
    ],
)
def test_challenge_markers_are_detected(text: str) -> None:
    assert detect_challenge(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "Senior Python Engineer",
        "The prototype was successful",
        "Apply for the role",
        "",
    ],
)
def test_clean_text_is_not_a_challenge(text: str) -> None:
    assert detect_challenge(text) is None


def test_short_markers_need_word_boundaries() -> None:
    # "otp" inside a longer word must not trip the guard.
    assert detect_challenge("the hotpot recipe") is None
    assert detect_challenge("use otp now") is not None


def test_patterns_are_reviewable_in_one_place() -> None:
    assert len(CHALLENGE_PATTERNS) >= 10


class TestInspectPage:
    def test_a_clean_page_is_clean(self) -> None:
        page = FakePage(title="Apply", body="Fill in the form and submit.")
        assert inspect_page(page) is None

    def test_a_challenge_in_the_body_is_found(self) -> None:
        page = FakePage(title="Apply", body="Please solve the CAPTCHA")
        assert inspect_page(page) is not None

    def test_a_challenge_in_the_title_is_found(self) -> None:
        page = FakePage(title="Just a moment...", body="")
        assert inspect_page(page) is not None

    def test_a_challenge_in_a_frame_url_is_found(self) -> None:
        page = FakePage(
            title="Apply",
            body="",
            frames=["https://www.google.com/recaptcha/api2/anchor"],
        )
        assert inspect_page(page) is not None

    def test_page_text_collects_title_body_and_frames(self) -> None:
        page = FakePage(title="Apply", body="Body text", frames=["https://example.com/f"])
        text = page_text(page)
        assert "Apply" in text
        assert "Body text" in text
        assert "https://example.com/f" in text
