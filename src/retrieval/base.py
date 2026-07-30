"""Base retriever interface with an optional caching layer."""

import sqlite3
from abc import ABC, abstractmethod
from dataclasses import asdict
from typing import Any, List, Optional

from ..models import RetrievalResult


class BaseRetriever(ABC):
    """Template method: `retrieve` handles caching, subclasses implement `_retrieve_impl`."""

    def __init__(self, cache_engine: Optional[Any] = None):
        self.cache = cache_engine

    def retrieve(self, query: str, top_k: int, **kwargs) -> List[RetrievalResult]:
        cache = getattr(self, "cache", None)
        fingerprint = None
        if cache is not None:
            fingerprint = self._cache_fingerprint(**kwargs)
            cached = cache.get_retrieval(query, type(self).__name__, top_k, fingerprint)
            if cached is not None:
                return [RetrievalResult(**entry) for entry in cached]

        results = self._retrieve_impl(query, top_k, **kwargs)

        if cache is not None:
            # `chunk` is populated later by the engine from the chunk store; caching
            # it here would persist a whole document body per retrieval result.
            payload = []
            for result in results:
                entry = asdict(result)
                entry["chunk"] = None
                payload.append(entry)
            cache.set_retrieval(query, type(self).__name__, top_k, payload, fingerprint)

        return results

    @abstractmethod
    def _retrieve_impl(self, query: str, top_k: int, **kwargs) -> List[RetrievalResult]:
        pass

    def _cache_fingerprint(self, **kwargs) -> str:
        """Identifies the corpus state a cached result is only valid for.

        Cached retrieval must not survive re-ingestion, so the key includes a
        cheap digest of the backing corpus plus any retrieval options.
        """
        parts = [f"{k}={v}" for k, v in sorted(kwargs.items())]
        return "|".join([self._corpus_state(), *parts])

    def _corpus_state(self) -> str:
        """Subclasses backed by a mutable corpus override this. Default: unknown."""
        return "static"


class SQLiteCorpusMixin:
    """Corpus fingerprint for retrievers reading the local `chunks` table."""

    def _corpus_state(self) -> str:
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                count, newest = conn.execute(
                    "SELECT COUNT(*), COALESCE(MAX(chunk_id), '') FROM chunks"
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return "unavailable"
        return f"{count}:{newest}"
