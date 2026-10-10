"""Tests for Phase 7 RAG/research components."""

from src.rag.chroma_store import ChromaVectorStore
from src.research.engine import research_company, research_job_description


def test_chroma_store_placeholder():
    store = ChromaVectorStore()
    assert store.collection_name == "job_descriptions"
    results = store.search("python engineer")
    assert isinstance(results, list)


def test_research_company():
    result = research_company("Tech Corp")
    assert result["company"] == "Tech Corp"


def test_research_job_description():
    result = research_job_description("Python engineer needed")
    assert result["description_length"] == 22
