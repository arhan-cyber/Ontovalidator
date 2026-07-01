import os
import tempfile
import unittest

from ingestion_pipeline import run_demo as run_ingestion_demo
from svo_engine import run_demo as run_svo_demo


class PipelineDemoTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
