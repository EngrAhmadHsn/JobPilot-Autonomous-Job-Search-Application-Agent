"""Shared text normalization for keyword matching (WS-05).

Both the research engine (grounding filter) and the ATS analyzer (keyword
coverage, title alignment) need the same notion of "these two strings mention
the same thing". The conventions follow the existing ``_norm`` helpers in
``src/resume/tailor.py`` and ``src/jobs/requirements.py``: lowercase, strip
punctuation, but keep ``+``, ``#`` and ``.`` inside a token so ``c++``,
``c#`` and ``node.js`` survive.

Unlike the substring containment used by the factuality validator, this module
also provides *token* level views: a token set catches a phrase's words
without the false positives of substring matching (``go`` inside ``google``).
"""

from __future__ import annotations

import re

# Words that carry no evidentiary weight when checking whether one text
# mentions the same thing as another.
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "and",
        "or",
        "to",
        "in",
        "on",
        "for",
        "with",
        "at",
        "by",
        "from",
        "as",
        "is",
        "are",
        "be",
        "been",
        "will",
        "would",
        "we",
        "you",
        "our",
        "us",
        "they",
        "their",
        "that",
        "this",
        "these",
        "it",
        "its",
        "your",
        "who",
        "have",
        "has",
        "had",
        "do",
        "does",
        "not",
        "but",
        "than",
        "then",
        "also",
        "into",
        "such",
        "must",
        "should",
        "can",
        "may",
    }
)

_PUNCTUATION_RE = re.compile(r"[^a-z0-9+#. ]")


def normalize(value: str) -> str:
    """Lowercase and strip punctuation, keeping ``+``, ``#`` and ``.``."""
    return _PUNCTUATION_RE.sub(" ", value.lower()).strip()


def tokenize(value: str) -> list[str]:
    """Split normalized text into tokens.

    A trailing/leading period is sentence punctuation, not part of the word
    (``systems.`` -> ``systems``), while an internal one is meaningful
    (``node.js``). ``+`` and ``#`` are never stripped (``c++``, ``c#``).
    """
    tokens: list[str] = []
    for raw in normalize(value).split():
        token = raw.strip(".")
        if token:
            tokens.append(token)
    return tokens


def content_tokens(value: str) -> list[str]:
    """Tokens that carry evidentiary weight (stop-words removed)."""
    return [token for token in tokenize(value) if token not in STOPWORDS]


def token_set(value: str) -> set[str]:
    """The set of tokens of a text (stop-words included)."""
    return set(tokenize(value))
