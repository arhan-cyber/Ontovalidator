"""Confirm retrieval is scoped to one document, not the whole shared DB.

Previously the SQLite retrievers ran `SELECT ... FROM chunks` with no
`document_id` filter, so any two documents ingested into the same DB file
could leak evidence into each other's verdicts.
"""

from src.config import PipelineConfig, BackendMode
from src.engine import SVOVerificationEngine
from src.models import OntologyAssertion
from src.retrieval.lexical import SQLiteLexicalRetriever
from src.retrieval.semantic import SQLiteSemanticRetriever
from src.retrieval.graph import SQLiteGraphRetriever


def test_no_cross_document_evidence_in_validate_triples_batch(temp_db_path):
    config = PipelineConfig(backend_mode=BackendMode.DEMO, sqlite_path=temp_db_path)
    engine = SVOVerificationEngine.from_config(config)

    engine.validate_triples_batch(
        document_id="doc_a",
        raw_text="Rockets use liquid oxygen as an oxidizer.",
        triples=[],
        top_k=5,
    )

    triple = OntologyAssertion(
        assertion_id="t1",
        subject="Rockets",
        relation="use",
        object="liquid oxygen",
        polarity="must_hold",
        rule_type="constraint",
    )
    result = engine.validate_triples_batch(
        document_id="doc_b",
        raw_text="Bees pollinate flowering plants.",
        triples=[triple],
        top_k=5,
    )

    verdict = result["verdicts"][0]
    for span in verdict["evidence"]:
        assert "rocket" not in span["text"].lower()
        assert "oxidizer" not in span["text"].lower()
    for rejected in verdict["rejected_evidence"]:
        assert "rocket" not in rejected["text"].lower()


def _ingest_two_documents(db_path):
    from src.ingestion import DataIngestor, SimpleEmbeddingModel, MockSVOExtractor, MockConceptExtractor

    ingestor = DataIngestor(
        sqlite_conn_path=db_path,
        es_client=None,
        milvus_collection=None,
        neo4j_driver=None,
        embedding_model=SimpleEmbeddingModel(),
        svo_extractor=MockSVOExtractor(),
        concept_extractor=MockConceptExtractor(),
    )
    ingestor.ingest_document("doc_a", "Rockets use liquid oxygen as an oxidizer.")
    ingestor.ingest_document("doc_b", "Bees pollinate flowering plants.")


def test_lexical_retriever_scoped_to_document_id(temp_db_path):
    _ingest_two_documents(temp_db_path)
    retriever = SQLiteLexicalRetriever(temp_db_path)

    scoped = retriever.retrieve("Rockets liquid oxygen oxidizer", 10, document_id="doc_b")
    assert scoped == []

    unscoped = retriever.retrieve("Rockets liquid oxygen oxidizer", 10)
    assert len(unscoped) > 0


def test_semantic_retriever_scoped_to_document_id(temp_db_path):
    _ingest_two_documents(temp_db_path)
    retriever = SQLiteSemanticRetriever(temp_db_path)

    scoped = retriever.retrieve("Rockets liquid oxygen oxidizer", 10, document_id="doc_b")
    assert scoped == []


def test_graph_retriever_scoped_to_document_id(temp_db_path):
    _ingest_two_documents(temp_db_path)
    retriever = SQLiteGraphRetriever(temp_db_path)

    scoped = retriever.retrieve("Rockets liquid oxygen oxidizer", 10, document_id="doc_b")
    # No graph edges match either, so this exercises the lexical-overlap
    # fallback inside the graph retriever - still must respect document_id.
    assert scoped == []
