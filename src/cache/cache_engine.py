"""SQLite-backed cache for embeddings, retrieval results, and verdicts."""

import hashlib
import pickle
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

DAY = 86400


@contextmanager
def _connect(db_path: str):
    """Commit-on-success connection that is always closed.

    `with sqlite3.connect(...)` commits but leaves the handle open, which leaks
    file descriptors across the many short-lived cache operations here.
    """
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


@dataclass
class CacheEntry:
    key: str
    entry_type: str  # "embedding", "retrieval", "verdict", "feedback"
    value: Any
    ttl_seconds: int = DAY * 7


class CacheEngine:
    """Content-addressed cache keyed by an explicit fingerprint of the inputs.

    Every key includes a fingerprint of the data the value was derived from
    (the model name for embeddings, the corpus state for retrieval, the
    document text for verdicts). Without that, re-ingesting a document under an
    id that was seen before would serve a stale answer for the whole TTL.
    """

    def __init__(self, cache_db_path: str = "cache.db"):
        self.db_path = cache_db_path
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self._init_db()

    def _init_db(self) -> None:
        with _connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    entry_type TEXT,
                    value BLOB,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    ttl_seconds INTEGER
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_type ON cache(entry_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_created ON cache(created_at)")
            conn.commit()

    @staticmethod
    def _make_key(prefix: str, *args) -> str:
        content = f"{prefix}:{'|'.join(str(a) for a in args)}"
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def fingerprint(*parts) -> str:
        """Short digest of arbitrary inputs, for use as a cache-key component."""
        joined = "|".join("" if p is None else str(p) for p in parts)
        return hashlib.sha256(joined.encode()).hexdigest()[:16]

    # --- embeddings -------------------------------------------------------

    def get_embedding(self, text: str, model_id: str = "default") -> Optional[List[float]]:
        return self._get(self._make_key("embedding", model_id, text))

    def set_embedding(
        self,
        text: str,
        embedding: List[float],
        model_id: str = "default",
        ttl_seconds: int = DAY * 30,
    ) -> None:
        self._set(self._make_key("embedding", model_id, text), embedding, "embedding", ttl_seconds)

    # --- retrieval --------------------------------------------------------

    def get_retrieval(
        self,
        query: str,
        retriever_type: str,
        top_k: int,
        corpus_fingerprint: str = "",
    ) -> Optional[List[Dict[str, Any]]]:
        return self._get(self._make_key("retrieval", retriever_type, query, top_k, corpus_fingerprint))

    def set_retrieval(
        self,
        query: str,
        retriever_type: str,
        top_k: int,
        results: List[Dict[str, Any]],
        corpus_fingerprint: str = "",
        ttl_seconds: int = DAY * 7,
    ) -> None:
        self._set(
            self._make_key("retrieval", retriever_type, query, top_k, corpus_fingerprint),
            results,
            "retrieval",
            ttl_seconds,
        )

    # --- verdicts ---------------------------------------------------------

    def get_verdict(
        self,
        assertion_id: str,
        document_id: str,
        document_fingerprint: str = "",
    ) -> Optional[Dict[str, Any]]:
        return self._get(self._make_key("verdict", assertion_id, document_id, document_fingerprint))

    def set_verdict(
        self,
        assertion_id: str,
        document_id: str,
        verdict: Dict[str, Any],
        document_fingerprint: str = "",
        ttl_seconds: int = DAY * 14,
    ) -> None:
        self._set(
            self._make_key("verdict", assertion_id, document_id, document_fingerprint),
            verdict,
            "verdict",
            ttl_seconds,
        )

    # --- generic ----------------------------------------------------------

    def get(self, namespace: str, *key_parts) -> Optional[Any]:
        return self._get(self._make_key(namespace, *key_parts))

    def set(self, namespace: str, value: Any, *key_parts, ttl_seconds: int = DAY * 14) -> None:
        self._set(self._make_key(namespace, *key_parts), value, namespace, ttl_seconds)

    def _get(self, key: str) -> Optional[Any]:
        try:
            with _connect(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    SELECT value FROM cache
                    WHERE key = ?
                      AND (ttl_seconds IS NULL
                           OR datetime(created_at, '+' || ttl_seconds || ' seconds') > datetime('now'))
                    """,
                    (key,),
                )
                row = cursor.fetchone()
        except sqlite3.Error:
            return None

        if row:
            try:
                value = pickle.loads(row[0])
            except (pickle.UnpicklingError, EOFError, AttributeError):
                return None
            with self._lock:
                self.hits += 1
            return value

        with self._lock:
            self.misses += 1
        return None

    def _set(self, key: str, value: Any, entry_type: str, ttl_seconds: int) -> None:
        try:
            payload = pickle.dumps(value)
        except (pickle.PicklingError, TypeError):
            return
        try:
            with _connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO cache (key, entry_type, value, created_at, ttl_seconds)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
                    """,
                    (key, entry_type, payload, ttl_seconds),
                )
                conn.commit()
        except sqlite3.Error:
            pass

    def clear_expired(self) -> int:
        """Delete entries past their TTL. Returns the number removed."""
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                DELETE FROM cache
                WHERE ttl_seconds IS NOT NULL
                  AND datetime(created_at, '+' || ttl_seconds || ' seconds') <= datetime('now')
                """
            )
            conn.commit()
            return cursor.rowcount

    def clear_all(self, entry_type: Optional[str] = None) -> int:
        with _connect(self.db_path) as conn:
            if entry_type:
                cursor = conn.execute("DELETE FROM cache WHERE entry_type = ?", (entry_type,))
            else:
                cursor = conn.execute("DELETE FROM cache")
            conn.commit()
            return cursor.rowcount

    def get_stats(self) -> Dict[str, Any]:
        with _connect(self.db_path) as conn:
            by_type = {
                row[0]: row[1]
                for row in conn.execute("SELECT entry_type, COUNT(*) FROM cache GROUP BY entry_type")
            }
            total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]

        lookups = self.hits + self.misses
        return {
            "total_entries": total,
            "by_type": by_type,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / lookups, 4) if lookups else 0.0,
        }


__all__ = ["CacheEngine", "CacheEntry"]
