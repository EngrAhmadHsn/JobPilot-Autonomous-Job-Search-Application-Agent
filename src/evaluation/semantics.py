"""The real semantic channel over a golden corpus (WS-09 Part 2, Phase F).

The offline harness measures the deterministic scorers with a lexical
stand-in, because an offline run must be free and provider-independent.
The **live** run must not use that stand-in: a stand-in is not the semantic
channel, and a report that says "live" while ranking on token overlap is
the thing plan §7 warns against.

So this module computes the *real* semantic score for a listing, using the
production text contract and the production embedding provider:

- the document text is :meth:`ChromaVectorStore.document_text` — the exact
  string production embeds (title + required/preferred skills + description,
  under the asymmetric document prefix);
- the query text is :func:`candidate_query_text` under the asymmetric
  query prefix;
- the score is the cosine similarity scaled to 0-100, exactly as
  :meth:`ChromaVectorStore.similarities_for_all` computes it.

Reusing the production builders (rather than re-deriving the strings) is
what makes the live number *comparable* to the production ranking: the
same text in the same embedding space.

The provider is injected, so the module is testable without a model file
and without an API key. A missing provider is a **failure**, never a
silent fallback to the lexical stand-in: a live run that quietly ranked
on token overlap would be a lie in the report.
"""

from __future__ import annotations

import logging
from typing import Any

from src.jobs.contracts import JobListing
from src.rag.chroma_store import ChromaVectorStore, candidate_query_text
from src.resume.profile import CandidateProfile

logger = logging.getLogger(__name__)

__all__ = [
    "RealSemanticChannel",
    "cosine_similarity",
]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """The cosine similarity of two vectors, scaled to 0-100.

    The same formula and the same scale as
    :meth:`ChromaVectorStore.similarities_for_all`, so a score computed
    here and a score computed by the store are directly comparable.
    """
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return max(0.0, min(100.0, (dot / (left_norm * right_norm)) * 100.0))


class RealSemanticChannel:
    """Semantic scores for a corpus, computed by the real embedding provider.

    The channel embeds the profile query and every listing document once,
    then scores each listing against the query. It holds the provider (not
    the vectors) — the provider is what makes a run "live", and the
    provider's identity is what the report records.
    """

    def __init__(self, embedding_fn: Any) -> None:
        """Store the embedding provider.

        Args:
            embedding_fn: Anything with the ``EmbeddingFn`` protocol
                (``embed_query`` / ``embed_documents``). The production
                provider comes from
                :func:`src.llm.embeddings.build_embedding_fn`.
        """
        self._embedding_fn = embedding_fn

    @property
    def embedding_fn(self) -> Any:
        """The provider, so the report can name it."""
        return self._embedding_fn

    def __call__(self, profile: CandidateProfile, listings: list[JobListing]) -> dict[str, float]:
        """Score every listing against the profile — the channel's call form.

        The channel is used exactly like the offline lexical stand-in, so
        the two modes differ only in *who computes the score*.
        """
        return self.score(profile, listings)

    def score(self, profile: CandidateProfile, listings: list[JobListing]) -> dict[str, float]:
        """Score every listing against the profile's semantic query.

        Args:
            profile: The candidate profile, whose text forms the query.
            listings: The corpus to score.

        Returns:
            A mapping of listing id to a 0-100 similarity.

        Raises:
            RuntimeError: The provider returned a vector of the wrong
                length, or no vector at all. A mismatched space is a
                configuration error, not a zero score.
        """
        if not listings:
            return {}

        from src.llm.embeddings import build_query_text

        query_vector = self._embedding_fn.embed_query(
            build_query_text(candidate_query_text(profile))
        )
        document_texts = [ChromaVectorStore.document_text(listing) for listing in listings]
        document_vectors = self._embedding_fn.embed_documents(document_texts)
        if len(document_vectors) != len(listings):
            raise RuntimeError(
                f"The embedding provider returned {len(document_vectors)} vectors for "
                f"{len(listings)} documents; refusing to misalign the scores."
            )
        if not query_vector:
            raise RuntimeError("The embedding provider returned no query vector")

        scores: dict[str, float] = {}
        for listing, vector in zip(listings, document_vectors):
            if len(vector) != len(query_vector):
                raise RuntimeError(
                    f"Embedding dimension mismatch for listing {listing.id!r}: the provider "
                    f"returned {len(vector)} dimensions and the query has {len(query_vector)}. "
                    f"The document and query are in different embedding spaces."
                )
            scores[listing.id] = cosine_similarity(query_vector, vector)
        return scores
