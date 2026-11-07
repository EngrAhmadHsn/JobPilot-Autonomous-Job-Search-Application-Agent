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
from collections.abc import Iterable

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.errors import NotFoundError

from src.config.settings import Settings, ensure_dir, get_settings
from src.jobs.contracts import JobListing
from src.llm.embeddings import (
    EmbeddingFn,
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

MAX_DESCRIPTION_CHARS = 8_000

#: How many vectors are loaded per page in the full-corpus similarity scan.
#: The scan is bounded so the peak memory is this, not the corpus size.
SCAN_PAGE_SIZE = 500


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

        self._client = chromadb.PersistentClient(
            path=str(ensure_dir(persist_dir or settings.chroma_dir))
        )
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

    def upsert_jobs(self, listings: list[JobListing]) -> int:
        """Embed and upsert listings (id-stable); returns the number written.

        Embedding and upserting proceed in ``EMBED_BATCH_SIZE`` chunks so a
        daily-quota stop (FU-4) mid-corpus leaves every completed chunk in the
        store — the next run re-embeds the rest from cache hits and only pays
        for the remainder. One fully-missed chunk costs one API batch request.
        """
        if not listings:
            return 0
        written = 0
        for start in range(0, len(listings), EMBED_BATCH_SIZE):
            chunk = listings[start : start + EMBED_BATCH_SIZE]
            documents = [self.document_text(job) for job in chunk]
            vectors = self._embedding_fn.embed_documents(documents)
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
        search report a phantom gap and flip ``degraded``. That path needs a
        score for every listing anyway, so it computes the cosine against the
        persisted vectors directly — exact, complete, free of the off-by-one.

        WS-12: the scan is **bounded**. The corpus is capped by the
        admission control, but the cap is a configuration value and this is
        the most expensive read in the system (it loads every vector). The
        vectors are therefore fetched in pages, so the peak memory is the
        page size rather than the size of the corpus, and the scan stops at
        the configured ceiling even when the corpus is larger than the cap
        (the cap may have been raised after the corpus was built).
        """
        if self._collection.count() == 0:
            return {}
        vector = self._embedding_fn.embed_query(build_query_text(query_text))

        from src.security.limits import get_limits

        limit = get_limits().max_corpus_listings
        scores: dict[str, float] = {}

        # The ids first (cheap — no vectors), then the vectors in pages.
        all_ids = self._collection.get(include=[]).get("ids") or []
        # The budget is spent over the pages, not per page: the last page
        # is trimmed to whatever is left of the limit, so a corpus larger
        # than the limit is really *cut* at the limit rather than merely
        # warned about.
        remaining = min(len(all_ids), limit)
        for start in range(0, remaining, SCAN_PAGE_SIZE):
            page_ids = all_ids[start : min(start + SCAN_PAGE_SIZE, remaining)]
            result = self._collection.get(ids=page_ids, include=["embeddings"])
            ids = result.get("ids") or []
            embeddings = result.get("embeddings")
            if embeddings is None:  # numpy array: `or []` would raise on truthiness
                embeddings = []
            for job_id, embedding in zip(ids, embeddings):
                scores[job_id] = self._cosine_similarity(vector, embedding)

        if len(all_ids) > limit:
            logger.warning(
                "Similarity scan covered %d of %d listings (the corpus exceeds the %d cap)",
                len(scores),
                len(all_ids),
                limit,
            )
        return scores

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
