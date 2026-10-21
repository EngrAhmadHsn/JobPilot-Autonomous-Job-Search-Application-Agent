"""Prompt-injection patterns (WS-06 · SEC-01).

Web content is data, never instruction. This module is the single, reviewable
place where "this text looks like an instruction smuggled into content" is
decided. It is deliberately a **deterministic pattern list**, not a model
judgement: a poisoned listing must not be able to talk its way past the
filter.

The list was introduced with the grounded research engine (WS-05) and is now
shared, because the same rule has to hold for every place untrusted text can
reach a deliverable: the research insights, the tailored summary, the cover
letter, and every bullet.
"""

from __future__ import annotations

import re

# Instruction-like text smuggled into content. A match rejects the whole
# item (or, in prose, the whole sentence).
INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+instructions?",
        r"disregard\s+(?:all\s+)?(?:previous|prior|above|earlier)",
        r"forget\s+(?:everything|all)\s+(?:above|before|you\s+were\s+told)",
        r"system\s+prompt|developer\s+message|new\s+instructions|important\s+message",
        r"you\s+are\s+now|act\s+as\b|pretend\s+(?:you|to\s+be)|roleplay",
        (
            r"(?:reveal|print|repeat|show)\s+(?:me\s+)?(?:your|the)\s+"
            r"(?:instructions|prompt|system\s+prompt|rules)"
        ),
        r"jailbreak|do\s+anything\s+now|developer\s+mode|\bsudo\b",
        r"instead,?\s+(?:say|write|respond|claim|state|recommend|describe)",
        r"override\s+(?:your|the)\s+(?:instructions|rules|system|guidelines)",
        r"as\s+an\s+ai(?:\s+language)?\s+model",
        r"upload\s+(?:your|the)\s+(?:environment\s+variables|secrets?|credentials?|api\s+keys?)",
        r"send\s+(?:your|the)\s+(?:secrets?|credentials?|api\s+keys?)\s+to\b",
    )
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def is_injection(text: str) -> bool:
    """True when *text* looks like an instruction rather than content."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in INJECTION_PATTERNS)


def strip_injected_sentences(text: str) -> tuple[str, list[str]]:
    """Remove the injected sentences from *text*.

    Args:
        text: The text to clean.

    Returns:
        The cleaned text and the sentences that were removed. The text is
        returned unchanged when nothing was injected.
    """
    if not text or not is_injection(text):
        return text, []
    kept: list[str] = []
    removed: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        stripped = sentence.strip()
        if not stripped:
            continue
        if is_injection(stripped):
            removed.append(stripped)
            continue
        kept.append(stripped)
    return " ".join(kept), removed
