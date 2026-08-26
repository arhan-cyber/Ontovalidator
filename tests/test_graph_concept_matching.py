"""Bug 3 repro tests: src/retrieval/graph.py's concept matching used raw substring
containment (`cp in query.lower()` / `token in cp`), so short/generic concept names
spuriously matched unrelated queries purely on character overlap:
  - concept "cat" matched query "category" (should not: "cat" is not a whole word there)
  - concept "ca" matched query "cats are great" (should not: "ca" is a substring of "cats")

Fixed via `_concept_matches_query` in src/retrieval/graph.py, which does
whole-word/phrase-boundary-aware token matching instead.
"""

import json

from src.retrieval.graph import SQLiteGraphRetriever, _concept_matches_query
from src.storage.chunk_store import ensure_chunks_schema
from src.storage.sqlite_conn import connect as _connect


def _seed(db_path, chunk_id, text, provides=None, depends_on=None, document_id="doc1"):
    conn = _connect(db_path)
    try:
        ensure_chunks_schema(conn)
        metadata = json.dumps({"provides": provides or [], "depends_on": depends_on or []})
        conn.execute(
            "INSERT INTO chunks (chunk_id, document_id, text, metadata) VALUES (?, ?, ?, ?)",
            (chunk_id, document_id, text, metadata),
        )
        conn.commit()
    finally:
        conn.close()


# --- unit-level: the matching predicate directly ---

def test_short_concept_not_substring_matched_against_longer_word():
    # concept "cat" must not match because query "category" contains it only as a substring
    assert _concept_matches_query("cat", {"category"}, ["category"]) is False


def test_short_concept_matches_whole_word_query():
    assert _concept_matches_query("cat", {"cat", "sat", "on", "the", "mat"}, ["the", "cat", "sat", "on", "the", "mat"]) is True


def test_short_query_token_not_substring_matched_against_longer_concept():
    # concept "ca" must not match query "cats are great" merely because "ca" is a
    # substring of "cats"
    tokens = {"cats", "are", "great"}
    words = ["cats", "are", "great"]
    assert _concept_matches_query("ca", tokens, words) is False


def test_multi_word_concept_requires_contiguous_phrase_match():
    assert _concept_matches_query(
        "machine learning", {"machine", "learning", "is", "fun"}, ["machine", "learning", "is", "fun"]
    ) is True
    # tokens present but not contiguous/ordered -> no match
    assert _concept_matches_query(
        "machine learning", {"machine", "learning"}, ["learning", "is", "about", "machine"]
    ) is False


# --- integration-level: through the retriever, via graph traversal side effects ---

def test_retriever_does_not_spuriously_traverse_on_substring_concept(tmp_path):
    db_path = str(tmp_path / "graph.db")
    # A chunk that "provides" the short concept "cat" -- unrelated content.
    _seed(db_path, "c1", "Felines are interesting animals.", provides=["cat"])
    # A second, unrelated chunk about categories that should NOT connect via "cat".
    _seed(db_path, "c2", "This document lists product categories for the catalog.")

    retriever = SQLiteGraphRetriever(db_path)
    results = retriever.retrieve("Please describe the category structure", top_k=10)

    # Graph traversal must not have matched "cat" against "category"/"catalog",
    # so c1 (which only connects via the "cat" concept) must not surface via a
    # graph hop -- it may still appear (or not) via the token-overlap fallback,
    # but only proportional to genuine token overlap, not a graph traversal hit
    # of score >= 1.0 (which only "visited_chunks" graph hops produce).
    graph_hit_c1 = [r for r in results if r.chunk_id == "c1" and r.score >= 1.0]
    assert graph_hit_c1 == []


def test_retriever_matches_whole_word_concept_correctly(tmp_path):
    db_path = str(tmp_path / "graph.db")
    _seed(db_path, "c1", "Felines are interesting animals.", provides=["cat"])
    _seed(db_path, "c2", "Cats need regular veterinary checkups.", depends_on=["cat"])

    retriever = SQLiteGraphRetriever(db_path)
    results = retriever.retrieve("Tell me about the cat", top_k=10)

    result_ids = {r.chunk_id for r in results}
    assert "c1" in result_ids
    assert "c2" in result_ids
