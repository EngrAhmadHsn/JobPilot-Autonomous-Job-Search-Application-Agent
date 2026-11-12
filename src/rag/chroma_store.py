"""Real Chroma-backed vector store for job listings (WS-03).

Persists normalized listings as embedding vectors in a Chroma persistent
collection and answers candidate-vs-listing semantic queries. Embeddings flow
through the shared ``EmbeddingFn`` (``build_embedding_fn`` picks the
production provider; FastembedEmbedding by default since FU-7), so the SQLite
content-hash cache applies to every store write and query on the Gemini path —
a repeat run makes zero API calls.

Design points:

- Cosine space (``hnsw.space=cosine``), as recommended for
  ``gemini-embedding-2``; cosine distance ``d`` maps to similarity
  ``sim = (1 - d) * 100`` clamped to 0-100.
- The collection metadata records the embedding model and dimensionality.
  Embedding spaces are version-locked: opening a store built with a different
  model/dimension raises ``VectorStoreMismatch`` with re-embed instructions
  instead of silently mixing incompatible vectors.
- Chroma ids are the stable ``JobListing.id`` values, so re-upserting a
  listing updates its vector in place (no duplicates).
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.errors import NotFoundError

from src.config.settings import Settings, ensure_dir, get_settings
from src.jobs.contracts import JobListing
from src.llm.embeddings import (
    EmbeddingFn,
    ProgressHook,
    build_document_text,
    build_embedding_fn,
    build_query_text,
)
from src.resume.profile import CandidateProfile

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION_NAME = "job_listings"

# Embedding/upsert chunk size: aligned with the API batch cap so a fully
# missed chunk is exactly one batch request (FU-1 resumability, FU-4 budget).
EMBED_BATCH_SIZE = 100

#: How many characters of the description go into the embedded document.
#:
#: WS-24: this was 8,000, which was the binding constraint on what the local
#: embedding model saw — not the model. EmbeddingGemma-2 accepts 8,192
#: **tokens**, which is roughly 32,000 characters of English prose, so the
#: 8,000-character cap truncated four-fifths of what the model could read.
#: The cap now sits at 16,000 characters, comfortably inside the model's
#: token budget and still bounded.
#:
#: It matches the provider's own ``MAX_TEXT_CHARS`` (also 16,000), so
#: there is exactly one place where the limit is expressed and no
#: second, quieter truncation underneath it.
#:
#: The contract cap (``max_description_chars``, default 20,000) is separate
#: and unchanged: it bounds the **stored** description, this bounds the
#: **embedded** text.
MAX_DESCRIPTION_CHARS = 16_000

#: How many vectors are loaded per page in the full-corpus similarity scan.
#: The scan is bounded so the peak memory is this, not the corpus size.
SCAN_PAGE_SIZE = 500

#: How many corpus scans to memoize **in this process** (WS-24c).
_PROCESS_SCAN_ENTRIES = 4

#: How long a memoized scan may be served, in seconds (WS-24c).
#:
#: The memo is cleared when *this* process writes a vector, but the embedding
#: worker is a separate process: it can upsert or evict vectors while the API
#: holds a scan. Without a bound, such a write would stay invisible until the
#: API restarted. Two minutes is long enough that an operator narrowing
#: filters (which do not change the semantic query) keeps hitting the memo,
#: and short enough that a background refresh surfaces promptly.
_PROCESS_SCAN_TTL_SECONDS = 120.0

#: The in-process memo of full-corpus scans, keyed by the query text and the
#: collection state the scan was computed against.
#:
#: This is **not** the persistent cache WS-14 · Phase G forbids. That rule
#: names two harms, and both are properties of a *shared, durable* cache:
#:
#: - a hit on identical profile text would tell a second tenant that somebody
#:   else had submitted the same text, and
#: - the stored vector is a fingerprint of the candidate, and a vector can be
#:   inverted far enough to say what the text was about.
#:
#: A process-local dictionary is neither shared across tenants nor durable:
#: nothing is written to disk, nothing is logged, and the entry dies with the
#: process. Two tenants cannot collide here for the same reason they cannot
#: collide in ``CandidateContext`` — the key is derived from the text itself,
#: so an identical match requires an identical text, and a tenant holding the
#: db cannot read another's key.
#:
#: The value is a *similarity map*, not a vector, so it is not invertible into
#: the candidate's prose at all. The key carries only a digest of the text for
#: the same reason.
_PROCESS_SCAN: OrderedDict[tuple[str, str, int], tuple[float, dict[str, float]]] = OrderedDict()


def _remember_scan(key: tuple[str, str, int], scores: dict[str, float]) -> None:
    """Store one scan, bounding the memo (WS-24c)."""
    _PROCESS_SCAN[key] = (time.monotonic(), dict(scores))
    _PROCESS_SCAN.move_to_end(key)
    while len(_PROCESS_SCAN) > _PROCESS_SCAN_ENTRIES:
        _PROCESS_SCAN.popitem(last=False)


def _recall_scan(key: tuple[str, str, int]) -> dict[str, float] | None:
    """The memoized scan for ``key``, or ``None`` when absent or expired."""
    entry = _PROCESS_SCAN.get(key)
    if entry is None:
        return None
    stored_at, scores = entry
    if time.monotonic() - stored_at > _PROCESS_SCAN_TTL_SECONDS:
        _PROCESS_SCAN.pop(key, None)
        return None
    _PROCESS_SCAN.move_to_end(key)
    return dict(scores)


def clear_process_scan_cache() -> None:
    """Drop every memoized scan (tests; operational use)."""
    _PROCESS_SCAN.clear()


#: How many resident matrix entries to keep. One is enough for one corpus: at
#: 24 MB for the live 7,666 vectors, keeping a second corpus state to avoid a
#: 1.04 s rebuild after a flip is not worth the bookkeeping.
_VECTOR_MATRIX_ENTRIES = 1

#: The resident copy of the corpus's normalized vectors, keyed by the same
#: scope the scan memo uses (``persist dir | collection name``).
#:
#: Each value is ``(stored_at, id_count, ids, unit_matrix, degenerate)``:
#:
#: - ``stored_at`` drives the TTL, for the same reason the scan memo has one —
#:   the embedding worker is a separate process, so a write it makes is
#:   invisible here until the count changes or the TTL expires;
#: - ``id_count`` is what makes that write visible at all;
#: - ``unit_matrix`` is the L2-normalized float32 matrix, row-aligned with
#:   ``ids``;
#: - ``degenerate`` marks the zero-norm rows, which score 0 rather than NaN.
#:
#: WS-28. The 47 MB Chroma hands back is the serialized form; decoded it is
#: **24 MB** of float32, and a matvec against it is 1.1 ms against a 1.04 s
#: fetch. The scan still multiplies the whole matrix — this is not an ANN
#: index, and every listing still gets a score (see §11.12: HNSW top-50 is
#: 5.0 ms but answers a different question).
_VECTOR_MATRIX: OrderedDict[str, tuple[float, int, list[str], Any, list[bool]]] = OrderedDict()


def clear_vector_matrix_cache() -> None:
    """Drop the resident vector matrix (tests; operational use)."""
    _VECTOR_MATRIX.clear()


def _recall_matrix(scope: str, count: int) -> tuple[list[str], Any, list[bool]] | None:
    """The resident ``(ids, unit_matrix, degenerate)``, or ``None``."""
    entry = _VECTOR_MATRIX.get(scope)
    if entry is None:
        return None
    stored_at, built_count, ids, matrix, degenerate = entry
    if built_count != count:
        # A write from another process: the only signal we have is the size.
        _VECTOR_MATRIX.pop(scope, None)
        return None
    if time.monotonic() - stored_at > _PROCESS_SCAN_TTL_SECONDS:
        _VECTOR_MATRIX.pop(scope, None)
        return None
    _VECTOR_MATRIX.move_to_end(scope)
    return ids, matrix, degenerate


def _remember_matrix(scope: str, ids: list[str], matrix: Any, degenerate: list[bool]) -> None:
    """Hold the matrix for this scope, bounded to one entry."""
    _VECTOR_MATRIX[scope] = (time.monotonic(), len(ids), ids, matrix, degenerate)
    _VECTOR_MATRIX.move_to_end(scope)
    while len(_VECTOR_MATRIX) > _VECTOR_MATRIX_ENTRIES:
        _VECTOR_MATRIX.popitem(last=False)


class VectorStoreMismatch(RuntimeError):
    """The persisted collection was built with a different embedding space."""


class _CachedEmbeddingFunction(EmbeddingFunction):
    """Chroma adapter around an ``EmbeddingFn`` (same cache, same prefixes)."""

    def __init__(self, fn: EmbeddingFn) -> None:
        self._fn = fn

    def __call__(self, input: Documents) -> Embeddings:
        return self._fn.embed_documents(list(input))

    @staticmethod
    def name() -> str:
        # Chroma persists this identifier alongside collection configuration.
        return "agentic_job_applier.cached_embedding_function"

    @staticmethod
    def get_config() -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> _CachedEmbeddingFunction:
        raise NotImplementedError(
            "Rebuild the store with its EmbeddingFn instead (config-based "
            "reconstruction is not supported for custom functions)"
        )


class ChromaVectorStore:
    """Persistent Chroma collection of embedded job listings."""

    def __init__(
        self,
        *,
        persist_dir: str | None = None,
        embedding_fn: EmbeddingFn | None = None,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or get_settings()
        self.collection_name = collection_name
        self._embedding_fn = embedding_fn or build_embedding_fn(settings)
        # FU-7: identity comes from the provider actually constructed, not from
        # settings alone — the env selecting fastembed while stale settings say
        # gemini must surface as a VectorStoreMismatch, never as silent
        # degradation (the store-wide except in job_workflow would hide it).
        # Fakes without identity attributes keep their settings-based semantics.
        self.embedding_model = getattr(self._embedding_fn, "model", settings.embedding_model)
        self.dimension = getattr(
            self._embedding_fn, "dimensionality", settings.embedding_dimensionality
        )

        # WS-24c: remembered for the scan-memo key. Two stores can share a
        # collection *name* while pointing at different directories (the
        # tests build one per tmp_path), and a shared scan between them
        # would be a wrong answer, not a slow one.
        self._persist_dir = str(ensure_dir(persist_dir or settings.chroma_dir))
        self._client = chromadb.PersistentClient(path=self._persist_dir)
        self._collection = self._open_collection()

    # -- setup ---------------------------------------------------------------

    def _open_collection(self):
        expected = {"embedding_model": self.embedding_model, "dimension": self.dimension}
        chroma_ef = _CachedEmbeddingFunction(self._embedding_fn)
        try:
            # Passing the live embedding function keeps chroma from trying to
            # reconstruct one from persisted configuration.
            existing = self._client.get_collection(
                self.collection_name, embedding_function=chroma_ef
            )
        except NotFoundError:
            existing = None
        if existing is not None:
            metadata = existing.metadata or {}
            stored_model = metadata.get("embedding_model")
            stored_dim = metadata.get("dimension")
            if stored_model != self.embedding_model or stored_dim != self.dimension:
                raise VectorStoreMismatch(
                    f"Chroma collection {self.collection_name!r} was built with embedding "
                    f"model {stored_model!r} (dimension {stored_dim}) but the constructed "
                    f"embedding provider specifies {self.embedding_model!r} (dimension "
                    f"{self.dimension}). Embedding spaces are version-locked and cannot be "
                    f"mixed. Remediation: delete the chroma data directory (default "
                    f"data/chroma) and re-run upsert_jobs to re-embed all listings with the "
                    f"configured model."
                )
            return existing
        return self._client.get_or_create_collection(
            name=self.collection_name,
            metadata=expected,
            configuration={"hnsw": {"space": "cosine"}},
            embedding_function=chroma_ef,
        )

    # -- write path ----------------------------------------------------------

    @staticmethod
    def document_text(job: JobListing) -> str:
        """Compose the embedded document for a listing (stable format)."""
        body_parts: list[str] = []
        if job.required_skills:
            body_parts.append(f"Required skills: {', '.join(job.required_skills)}.")
        if job.preferred_skills:
            body_parts.append(f"Preferred skills: {', '.join(job.preferred_skills)}.")
        if job.description:
            description = job.description[:MAX_DESCRIPTION_CHARS]
            if len(job.description) > MAX_DESCRIPTION_CHARS:
                logger.info(
                    "Description for job %s truncated from %d to %d chars before embedding",
                    job.id,
                    len(job.description),
                    MAX_DESCRIPTION_CHARS,
                )
            body_parts.append(description)
        return build_document_text(job.title, " ".join(body_parts))

    @staticmethod
    def content_hash(document: str) -> str:
        """The identity of one embedded document (WS-18)."""
        return hashlib.sha256(document.encode("utf-8")).hexdigest()

    @staticmethod
    def job_metadata(job: JobListing, *, content_hash: str = "") -> dict:
        """Listing metadata persisted alongside the vector (chroma rejects None).

        WS-18: ``content_hash`` is stored with the vector so a later refresh
        can ask "is *this version* of the document embedded?" without
        re-reading and re-hashing every document, and so the verifier can
        prove that the vector it finds belongs to the work item it is about
        to complete.
        """
        return {
            "company": job.company or "",
            "location": job.location or "",
            "remote_policy": job.remote_policy or "",
            "seniority": job.seniority or "",
            "source": job.source or "",
            "content_hash": content_hash,
        }

    def upsert_jobs(
        self, listings: list[JobListing], *, on_progress: ProgressHook | None = None
    ) -> int:
        """Embed and upsert listings (id-stable); returns the number written.

        Embedding and upserting proceed in ``EMBED_BATCH_SIZE`` chunks so a
        daily-quota stop (FU-4) mid-corpus leaves every completed chunk in the
        store — the next run re-embeds the rest from cache hits and only pays
        for the remainder. One fully-missed chunk costs one API batch request.

        ``on_progress`` is handed to the embedding provider, which calls it as
        its own sub-batches complete (the durable worker renews its lease from
        there). It is forwarded only when it is set, so a store built around a
        caller's own embedding function needs no knowledge of it.
        """
        if not listings:
            return 0
        written = 0
        for start in range(0, len(listings), EMBED_BATCH_SIZE):
            chunk = listings[start : start + EMBED_BATCH_SIZE]
            documents = [self.document_text(job) for job in chunk]
            if on_progress is None:
                vectors = self._embedding_fn.embed_documents(documents)
            else:
                vectors = self._embedding_fn.embed_documents(documents, on_progress=on_progress)
            self._collection.upsert(
                ids=[job.id for job in chunk],
                embeddings=vectors,
                documents=documents,
                metadatas=[
                    self.job_metadata(job, content_hash=self.content_hash(document))
                    for job, document in zip(chunk, documents, strict=True)
                ],
            )
            written += len(chunk)
            if len(listings) > EMBED_BATCH_SIZE:
                logger.info(
                    "Upserted %d/%d jobs into Chroma collection %s",
                    written,
                    len(listings),
                    self.collection_name,
                )
        logger.info(
            "Upserted %d jobs into Chroma collection %s", len(listings), self.collection_name
        )
        # WS-24c: a re-embedded listing changes its score without changing
        # the row count, so the count in the scan key is not enough — any
        # write drops the memoized scans outright.
        # WS-28: and the resident vector matrix, which holds the vectors those
        # scans were computed from.
        clear_process_scan_cache()
        clear_vector_matrix_cache()
        return written

    # -- read path -----------------------------------------------------------

    def delete_jobs(self, job_ids: list[str]) -> int:
        """Remove the vectors of the given listings; returns the count.

        WS-15: the corpus evicts its stale listings, and a listing that
        has been evicted must not keep a vector — the store is what the
        search reads, so a vector without a row is a listing that scores
        against a profile but can never be fetched, shown, or applied to.
        The two stores are therefore evicted together.
        """
        if not job_ids:
            return 0
        self._collection.delete(ids=list(job_ids))
        # WS-24c: the memoized scans are no longer the corpus.
        # WS-28: and the resident matrix is no longer its vectors.
        clear_process_scan_cache()
        clear_vector_matrix_cache()
        logger.info(
            "Deleted %d vectors from Chroma collection %s", len(job_ids), self.collection_name
        )
        return len(job_ids)

    def query_similar(self, query_text: str, n: int = 10) -> list[tuple[str, float]]:
        """Return (job_id, similarity 0-100) for the n most similar listings."""
        if self._collection.count() == 0:
            return []
        vector = self._embedding_fn.embed_query(build_query_text(query_text))
        result = self._collection.query(
            query_embeddings=[vector],
            n_results=max(1, min(n, self._collection.count())),
        )
        ids = result["ids"][0]
        distances = result["distances"][0]
        return [
            (job_id, self._distance_to_similarity(distance))
            for job_id, distance in zip(ids, distances)
        ]

    def count(self) -> int:
        return self._collection.count()

    def _scope_key(self) -> str:
        """The store's identity, for the process-level caches.

        The persist directory *and* the collection name: two stores can share a
        collection name while pointing at different directories (the tests
        build one per tmp path), and a shared entry between them would be a
        wrong answer rather than a slow one.
        """
        return f"{self._persist_dir}\x1f{self.collection_name}"

    def _scan_key(self, query_text: str, covered: int) -> tuple[str, str, int]:
        """The memo key for one full-corpus scan (WS-24c; key changed WS-28).

        Each part closes a way the memo could be wrong:

        - the **collection name and directory**, so two stores in one process
          — the tests build one per tmp directory — never share a scan;
        - a **digest** of the query text, so the raw candidate text is never
          held as a key and two different texts never collide; and
        - the collection's **count**, so a corpus that grew or shrank cannot be
          served a stale map. WS-28 changed this from "ids fetched" to "count":
          both are the same number, but only the count is O(1), and the old key
          forced a hit to enumerate every id before it could know it was one. A
          write also clears the memo outright (see :meth:`upsert_jobs` /
          :meth:`delete_jobs`), because a re-embedded listing changes a score
          without changing the count.
        """
        digest = hashlib.sha256(query_text.encode("utf-8", errors="replace")).hexdigest()
        return (self._scope_key(), digest, covered)

    def stored_ids(self) -> set[str]:
        """Ids of every listing that has a vector in the collection."""
        result = self._collection.get(include=[])
        return set(result.get("ids") or [])

    def embedded_hashes(self, job_ids: Iterable[str]) -> dict[str, str]:
        """The content hash of the vector stored for each id that has one (WS-18).

        The hash comes from the vector's metadata when it was written by this
        version of the store, and is recomputed from the stored document when
        it was not (vectors that pre-date WS-18). The fallback is what makes
        the check honest for an existing corpus instead of treating every old
        vector as missing.

        The read is paged, so a reconciliation over a 50,000-listing corpus
        does not hold 50,000 documents in memory at once.
        """
        ids = list(dict.fromkeys(str(job_id) for job_id in job_ids))
        found: dict[str, str] = {}
        for start in range(0, len(ids), SCAN_PAGE_SIZE):
            page = ids[start : start + SCAN_PAGE_SIZE]
            result = self._collection.get(ids=page, include=["documents", "metadatas"])
            page_ids = result.get("ids") or []
            documents = result.get("documents")
            if documents is None:
                documents = []
            metadatas = result.get("metadatas")
            if metadatas is None:
                metadatas = []
            for job_id, document, metadata in zip(page_ids, documents, metadatas, strict=False):
                stored = (metadata or {}).get("content_hash") or ""
                if not stored and document is not None:
                    stored = self.content_hash(document)
                if stored:
                    found[job_id] = stored
        return found

    def cached_flags(self, texts: list[str]) -> list[bool]:
        """Which of *texts* already have a vector in the embedding cache (WS-18).

        Observability only: the provider consults the same cache again on the
        write path, and a hit costs a lookup rather than an embedding. The
        count is what makes "the refresh was cheap because the cache was warm"
        a statement the metrics can support.
        """
        is_cached = getattr(self._embedding_fn, "is_cached", None)
        if is_cached is None or not texts:
            return [False] * len(texts)
        try:
            return [bool(flag) for flag in is_cached(texts)]
        except Exception:  # noqa: BLE001 - a metric must not fail the write
            return [False] * len(texts)

    def verify_listings(self, listings: list[JobListing], hashes: dict[str, str]) -> set[str]:
        """The ids of *listings* whose stored vector matches *hashes*.

        This is the verifier the work item completion depends on: a 2xx from
        the upsert is not proof that the vector is there and is the right
        one, and "mark complete because the write returned" is exactly how a
        crash window becomes silent data loss.
        """
        stored = self.embedded_hashes(job.id for job in listings)
        return {
            job.id
            for job in listings
            if hashes.get(job.id) is not None and stored.get(job.id) == hashes[job.id]
        }

    def similarities_for_all(self, query_text: str) -> dict[str, float]:
        """Similarity 0-100 for **every** stored listing.

        Chroma's ``query()`` drops one row when ``n_results`` equals the
        collection count (known Chroma edge case), which made the store-only
        search report a phantom gap and flip ``degraded``. That path needs
        a score for every listing anyway, so it computes the cosine against the
        persisted vectors directly — exact, complete, free of the off-by-one.

        WS-24: the cosine is computed with **NumPy**, not a Python loop. The
        loop cost 0.324 ms per vector — 2.2 s over the 6,696-listing corpus
        and ~16 s at the 50,000 cap, measured. The same arithmetic as a
        normalized matrix-vector product is ~0.020 s, because it runs in
        optimized C over contiguous memory rather than in the interpreter.
        The computation is identical; only the execution changes.

        The Chroma ``query()`` off-by-one is not worked around any more —
        it is **accepted**. There is no Chroma query in this path, so there
        is nothing for it to drop a row from.

        WS-12: the scan is **bounded**. The corpus is capped by the
        admission control, but the cap is a configuration value and this is
        the most expensive read in the system (it loads every vector). The
        vectors are therefore fetched in pages, so the peak memory is the
        page size rather than the size of the corpus, and the scan stops at
        the configured ceiling even when the corpus is larger than the cap
        (the cap may have been raised after the corpus was built).
        """
        count = self._collection.count()
        if count == 0:
            return {}

        from src.security.limits import get_limits

        limit = get_limits().max_corpus_listings
        # The budget is spent over the pages, not per page: the last page is
        # trimmed to whatever is left of the limit, so a corpus larger than the
        # limit is really *cut* at the limit rather than merely warned about.
        remaining = min(count, limit)

        # WS-24c: the whole scan is memoized **in this process**, keyed by the
        # query text and the collection state it was computed against. A repeat
        # search by an unchanged profile is then a dictionary read instead of
        # an ONNX embed plus a vector scan. See ``_PROCESS_SCAN`` for why this
        # is not the persistent cache WS-14 Phase G forbids.
        #
        # WS-28: the key uses ``collection.count()`` rather than the number of
        # ids fetched. The old key needed the id list, so a "hit" still paid
        # the 23 ms enumeration before it could know it was a hit.
        memo_key = self._scan_key(query_text, remaining)
        cached_scan = _recall_scan(memo_key)
        if cached_scan is not None:
            return cached_scan

        vector = self._embedding_fn.embed_query(build_query_text(query_text))

        # WS-28: the resident matrix. Fetching 47 MB out of Chroma costs ~1 s;
        # the decoded matrix is 24 MB of float32 and a matvec against it is
        # ~1 ms. The vectors do not change unless the collection does, so they
        # are held rather than re-read per search.
        resident = _recall_matrix(self._scope_key(), count)
        if resident is None:
            ids, matrix, degenerate = self._load_vector_matrix(remaining)
            _remember_matrix(self._scope_key(), ids, matrix, degenerate)
        else:
            ids, matrix, degenerate = resident

        scores = self._scores_from_matrix(ids, matrix, vector, degenerate)

        _remember_scan(memo_key, scores)

        if count > limit:
            logger.warning(
                "Similarity scan covered %d of %d listings (the corpus exceeds the %d cap)",
                len(scores),
                count,
                limit,
            )
        return scores

    def _load_vector_matrix(self, remaining: int) -> tuple[list[str], Any, list[bool]]:
        """Fetch the corpus's vectors once and reduce them to a unit matrix.

        The ids come first (cheap — no vectors), then the vectors in pages, so
        the peak memory while *reading* is one page rather than the whole
        corpus. The assembled matrix replaces those pages; it is 24 MB at the
        live corpus size, against the 47 MB of serialized bytes Chroma hands
        back.

        Returns ``(ids, unit_matrix, degenerate)``, where ``degenerate`` marks
        the zero-norm rows — a vector with no direction scores 0, not NaN, and
        the mask is returned rather than stashed on the instance because the
        store is rebuilt per request and hidden state would be a second thing
        to keep in step with the matrix.
        """
        import numpy as np

        all_ids = self._collection.get(include=[]).get("ids") or []
        remaining = min(len(all_ids), remaining)
        kept_ids: list[str] = []
        rows: list[Any] = []
        for start in range(0, remaining, SCAN_PAGE_SIZE):
            page_ids = all_ids[start : min(start + SCAN_PAGE_SIZE, remaining)]
            result = self._collection.get(ids=page_ids, include=["embeddings"])
            ids = result.get("ids") or []
            embeddings = result.get("embeddings")
            if embeddings is None:  # numpy array: `or []` would raise on truthiness
                embeddings = []
            if not ids:
                continue
            kept_ids.extend(ids)
            rows.append(np.asarray(embeddings, dtype=np.float32))

        if not rows:
            return [], None, []
        matrix = np.vstack(rows)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        unit = matrix / np.where(norms == 0, 1.0, norms)
        degenerate = (norms[:, 0] == 0).tolist()
        return kept_ids, unit, degenerate

    def _scores_from_matrix(
        self,
        ids: list[str],
        unit_matrix: Any,
        vector: list[float],
        degenerate: list[bool],
    ) -> dict[str, float]:
        """Cosine 0-100 for every row, as one matrix-vector product."""
        import numpy as np

        if unit_matrix is None or not ids:
            return {}
        query = np.asarray(vector, dtype=np.float32)
        if query.shape[0] != unit_matrix.shape[1] or len(ids) != unit_matrix.shape[0]:
            # A shape the fast path cannot use: fall back to the reference
            # computation rather than returning wrong numbers.
            return {
                job_id: self._cosine_similarity(vector, row)
                for job_id, row in zip(ids, unit_matrix)
            }
        query_norm = float(np.linalg.norm(query))
        if not query_norm:
            return dict.fromkeys(ids, 0.0)

        values = (unit_matrix @ (query / query_norm)).tolist()
        if len(degenerate) != len(ids):
            degenerate = [False] * len(ids)

        scores: dict[str, float] = {}
        for index, job_id in enumerate(ids):
            if degenerate[index]:
                scores[job_id] = 0.0
            else:
                scores[job_id] = max(0.0, min(100.0, float(values[index]) * 100.0))
        return scores

    @staticmethod
    def _similarities_for_page(
        ids: list[str], embeddings: object, vector: list[float]
    ) -> dict[str, float]:
        """Cosine similarity for one page of vectors, computed with NumPy.

        The reference implementation is :meth:`_cosine_similarity`, which
        computes the same quantity one vector at a time. This one computes
        the same quantity for the whole page as a single normalized
        matrix-vector product.

        The two agree to floating-point tolerance: normalizing the rows and
        the query and taking the dot product is algebraically the cosine
        similarity. A zero-norm row (a degenerate vector) has no direction
        and scores 0, which is what the reference implementation does too.
        """
        import numpy as np

        matrix = np.asarray(embeddings, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != len(ids):
            # A shape the fast path cannot use: fall back to the reference
            # computation rather than returning wrong numbers.
            return {
                job_id: ChromaVectorStore._cosine_similarity(vector, embedding)
                for job_id, embedding in zip(ids, embeddings)
            }
        query = np.asarray(vector, dtype=np.float32)
        if query.shape[0] != matrix.shape[1]:
            return {
                job_id: ChromaVectorStore._cosine_similarity(vector, embedding)
                for job_id, embedding in zip(ids, embeddings)
            }

        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        query_norm = float(np.linalg.norm(query))
        if not query_norm:
            return dict.fromkeys(ids, 0.0)
        # A zero-norm row has no direction; it scores 0 rather than NaN.
        degenerate = norms[:, 0] == 0
        safe_norms = np.where(norms == 0, 1.0, norms)
        unit_matrix = matrix / safe_norms
        unit_query = query / query_norm
        similarities = unit_matrix @ unit_query

        values = similarities.tolist()
        page: dict[str, float] = {}
        for index, job_id in enumerate(ids):
            if degenerate[index]:
                page[job_id] = 0.0
            else:
                page[job_id] = max(0.0, min(100.0, float(values[index]) * 100.0))
        return page

    @staticmethod
    def _cosine_similarity(left, right) -> float:
        left_values = [float(value) for value in left]
        right_values = [float(value) for value in right]
        dot = sum(a * b for a, b in zip(left_values, right_values))
        left_norm = sum(value * value for value in left_values) ** 0.5
        right_norm = sum(value * value for value in right_values) ** 0.5
        if not left_norm or not right_norm:
            return 0.0
        return max(0.0, min(100.0, (dot / (left_norm * right_norm)) * 100.0))

    def get_job_metadata(self, job_id: str) -> dict | None:
        """Persisted metadata for one listing, or None when absent."""
        result = self._collection.get(ids=[job_id], include=["metadatas"])
        metadatas = result.get("metadatas") or []
        return metadatas[0] if metadatas else None

    @staticmethod
    def _distance_to_similarity(distance: float) -> float:
        # Chroma cosine space: distance = 1 - cosine_similarity, in [0, 2].
        return max(0.0, min(100.0, (1.0 - distance) * 100.0))


def candidate_query_text(profile: CandidateProfile) -> str:
    """Compose the semantic query describing a candidate (WS-04, widened WS-20).

    WS-20 uses the **whole** professional record — title, summary, skills,
    experience titles and bullets, project technologies and descriptions,
    education and certifications — instead of only the first 20 skills and a
    300-character summary. Contact information is deliberately excluded.
    """
    from src.matching.lexical import candidate_lexical_text

    text = candidate_lexical_text(profile)
    return text if text.strip() else "job search"
