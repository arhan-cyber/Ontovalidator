"""Semantic (dense vector) retrieval implementations."""

import re
import sqlite3
from typing import List, Dict, Any, Optional

from .base import BaseRetriever
from ..models import RetrievalResult


class MilvusSemanticRetriever(BaseRetriever):
    """Production semantic retriever using Milvus ANN search."""

    def __init__(self, collection_name: str, embedding_model, search_params: dict = None):
        from pymilvus import Collection

        self.collection = Collection(collection_name)
        self.collection.load()
        self.embedding_model = embedding_model
        self.search_params = search_params or {"metric_type": "COSINE", "params": {"nprobe": 10}}

    def retrieve(self, query: str, top_k: int) -> List[RetrievalResult]:
        results = []
        try:
            query_vector = self.embedding_model.encode(query)
            if hasattr(query_vector, "tolist"):
                query_vector = query_vector.tolist()

            search_response = self.collection.search(
                data=[query_vector],
                anns_field="embedding",
                param=self.search_params,
                limit=top_k,
                output_fields=["chunk_id"]
            )

            for hits in search_response:
                for hit in hits:
                    results.append(RetrievalResult(
                        chunk_id=str(hit.id),
                        score=float(hit.distance),
                        source="semantic"
                    ))
        except Exception as e:
            print(f"Milvus semantic retrieval failed: {e}")

        return results


class SQLiteSemanticRetriever(BaseRetriever):
    """Lightweight semantic retriever using Jaccard similarity on SQLite."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def retrieve(self, query: str, top_k: int) -> List[RetrievalResult]:
        query_tokens = set(re.findall(r"\w+", query.lower()))
        if not query_tokens:
            return []

        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute("SELECT chunk_id, text FROM chunks").fetchall()
        finally:
            conn.close()

        scored = []
        for chunk_id, text in rows:
            text_tokens = set(re.findall(r"\w+", text.lower()))
            if not text_tokens:
                continue
            overlap = len(query_tokens & text_tokens)
            union = len(query_tokens | text_tokens)
            score = overlap / union if union else 0.0
            if score:
                scored.append((score, chunk_id))

        scored.sort(reverse=True)
        return [
            RetrievalResult(chunk_id=chunk_id, score=float(score), source="semantic")
            for score, chunk_id in scored[:top_k]
        ]
