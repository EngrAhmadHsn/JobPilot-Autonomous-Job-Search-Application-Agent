"""Real Chroma-backed vector store for job listings (WS-03).

Persists normalized listings as embedding vectors in a Chroma persistent
collection and answers candidate-vs-listing semantic queries. Embeddings flow
through the shared ``EmbeddingFn`` (``GeminiEmbedding`` in production), so the
SQLite content-hash cache applies to every store write and query — a repeat
run makes zero API calls.

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

import logging

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.errors import NotFoundError

from src.config.settings import Settings, ensure_dir, get_settings
from src.jobs.contracts import JobListing
from src.llm.embeddings import EmbeddingFn, GeminiEmbedding, build_document_text, build_query_text
from src.resume.profile import CandidateProfile

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION_NAME = "job_listings"

# Embedding/upsert chunk size: aligned with the API batch cap so a fully
# missed chunk is exactly one batch request (FU-1 resumability, FU-4 budget).
EMBED_BATCH_SIZE = 100

# Description text is truncated before embedding (the API silently truncates
# beyond its token cap; see src/llm/embeddings.py).
MAX_DESCRIPTION_CHARS = 6_000


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
        self.embedding_model = settings.embedding_model
        self.dimension = settings.embedding_dimensionality
        self._embedding_fn = embedding_fn or GeminiEmbedding()

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
                    f"model {stored_model!r} (dimension {stored_dim}) but settings specify "
                    f"{self.embedding_model!r} (dimension {self.dimension}). Embedding spaces "
                    f"are version-locked and cannot be mixed. Remediation: delete the chroma "
                    f"data directory (default data/chroma) and re-run upsert_jobs to re-embed "
                    f"all listings with the configured model."
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
    def job_metadata(job: JobListing) -> dict:
        """Listing metadata persisted alongside the vector (chroma rejects None)."""
        return {
            "company": job.company or "",
            "location": job.location or "",
            "remote_policy": job.remote_policy or "",
            "seniority": job.seniority or "",
            "source": job.source or "",
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
                metadatas=[self.job_metadata(job) for job in chunk],
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
    """Compose the semantic query describing a candidate (WS-04 call site)."""
    parts: list[str] = []
    if profile.personal_information.title:
        parts.append(profile.personal_information.title)
    if profile.skills:
        parts.append(f"Skills: {', '.join(profile.skills[:20])}.")
    if profile.summary:
        parts.append(profile.summary[:300])
    return " | ".join(parts) if parts else "job search"
