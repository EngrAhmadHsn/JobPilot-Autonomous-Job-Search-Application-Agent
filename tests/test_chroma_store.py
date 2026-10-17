"""Tests for the real Chroma vector store (src/rag/chroma_store.py).

Uses tmp-dir PersistentClients and a deterministic FakeEmbeddingFn — vectors
are derived from stable token hashes so that related documents share
dimensions and rank above unrelated ones, with no LLM/network involved.
"""

from __future__ import annotations

import math
import re
import zlib
from types import SimpleNamespace

import pytest

from src.jobs.contracts import JobListing
from src.rag.chroma_store import (
    ChromaVectorStore,
    VectorStoreMismatch,
    candidate_query_text,
)
from src.resume.profile import CandidateProfile, PersonalInformation

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


def make_settings(tmp_path, model="gemini-embedding-2", dimension=DIM):
    return SimpleNamespace(
        chroma_dir=str(tmp_path / "chroma"),
        embedding_model=model,
        embedding_dimensionality=dimension,
    )


def make_store(tmp_path, **kwargs) -> tuple[ChromaVectorStore, FakeEmbeddingFn]:
    fn = FakeEmbeddingFn()
    settings = make_settings(tmp_path, **{k: v for k, v in kwargs.items() if k != "fn"})
    store = ChromaVectorStore(settings=settings, embedding_fn=fn)
    return store, fn


def make_job(id: str, title: str, description: str, **kwargs) -> JobListing:
    defaults = {
        "source": "greenhouse",
        "company": "Acme",
        "title": title,
        "description": description,
    }
    defaults.update(kwargs)
    return JobListing(id=id, **defaults)


PYTHON_JOB = make_job(
    "py-1",
    "Backend Python Engineer",
    "Build APIs with Python, FastAPI and PostgreSQL for our platform.",
    required_skills=["Python", "FastAPI"],
    location="Remote",
    remote_policy="remote",
)
ML_JOB = make_job(
    "ml-1",
    "Machine Learning Engineer",
    "Train and deploy python machine learning models in production.",
    required_skills=["Python"],
)
CHEF_JOB = make_job(
    "chef-1",
    "Head Chef",
    "Lead the kitchen, design menus and cook seasonal dishes daily.",
)


def test_upsert_and_query_ranks_related_above_unrelated(tmp_path):
    store, fn = make_store(tmp_path)
    assert store.upsert_jobs([PYTHON_JOB, ML_JOB, CHEF_JOB]) == 3
    assert store.count() == 3
    assert fn.document_calls == 1

    results = store.query_similar("python backend engineer building apis", n=3)

    assert results[0][0] in {"py-1", "ml-1"}
    scores = dict(results)
    assert scores["py-1"] > scores["chef-1"]
    assert scores["ml-1"] > scores["chef-1"]
    assert all(0.0 <= similarity <= 100.0 for similarity in scores.values())
    assert fn.query_calls == 1


def test_similarity_identical_text_near_100(tmp_path):
    store, _ = make_store(tmp_path)
    store.upsert_jobs([PYTHON_JOB])
    results = store.query_similar(ChromaVectorStore.document_text(PYTHON_JOB))
    assert results
    assert results[0][0] == "py-1"
    assert results[0][1] > 90.0


def test_upsert_is_id_stable(tmp_path):
    store, _ = make_store(tmp_path)
    store.upsert_jobs([PYTHON_JOB])
    updated = PYTHON_JOB.model_copy(update={"description": "Updated description."})
    store.upsert_jobs([updated])
    assert store.count() == 1


def test_metadata_persisted(tmp_path):
    store, _ = make_store(tmp_path)
    store.upsert_jobs([PYTHON_JOB])
    metadata = store.get_job_metadata("py-1")
    assert metadata == {
        "company": "Acme",
        "location": "Remote",
        "remote_policy": "remote",
        "seniority": "",
        "source": "greenhouse",
    }


def test_document_text_format(tmp_path):
    text = ChromaVectorStore.document_text(PYTHON_JOB)
    assert text.startswith("title: Backend Python Engineer | text: ")
    assert "Required skills: Python, FastAPI" in text
    assert "Build APIs" in text


def test_long_description_truncated_before_embedding(tmp_path):
    job = make_job("long-1", "Title", "word " * 3_000)  # ~15k chars
    text = ChromaVectorStore.document_text(job)
    assert len(text) < 8_400  # prefix + skills + 8k description cap


def test_empty_store_query_returns_empty(tmp_path):
    store, _ = make_store(tmp_path)
    assert store.query_similar("anything") == []


def test_model_dimension_drift_raises_with_remediation(tmp_path):
    store, _ = make_store(tmp_path)
    store.upsert_jobs([PYTHON_JOB])

    with pytest.raises(VectorStoreMismatch, match="delete the chroma"):
        make_store(tmp_path, model="text-embedding-004")

    with pytest.raises(VectorStoreMismatch, match="re-embed"):
        make_store(tmp_path, dimension=4)


class IdentityEmbeddingFn(FakeEmbeddingFn):
    """Fake that exposes the provider-identity attributes (FU-7 fastembed/gemini)."""

    def __init__(self, model: str, dimensionality: int = DIM) -> None:
        super().__init__()
        self.model = model
        self.dimensionality = dimensionality


def test_drift_guard_uses_constructed_provider_identity_over_settings(tmp_path):
    """FU-7: the guard compares the collection against the provider actually
    constructed — a fn whose identity differs from settings must win both ways."""
    settings = make_settings(tmp_path, model="gemini-embedding-2")  # stale on purpose
    store = ChromaVectorStore(
        settings=settings, embedding_fn=IdentityEmbeddingFn("google/embeddinggemma-2@int8")
    )
    store.upsert_jobs([PYTHON_JOB])

    # Same provider identity reopens cleanly despite stale settings.
    reopened = ChromaVectorStore(
        settings=make_settings(tmp_path, model="gemini-embedding-2"),
        embedding_fn=IdentityEmbeddingFn("google/embeddinggemma-2@int8"),
    )
    assert reopened.count() == 1

    # A different provider identity mismatches even though settings did not change.
    with pytest.raises(VectorStoreMismatch, match="google/embeddinggemma-2@fp32"):
        ChromaVectorStore(
            settings=make_settings(tmp_path, model="gemini-embedding-2"),
            embedding_fn=IdentityEmbeddingFn("google/embeddinggemma-2@fp32"),
        )


def test_fakes_without_identity_keep_settings_semantics(tmp_path):
    """FakeEmbeddingFn has no .model/.dimensionality: the guard falls back to
    settings, so existing test doubles keep their semantics."""
    store, _ = make_store(tmp_path)  # settings say gemini-embedding-2 / DIM
    store.upsert_jobs([PYTHON_JOB])
    reopened, _ = make_store(tmp_path)
    assert reopened.count() == 1  # no mismatch raised


def test_same_model_same_dimension_reopens_cleanly(tmp_path):
    store, _ = make_store(tmp_path)
    store.upsert_jobs([PYTHON_JOB])
    reopened, _ = make_store(tmp_path)
    assert reopened.count() == 1
    assert reopened.query_similar("python apis") != []


def test_candidate_query_text_composition():
    profile = CandidateProfile(
        personal_information=PersonalInformation(title="AI Engineer"),
        skills=["Python", "PyTorch", "LangGraph"],
        summary="Builds LLM systems.",
    )
    text = candidate_query_text(profile)
    assert "AI Engineer" in text
    assert "Python" in text
    assert "Builds LLM systems." in text


def test_upsert_empty_list_is_noop(tmp_path):
    store, fn = make_store(tmp_path)
    assert store.upsert_jobs([]) == 0
    assert fn.document_calls == 0
    assert store.count() == 0
