"""Graph-based retrieval implementations."""

import re
import sqlite3
import json
from typing import List, Dict, Any, Optional

from .base import BaseRetriever, SQLiteCorpusMixin
from ..models import RetrievalResult
from ..storage.sqlite_conn import connect as _connect


def _concept_matches_query(cp: str, query_tokens: set, query_word_list: List[str]) -> bool:
    """Whole-word/phrase-boundary-aware match of a concept string against a query.

    Replaces raw substring containment (`cp in query.lower()` / `token in cp`), which
    spuriously matched e.g. concept "cat" against query "category", or concept "ca"
    against query "cats are great" purely on character overlap. A concept matches only
    if its tokens equal a whole query token (single-word concept) or appear as a
    contiguous run of whole query tokens in order (multi-word/phrase concept).
    """
    cp_tokens = re.findall(r"\w+", cp)
    if not cp_tokens:
        return False
    if len(cp_tokens) == 1:
        return cp_tokens[0] in query_tokens
    n = len(cp_tokens)
    for i in range(len(query_word_list) - n + 1):
        if query_word_list[i:i + n] == cp_tokens:
            return True
    return False


class GraphRetriever(BaseRetriever):
    """Production graph retriever using Neo4j multi-hop traversal."""

    def __init__(self, neo4j_driver, cache_engine: Optional[Any] = None):
        super().__init__(cache_engine=cache_engine)
        self.driver = neo4j_driver

    def _retrieve_impl(self, query: str, top_k: int, max_hops: int = 3, **kwargs) -> List[RetrievalResult]:
        results = []

        cypher_query = f"""
        CALL db.index.fulltext.queryNodes("concept_name_index", $query) YIELD node, score
        MATCH path = (node)-[:PROVIDES|DEPENDS_ON*1..{max_hops}]-(c:Chunk)
        RETURN DISTINCT c.id AS chunk_id, score * (0.8 ^ (length(path)-1)) AS path_score
        ORDER BY path_score DESC
        LIMIT $top_k
        """

        try:
            with self.driver.session() as session:
                records = session.run(cypher_query, query=query, top_k=top_k)

                for record in records:
                    chunk_id = record["chunk_id"]
                    path_score = record["path_score"]

                    if chunk_id:
                        results.append(RetrievalResult(
                            chunk_id=chunk_id,
                            score=float(path_score),
                            source="graph"
                        ))

                        if len(results) >= top_k:
                            break
        except Exception as e:
            print(f"Graph retrieval failed: {e}")

        return results


class SQLiteGraphRetriever(SQLiteCorpusMixin, BaseRetriever):
    """Lightweight graph retriever using SQLite in-memory concept graph."""

    def __init__(self, db_path: str, cache_engine: Optional[Any] = None):
        super().__init__(cache_engine=cache_engine)
        self.db_path = db_path

    def _retrieve_impl(
        self,
        query: str,
        top_k: int,
        max_hops: int = 3,
        document_id: Optional[str] = None,
        **kwargs,
    ) -> List[RetrievalResult]:
        query_tokens = set(re.findall(r"\w+", query.lower()))
        if not query_tokens:
            return []

        conn = _connect(self.db_path)
        try:
            if document_id is not None:
                try:
                    rows = conn.execute(
                        "SELECT chunk_id, text, metadata FROM chunks WHERE document_id = ?",
                        (document_id,),
                    ).fetchall()
                except sqlite3.OperationalError:
                    try:
                        rows = [
                            (r[0], r[1], None)
                            for r in conn.execute(
                                "SELECT chunk_id, text FROM chunks WHERE document_id = ?",
                                (document_id,),
                            ).fetchall()
                        ]
                    except Exception:
                        rows = []
            else:
                try:
                    rows = conn.execute("SELECT chunk_id, text, metadata FROM chunks").fetchall()
                except sqlite3.OperationalError:
                    try:
                        rows = [(r[0], r[1], None) for r in conn.execute("SELECT chunk_id, text FROM chunks").fetchall()]
                    except Exception:
                        rows = []
        finally:
            conn.close()

        chunks_map = {}
        concept_to_providers = {}
        concept_to_dependents = {}

        for chunk_id, text, metadata_json in rows:
            try:
                metadata = json.loads(metadata_json) if metadata_json else {}
            except Exception:
                metadata = {}

            provides = metadata.get("provides", [])
            depends_on = metadata.get("depends_on", [])

            chunks_map[chunk_id] = {
                "chunk_id": chunk_id,
                "text": text,
                "provides": provides,
                "depends_on": depends_on
            }

            for cp in provides:
                concept_to_providers.setdefault(cp.lower(), []).append(chunk_id)
            for cp in depends_on:
                concept_to_dependents.setdefault(cp.lower(), []).append(chunk_id)

        query_word_list = re.findall(r"\w+", query.lower())
        matched_concepts = []
        for cp in list(concept_to_providers.keys()) + list(concept_to_dependents.keys()):
            if _concept_matches_query(cp, query_tokens, query_word_list):
                matched_concepts.append(cp)
        matched_concepts = list(dict.fromkeys(matched_concepts))

        visited_chunks = {}
        for cp in matched_concepts:
            connected = set(concept_to_providers.get(cp, []) + concept_to_dependents.get(cp, []))
            for cid in connected:
                visited_chunks[cid] = max(visited_chunks.get(cid, 0.0), 1.0)

            for hop in range(1, max_hops):
                next_connected = set()
                for cid in connected:
                    cdata = chunks_map.get(cid)
                    if not cdata:
                        continue
                    all_chunk_concepts = cdata["provides"] + cdata["depends_on"]
                    for c_name in all_chunk_concepts:
                        c_name_lower = c_name.lower()
                        others = concept_to_providers.get(c_name_lower, []) + concept_to_dependents.get(c_name_lower, [])
                        for other_id in others:
                            if other_id != cid:
                                next_connected.add(other_id)

                score_decay = 0.8 ** hop
                for cid in next_connected:
                    visited_chunks[cid] = max(visited_chunks.get(cid, 0.0), score_decay)
                connected = next_connected

        if not visited_chunks:
            scored = []
            for chunk_id, text, _ in rows:
                text_tokens = set(re.findall(r"\w+", text.lower()))
                overlap = len(query_tokens & text_tokens)
                if overlap:
                    scored.append((overlap, chunk_id))
            scored.sort(reverse=True)
            return [
                RetrievalResult(chunk_id=chunk_id, score=float(score) * 0.9, source="graph")
                for score, chunk_id in scored[:top_k]
            ]

        results = [
            RetrievalResult(chunk_id=cid, score=score, source="graph")
            for cid, score in visited_chunks.items()
        ]
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]
