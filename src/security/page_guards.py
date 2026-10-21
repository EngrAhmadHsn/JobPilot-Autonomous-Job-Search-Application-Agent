"""Browser page guards (WS-06 · SEC-09).

Before the agent touches a form it has to know whether the page is asking for
something it must never do: solving a CAPTCHA, passing a multi-factor
challenge, proving it is human. Those flows **stop** the application with
``status="blocked_human_review"`` — the agent never clicks, types into, or
attempts to solve a challenge (SEC-09 forbids bypass, not just this
workstream).

The detection is a deterministic pattern match on the page's own text (title,
body, frame URLs). No model is involved, so the decision cannot be talked
into being different.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# The markers that identify an anti-bot or multi-factor challenge. Each entry
# is a regular expression; the short ones use word boundaries so that
# "prototype" is not an OTP prompt.
CHALLENGE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"captcha",
        r"multi[-\s]?factor",
        r"two[-\s]?factor",
        r"\b2fa\b",
        r"\bmfa\b",
        r"\botp\b",
        r"one[-\s]?time\s+(?:code|password|passcode)",
        r"verification\s+code",
        r"security\s+question",
        r"verify you are (?:a )?human",
        r"just a moment",
        r"checking your browser",
        r"enable javascript and cookies",
    )
)


def detect_challenge(text: str) -> str | None:
    """The first challenge marker found in *text* (``None`` when clean)."""
    if not text:
        return None
    for pattern in CHALLENGE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def page_text(page) -> str:
    """The visible text of a page: its title, its body, and its frame URLs.

    Duck-typed on purpose — the module must not depend on Playwright, so it
    can be exercised with a fake page in the tests.
    """
    parts: list[str] = []

    title = getattr(page, "title", None)
    if callable(title):
        try:
            parts.append(str(title() or ""))
        except Exception as exc:  # noqa: BLE001 - an unreadable title is not a challenge
            logger.debug("Page title could not be read: %s", exc)

    try:
        body = page.locator("body")
        inner_text = getattr(body, "inner_text", None)
        if callable(inner_text):
            parts.append(str(inner_text() or ""))
    except Exception as exc:  # noqa: BLE001 - an unreadable body is not a challenge
        logger.debug("Page body could not be read: %s", exc)

    frames = getattr(page, "frames", None)
    if frames is not None:
        try:
            for frame in frames:
                url = getattr(frame, "url", "")
                if url:
                    parts.append(str(url))
        except Exception as exc:  # noqa: BLE001 - unreadable frames are not a challenge
            logger.debug("Page frames could not be read: %s", exc)

    return "\n".join(part for part in parts if part)


def inspect_page(page) -> str | None:
    """The challenge marker on *page*, or ``None`` when the page is clean."""
    return detect_challenge(page_text(page))
