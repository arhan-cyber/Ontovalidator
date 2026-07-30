"""Multi-modal ingestion: every modality is stored, typed, and retrievable."""

import os
import sqlite3
from contextlib import closing

import pytest

from src.config import PipelineConfig
from src.ingestion import DataIngestor, MockConceptExtractor, MockSVOExtractor, SimpleEmbeddingModel
from src.models import ChunkType
from src.retrieval import SQLiteLexicalRetriever
from src.storage import SQLiteChunkStore

DOCUMENT = """Published: 2020-05-14

Aspirin is a widely used analgesic.

Known uses:
- Aspirin treats headache
- Aspirin reduces fever
"""

TABLE = """
<table>
  <tr><th>Drug</th><th>Treats</th></tr>
  <tr><td>Aspirin</td><td>Headache</td></tr>
</table>
"""


def make_ingestor(db_path, config=None):
    return DataIngestor(
        sqlite_conn_path=db_path,
        es_client=None,
        milvus_collection=None,
        neo4j_driver=None,
        embedding_model=SimpleEmbeddingModel(),
        svo_extractor=MockSVOExtractor(),
        concept_extractor=MockConceptExtractor(),
        config=config,
    )


@pytest.fixture
def db_path(tmp_workspace):
    return os.path.join(tmp_workspace, "svo.db")


def stored_chunks(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute(
            "SELECT text, chunk_type, type_metadata, timestamp FROM chunks"
        ).fetchall()


class TestModalityExtraction:
    def test_list_items_become_their_own_chunks(self, db_path):
        result = make_ingestor(db_path).ingest_document("doc1", DOCUMENT)

        assert result["chunk_types"][ChunkType.LIST_ITEM.value] == 2
        list_texts = [row[0] for row in stored_chunks(db_path) if row[1] == "list_item"]
        assert "Aspirin treats headache" in list_texts

    def test_table_rows_become_their_own_chunks(self, db_path):
        result = make_ingestor(db_path).ingest_document("doc1", DOCUMENT, tables=[TABLE])

        assert result["chunk_types"][ChunkType.TABLE_ROW.value] == 1
        table_texts = [row[0] for row in stored_chunks(db_path) if row[1] == "table_row"]
        assert table_texts == ["Drug: Aspirin | Treats: Headache"]

    def test_prose_chunks_keep_the_text_type(self, db_path):
        result = make_ingestor(db_path).ingest_document("doc1", DOCUMENT)

        assert result["chunk_types"][ChunkType.TEXT.value] > 0

    def test_extraction_can_be_disabled_by_config(self, db_path):
        config = PipelineConfig(sqlite_path=db_path, enable_list_extraction=False)
        result = make_ingestor(db_path, config).ingest_document("doc1", DOCUMENT)

        assert ChunkType.LIST_ITEM.value not in result["chunk_types"]

    def test_ocr_is_skipped_unless_enabled(self, db_path):
        result = make_ingestor(db_path).ingest_document("doc1", DOCUMENT, images=["/nonexistent.png"])

        assert ChunkType.IMAGE.value not in result["chunk_types"]


class TestPersistence:
    def test_type_metadata_survives_a_round_trip(self, db_path):
        make_ingestor(db_path).ingest_document("doc1", DOCUMENT, tables=[TABLE])
        store = SQLiteChunkStore(db_path)

        with closing(sqlite3.connect(db_path)) as conn:
            chunk_ids = [
                row[0] for row in conn.execute("SELECT chunk_id FROM chunks WHERE chunk_type = 'table_row'")
            ]
        chunk = store.get_chunks(chunk_ids)[0]

        assert chunk.chunk_type == ChunkType.TABLE_ROW
        assert chunk.type_metadata["headers"] == ["Drug", "Treats"]

    def test_timestamps_survive_a_round_trip(self, db_path):
        make_ingestor(db_path).ingest_document("doc1", DOCUMENT)
        store = SQLiteChunkStore(db_path)

        with closing(sqlite3.connect(db_path)) as conn:
            chunk_ids = [row[0] for row in conn.execute("SELECT chunk_id FROM chunks")]
        chunks = store.get_chunks(chunk_ids)

        assert all(c.timestamp is not None for c in chunks)
        assert all(c.timestamp.year == 2020 for c in chunks)

    def test_a_legacy_database_is_migrated_in_place(self, db_path):
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute(
                "CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, document_id TEXT, text TEXT, metadata TEXT)"
            )
            conn.execute("INSERT INTO chunks VALUES ('old', 'doc0', 'Legacy chunk.', '{}')")
            conn.commit()

        make_ingestor(db_path).ingest_document("doc1", DOCUMENT)
        legacy = SQLiteChunkStore(db_path).get_chunks(["old"])[0]

        assert legacy.text == "Legacy chunk."
        assert legacy.chunk_type == ChunkType.TEXT


class TestRetrievalAcrossModalities:
    def test_a_table_row_can_be_retrieved(self, db_path):
        make_ingestor(db_path).ingest_document("doc1", "Unrelated prose.", tables=[TABLE])

        results = SQLiteLexicalRetriever(db_path).retrieve("Drug Aspirin Treats Headache", 5)
        retrieved = SQLiteChunkStore(db_path).get_chunks([r.chunk_id for r in results])

        assert any(c.chunk_type == ChunkType.TABLE_ROW for c in retrieved)

    def test_a_list_item_can_be_retrieved(self, db_path):
        make_ingestor(db_path).ingest_document("doc1", DOCUMENT)

        results = SQLiteLexicalRetriever(db_path).retrieve("Aspirin reduces fever", 10)
        retrieved = SQLiteChunkStore(db_path).get_chunks([r.chunk_id for r in results])

        assert any(c.chunk_type == ChunkType.LIST_ITEM for c in retrieved)
