"""Tests for the shared text normalization helpers (src/core/text.py)."""

from src.core.text import content_tokens, normalize, token_set, tokenize


def test_normalize_keeps_technology_punctuation() -> None:
    assert normalize("C++, C#, Node.js").split() == ["c++", "c#", "node.js"]


def test_tokenize_drops_sentence_punctuation_but_keeps_inner_dots() -> None:
    assert tokenize("Built pipelines.") == ["built", "pipelines"]
    assert tokenize("Node.js runtime") == ["node.js", "runtime"]


def test_tokenize_keeps_plus_and_hash_tokens() -> None:
    assert tokenize("C++ and C#") == ["c++", "and", "c#"]


def test_content_tokens_remove_stop_words() -> None:
    assert content_tokens("You will build the agent pipelines") == [
        "build",
        "agent",
        "pipelines",
    ]


def test_token_set_is_deduplicated() -> None:
    assert token_set("python python fastapi") == {"python", "fastapi"}
