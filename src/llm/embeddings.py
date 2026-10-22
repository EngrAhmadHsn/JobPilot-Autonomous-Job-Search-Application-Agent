"""Embedding layer for semantic matching (WS-03).

Two interchangeable ``EmbeddingFn`` providers sit behind a small protocol so
callers (the Chroma store, the matching pipeline) swap providers and test
fakes freely:

- ``FastembedEmbedding`` (FU-7 default): EmbeddingGemma-2 (text-only, int8
  ONNX) runs locally in-process via fastembed — milliseconds of CPU per call,
  zero marginal cost, no API quota. The model is downloaded once into
  ``FASTEMBED_CACHE_PATH`` (default ``data/fastembed``) and loaded lazily.
- ``GeminiEmbedding``: the Gemini embedding API, kept selectable for A/B and
  fallback (free-tier RPD 20 x 100-text batches ~= 2,000 texts/day). Its FU-4
  quota management stays dormant but fully functional.

``build_embedding_fn(settings)`` is the single factory both production
construction sites call; ``EMBEDDING_PROVIDER`` selects the provider.

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

Both providers share the same text contract as ``gemini-embedding-2``:
asymmetric ``MODEL_PREFIX_DOC`` / ``MODEL_PREFIX_QUERY`` prefixes are applied
by the *callers* (``build_document_text`` / ``build_query_text``, the Chroma
store), never inside the provider, so the two providers see byte-identical
inputs and A/B comparisons are exact. Every vector a Gemini call produces is
cached in ``data/embedding_cache.sqlite`` keyed by ``sha256(model|dim|text)``;
the same database keeps a persistent UTC-day counter of successful API batch
requests (FU-4): the Gemini path paces batches at the configured RPM limit,
refuses to call once the day's request budget is spent (raising
``LLMDailyQuotaExhausted`` so callers stop cleanly and resume after the
reset), and exposes ``estimate_api_requests`` so the daily refresh can plan
its spend. The local provider needs neither cache nor budget hooks — it makes
no API requests at all, and the refresh's ``getattr``-guarded accounting
hooks already tolerate their absence (planned/used stay 0).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from array import array
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from src.config.settings import Settings, ensure_dir, get_settings
from src.llm.client import (
    LLMConfigError,
    LLMDailyQuotaExhausted,
    LLMError,
    LLMRateLimited,
    classify_provider_error,
)

logger = logging.getLogger(__name__)

MODEL_PREFIX_DOC = "title: {title} | text: {body}"
MODEL_PREFIX_QUERY = "task: search result | query: {text}"

# The local EmbeddingGemma-2 model has an 8,192-token context window;
# ~8,000 characters of description stays comfortably within ~2,000 tokens.
MAX_TEXT_CHARS = 8_000

# -- FU-7: local provider (fastembed + EmbeddingGemma-2, text-only) -------------

# HF repo holding the official ONNX exports. The fp16 variants in this repo
# are FORBIDDEN by the model card (fp16 overflow -> NaNs); only the int8 and
# fp32 graphs below may ever be registered.
FASTEMBED_HF_REPO = "onnx-community/embeddinggemma-2-ONNX"

# Embedding identity (settings/cache keys) -> ONNX graph files. The @variant
# suffix is identity, not decoration: it flows into every cache key and the
# Chroma collection metadata, so a variant switch is structurally forced into
# a clean re-embed instead of silently mixing embedding spaces.
FASTEMBED_VARIANT_FILES: dict[str, tuple[str, list[str]]] = {
    "int8": ("onnx/model_quantized.onnx", ["onnx/model_quantized.onnx_data"]),
    "fp32": ("onnx/model.onnx", ["onnx/model.onnx_data"]),
}
FASTEMBED_DIMENSION = 768

# Open-item finding (FU-7, verified live 2026-10-11): the ONNX export ships
# transformers' "unknown" sentinel as model_max_length (1e30-ish), and
# fastembed refuses to guess a truncation limit from it — first load raises
# ValueError. The model card documents an 8,192-token context window, so the
# LOCAL CACHE COPY of tokenizer_config.json is patched to the real cap before
# load. Safe against fastembed's cache-integrity check: only the ONNX graph
# and its external data file are size-verified strictly; other files load
# best-effort. 6,000-char inputs (~1,500-2,000 tokens) stay well inside it.
FASTEMBED_TOKENIZER_CONTEXT = 8_192

# Registered per process (fastembed keeps a module-level registry; a second
# registration of the same name raises).
_fastembed_registered: set[str] = set()

# One loaded ONNX session per registered variant (shared across instances).
_fastembed_loaded_models: dict[str, Any] = {}


def parse_gemma_identity(model: str) -> str | None:
    """``google/embeddinggemma-2@<variant>`` -> variant, else None."""
    prefix = "google/embeddinggemma-2@"
    if not model.startswith(prefix):
        return None
    return model[len(prefix) :]


def fastembed_cache_dir(settings: Settings | None = None) -> str:
    """Model-weights cache directory (FASTEMBED_CACHE_PATH or data/fastembed).

    Shared by the provider and the API warm-up so both resolve the same
    location and the warm-up's is-cached check is authoritative.
    """
    settings = settings or get_settings()
    return os.getenv("FASTEMBED_CACHE_PATH") or str(Path(settings.data_dir) / "fastembed")


def ensure_tokenizer_context(cache_dir: str, hf_repo: str = FASTEMBED_HF_REPO) -> None:
    """Patch a sentinel ``model_max_length`` in the cached tokenizer config.

    Open-item finding (FU-7, verified live 2026-10-11): the ONNX export ships
    transformers' "unknown" sentinel (~1e30) as ``model_max_length`` and
    fastembed refuses to guess a truncation limit from it — first load raises
    ValueError. The model card documents an 8,192-token context window.

    The patch is **byte-length-preserving**: the sentinel digits are replaced
    in place with the real cap padded by spaces (valid JSON whitespace). This
    matters because fastembed's post-download verification compares local file
    sizes against REMOTE sizes — a resized tokenizer_config.json makes every
    later download report "corrupted" (found live the hard way). Runs before
    every ``TextEmbedding`` construction; no-op when the model is not
    downloaded yet or the cap is already usable. Idempotent.
    """
    import re
    import sys

    snapshots = Path(cache_dir) / f"models--{hf_repo.replace('/', '--')}" / "snapshots"
    if not snapshots.exists():
        return
    for snapshot in snapshots.iterdir():
        config_path = snapshot / "tokenizer_config.json"
        if not config_path.is_file():
            continue
        try:
            raw = config_path.read_text(encoding="utf-8")
        except OSError:
            continue
        match = re.search(r'"model_max_length"\s*:\s*(\d+)', raw)
        if match is None:
            continue
        value = int(match.group(1))
        if 0 < value <= sys.maxsize:
            continue  # already usable
        cap_digits = str(FASTEMBED_TOKENIZER_CONTEXT)
        sentinel_digits = match.group(1)
        if len(sentinel_digits) < len(cap_digits):
            # Sentinel shorter than the cap cannot be padded in place; the
            # transformers sentinel is 31 digits, so this is unreachable in
            # practice — leave the cache untouched rather than break the
            # size-verified download.
            logger.error(
                "Cannot patch %s in place (sentinel shorter than cap); local model load may fail",
                config_path,
            )
            continue
        replacement = cap_digits + " " * (len(sentinel_digits) - len(cap_digits))
        try:
            config_path.write_text(
                raw[: match.start(1)] + replacement + raw[match.end(1) :], encoding="utf-8"
            )
        except OSError:
            logger.warning("Could not patch %s; load may fail on the context cap", config_path)
            continue
        logger.warning(
            "Patched %s: model_max_length sentinel -> %d (model card context window, "
            "byte-length-preserving)",
            config_path,
            FASTEMBED_TOKENIZER_CONTEXT,
        )


def _register_gemma_variant(variant: str) -> str:
    """Register one EmbeddingGemma-2 ONNX variant with fastembed (idempotent).

    Mirrors FU-7 Spec 3: the graph mean-pools and L2-normalizes internally, so
    fastembed post-processing is disabled and the ``sentence_embedding``
    output is selected explicitly (validated at load time by fastembed).
    The download is pattern-restricted: only the named graph, its external
    data file, and tokenizer/config JSONs are ever fetched — the vision/audio
    encoders in the same repo are not.
    """
    registration_name = f"{FASTEMBED_HF_REPO}:{variant}"
    if registration_name in _fastembed_registered:
        return registration_name
    try:
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType
    except ImportError as exc:  # pragma: no cover - environment issue
        raise LLMConfigError(
            "fastembed is not installed; add it to the environment (pyproject declares it)"
        ) from exc
    if variant not in FASTEMBED_VARIANT_FILES:
        raise LLMConfigError(
            f"Unsupported EmbeddingGemma-2 variant {variant!r}; supported: "
            f"{sorted(FASTEMBED_VARIANT_FILES)} (fp16 is forbidden by the model card)"
        )
    model_file, additional_files = FASTEMBED_VARIANT_FILES[variant]
    try:
        TextEmbedding.add_custom_model(
            model=registration_name,
            pooling=PoolingType.DISABLED,  # graph mean-pools internally
            normalization=False,  # graph L2-normalizes internally
            sources=ModelSource(hf=FASTEMBED_HF_REPO),
            dim=FASTEMBED_DIMENSION,
            model_file=model_file,
            additional_files=additional_files,
            output_name="sentence_embedding",  # explicit: validated at load time
        )
    except ValueError as exc:
        # Re-registration inside one process (e.g. two embedders built) is fine;
        # anything else is a real registration problem.
        if "already registered" not in str(exc):
            raise
    _fastembed_registered.add(registration_name)
    return registration_name


class _TextOnlySession:
    """Session shim making the fused multimodal graph text-only (FU-7 open item 2).

    Open-item finding, verified live 2026-10-11: the embeddinggemma-2 ONNX
    graph *requires* ``image_features``/``video_features``/``audio_features``
    ([num_tokens, 512] each) — fastembed feeds only ``input_ids`` +
    ``attention_mask``, so the raw session rejects every text-only call. The
    shim injects zero-filled [0, 512] feature tensors for the missing inputs;
    verified live, a zero-fill run is L2-normalized (norm 1.0) and produces
    byte-identical sentence embeddings for 0 and 1 filler rows, i.e. the
    features are genuinely unused for text-only inputs.
    """

    # onnxruntime only exposes .run() to fastembed's embed path; the
    # accessors are forwarded so any introspection keeps working.
    def __init__(self, session: Any) -> None:
        import numpy as np

        self._np = np
        self._session = session
        self._feature_shapes = {
            item.name: item.shape
            for item in session.get_inputs()
            if item.name not in ("input_ids", "attention_mask")
        }

    def run(self, output_names: Any, feed: dict) -> Any:
        for name, shape in self._feature_shapes.items():
            if name in feed:
                continue
            dims = [dim if isinstance(dim, int) and dim > 0 else 0 for dim in shape]
            feed[name] = self._np.zeros(dims, dtype=self._np.float32)
        return self._session.run(output_names, feed)

    def get_inputs(self):
        return self._session.get_inputs()

    def get_outputs(self):
        return self._session.get_outputs()

    def get_modelmeta(self):
        return self._session.get_modelmeta()


class FastembedEmbedding:
    """Local in-process EmbeddingFn: fastembed + EmbeddingGemma-2 (FU-7 default).

    No API, no quota, no cache: every embed call is milliseconds of CPU. The
    ONNX model is loaded lazily (so constructing the class is safe without the
    weights on disk — construction never downloads), the weights live under
    ``FASTEMBED_CACHE_PATH`` (default ``data/fastembed``), and offline tests
    inject a ``text_embedding`` double (mirroring ``GeminiEmbedding``'s
    ``client=``).

    Text contract is identical to ``GeminiEmbedding``: callers apply the
    asymmetric prefixes (``build_document_text`` / ``build_query_text``), this
    class only truncates at ``MAX_TEXT_CHARS`` — the two providers therefore
    see byte-identical inputs and A/B comparisons are exact.
    """

    MODEL_PREFIX_DOC = MODEL_PREFIX_DOC
    MODEL_PREFIX_QUERY = MODEL_PREFIX_QUERY
    MAX_TEXT_CHARS = MAX_TEXT_CHARS
    # fastembed's own default (256) OOMs outright on ~2,000-token job documents
    # (live-verified: ~2.4 GB single buffer); the int8 graph's MatMulNBits
    # dequantization buffers still exhaust 9 GiB free at 16 (live-verified), so
    # 8 is the largest verified-safe batch. Local CPU embed cost is dominated
    # by per-document compute, so the small batch costs nothing.
    FASTEMBED_BATCH_SIZE = 8

    def __init__(
        self,
        *,
        model: str | None = None,
        dimensionality: int | None = None,
        cache_dir: str | None = None,
        text_embedding: Any = None,
        cache_path: str | Path | None = None,
    ) -> None:
        settings = get_settings()
        self.model = model or settings.embedding_model
        self.dimensionality = dimensionality or settings.embedding_dimensionality
        self._cache_dir = cache_dir or fastembed_cache_dir(settings)
        self._injected_model = text_embedding
        self._model: Any = None
        # The same content-hash cache the Gemini path uses. The local provider
        # makes no API calls, but the cache is what keeps the daily refresh
        # (FU-1) incremental: without it every refresh would re-embed the
        # whole corpus (~4.3 s/doc locally), instead of embedding only the
        # new or changed listings.
        if cache_path is None:
            cache_path = Path(settings.data_dir) / "embedding_cache.sqlite"
        self._cache = EmbeddingCache(cache_path)

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        if self._injected_model is not None:
            self._model = self._injected_model
            return self._model
        variant = parse_gemma_identity(self.model)
        if variant is None:
            raise LLMConfigError(
                f"EMBEDDING_MODEL {self.model!r} is not a supported local identity "
                f"(google/embeddinggemma-2@{sorted(FASTEMBED_VARIANT_FILES)}); "
                "set EMBEDDING_PROVIDER=gemini for API models"
            )
        if self.dimensionality != FASTEMBED_DIMENSION:
            raise LLMConfigError(
                f"EmbeddingGemma-2 is {FASTEMBED_DIMENSION}-dimensional; "
                f"EMBEDDING_DIMENSIONALITY is {self.dimensionality}"
            )
        from fastembed import TextEmbedding

        ensure_tokenizer_context(self._cache_dir)
        registration_name = _register_gemma_variant(variant)
        shared = _fastembed_loaded_models.get(registration_name)
        if shared is not None:
            self._model = shared
            return self._model
        logger.info(
            "Loading local embedding model %s (weights cached under %s)",
            registration_name,
            self._cache_dir,
        )
        self._model = TextEmbedding(
            model_name=registration_name,
            cache_dir=self._cache_dir,
            providers=["CPUExecutionProvider"],
        )
        # The fused graph needs multimodal feature inputs fastembed never feeds
        # (verified live): wrap the onnxruntime session (TextEmbedding.model is
        # the embedding object; its .model is the session) so every text-only
        # call succeeds.
        self._model.model.model = _TextOnlySession(self._model.model.model)
        # One shared session per variant: the ONNX arenas are large (two
        # resident fp32 sessions exhausted RAM mid-batch, live-verified), and
        # the API warm-up, the store, and the executor all build their own
        # FastembedEmbedding instances.
        _fastembed_loaded_models[registration_name] = self._model
        return self._model

    # -- public API ---------------------------------------------------------

    @staticmethod
    def _cache_limit() -> int:
        """The cap on the number of vectors the embedding cache may hold."""
        from src.security.limits import get_limits

        return get_limits().max_cache_entries

    def is_cached(self, texts: list[str]) -> list[bool]:
        """Which of *texts* already have a vector in the cache.

        WS-15: the refresh asks this before it plans its embedding work, so
        the budget can be denominated in the embeddings that actually cost
        something (the misses) rather than in the listings that happen to
        be at the front of a board's response.
        """
        if not texts:
            return []
        return [
            self._cache.get(
                EmbeddingCache.key(self.model, self.dimensionality, self._truncate(text))
            )
            is not None
            for text in texts
        ]

    def remaining_work_budget(self) -> int:
        """Documents that may still be embedded today (the daily work cap).

        WS-15: the local provider has no provider quota to spend, so before
        this counter the flood had no ceiling across time at all. The count
        is persistent (it lives in the cache database), so restarting the
        process does not hand the attacker a fresh budget.
        """
        return max(0, self._work_limit() - self._cache.work_today())

    @staticmethod
    def _work_limit() -> int:
        """The cap on the documents one UTC day may embed."""
        from src.security.limits import get_limits

        return get_limits().max_embed_work_per_day

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed N documents, returning exactly N vectors in input order.

        Cache hits never reach the model: the shared content-hash cache
        (``sha256(model|dim|text)``) makes a repeat corpus embedding free and
        keeps the daily refresh incremental. The cache key carries the model
        identity, so the local (``@int8``) and Gemini spaces can never mix.
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
            # WS-15: the daily work budget. A flood that spreads itself
            # over many refreshes must still hit a ceiling, and the stop
            # has to be a *clean* one: the rows stay persisted, the cache
            # keeps the completed work, and the next day resumes.
            remaining = self.remaining_work_budget()
            if remaining < len(misses):
                raise LLMDailyQuotaExhausted(
                    f"Daily embedding work budget spent "
                    f"({self._work_limit()} documents/day); "
                    "stopping cleanly — resume after the daily reset"
                )
            fresh = self._embed_local([text for _, text in misses])
            if len(fresh) != len(misses):
                raise LLMError(
                    f"Local embedder returned {len(fresh)} vectors for {len(misses)} inputs; "
                    "refusing to misalign results"
                )
            for (index, text), vector in zip(misses, fresh):
                vectors[index] = vector
                self._cache.put(
                    EmbeddingCache.key(self.model, self.dimensionality, text),
                    self.model,
                    self.dimensionality,
                    vector,
                )
            # The work is counted only once it has actually been done.
            self._cache.record_work(len(misses))
            self._cache.prune_if_needed(self._cache_limit())
        return [vectors[index] for index in range(len(texts))]

    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        """Run the local model over texts that missed the cache."""
        raw = self._ensure_model().embed(texts, batch_size=self.FASTEMBED_BATCH_SIZE)
        return [[float(value) for value in vector] for vector in raw]

    def embed_query(self, text: str) -> list[float]:
        """Embed one query, and **never cache it** (WS-14 · Phase G).

        The query is the candidate's own text — their title, their
        skills, their summary. The corpus embeddings are shared board
        data and are worth caching; a candidate's vector is not shared
        data, and a shared cache that holds it is two problems at once:

        - a cache hit on an identical profile tells a second tenant
          that somebody else submitted the same text;
        - the stored vector is a fingerprint of the candidate, and a
          vector can be inverted far enough to say what the text was
          about.

        So the query is embedded fresh every time and never written to
        the disk. The cost is one embedding call per search, which for
        the local provider is milliseconds.
        """
        return self._embed_local([self._truncate(text)])[0]

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


def build_embedding_fn(settings: Settings | None = None) -> EmbeddingFn:
    """Single factory for production embedding providers (FU-7).

    ``EMBEDDING_PROVIDER`` selects: ``fastembed`` (local, default) or
    ``gemini`` (API, A/B + fallback). Settings already fail fast on unknown
    values; the re-check here keeps the factory safe for direct callers.
    """
    settings = settings or get_settings()
    if settings.embedding_provider == "fastembed":
        return FastembedEmbedding()
    if settings.embedding_provider == "gemini":
        return GeminiEmbedding()
    raise LLMConfigError(
        f"Unknown EMBEDDING_PROVIDER {settings.embedding_provider!r}; "
        "expected 'fastembed' or 'gemini'"
    )


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

    The same database holds the persistent ``api_requests`` UTC-day counter
    (FU-4): successful API batch requests, counted across process restarts so
    the daily budget is accurate even when the backfill and the app alternate.

    WS-12: the table is bounded. Every unique text earns a row, so a flood
    of fake listings would grow it without limit — the disk-exhaustion half
    of the embedding-flood attack. :meth:`prune` drops the oldest rows once
    the cap is passed.
    """

    #: How many writes happen between two real row counts. Counting is a
    #: full scan, and the table is exactly what a flood makes large.
    _PRUNE_CHECK_INTERVAL = 256

    def __init__(self, path: str | Path) -> None:
        target = Path(path)
        ensure_dir(target.parent)
        self._conn = sqlite3.connect(target)
        self._writes_since_prune = 0
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS embeddings ("
            " key TEXT PRIMARY KEY,"
            " model TEXT NOT NULL,"
            " dim INTEGER NOT NULL,"
            " vector BLOB NOT NULL,"
            " created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        # WS-12: the eviction order is "oldest first", and the order has to
        # be cheap to read. Without this index every prune is a full sort of
        # the table, which is exactly the cost a flooding corpus creates.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_embeddings_created_at ON embeddings (created_at)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS api_requests ("
            " day TEXT PRIMARY KEY,"
            " count INTEGER NOT NULL)"
        )
        # WS-14 · Phase G: the per-tenant spend, next to the platform's
        # own counter. The two have to live together: the fair share is
        # computed from both, and a counter in one place and a counter
        # in another is two truths.
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS tenant_spend ("
            " day TEXT NOT NULL,"
            " owner_id TEXT NOT NULL,"
            " count INTEGER NOT NULL,"
            " PRIMARY KEY (day, owner_id))"
        )
        # WS-15: the daily **embedding work** counter. The API provider
        # counts batch requests against a quota; the local provider has no
        # quota to spend, so without this the flood had no ceiling at all
        # across time — 2,000 embeddings per refresh, every refresh,
        # forever. The counter counts the *documents actually embedded*
        # (the cache misses), and it lives next to the vectors, so a
        # restart does not hand the attacker a fresh budget.
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS embed_work ( day TEXT PRIMARY KEY, count INTEGER NOT NULL)"
        )
        self._conn.commit()

    @property
    def connection(self):
        """The cache's SQLite connection.

        The per-tenant spend counters live in this database, next to the
        platform's own daily request counter (WS-14 · Phase G), so the
        fair share is computed from two counters that are always
        consistent with each other.
        """
        return self._conn

    @staticmethod
    def _utc_day() -> str:
        return datetime.now(UTC).date().isoformat()

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

    def count(self) -> int:
        """How many vectors the cache holds."""
        row = self._conn.execute("SELECT count(*) FROM embeddings").fetchone()
        return int(row[0]) if row else 0

    def prune_if_needed(self, max_entries: int) -> int:
        """Prune the cache when it has grown past *max_entries*.

        The count is only taken when this process has written enough rows to
        make it plausible, because ``count(*)`` is a full scan of the table
        and the table is exactly what a flooding corpus makes large. The
        in-process counter is therefore the fast path and the real count is
        the confirmation.
        """
        self._writes_since_prune += 1
        if self._writes_since_prune < self._PRUNE_CHECK_INTERVAL:
            return 0
        self._writes_since_prune = 0
        if self.count() <= max_entries:
            return 0
        return self.prune(max_entries)

    def prune(self, max_entries: int) -> int:
        """Drop the oldest vectors until at most *max_entries* remain.

        WS-12: the cache is a permanent table, so without a bound it grows
        until the disk is full — and a flood of unique fake listings is the
        cheapest way to fill it, because every one of them is a cache miss
        that earns a row. The oldest entries go first: a listing that has
        not been re-embedded in a long time is the least likely to be
        embedded again.

        Returns:
            The number of entries removed.
        """
        if max_entries < 1:
            return 0
        total = self.count()
        excess = total - max_entries
        if excess <= 0:
            return 0
        # Delete in one statement: the oldest rows, by insertion order.
        self._conn.execute(
            "DELETE FROM embeddings WHERE key IN ("
            "  SELECT key FROM embeddings ORDER BY created_at ASC, rowid ASC LIMIT ?"
            ")",
            (excess,),
        )
        self._conn.commit()
        logger.info("Pruned %d embedding cache entries (cap %d)", excess, max_entries)
        return excess

    def record_api_request(self) -> int:
        """Count one successful API batch request for the current UTC day.

        Returns the day's running total.
        """
        day = self._utc_day()
        self._conn.execute(
            "INSERT INTO api_requests (day, count) VALUES (?, 1) "
            "ON CONFLICT(day) DO UPDATE SET count = count + 1",
            (day,),
        )
        self._conn.commit()
        row = self._conn.execute("SELECT count FROM api_requests WHERE day = ?", (day,)).fetchone()
        return int(row[0])

    def requests_today(self) -> int:
        row = self._conn.execute(
            "SELECT count FROM api_requests WHERE day = ?", (self._utc_day(),)
        ).fetchone()
        return int(row[0]) if row else 0

    def record_work(self, count: int = 1) -> int:
        """Count *count* documents as embedded today; return the day's total.

        WS-15: this is the counter that bounds the embedding flood **over
        time**, not over one refresh. It counts documents that were actually
        embedded — the cache misses — because a cache hit costs a lookup
        and nothing else, and a limit that counted hits would be a limit on
        the wrong thing.
        """
        if count <= 0:
            return self.work_today()
        day = self._utc_day()
        self._conn.execute(
            "INSERT INTO embed_work (day, count) VALUES (?, ?) "
            "ON CONFLICT(day) DO UPDATE SET count = count + ?",
            (day, count, count),
        )
        self._conn.commit()
        return self.work_today()

    def work_today(self) -> int:
        """How many documents have been embedded today (the UTC day)."""
        row = self._conn.execute(
            "SELECT count FROM embed_work WHERE day = ?", (self._utc_day(),)
        ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        self._conn.close()


class GeminiEmbedding:
    """Default EmbeddingFn: Gemini ``embed_content`` with a SQLite cache.

    The genai client is created lazily (and never when one is injected), so
    constructing this class is safe without configuration; only an actual
    embed call without a key raises ``LLMConfigError``.

    FU-4 quota management (real API path only — injected test clients are
    neither paced nor budget-gated): batches are paced at
    ``60 / EMBEDDING_RPM_LIMIT`` seconds, the persistent daily counter gates
    calls once ``EMBEDDING_RPD_LIMIT`` successful batch requests are spent
    (raising ``LLMDailyQuotaExhausted`` so callers stop cleanly and resume
    after the UTC-day reset), and per-minute 429s are retried a bounded
    number of times before raising so interactive callers degrade instead of
    hanging.
    """

    MODEL_PREFIX_DOC = MODEL_PREFIX_DOC
    MODEL_PREFIX_QUERY = MODEL_PREFIX_QUERY
    MAX_TEXT_CHARS = MAX_TEXT_CHARS
    # Live-verified cap (2026-10-11): BatchEmbedContentsRequest rejects >100.
    API_BATCH_SIZE = 100
    # Per-minute 429 handling: bounded retries (65s respects RPM 5 with
    # margin), then raise — a search must degrade, not stall for hours.
    RATE_LIMIT_RETRIES = 2
    RATE_LIMIT_WAIT_SECONDS = 65.0

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        dimensionality: int | None = None,
        cache_path: str | Path | None = None,
        client: Any = None,
        rpm_limit: int | None = None,
        rpd_limit: int | None = None,
    ) -> None:
        settings = get_settings()
        self.model = model or settings.embedding_model
        self.dimensionality = dimensionality or settings.embedding_dimensionality
        self._rpm_limit = rpm_limit or settings.embedding_rpm_limit
        self._rpd_limit = rpd_limit or settings.embedding_rpd_limit
        self._min_request_interval = 60.0 / max(1, self._rpm_limit)
        self._last_request_at: float | None = None
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

    @staticmethod
    def _cache_limit() -> int:
        """The cap on the number of vectors the embedding cache may hold."""
        from src.security.limits import get_limits

        return get_limits().max_cache_entries

    @staticmethod
    def _work_limit() -> int:
        """The cap on the documents one UTC day may embed."""
        from src.security.limits import get_limits

        return get_limits().max_embed_work_per_day

    def is_cached(self, texts: list[str]) -> list[bool]:
        """Which of *texts* already have a vector in the cache.

        WS-15: the refresh asks this before it plans its embedding work, so
        the budget can be denominated in the embeddings that actually cost
        something (the misses) rather than in the listings that happen to
        be at the front of a board's response.
        """
        if not texts:
            return []
        return [
            self._cache.get(
                EmbeddingCache.key(self.model, self.dimensionality, self._truncate(text))
            )
            is not None
            for text in texts
        ]

    def remaining_work_budget(self) -> int:
        """Documents that may still be embedded today (the daily work cap).

        WS-15: the same ceiling the local provider has, so the two
        providers are bounded the same way. The API provider's own quota
        (batch requests per day) is the tighter of the two in practice;
        this is the one that counts the documents.
        """
        return max(0, self._work_limit() - self._cache.work_today())

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed N documents, returning exactly N vectors in input order.

        Cache hits never touch the API; only misses are sent, each as its own
        ``contents`` entry (the aggregation gotcha: a joined string would come
        back as a single blended vector). Misses are sent in batches of
        ``API_BATCH_SIZE`` — the live API caps a batch at 100 requests and
        rejects larger calls outright (found live at 4,314-job scale).
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
            fresh: list[list[float]] = []
            for start in range(0, len(misses), self.API_BATCH_SIZE):
                fresh.extend(
                    self._embed_with_quota(
                        [text for _, text in misses[start : start + self.API_BATCH_SIZE]]
                    )
                )
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
            # WS-15: the work is counted only once it has actually been
            # done, and the count is the documents, not the batches.
            self._cache.record_work(len(misses))
            self._cache.prune_if_needed(self._cache_limit())
        return [vectors[index] for index in range(len(texts))]

    def embed_query(self, text: str) -> list[float]:
        """Embed one query, and **never cache it** (WS-14 · Phase G).

        The same reasoning as the local provider, with one extra cost:
        the query is the candidate's own text, so it never goes into the
        shared cache — and on this provider a cache miss is a real API
        call, so the per-tenant fair share below is what keeps one
        tenant's searches from spending everybody's quota.
        """
        return self._embed_with_quota([self._truncate(text)])[0]

    # -- quota budget (FU-4) --------------------------------------------------

    def remaining_daily_budget(self) -> int:
        """Successful API batch requests left today (persistent UTC counter)."""
        return max(0, self._rpd_limit - self._cache.requests_today())

    def estimate_api_requests(self, texts: list[str]) -> int:
        """How many API batch requests ``texts`` would cost right now.

        Counts cache misses (identical preparation to ``embed_documents``) in
        ``API_BATCH_SIZE``-sized batches — the daily refresh (FU-1) uses this
        to plan the day's embedding spend before spending it.
        """
        if not texts:
            return 0
        misses = 0
        for text in texts:
            prepared = self._truncate(text)
            if (
                self._cache.get(EmbeddingCache.key(self.model, self.dimensionality, prepared))
                is None
            ):
                misses += 1
        return -(-misses // self.API_BATCH_SIZE)  # ceil division

    def _throttle(self) -> None:
        """Space real API calls at least ``60 / rpm_limit`` seconds apart."""
        if self._last_request_at is not None:
            remaining = self._min_request_interval - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _embed_with_quota(self, texts: list[str]) -> list[list[float]]:
        """One batch call under pacing + daily budget (real API path only).

        Injected test clients skip pacing, budget gating, and recording —
        their call patterns are asserted directly by tests.
        """
        real_path = self._injected_client is None
        if real_path:
            if self.remaining_daily_budget() <= 0:
                raise LLMDailyQuotaExhausted(
                    f"Embedding daily budget spent ({self._rpd_limit} batch requests/day); "
                    "stopping cleanly — resume after the daily reset (cache keeps progress)"
                )
            # WS-14 · Phase G: the fair share. A tenant may not spend
            # more than its share of the platform's daily budget, so one
            # tenant's searches cannot starve the others (threat T7).
            self._assert_tenant_allowance()
            self._throttle()
        attempts = 0
        while True:
            try:
                vectors = self._embed_api(texts)
                break
            except LLMDailyQuotaExhausted:
                raise  # the provider itself says the day is spent: stop now
            except LLMRateLimited:
                if not real_path or attempts >= self.RATE_LIMIT_RETRIES:
                    raise
                attempts += 1
                logger.warning(
                    "Embedding rate limited (attempt %d/%d); sleeping %.0fs before retry",
                    attempts,
                    self.RATE_LIMIT_RETRIES,
                    self.RATE_LIMIT_WAIT_SECONDS,
                )
                time.sleep(self.RATE_LIMIT_WAIT_SECONDS)
                self._throttle()
        if real_path:
            used = self._cache.record_api_request()
            logger.info(
                "Embedding API batch request recorded: %d/%d used today (UTC counter)",
                used,
                self._rpd_limit,
            )
            # The spend is attributed to the tenant, so "who spent the
            # quota" has an answer and the fair share can be computed.
            from src.llm.tenant import current_tenant, record_spend

            tenant = current_tenant()
            if tenant:
                record_spend(self._cache.connection, tenant)
        return vectors

    def _assert_tenant_allowance(self) -> None:
        """Refuse the call when the tenant has spent its share.

        The share is the platform's daily budget divided by the number
        of tenants that have spent today. A single tenant has the whole
        budget; a second tenant halves it, and the budget that is left
        goes to whichever tenant has used less.
        """
        from src.llm.tenant import TenantBudgetExceeded, current_tenant, tenant_allowance

        if not current_tenant():
            return
        allowance = tenant_allowance(self._cache.connection, self._rpd_limit)
        if allowance <= 0:
            raise TenantBudgetExceeded(
                "This account has used its share of the embedding budget for today "
                f"({self._rpd_limit} batch requests/day, shared between the accounts "
                "that are using it). Try again after the daily reset."
            )

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
