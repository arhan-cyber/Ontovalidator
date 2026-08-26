"""Lexical (BM25) retrieval implementations."""

import re
import sqlite3
from typing import Any, List, Optional

from .base import BaseRetriever, SQLiteCorpusMixin
from ..models import RetrievalResult
from ..storage.sqlite_conn import connect as _connect


class LexicalRetriever(BaseRetriever):
    """Production lexical retriever using Elasticsearch BM25."""

    def __init__(self, es_client, index_name: str = "svo_chunks", cache_engine: Optional[Any] = None):
        super().__init__(cache_engine=cache_engine)
        self.es_client = es_client
        self.index_name = index_name

    def _retrieve_impl(self, query: str, top_k: int, **kwargs) -> List[RetrievalResult]:
        es_query = {
            "query": {
                "match": {
                    "text": {
                        "query": query,
                        "fuzziness": "AUTO"
                    }
                }
            },
            "size": top_k
        }

        results = []
        try:
            response = self.es_client.search(index=self.index_name, body=es_query)

            for hit in response.get("hits", {}).get("hits", []):
                results.append(RetrievalResult(
                    chunk_id=hit["_id"],
                    score=hit["_score"],
                    source="lexical"
                ))
        except Exception as e:
            print(f"Lexical retrieval failed: {e}")

        return results


class SQLiteLexicalRetriever(SQLiteCorpusMixin, BaseRetriever):
    """Lightweight lexical retriever using SQLite (CPU-only, no external deps)."""

    def __init__(self, db_path: str, cache_engine: Optional[Any] = None):
        super().__init__(cache_engine=cache_engine)
        self.db_path = db_path

    def _retrieve_impl(
        self, query: str, top_k: int, document_id: Optional[str] = None, **kwargs
    ) -> List[RetrievalResult]:
        query_tokens = set(re.findall(r"\w+", query.lower()))
        if not query_tokens:
            return []

        conn = _connect(self.db_path)
        try:
            if document_id is not None:
                rows = conn.execute(
                    "SELECT chunk_id, text FROM chunks WHERE document_id = ?", (document_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT chunk_id, text FROM chunks").fetchall()
        finally:
            conn.close()

        scored = []
        for chunk_id, text in rows:
            text_tokens = set(re.findall(r"\w+", text.lower()))
            overlap = len(query_tokens & text_tokens)
            if overlap:
                scored.append((overlap, chunk_id))

        scored.sort(reverse=True)
        return [
            RetrievalResult(chunk_id=chunk_id, score=float(score), source="lexical")
            for score, chunk_id in scored[:top_k]
        ]
