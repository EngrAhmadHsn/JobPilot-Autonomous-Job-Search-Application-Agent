"""Deterministic embedding double + store factory (WS-04).

Same token-hash vector scheme as the WS-03 chroma tests (vectors derived from
stable token hashes so related documents rank above unrelated ones), packaged
under tests/fixtures so the pipeline tests, API tests, and the offline
milestone demo share one implementation. No network, no API key.
"""

from __future__ import annotations

import math
import re
import zlib
from types import SimpleNamespace

from src.rag.chroma_store import ChromaVectorStore

DIM = 64


def token_vector(text: str) -> list[float]:
    """Deterministic bag-of-tokens unit vector (stable across runs)."""
    vector = [0.0] * DIM
    for token in re.findall(r"[a-z]+", text.casefold()):
        index = zlib.crc32(token.encode("utf-8")) % DIM
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class FakeEmbeddingFn:
    """EmbeddingFn double: deterministic token-hash vectors, call-counting."""

    def __init__(self) -> None:
        self.document_calls = 0
        self.query_calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += 1
        return [token_vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return token_vector(text)


def make_store(persist_dir, embedding_fn: FakeEmbeddingFn | None = None) -> ChromaVectorStore:
    """ChromaVectorStore in a tmp dir backed by the deterministic fake."""
    settings = SimpleNamespace(
        chroma_dir=str(persist_dir),
        embedding_model="fake-embedding",
        embedding_dimensionality=DIM,
    )
    return ChromaVectorStore(settings=settings, embedding_fn=embedding_fn or FakeEmbeddingFn())
