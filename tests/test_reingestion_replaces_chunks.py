"""Re-ingesting a document_id must replace its chunks, not accumulate them.

Each ingestion generates fresh chunk_id UUIDs, so `INSERT OR REPLACE` keyed
on chunk_id never touched a document's previous rows - re-posting a
corrected document under the same document_id (or two concurrent requests
racing for the same document_id) silently left old, possibly-wrong content
in the DB forever, growing without bound and still surfacing as evidence.
`_write_sqlite` now deletes a document's prior rows in the same transaction
as the new inserts, so re-ingestion is a clean replace and concurrent
same-document_id writers serialize into one consistent result.
"""

import os
import sqlite3
import tempfile
import threading
import time

from src.ingestion import DataIngestor, MockConceptExtractor, MockSVOExtractor, SimpleEmbeddingModel


def _make_ingestor(db_path):
    return DataIngestor(
        sqlite_conn_path=db_path,
        es_client=None,
        milvus_collection=None,
        neo4j_driver=None,
        embedding_model=SimpleEmbeddingModel(),
        svo_extractor=MockSVOExtractor(),
        concept_extractor=MockConceptExtractor(),
    )


def test_sequential_reingest_replaces_old_chunks(tmp_path):
    db_path = os.path.join(tmp_path, "reingest.db")
    _make_ingestor(db_path).ingest_document("doc1", "Original wrong content. Should be replaced.")
    _make_ingestor(db_path).ingest_document("doc1", "Corrected content.")

    conn = sqlite3.connect(db_path)
    try:
        rows = [r[0] for r in conn.execute("SELECT text FROM chunks WHERE document_id='doc1'").fetchall()]
    finally:
        conn.close()

    assert rows == ["Corrected content."]


def test_reingest_does_not_affect_other_documents(tmp_path):
    db_path = os.path.join(tmp_path, "multi.db")
    _make_ingestor(db_path).ingest_document("doc_a", "Content for document A.")
    _make_ingestor(db_path).ingest_document("doc_b", "Content for document B.")
    _make_ingestor(db_path).ingest_document("doc_a", "Updated content for document A.")

    conn = sqlite3.connect(db_path)
    try:
        a_rows = [r[0] for r in conn.execute("SELECT text FROM chunks WHERE document_id='doc_a'").fetchall()]
        b_rows = [r[0] for r in conn.execute("SELECT text FROM chunks WHERE document_id='doc_b'").fetchall()]
    finally:
        conn.close()

    assert a_rows == ["Updated content for document A."]
    assert b_rows == ["Content for document B."]  # untouched by doc_a's re-ingestion


def test_concurrent_same_document_id_ingestion_never_leaves_a_mixed_state(tmp_path):
    db_path = os.path.join(tmp_path, "race.db")
    large_text = "Paris is the capital of France. " * 200
    small_text = "Berlin is the capital of Germany."
    results = {}

    def run(name, text):
        results[name] = _make_ingestor(db_path).ingest_document("race_doc", text)

    t1 = threading.Thread(target=run, args=("large", large_text))
    t2 = threading.Thread(target=run, args=("small", small_text))
    t1.start()
    time.sleep(0.05)
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert results["large"]["status"] == "success"
    assert results["small"]["status"] == "success"

    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id='race_doc'").fetchone()[0]
    finally:
        conn.close()

    # Whichever ingestion's transaction committed last wins entirely - the
    # count must be exactly one or the other, never a partial mix of both.
    assert count in (1, 200), f"expected a clean last-writer-wins result, got {count} chunks"
