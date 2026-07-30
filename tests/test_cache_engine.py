"""Cache engine: keying, TTL expiry, and maintenance operations."""

import os
import sqlite3
from contextlib import closing

import pytest

from src.cache import CacheEngine


@pytest.fixture
def cache(tmp_workspace):
    return CacheEngine(os.path.join(tmp_workspace, "cache.db"))


def _age_entries(db_path, seconds):
    """Backdate every row so TTL logic can be exercised without sleeping."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "UPDATE cache SET created_at = datetime(created_at, '-' || ? || ' seconds')",
            (seconds,),
        )
        conn.commit()


class TestEmbeddingCache:
    def test_roundtrip(self, cache):
        cache.set_embedding("hello", [0.1, 0.2, 0.3], "model-a")
        assert cache.get_embedding("hello", "model-a") == [0.1, 0.2, 0.3]

    def test_miss_returns_none(self, cache):
        assert cache.get_embedding("never stored", "model-a") is None

    def test_different_models_do_not_share_entries(self, cache):
        cache.set_embedding("hello", [1.0], "model-a")

        assert cache.get_embedding("hello", "model-b") is None
        assert cache.get_embedding("hello", "model-a") == [1.0]


class TestRetrievalCache:
    def test_roundtrip(self, cache):
        results = [{"chunk_id": "c1", "score": 0.5}]
        cache.set_retrieval("query", "SQLiteLexicalRetriever", 5, results, "fp1")

        assert cache.get_retrieval("query", "SQLiteLexicalRetriever", 5, "fp1") == results

    def test_a_changed_corpus_fingerprint_misses(self, cache):
        cache.set_retrieval("query", "SQLiteLexicalRetriever", 5, [{"chunk_id": "c1"}], "fp1")

        assert cache.get_retrieval("query", "SQLiteLexicalRetriever", 5, "fp2") is None

    def test_top_k_and_retriever_are_part_of_the_key(self, cache):
        cache.set_retrieval("query", "SQLiteLexicalRetriever", 5, [{"chunk_id": "c1"}], "fp1")

        assert cache.get_retrieval("query", "SQLiteLexicalRetriever", 10, "fp1") is None
        assert cache.get_retrieval("query", "SQLiteSemanticRetriever", 5, "fp1") is None


class TestVerdictCache:
    def test_roundtrip(self, cache):
        cache.set_verdict("t1", "doc1", {"label": "supported"}, "doc-fp")

        assert cache.get_verdict("t1", "doc1", "doc-fp") == {"label": "supported"}

    def test_changed_document_content_misses_even_under_the_same_id(self, cache):
        cache.set_verdict("t1", "doc1", {"label": "supported"}, "fingerprint-v1")

        assert cache.get_verdict("t1", "doc1", "fingerprint-v2") is None


class TestExpiry:
    def test_expired_entries_are_not_served(self, cache):
        cache.set_embedding("hello", [1.0], "model-a", ttl_seconds=60)
        _age_entries(cache.db_path, 120)

        assert cache.get_embedding("hello", "model-a") is None

    def test_clear_expired_removes_only_stale_rows(self, cache):
        cache.set_embedding("old", [1.0], "model-a", ttl_seconds=60)
        _age_entries(cache.db_path, 120)
        cache.set_embedding("fresh", [2.0], "model-a", ttl_seconds=600)

        assert cache.clear_expired() == 1
        assert cache.get_embedding("fresh", "model-a") == [2.0]


class TestMaintenance:
    def test_stats_count_entries_by_type(self, cache):
        cache.set_embedding("a", [1.0])
        cache.set_retrieval("q", "R", 5, [], "fp")
        cache.set_verdict("t1", "doc1", {}, "fp")

        stats = cache.get_stats()
        assert stats["total_entries"] == 3
        assert stats["by_type"] == {"embedding": 1, "retrieval": 1, "verdict": 1}

    def test_stats_track_hit_rate(self, cache):
        cache.set_embedding("a", [1.0])
        cache.get_embedding("a")
        cache.get_embedding("missing")

        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_clear_all_can_target_one_entry_type(self, cache):
        cache.set_embedding("a", [1.0])
        cache.set_verdict("t1", "doc1", {}, "fp")

        assert cache.clear_all("embedding") == 1
        assert cache.get_verdict("t1", "doc1", "fp") == {}

    def test_clear_all_empties_the_cache(self, cache):
        cache.set_embedding("a", [1.0])
        cache.set_verdict("t1", "doc1", {}, "fp")

        cache.clear_all()
        assert cache.get_stats()["total_entries"] == 0

    def test_reopening_the_database_preserves_entries(self, tmp_workspace):
        path = os.path.join(tmp_workspace, "cache.db")
        CacheEngine(path).set_embedding("hello", [1.0], "model-a")

        assert CacheEngine(path).get_embedding("hello", "model-a") == [1.0]

    def test_fingerprint_is_deterministic_and_content_sensitive(self):
        assert CacheEngine.fingerprint("abc") == CacheEngine.fingerprint("abc")
        assert CacheEngine.fingerprint("abc") != CacheEngine.fingerprint("abd")
