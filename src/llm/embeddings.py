"""Embedding layer for semantic matching (WS-03).

Wraps the Gemini embedding API behind a small protocol so callers (the Chroma
store, the matching pipeline) can swap in deterministic fakes for tests.

Verified ``gemini-embedding-2`` facts this module relies on (docs checked
2026-10-11 and **confirmed against the live API on 2026-10-11**; see
docs/implementation/03-matching-engine.md):

- ``client.models.embed_content(model, contents, config)`` returns one vector
  per document at ``result.embeddings[i].values``. Aggregation gotcha,
  live-verified: N **bare strings** in one ``contents`` call are treated as
  parts of a single content and come back as ONE blended embedding. Each text
  must be wrapped in its own ``types.Content(role="user", parts=[Part(text)])``
  to get N vectors back.
- No ``task_type`` on embedding-2 (that is embedding-001-only). Asymmetric
  prompt prefixes are used instead: documents are embedded as
  ``title: ... | text: ...`` and queries as ``task: search result | query: ...``.
- Input is capped at 8,192 tokens; over-limit input is silently truncated, so
  text is proactively truncated (with a warning) before it reaches the API.
- Embedding spaces are version-locked: the model name and dimensionality are
  part of every cache key, and the Chroma store persists them as collection
  metadata so a model change is detected instead of silently mixing spaces.

Every vector is cached in ``data/embedding_cache.sqlite`` keyed by
``sha256(model|dim|text)``; identical text (under the same model and
dimensionality) never triggers a second API call.
"""

from __future__ import annotations

import logging
import sqlite3
from array import array
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from src.config.settings import ensure_dir, get_settings
from src.llm.client import LLMConfigError, LLMError, classify_provider_error

logger = logging.getLogger(__name__)

MODEL_PREFIX_DOC = "title: {title} | text: {body}"
MODEL_PREFIX_QUERY = "task: search result | query: {text}"

# The API silently truncates beyond 8,192 tokens; ~6,000 characters of
# description stays comfortably inside the cap together with the prefix.
MAX_TEXT_CHARS = 6_000


def build_document_text(title: str, body: str) -> str:
    """Compose a job document string with the asymmetric document prefix."""
    return MODEL_PREFIX_DOC.format(title=title.strip(), body=body.strip())


def build_query_text(text: str) -> str:
    """Compose a query string with the asymmetric query prefix."""
    return MODEL_PREFIX_QUERY.format(text=text.strip())


class EmbeddingFn(Protocol):
    """Protocol for embedding providers (GeminiEmbedding is the default impl)."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class EmbeddingCache:
    """SQLite content-hash cache: sha256(model|dim|text) -> vector.

    Vectors are stored as little-endian float32 blobs. Keys include the model
    name and dimensionality so a model or dimension change can never read a
    vector from an incompatible embedding space.
    """

    def __init__(self, path: str | Path) -> None:
        target = Path(path)
        ensure_dir(target.parent)
        self._conn = sqlite3.connect(target)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS embeddings ("
            " key TEXT PRIMARY KEY,"
            " model TEXT NOT NULL,"
            " dim INTEGER NOT NULL,"
            " vector BLOB NOT NULL,"
            " created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        self._conn.commit()

    @staticmethod
    def key(model: str, dim: int, text: str) -> str:
        return sha256(f"{model}|{dim}|{text}".encode()).hexdigest()

    def get(self, key: str) -> list[float] | None:
        row = self._conn.execute("SELECT vector FROM embeddings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        # float64: exact round-trip of the API's Python floats (float32 would
        # make cached runs return slightly different vectors than fresh ones).
        return array("d", row[0]).tolist()

    def put(self, key: str, model: str, dim: int, vector: list[float]) -> None:
        blob = array("d", vector).tobytes()
        self._conn.execute(
            "INSERT OR REPLACE INTO embeddings (key, model, dim, vector) VALUES (?, ?, ?, ?)",
            (key, model, dim, blob),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


class GeminiEmbedding:
    """Default EmbeddingFn: Gemini ``embed_content`` with a SQLite cache.

    The genai client is created lazily (and never when one is injected), so
    constructing this class is safe without configuration; only an actual
    embed call without a key raises ``LLMConfigError``.
    """

    MODEL_PREFIX_DOC = MODEL_PREFIX_DOC
    MODEL_PREFIX_QUERY = MODEL_PREFIX_QUERY
    MAX_TEXT_CHARS = MAX_TEXT_CHARS

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        dimensionality: int | None = None,
        cache_path: str | Path | None = None,
        client: Any = None,
    ) -> None:
        settings = get_settings()
        self.model = model or settings.embedding_model
        self.dimensionality = dimensionality or settings.embedding_dimensionality
        self._api_key = api_key if api_key is not None else settings.llm_api_key
        self._injected_client = client
        self._client: Any = None
        self._types: Any = None  # set when the real genai client is built
        if cache_path is None:
            cache_path = Path(settings.data_dir) / "embedding_cache.sqlite"
        self._cache = EmbeddingCache(cache_path)

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._injected_client is not None:
            self._client = self._injected_client
            return self._client
        if not self._api_key:
            raise LLMConfigError(
                "LLM_API_KEY is not set; embeddings need a Gemini API key in .env (never commit it)"
            )
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - environment issue
            raise LLMConfigError(
                "google-genai is not installed; add it to the environment"
            ) from exc
        self._types = types
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    # -- public API ---------------------------------------------------------

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed N documents, returning exactly N vectors in input order.

        Cache hits never touch the API; only misses are sent, each as its own
        ``contents`` entry in one call (the aggregation gotcha: a joined
        string would come back as a single blended vector).
        """
        if not texts:
            return []
        prepared = [self._truncate(text) for text in texts]
        keys = [EmbeddingCache.key(self.model, self.dimensionality, text) for text in prepared]
        vectors: dict[int, list[float]] = {}
        misses: list[tuple[int, str]] = []
        for index, (key, text) in enumerate(zip(keys, prepared)):
            cached = self._cache.get(key)
            if cached is not None:
                vectors[index] = cached
            else:
                misses.append((index, text))
        if misses:
            fresh = self._embed_api([text for _, text in misses])
            if len(fresh) != len(misses):
                raise LLMError(
                    f"Embedding API returned {len(fresh)} vectors for "
                    f"{len(misses)} inputs; refusing to misalign results"
                )
            for (index, text), vector in zip(misses, fresh):
                vectors[index] = vector
                self._cache.put(
                    EmbeddingCache.key(self.model, self.dimensionality, text),
                    self.model,
                    self.dimensionality,
                    vector,
                )
        return [vectors[index] for index in range(len(texts))]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([self._truncate(text)])[0]

    # -- internals ----------------------------------------------------------

    def _truncate(self, text: str) -> str:
        if len(text) > self.MAX_TEXT_CHARS:
            logger.warning(
                "Embedding input truncated from %d to %d chars (model input cap)",
                len(text),
                self.MAX_TEXT_CHARS,
            )
            return text[: self.MAX_TEXT_CHARS]
        return text

    def _embed_api(self, texts: list[str]) -> list[list[float]]:
        client = self._ensure_client()
        try:
            if self._injected_client is None:
                # Verified against the live API (2026-10-11): N bare strings in
                # one ``contents`` call are treated as parts of ONE content and
                # come back as a single aggregated embedding. Each text must be
                # its own Content object to get N vectors back.
                contents = [
                    self._types.Content(role="user", parts=[self._types.Part(text=text)])
                    for text in texts
                ]
                config = self._types.EmbedContentConfig(output_dimensionality=self.dimensionality)
            else:
                # Injected (test) clients have no SDK types module; they
                # receive plain strings and must accept config=None.
                contents = list(texts)
                config = None
            result = client.models.embed_content(
                model=self.model,
                contents=contents,
                config=config,
            )
        except LLMError:
            raise
        except Exception as exc:
            raise classify_provider_error(exc) from exc
        embeddings = getattr(result, "embeddings", None) or []
        if len(embeddings) != len(texts):
            raise LLMError(
                f"Embedding API returned {len(embeddings)} embeddings for {len(texts)} inputs"
            )
        values = [list(item.values) for item in embeddings]
        if any(not vector for vector in values):
            raise LLMError("Embedding API returned an empty vector")
        return values
