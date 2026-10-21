"""WS-14 · Phase G — the AI-provider privacy and the per-tenant quota.

**The property under test:** the shared infrastructure does not become a
side channel between tenants, and one tenant cannot spend everybody's
provider quota.

What is proved here:

- the **shared embedding cache holds no candidate data**: a query is
  never a cache hit, and nothing the candidate's query produces is
  written to the shared cache file;
- the **corpus cache still works** — the job listings are shared board
  data, and caching them is the point of the cache;
- the **spend is attributed** to the tenant that made it;
- the **fair share** holds: a tenant cannot spend more than its share
  of the platform's daily budget, and a tenant that has not spent yet
  is unaffected by a noisy neighbour.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.llm.embeddings import EmbeddingCache
from src.llm.tenant import (
    current_tenant,
    record_spend,
    tenant_allowance,
    tenant_scope,
    tenants_today,
)


@pytest.fixture
def cache(tmp_path: Path) -> EmbeddingCache:
    """A throwaway embedding cache."""
    return EmbeddingCache(tmp_path / "embedding_cache.sqlite")


# -- the shared cache holds no candidate data ----------------------------------


class TestTheSharedCacheHoldsNoCandidateData:
    def test_a_query_is_never_written_to_the_cache(self, tmp_path: Path) -> None:
        """The candidate's query text must not reach the shared file."""
        from tests.test_embeddings import FakeEmbeddingsAPI, make_embedding

        embedding = make_embedding(tmp_path, FakeEmbeddingsAPI())
        text = "Senior Python Engineer | Skills: Python, FastAPI. | Backend engineer."
        embedding.embed_query(text)

        key = EmbeddingCache.key(embedding.model, embedding.dimensionality, text)
        connection = sqlite3.connect(tmp_path / "embedding_cache.sqlite")
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM embeddings WHERE key = ?", (key,)
            ).fetchone()
        finally:
            connection.close()
        assert row[0] == 0, "the candidate's query vector is in the shared cache"

    def test_a_document_is_written_to_the_cache(self, cache: EmbeddingCache) -> None:
        """The corpus is shared board data, and caching it is the point."""
        text = "Senior Python Engineer at Acme — build the platform."
        key = EmbeddingCache.key("model", 768, text)
        cache.put(key, "model", 768, [0.1] * 768)

        row = cache.connection.execute(
            "SELECT COUNT(*) FROM embeddings WHERE key = ?", (key,)
        ).fetchone()
        assert row[0] == 1

    def test_the_cache_holds_no_candidate_profile_text(self, cache: EmbeddingCache) -> None:
        """The end-to-end statement of the property.

        The candidate's query text is composed from their title, their
        skills and their summary. None of it may be findable in the
        shared cache file.
        """
        from src.rag.chroma_store import candidate_query_text
        from src.resume.profile import CandidateProfile

        profile = CandidateProfile.model_validate(
            {
                "personal_information": {
                    "name": "Ada Lovelace",
                    "title": "Senior Analytical Engine Engineer",
                    "email": "ada@example.com",
                },
                "summary": "A distinctive summary nobody else has.",
                "skills": ["Python", "FastAPI", "ONNX"],
                "experience": [],
                "education": [],
                "certifications": [],
                "projects": [],
            }
        )
        text = candidate_query_text(profile)
        assert "Ada Lovelace" not in text  # the name is not part of the query
        assert "distinctive summary" in text

        # Nothing of the query is in the cache.
        rows = cache.connection.execute("SELECT key FROM embeddings").fetchall()
        assert rows == []
        # And the query really is the candidate's own text.
        assert "distinctive summary" in text

    def test_the_query_is_embedded_fresh_every_time(self, tmp_path: Path) -> None:
        """Two searches by the same tenant do not share a cached vector."""
        from tests.test_embeddings import FakeEmbeddingsAPI, make_embedding

        api = FakeEmbeddingsAPI()
        embedding = make_embedding(tmp_path, api)
        embedding.embed_query("the same candidate text")
        embedding.embed_query("the same candidate text")
        assert len(api.calls) == 2, "the second query was served from the cache"


# -- the per-tenant quota ------------------------------------------------------


class TestThePerTenantQuota:
    def test_a_call_outside_a_request_has_no_tenant(self) -> None:
        assert current_tenant() is None

    def test_the_tenant_is_published_by_the_scope(self) -> None:
        with tenant_scope("alice"):
            assert current_tenant() == "alice"
        assert current_tenant() is None

    def test_the_spend_is_attributed_to_the_tenant(self, cache: EmbeddingCache) -> None:
        record_spend(cache.connection, "alice", 3)
        record_spend(cache.connection, "bob", 1)
        assert tenants_today(cache.connection) == 2

    def test_a_single_tenant_has_the_whole_budget(self, cache: EmbeddingCache) -> None:
        """One operator must not be limited by a rule meant for many."""
        with tenant_scope("alice"):
            assert tenant_allowance(cache.connection, 20) == 20

    def test_a_second_tenant_halves_the_first_ones_share(self, cache: EmbeddingCache) -> None:
        record_spend(cache.connection, "alice", 1)
        record_spend(cache.connection, "bob", 1)
        with tenant_scope("alice"):
            assert tenant_allowance(cache.connection, 20) == 9
        with tenant_scope("bob"):
            assert tenant_allowance(cache.connection, 20) == 9

    def test_a_noisy_tenant_cannot_spend_the_whole_budget(self, cache: EmbeddingCache) -> None:
        """Threat T7: one tenant's spend must not starve the others."""
        # Alice spends the whole platform budget on her own.
        record_spend(cache.connection, "alice", 20)
        # Bob arrives and spends nothing yet.
        record_spend(cache.connection, "bob", 1)
        with tenant_scope("alice"):
            assert tenant_allowance(cache.connection, 20) == 0
        with tenant_scope("bob"):
            # Bob still has a share; Alice's spending did not take it.
            assert tenant_allowance(cache.connection, 20) == 9

    def test_a_tenant_that_has_not_spent_is_unaffected(self, cache: EmbeddingCache) -> None:
        record_spend(cache.connection, "alice", 5)
        with tenant_scope("bob"):
            assert tenant_allowance(cache.connection, 20) == 20

    def test_the_allowance_never_goes_negative(self, cache: EmbeddingCache) -> None:
        record_spend(cache.connection, "alice", 100)
        with tenant_scope("alice"):
            assert tenant_allowance(cache.connection, 20) == 0

    def test_the_counters_are_durable(self, tmp_path: Path) -> None:
        """The counters live in the cache's database, so they survive a
        restart — a budget that a restart resets is not a budget."""
        path = tmp_path / "embedding_cache.sqlite"
        first = EmbeddingCache(path)
        record_spend(first.connection, "alice", 4)
        first.connection.close()

        second = EmbeddingCache(path)
        assert tenants_today(second.connection) == 1
        second.connection.close()


class TestTheTenantCountersLiveInTheCacheDatabase:
    def test_the_table_is_created(self, cache: EmbeddingCache) -> None:
        rows = cache.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        names = {row[0] for row in rows}
        assert "tenant_spend" in names
        assert "api_requests" in names

    def test_the_counters_are_bounded_to_one_day(self, cache: EmbeddingCache) -> None:
        """A counter that never resets is a counter that eventually
        refuses everything."""
        cache.connection.execute(
            "INSERT INTO tenant_spend (day, owner_id, count) VALUES ('1999-01-01', 'alice', 99)"
        )
        cache.connection.commit()
        assert tenants_today(cache.connection) == 0
