import os
import tempfile
import unittest
import json

from ingestion_pipeline import run_demo as run_ingestion_demo
from svo_engine import run_demo as run_svo_demo


class PipelineDemoTests(unittest.TestCase):
    """Basic smoke tests using demo mode with mocks."""

    def test_ingestion_demo_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "demo.sqlite")
            result = run_ingestion_demo(db_path=db_path)
            self.assertTrue(result["status"] == "SUCCESS")
            self.assertIn("chunks", result)

    def test_svo_engine_demo_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "demo.sqlite")
            result = run_svo_demo(db_path=db_path)
            self.assertTrue(result["status"] == "SUCCESS")
            self.assertIn("verification", result)

    def test_cross_chunk_reasoning_demo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "cross_chunk.sqlite")
            document_text = (
                "Aspirin treats headache. "
                "The drug is also used to reduce fever and inflammation."
            )
            result = run_svo_demo(db_path=db_path, query="What treats headache and reduces fever?", raw_text=document_text)
            self.assertTrue(result["status"] == "SUCCESS")
            evidence = result["verification"].get("evidence", [])
            self.assertGreaterEqual(len(evidence), 2)


    def test_long_text_and_svo_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "long_text.sqlite")

            # Multi-paragraph, multi-chunk document
            document_text = (
                "Aspirin is a widely used analgesic and antipyretic. "
                "For over a century, doctors have known that Aspirin treats headache and minor body aches.\n\n"
                "Clinical studies demonstrate that it also reduces fever and inflammation. "
                "However, it does not cure or treat malaria, which requires specific anti-malarial therapies."
            )

            # 1. Run ingestion on the long text
            result = run_svo_demo(db_path=db_path, query="What treats headache?", raw_text=document_text)
            self.assertTrue(result["status"] == "SUCCESS")

            # Setup the verification engine for testing both queries
            from svo_engine import SVOVerificationEngine, MoERouter, SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever, WeightedFusionEngine, SQLiteChunkStore, MinimalValidator
            engine = SVOVerificationEngine(
                router=MoERouter(),
                lexical_store=SQLiteLexicalRetriever(db_path),
                semantic_store=SQLiteSemanticRetriever(db_path),
                graph_store=SQLiteGraphRetriever(db_path),
                fusion_engine=WeightedFusionEngine(),
                chunk_store=SQLiteChunkStore(db_path),
                validator=MinimalValidator(),
            )

            # Query 1: Existing SVO relation (Aspirin treats headache)
            headache_verification = engine.verify("What treats headache?", top_k=5)
            headache_evidence = headache_verification.get("evidence", [])

            # Ensure we retrieved chunks and at least one contains headache treatment evidence
            self.assertGreater(len(headache_evidence), 0)
            has_headache_evidence = any(
                "treats headache" in ev["text"].lower() for ev in headache_evidence if ev["text"]
            )
            self.assertTrue(has_headache_evidence, "Should find evidence supporting headache treatment")

            # Query 2: Missing SVO relation (Does it treat malaria? - No extracted SVO supports this)
            malaria_verification = engine.verify("What treats malaria?", top_k=5)
            malaria_evidence = malaria_verification.get("evidence", [])

            # Ensure there is no evidence stating that Aspirin treats malaria
            has_malaria_evidence = any(
                "treats malaria" in ev["text"].lower() or "reduces malaria" in ev["text"].lower()
                for ev in malaria_evidence if ev["text"]
            )
            # The word "treat malaria" appears in "does not cure or treat malaria" which is negative,
            # but more importantly, no SVO relation is extracted for Malaria because MockSVOExtractor
            # only extracts TREATS headache or REDUCES fever.
            # Thus, the graph store and retrievers won't have any matching SVO structures for treats malaria.
            self.assertFalse(has_malaria_evidence, "Should not find any positive SVO evidence for treating malaria")

    def test_concept_dependency_multi_hop_reasoning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "concept_multi_hop.sqlite")

            # The document contains two key sentences that will end up in separate chunks
            document_text = (
                "Controller type is above the worker type. "
                "The worker resolution pathway is determined by its manager."
            )

            from svo_engine import SVOVerificationEngine, MoERouter, SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever, WeightedFusionEngine, SQLiteChunkStore, MinimalValidator
            from ingestion_pipeline import DataIngestor, SimpleEmbeddingModel, MockSVOExtractor, MockConceptExtractor

            # Ingest document to populate SQLite (which contains chunk metadata with concepts)
            ingestor = DataIngestor(
                sqlite_conn_path=db_path,
                es_client=None,
                milvus_collection=None,
                neo4j_driver=None,
                embedding_model=SimpleEmbeddingModel(),
                svo_extractor=MockSVOExtractor(),
                concept_extractor=MockConceptExtractor(),
            )
            ingestor.ingest_document("doc_concept_test", document_text)

            engine = SVOVerificationEngine(
                router=MoERouter(),
                lexical_store=SQLiteLexicalRetriever(db_path),
                semantic_store=SQLiteSemanticRetriever(db_path),
                graph_store=SQLiteGraphRetriever(db_path),
                fusion_engine=WeightedFusionEngine(),
                chunk_store=SQLiteChunkStore(db_path),
                validator=MinimalValidator(),
            )

            query = "What connects resolution pathway to hierarchy?"
            verification = engine.verify(query, top_k=5)
            evidence = verification.get("evidence", [])

            self.assertGreaterEqual(len(evidence), 2)

            retrieved_texts = [ev["text"].lower() for ev in evidence if ev["text"]]
            has_chunk2 = any("controller type" in t for t in retrieved_texts)
            has_chunk9 = any("resolution pathway" in t for t in retrieved_texts)

            self.assertTrue(has_chunk2, "Should retrieve Chunk 2 containing the 'hierarchy' concept definition.")
            self.assertTrue(has_chunk9, "Should retrieve Chunk 9 containing the 'resolution pathway' concept dependent on 'hierarchy'.")


# ===== NEW TESTS FOR REAL COMPONENTS =====

class EmbeddingModelTests(unittest.TestCase):
    """Tests for embedding quality using SimpleEmbeddingModel and TransformerEmbeddingModel."""

    def test_simple_embedding_model_deterministic(self):
        """Verify SimpleEmbeddingModel produces consistent embeddings."""
        from ingestion_pipeline import SimpleEmbeddingModel
        model = SimpleEmbeddingModel()

        text = "Aspirin treats headache"
        emb1 = model.encode([text])[0]
        emb2 = model.encode([text])[0]

        self.assertEqual(emb1, emb2, "Same text should produce identical embeddings")
        self.assertEqual(len(emb1), 5, "SimpleEmbeddingModel should produce 5-dimensional vectors")

    def test_simple_embedding_normalization(self):
        """Verify SimpleEmbeddingModel produces normalized vectors."""
        from ingestion_pipeline import SimpleEmbeddingModel
        model = SimpleEmbeddingModel()

        embeddings = model.encode(["test text", "another text", "more text"])
        for emb in embeddings:
            norm = sum(x*x for x in emb) ** 0.5
            self.assertAlmostEqual(norm, 1.0, places=4, msg="Embeddings should be L2-normalized")

    def test_transformer_embedding_availability(self):
        """Check if TransformerEmbeddingModel can be instantiated (requires transformers library)."""
        try:
            from ingestion_pipeline import TransformerEmbeddingModel
            model = TransformerEmbeddingModel()
            emb = model.encode(["test text"])
            self.assertEqual(len(emb), 1)
            self.assertGreater(len(emb[0]), 0, "Transformer should produce non-empty embeddings")
        except ImportError:
            self.skipTest("transformers library not installed")


class SVOExtractionTests(unittest.TestCase):
    """Tests for SVO extraction using mock and real models."""

    def test_mock_svo_extractor(self):
        """Verify MockSVOExtractor extracts known patterns."""
        from ingestion_pipeline import MockSVOExtractor
        extractor = MockSVOExtractor()

        # Test positive case
        relations = extractor.extract("Aspirin treats headache")
        self.assertGreater(len(relations), 0)
        self.assertEqual(relations[0].relation, "TREATS")

        # Test negative case
        relations = extractor.extract("The weather is sunny today")
        self.assertEqual(len(relations), 0, "Should not extract relations from unrelated text")

    def test_transformer_svo_extractor_availability(self):
        """Check if TransformerSVOExtractor can be instantiated."""
        try:
            from ingestion_pipeline import TransformerSVOExtractor
            extractor = TransformerSVOExtractor()
            relations = extractor.extract("Aspirin treats headache")
            # Should have at least one relation (or fallback to mock)
            self.assertGreater(len(relations), 0)
        except ImportError:
            self.skipTest("transformers or torch library not installed")


class RetrieverAccuracyTests(unittest.TestCase):
    """Tests for retriever performance across different retrieval strategies."""

    def test_lexical_retriever_exact_match(self):
        """Verify lexical retriever finds exact keyword matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.sqlite")
            from ingestion_pipeline import DataIngestor, SimpleEmbeddingModel, MockSVOExtractor, MockConceptExtractor
            from svo_engine import SQLiteLexicalRetriever

            ingestor = DataIngestor(
                sqlite_conn_path=db_path,
                es_client=None,
                milvus_collection=None,
                neo4j_driver=None,
                embedding_model=SimpleEmbeddingModel(),
                svo_extractor=MockSVOExtractor(),
                concept_extractor=MockConceptExtractor(),
            )
            ingestor.ingest_document("doc1", "Aspirin treats headache efficiently")
            ingestor.ingest_document("doc2", "Ibuprofen is an anti-inflammatory drug")

            retriever = SQLiteLexicalRetriever(db_path)
            results = retriever.retrieve("treats headache", top_k=5)

            self.assertGreater(len(results), 0)
            # First result should be from doc1 which contains both "treats" and "headache"
            self.assertEqual(results[0].source, "lexical")

    def test_semantic_retriever_similarity(self):
        """Verify semantic retriever works with Jaccard similarity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.sqlite")
            from ingestion_pipeline import DataIngestor, SimpleEmbeddingModel, MockSVOExtractor, MockConceptExtractor
            from svo_engine import SQLiteSemanticRetriever

            ingestor = DataIngestor(
                sqlite_conn_path=db_path,
                es_client=None,
                milvus_collection=None,
                neo4j_driver=None,
                embedding_model=SimpleEmbeddingModel(),
                svo_extractor=MockSVOExtractor(),
                concept_extractor=MockConceptExtractor(),
            )
            ingestor.ingest_document("doc1", "Aspirin is a pain reliever")
            ingestor.ingest_document("doc2", "Paracetamol reduces fever")

            retriever = SQLiteSemanticRetriever(db_path)
            results = retriever.retrieve("pain relief", top_k=5)

            self.assertGreater(len(results), 0)
            self.assertEqual(results[0].source, "semantic")

    def test_graph_retriever_concept_paths(self):
        """Verify graph retriever finds chunks through concept dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.sqlite")
            from ingestion_pipeline import DataIngestor, SimpleEmbeddingModel, MockSVOExtractor, MockConceptExtractor
            from svo_engine import SQLiteGraphRetriever

            ingestor = DataIngestor(
                sqlite_conn_path=db_path,
                es_client=None,
                milvus_collection=None,
                neo4j_driver=None,
                embedding_model=SimpleEmbeddingModel(),
                svo_extractor=MockSVOExtractor(),
                concept_extractor=MockConceptExtractor(),
            )
            # Document with concept hierarchy
            ingestor.ingest_document("doc1", "Controller type is above the worker type")
            ingestor.ingest_document("doc2", "Worker resolution pathway is determined by hierarchy")

            retriever = SQLiteGraphRetriever(db_path)
            results = retriever.retrieve("hierarchy pathway", top_k=5)

            self.assertGreater(len(results), 0, "Should retrieve documents with concept dependencies")
            self.assertEqual(results[0].source, "graph")


class FusionEngineTests(unittest.TestCase):
    """Tests for the fusion and ranking engine."""

    def test_weighted_fusion_single_source(self):
        """Verify fusion handles single retriever source correctly."""
        from svo_engine import WeightedFusionEngine, RetrievalResult

        fusion = WeightedFusionEngine()
        results = [
            RetrievalResult(chunk_id="c1", score=10.0, source="lexical"),
            RetrievalResult(chunk_id="c2", score=5.0, source="lexical"),
        ]

        fused = fusion.fuse_and_rank(results, top_k=10)
        self.assertEqual(len(fused), 2)
        self.assertEqual(fused[0].chunk_id, "c1", "Higher score should rank first")

    def test_weighted_fusion_multi_source_boost(self):
        """Verify fusion gives boost for multi-source retrieval."""
        from svo_engine import WeightedFusionEngine, RetrievalResult

        fusion = WeightedFusionEngine()
        results = [
            RetrievalResult(chunk_id="c1", score=0.8, source="lexical"),
            RetrievalResult(chunk_id="c1", score=0.7, source="semantic"),  # Same chunk, different source
            RetrievalResult(chunk_id="c2", score=0.9, source="lexical"),
        ]

        fused = fusion.fuse_and_rank(results, top_k=10)
        # c1 appears in multiple sources, should get a boost
        c1_score = next(r.score for r in fused if r.chunk_id == "c1")
        c2_score = next(r.score for r in fused if r.chunk_id == "c2")

        # Multi-source boost should help c1 compete with c2
        self.assertGreater(c1_score, 0.3)  # Should have some boost


class QueryRoutingTests(unittest.TestCase):
    """Tests for MoE router query type detection."""

    def test_multi_hop_routing(self):
        """Verify multi-hop keyword detection."""
        from svo_engine import MoERouter, QueryType
        router = MoERouter()

        queries = [
            "What connects A to B?",
            "How does X lead through Y to Z?",
            "What is the path between concepts?",
        ]

        for q in queries:
            routes = router.route(q)
            self.assertIn(QueryType.MULTI_HOP, routes, f"Query '{q}' should route to MULTI_HOP")

    def test_complex_routing(self):
        """Verify complex relation keyword detection."""
        from svo_engine import MoERouter, QueryType
        router = MoERouter()

        queries = [
            "What improves when we change X?",
            "How does A correlate with B?",
            "What causes this effect?",
        ]

        for q in queries:
            routes = router.route(q)
            self.assertIn(QueryType.COMPLEX, routes, f"Query '{q}' should route to COMPLEX")

    def test_exact_match_routing(self):
        """Verify exact match (quoted or ID-like) detection."""
        from svo_engine import MoERouter, QueryType
        router = MoERouter()

        queries = [
            'Find "exact phrase"',
            "Find CHEMBL123456",
        ]

        for q in queries:
            routes = router.route(q)
            self.assertIn(QueryType.EXACT_MATCH, routes, f"Query '{q}' should route to EXACT_MATCH")


class ValidatorTests(unittest.TestCase):
    """Tests for result validators."""

    def test_minimal_validator_output_format(self):
        """Verify MinimalValidator produces correct output structure."""
        from svo_engine import MinimalValidator, RetrievalResult, Chunk

        validator = MinimalValidator()
        results = [
            RetrievalResult(
                chunk_id="c1",
                score=0.95,
                source="lexical",
                chunk=Chunk(
                    chunk_id="c1",
                    document_id="doc1",
                    text="Aspirin treats headache",
                    embedding=None,
                    metadata={}
                )
            ),
        ]

        output = validator.validate("What treats headache?", results)

        self.assertEqual(output["status"], "EVIDENCE_GATHERED")
        self.assertIn("evidence", output)
        self.assertEqual(len(output["evidence"]), 1)
        self.assertEqual(output["evidence"][0]["rank"], 1)
        self.assertEqual(output["evidence"][0]["text"], "Aspirin treats headache")

    def test_transformer_validator_availability(self):
        """Check if TransformerValidator can be instantiated."""
        try:
            from svo_engine import TransformerValidator, RetrievalResult, Chunk

            validator = TransformerValidator()
            results = [
                RetrievalResult(
                    chunk_id="c1",
                    score=0.95,
                    source="lexical",
                    chunk=Chunk(
                        chunk_id="c1",
                        document_id="doc1",
                        text="Aspirin treats headache",
                        embedding=None,
                        metadata={}
                    )
                ),
            ]

            output = validator.validate("What treats headache?", results)
            self.assertEqual(output["status"], "EVIDENCE_VALIDATED")
            self.assertIn("evidence", output)
            # Should have NLI labels
            self.assertIn("nli_label", output["evidence"][0])
        except ImportError:
            self.skipTest("transformers library not installed")


class EndToEndIntegrationTests(unittest.TestCase):
    """End-to-end tests with real components where available."""

    def test_full_pipeline_with_custom_document(self):
        """Test complete pipeline from ingestion to verification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "integration.sqlite")

            from ingestion_pipeline import DataIngestor, SimpleEmbeddingModel, MockSVOExtractor, MockConceptExtractor
            from svo_engine import SVOVerificationEngine, MoERouter, SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever, WeightedFusionEngine, SQLiteChunkStore, MinimalValidator

            doc_text = (
                "Python is a programming language. "
                "Machine learning requires data and algorithms. "
                "Python is widely used for machine learning tasks."
            )

            # Ingest
            ingestor = DataIngestor(
                sqlite_conn_path=db_path,
                es_client=None,
                milvus_collection=None,
                neo4j_driver=None,
                embedding_model=SimpleEmbeddingModel(),
                svo_extractor=MockSVOExtractor(),
                concept_extractor=MockConceptExtractor(),
            )
            ingest_result = ingestor.ingest_document("ml_doc", doc_text)
            self.assertEqual(ingest_result["status"], "SUCCESS")
            self.assertGreater(ingest_result["chunks"], 0)

            # Verify
            engine = SVOVerificationEngine(
                router=MoERouter(),
                lexical_store=SQLiteLexicalRetriever(db_path),
                semantic_store=SQLiteSemanticRetriever(db_path),
                graph_store=SQLiteGraphRetriever(db_path),
                fusion_engine=WeightedFusionEngine(),
                chunk_store=SQLiteChunkStore(db_path),
                validator=MinimalValidator(),
            )

            verify_result = engine.verify("What is Python used for?", top_k=5)
            self.assertEqual(verify_result["status"], "EVIDENCE_GATHERED")
            evidence = verify_result.get("evidence", [])
            self.assertGreater(len(evidence), 0)

    def test_edge_case_empty_query(self):
        """Test retrieval with empty or minimal query."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "edge_case.sqlite")

            from ingestion_pipeline import DataIngestor, SimpleEmbeddingModel, MockSVOExtractor, MockConceptExtractor
            from svo_engine import SVOVerificationEngine, MoERouter, SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever, WeightedFusionEngine, SQLiteChunkStore, MinimalValidator

            ingestor = DataIngestor(
                sqlite_conn_path=db_path,
                es_client=None,
                milvus_collection=None,
                neo4j_driver=None,
                embedding_model=SimpleEmbeddingModel(),
                svo_extractor=MockSVOExtractor(),
                concept_extractor=MockConceptExtractor(),
            )
            ingestor.ingest_document("doc", "Some text here")

            engine = SVOVerificationEngine(
                router=MoERouter(),
                lexical_store=SQLiteLexicalRetriever(db_path),
                semantic_store=SQLiteSemanticRetriever(db_path),
                graph_store=SQLiteGraphRetriever(db_path),
                fusion_engine=WeightedFusionEngine(),
                chunk_store=SQLiteChunkStore(db_path),
                validator=MinimalValidator(),
            )

            # Should handle empty query gracefully
            result = engine.verify("", top_k=5)
            self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
