"""Integration tests for the SVO verification pipeline."""

import json


def test_ingestion_demo_runs(demo_db_path):
    """Test that ingestion completes successfully."""
    from src.ingestion import run_demo as run_ingestion_demo

    result = run_ingestion_demo(db_path=demo_db_path)
    assert result["status"] == "SUCCESS"
    assert "chunks" in result
    assert result["chunks"] > 0


def test_svo_engine_demo_runs(verification_engine):
    """Test that verification engine produces output."""
    result = verification_engine.verify("What treats headache?", top_k=5)
    assert result["status"] in ["EVIDENCE_GATHERED", "EVIDENCE_VALIDATED"]
    assert "evidence" in result


def test_cross_chunk_reasoning(tmp_workspace):
    """Test multi-chunk reasoning."""
    from src.ingestion import run_demo as run_ingestion_demo
    from src.engine import SVOVerificationEngine
    from src.routing import MoERouter
    from src.retrieval import SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever
    from src.fusion import WeightedFusionEngine
    from src.storage import SQLiteChunkStore
    from src.validation import MinimalValidator
    import os

    db_path = os.path.join(tmp_workspace, "cross_chunk.sqlite")
    document_text = (
        "Aspirin treats headache. "
        "The drug is also used to reduce fever and inflammation."
    )
    result = run_ingestion_demo(db_path=db_path, raw_text=document_text)
    assert result["status"] == "SUCCESS"

    engine = SVOVerificationEngine(
        router=MoERouter(),
        lexical_store=SQLiteLexicalRetriever(db_path),
        semantic_store=SQLiteSemanticRetriever(db_path),
        graph_store=SQLiteGraphRetriever(db_path),
        fusion_engine=WeightedFusionEngine(),
        chunk_store=SQLiteChunkStore(db_path),
        validator=MinimalValidator(),
    )

    verification = engine.verify("What treats headache and reduces fever?", top_k=5)
    evidence = verification.get("evidence", [])
    assert len(evidence) >= 2


def test_long_text_and_svo_validation(tmp_workspace):
    """Test ingestion and validation on longer text."""
    from src.ingestion import run_demo as run_ingestion_demo
    from src.engine import SVOVerificationEngine
    from src.routing import MoERouter
    from src.retrieval import SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever
    from src.fusion import WeightedFusionEngine
    from src.storage import SQLiteChunkStore
    from src.validation import MinimalValidator
    import os

    db_path = os.path.join(tmp_workspace, "long_text.sqlite")

    document_text = (
        "Aspirin is a widely used analgesic and antipyretic. "
        "For over a century, doctors have known that Aspirin treats headache and minor body aches.\n\n"
        "Clinical studies demonstrate that it also reduces fever and inflammation. "
        "However, it does not cure or treat malaria, which requires specific anti-malarial therapies."
    )

    result = run_ingestion_demo(db_path=db_path, raw_text=document_text)
    assert result["status"] == "SUCCESS"

    engine = SVOVerificationEngine(
        router=MoERouter(),
        lexical_store=SQLiteLexicalRetriever(db_path),
        semantic_store=SQLiteSemanticRetriever(db_path),
        graph_store=SQLiteGraphRetriever(db_path),
        fusion_engine=WeightedFusionEngine(),
        chunk_store=SQLiteChunkStore(db_path),
        validator=MinimalValidator(),
    )

    # Query 1: Existing SVO relation
    headache_verification = engine.verify("What treats headache?", top_k=5)
    headache_evidence = headache_verification.get("evidence", [])
    assert len(headache_evidence) > 0
    has_headache_evidence = any(
        "treats headache" in ev["text"].lower() for ev in headache_evidence if ev.get("text")
    )
    assert has_headache_evidence, "Should find evidence supporting headache treatment"

    # Query 2: Missing SVO relation
    malaria_verification = engine.verify("What treats malaria?", top_k=5)
    malaria_evidence = malaria_verification.get("evidence", [])
    # We may find chunks mentioning malaria, but none should say it treats malaria
    has_malaria_treats = any(
        "treats malaria" in ev["text"].lower() for ev in malaria_evidence if ev.get("text")
    )
    assert not has_malaria_treats, "Should not find evidence that Aspirin treats malaria"


def test_query_routing():
    """Test the MoE router."""
    from src.routing import MoERouter
    from src.models import QueryType

    router = MoERouter()

    # Test exact match routing
    routes = router.route("What is CHEMBL12345?")
    assert QueryType.EXACT_MATCH in routes

    # Test complex reasoning routing
    routes = router.route("How does climate change affect agriculture?")
    assert QueryType.COMPLEX in routes

    # Test multi-hop routing
    routes = router.route("What connects A indirectly to B?")
    assert QueryType.MULTI_HOP in routes

    # Test ontology routing
    routes = router.route("Does this violate the constraint?")
    assert QueryType.ONTOLOGY in routes


def test_fusion_engine():
    """Test the fusion engine."""
    from src.fusion import WeightedFusionEngine
    from src.models import RetrievalResult

    engine = WeightedFusionEngine()

    results = [
        RetrievalResult(chunk_id="c1", score=0.5, source="lexical"),
        RetrievalResult(chunk_id="c1", score=0.7, source="semantic"),
        RetrievalResult(chunk_id="c2", score=0.6, source="lexical"),
    ]

    fused = engine.fuse_and_rank(results, top_k=2)
    assert len(fused) == 2
    # c1 appears in both lexical and semantic, should score higher
    assert fused[0].chunk_id == "c1"
    assert fused[0].source == "fusion"


def test_chunk_store():
    """Test SQLite chunk store."""
    from src.storage import SQLiteChunkStore
    from src.models import Chunk
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        store = SQLiteChunkStore(db_path)

        # Test empty retrieval
        chunks = store.get_chunks([])
        assert chunks == []

        # Insert and retrieve
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
        ingestor.ingest_document("test_doc", "This is a test chunk.")

        chunks = store.get_chunks([])
        assert len(chunks) > 0
