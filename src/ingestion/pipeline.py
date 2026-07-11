"""Document ingestion and processing pipeline."""

import uuid
import json
import re
import sqlite3
from typing import List, Dict, Any, Optional

from ..models import Chunk, SVORelation
from .extractors import MockSVOExtractor, MockConceptExtractor
from .embeddings import SimpleEmbeddingModel


class LocalElasticsearchClient:
    """Mock Elasticsearch client for demo mode."""

    def bulk(self, operations=None, **kwargs):
        return {"items": []}


class LocalMilvusCollection:
    """Mock Milvus collection for demo mode."""

    def __init__(self):
        self.records = []

    def insert(self, data):
        self.records.extend(data)

    def flush(self):
        return None


class LocalNeo4jDriver:
    """Mock Neo4j driver for demo mode."""

    def __init__(self):
        self.records = []

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, **kwargs):
        self.records.append((query, kwargs))
        return None


class DataIngestor:
    """Main ingestion pipeline: chunking, embedding, SVO extraction, and storage."""

    def __init__(
        self,
        sqlite_conn_path: str,
        es_client,
        milvus_collection,
        neo4j_driver,
        embedding_model,
        svo_extractor,
        concept_extractor=None,
        config=None
    ):
        self.sqlite_path = sqlite_conn_path
        self.es_client = es_client
        self.milvus_collection = milvus_collection
        self.neo4j_driver = neo4j_driver
        self.embedding_model = embedding_model
        self.svo_extractor = svo_extractor
        self.config = config

        if concept_extractor is None:
            self.concept_extractor = MockConceptExtractor()
        else:
            self.concept_extractor = concept_extractor

        if config and config.verbose:
            print(f"DataIngestor initialized with config: backend_mode={config.backend_mode.value}")

    _SENTENCE_PATTERN = re.compile(r".+?[.!?](?:\[[^\]]*\])*(?=\s+|$)")

    def chunk_document(self, document_id: str, raw_text: str) -> List[Chunk]:
        """Split raw text into chunks by sentence.

        Citation markers like "[62]" commonly sit directly against the
        preceding punctuation with no space (Wikipedia-style text), so a
        plain split on `[.!?]\\s+` treats the whole passage as one sentence.
        Matching sentences directly (rather than splitting on boundaries)
        lets trailing citation brackets stay attached to their sentence.
        """
        stripped = raw_text.strip()
        sentences = self._SENTENCE_PATTERN.findall(stripped)
        if not sentences:
            sentences = [stripped]
        chunks = []

        for sentence in sentences:
            if not sentence.strip():
                continue
            chunk_id = str(uuid.uuid4())
            chunks.append(Chunk(
                chunk_id=chunk_id,
                document_id=document_id,
                text=sentence.strip(),
                embedding=None,
                metadata={"source": "ingestion_script", "word_count": len(sentence.split())}
            ))

        if not chunks:
            chunks.append(Chunk(
                chunk_id=str(uuid.uuid4()),
                document_id=document_id,
                text=raw_text,
                embedding=None,
                metadata={"source": "ingestion_script", "word_count": len(raw_text.split())}
            ))

        return chunks

    def ingest_document(self, document_id: str, raw_text: str):
        """Main pipeline: chunk → embed → extract → store."""
        print(f"Starting ingestion for Document: {document_id}")

        # 1. Chunking
        chunks = self.chunk_document(document_id, raw_text)
        print(f"  -> Generated {len(chunks)} chunks.")

        # 2. Embeddings
        texts = [c.text for c in chunks]
        embeddings = self.embedding_model.encode(texts)
        if hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()

        for chunk, emb in zip(chunks, embeddings):
            chunk.embedding = emb
        print("  -> Generated vector embeddings.")

        # 3. SVO and Concept Extraction
        all_svos = []
        for chunk in chunks:
            extracted_svos = self.svo_extractor.extract(chunk.text)
            for svo in extracted_svos:
                svo.source_chunk_ids = [chunk.chunk_id]
                all_svos.append(svo)

        try:
            if hasattr(self.concept_extractor, "extract_concepts_batch"):
                chunk_texts = [c.text for c in chunks]
                concepts_batch = self.concept_extractor.extract_concepts_batch(chunk_texts)
                for chunk, concepts in zip(chunks, concepts_batch):
                    chunk.metadata["provides"] = concepts.get("provides", [])
                    chunk.metadata["depends_on"] = concepts.get("depends_on", [])
            else:
                for chunk in chunks:
                    concepts = self.concept_extractor.extract_concepts(chunk.text)
                    chunk.metadata["provides"] = concepts.get("provides", [])
                    chunk.metadata["depends_on"] = concepts.get("depends_on", [])
        except Exception as e:
            if self.config and self.config.verbose:
                print(f"  [!] Concept extraction failed: {type(e).__name__}: {e}")

        print(f"  -> Extracted {len(all_svos)} SVO relations and concepts.")

        # 4. Write to all stores
        self._write_sqlite(chunks)
        print("  -> Populated SQLite (Late Materialization ChunkStore).")

        self._write_elasticsearch(chunks)
        print("  -> Populated Elasticsearch (Lexical Store).")

        self._write_milvus(chunks)
        print("  -> Populated Milvus (Semantic Store).")

        self._write_neo4j(chunks, all_svos)
        print("  -> Populated Neo4j (Knowledge Graph Store).")

        print(f"Successfully completed ingestion for {document_id}!")
        return {
            "status": "success",
            "document_id": document_id,
            "chunks": len(chunks),
            "svos": len(all_svos),
            "sqlite_path": self.sqlite_path,
        }

    def _write_sqlite(self, chunks: List[Chunk]):
        conn = sqlite3.connect(self.sqlite_path)
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS chunks (
                        chunk_id TEXT PRIMARY KEY,
                        document_id TEXT,
                        text TEXT,
                        metadata TEXT
                    )
                """)
                for c in chunks:
                    conn.execute(
                        "INSERT OR REPLACE INTO chunks (chunk_id, document_id, text, metadata) VALUES (?, ?, ?, ?)",
                        (c.chunk_id, c.document_id, c.text, json.dumps(c.metadata))
                    )
        finally:
            conn.close()

    def _write_elasticsearch(self, chunks: List[Chunk]):
        if hasattr(self.es_client, "indices"):
            try:
                from ...ElasticSearch.es_helper import bulk_ingest_chunks
                bulk_ingest_chunks(self.es_client, chunks)
            except Exception as e:
                print(f"  [!] Production Elasticsearch write failed: {e}")
        else:
            actions = []
            for c in chunks:
                actions.append({"index": {"_index": "svo_chunks", "_id": c.chunk_id}})
                actions.append({"document_id": c.document_id, "text": c.text, "metadata": c.metadata})
            if actions:
                try:
                    self.es_client.bulk(operations=actions)
                except Exception as e:
                    print(f"  [!] Mock Elasticsearch write failed: {e}")

    def _write_milvus(self, chunks: List[Chunk]):
        data = [
            {
                "chunk_id": c.chunk_id,
                "embedding": c.embedding,
                "document_id": c.document_id
            }
            for c in chunks
        ]
        try:
            self.milvus_collection.insert(data)
            self.milvus_collection.flush()
        except Exception as e:
            print(f"  [!] Milvus write failed: {e}")

    def _write_neo4j(self, chunks: List[Chunk], svos: List[SVORelation] = None):
        if not self.neo4j_driver:
            print("  [!] Neo4j write skipped: No driver provided.")
            return
        with self.neo4j_driver.session() as session:
            for chunk in chunks:
                try:
                    session.run(
                        "MERGE (c:Chunk {id: $chunk_id}) SET c.text = $text, c.document_id = $document_id",
                        chunk_id=chunk.chunk_id,
                        text=chunk.text,
                        document_id=chunk.document_id
                    )

                    provides = chunk.metadata.get("provides", [])
                    for cp in provides:
                        concept_name = cp.strip().lower() if isinstance(cp, str) else str(cp).strip().lower()
                        session.run(
                            """
                            MERGE (c:Chunk {id: $chunk_id})
                            MERGE (cp:Concept {name: $concept_name})
                            MERGE (c)-[:PROVIDES]->(cp)
                            """,
                            chunk_id=chunk.chunk_id,
                            concept_name=concept_name
                        )

                    depends_on = chunk.metadata.get("depends_on", [])
                    for cp in depends_on:
                        concept_name = cp.strip().lower() if isinstance(cp, str) else str(cp).strip().lower()
                        session.run(
                            """
                            MERGE (c:Chunk {id: $chunk_id})
                            MERGE (cp:Concept {name: $concept_name})
                            MERGE (c)-[:DEPENDS_ON]->(cp)
                            """,
                            chunk_id=chunk.chunk_id,
                            concept_name=concept_name
                        )
                except Exception as e:
                    print(f"  [!] Neo4j write failed for chunk {chunk.chunk_id}: {e}")

            if svos:
                for svo in svos:
                    try:
                        rel_type = svo.relation.replace(' ', '_').replace('-', '_').upper()
                        session.run(
                            f"""
                            MERGE (s:Entity {{id: $subject_id}})
                            SET s.name = $subject_name
                            MERGE (o:Entity {{id: $object_id}})
                            SET o.name = $object_name
                            MERGE (s)-[r:`{rel_type}`]->(o)
                            """,
                            subject_id=svo.subject_id,
                            subject_name=svo.subject_name_type,
                            object_id=svo.object_id,
                            object_name=svo.object_name_type
                        )
                        for cid in svo.source_chunk_ids:
                            session.run(
                                f"""
                                MATCH (s:Entity {{id: $subject_id}})-[:`{rel_type}`]->(o:Entity {{id: $object_id}})
                                MATCH (c:Chunk {{id: $chunk_id}})
                                MERGE (c)-[:MENTIONS_RELATION]->(s)
                                MERGE (c)-[:MENTIONS_RELATION]->(o)
                                """,
                                subject_id=svo.subject_id,
                                object_id=svo.object_id,
                                chunk_id=cid
                            )
                    except Exception as e:
                        print(f"  [!] Neo4j write failed for SVO {svo.subject_id}-{svo.relation}-{svo.object_id}: {e}")


def run_demo(
    document_id: str = "demo_doc",
    raw_text: str = "Aspirin treats headache and reduces pain.",
    db_path: str = "svo_data.db",
    config=None,
    run_mode: str = None
) -> Dict[str, Any]:
    """
    Run the ingestion demo.

    Args:
        document_id: Document identifier
        raw_text: Text to ingest
        db_path: SQLite database path
        config: Optional PipelineConfig instance
        run_mode: Deprecated. Use config instead. "demo" or "full" mode
    """
    # Handle backward compatibility with run_mode parameter
    if config is None and run_mode is None:
        run_mode = "demo"  # Default behavior

    if config is not None:
        # Use config to determine backends
        from ..factories import EngineFactory
        ingestor = EngineFactory.create_ingestor(config)
    elif run_mode == "full":
        # Old behavior: use production backends
        try:
            from ..helpers.neo4j import get_neo4j_driver, initialize_neo4j_schema
            driver = get_neo4j_driver()
            initialize_neo4j_schema(driver)
        except ImportError:
            print("Error: Could not import 'neo4j'. Please run 'pip install neo4j'.")
            driver = LocalNeo4jDriver()

        try:
            from ..helpers.elasticsearch import get_elasticsearch_client
            es_client = get_elasticsearch_client()
        except ImportError:
            print("Error: Could not import 'elasticsearch'. Please run 'pip install elasticsearch'.")
            es_client = LocalElasticsearchClient()

        embedding_model = SimpleEmbeddingModel()
        dummy_emb = embedding_model.encode(["test"])
        emb_dim = len(dummy_emb[0]) if dummy_emb else 5

        try:
            from ..helpers.milvus import get_milvus_collection
            milvus_collection = get_milvus_collection(dim=emb_dim)
        except ImportError:
            print("Error: Could not import 'pymilvus'. Please run 'pip install pymilvus'.")
            milvus_collection = LocalMilvusCollection()

        ingestor = DataIngestor(
            sqlite_conn_path=db_path,
            es_client=es_client,
            milvus_collection=milvus_collection,
            neo4j_driver=driver,
            embedding_model=embedding_model,
            svo_extractor=MockSVOExtractor(),
            concept_extractor=MockConceptExtractor(),
        )
    else:
        # Default: demo mode with mock backends
        driver = LocalNeo4jDriver()
        es_client = LocalElasticsearchClient()
        milvus_collection = LocalMilvusCollection()
        embedding_model = SimpleEmbeddingModel()

        ingestor = DataIngestor(
            sqlite_conn_path=db_path,
            es_client=es_client,
            milvus_collection=milvus_collection,
            neo4j_driver=driver,
            embedding_model=embedding_model,
            svo_extractor=MockSVOExtractor(),
            concept_extractor=MockConceptExtractor(),
        )

    result = ingestor.ingest_document(document_id, raw_text)
    return result
