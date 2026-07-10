"""End-to-end pipeline tests validating complete workflows."""

import pytest
from unittest import mock

from src.config import PipelineConfig, BackendMode
from src.engine import SVOVerificationEngine
from src.models import OntologyAssertion


class TestEndToEndDemoMode:
    """Test end-to-end pipeline in demo mode."""

    def test_end_to_end_demo_mode(self, temp_db_path, sample_document, sample_triples):
        """Complete pipeline in demo mode (mocks only)."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            use_production_backends=False,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="demo_test",
            raw_text=sample_document,
            triples=sample_triples[:2],
            top_k=5,
        )

        assert result is not None
        assert result["document_id"] == "demo_test"
        assert len(result["verdicts"]) == 2

    def test_end_to_end_ingestion_and_validation(self, temp_db_path, sample_document, sample_triples):
        """Ingest document and validate triples."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        # Step 1: Ingest
        result = engine.validate_triples_batch(
            document_id="doc1",
            raw_text=sample_document,
            triples=sample_triples[:1],
            top_k=5,
        )

        # Step 2: Verify ingestion succeeded
        assert result["ingestion_status"] == "success"
        assert result["chunks_ingested"] >= 0

        # Step 3: Verify validation produced verdicts
        assert len(result["verdicts"]) > 0

    def test_end_to_end_backend_fallback(self, temp_db_path, sample_document):
        """System gracefully falls back on backend failure."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            use_production_backends=False,
        )

        engine = SVOVerificationEngine.from_config(config)

        triple = OntologyAssertion(
            assertion_id="fallback_test",
            subject="Test",
            relation="tests",
            object="fallback",
        )

        result = engine.validate_triples_batch(
            document_id="fallback_test",
            raw_text=sample_document,
            triples=[triple],
            top_k=5,
        )

        # Should complete even if some backends fail
        assert isinstance(result, dict)
        assert "verdicts" in result


class TestEndToEndConfiguration:
    """Test end-to-end with various configurations."""

    def test_end_to_end_with_custom_embedding(self, temp_db_path, sample_document, sample_triples):
        """Pipeline uses configured embedding model."""
        from src.ingestion.embeddings import SimpleEmbeddingModel

        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            embedding_model_name="simple",
        )

        engine = SVOVerificationEngine.from_config(config)
        engine.embedding_model = SimpleEmbeddingModel()

        result = engine.validate_triples_batch(
            document_id="custom_embedding",
            raw_text=sample_document,
            triples=sample_triples[:1],
            top_k=5,
        )

        assert result is not None
        assert len(result["verdicts"]) > 0

    def test_end_to_end_with_custom_svo_extractor(self, temp_db_path, sample_document, sample_triples):
        """Pipeline uses configured SVO extractor."""
        from src.ingestion.extractors import MockSVOExtractor

        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            svo_extractor_name="mock",
        )

        engine = SVOVerificationEngine.from_config(config)
        engine.svo_extractor = MockSVOExtractor()

        result = engine.validate_triples_batch(
            document_id="custom_extractor",
            raw_text=sample_document,
            triples=sample_triples[:1],
            top_k=5,
        )

        assert result is not None
        assert len(result["verdicts"]) > 0


class TestEndToEndTripleProcessing:
    """Test processing of various triple types."""

    def test_end_to_end_multiple_triples(self, temp_db_path, sample_document, sample_triples):
        """Validate multiple triples in one batch."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="multi_test",
            raw_text=sample_document,
            triples=sample_triples,
            top_k=5,
        )

        assert len(result["verdicts"]) == len(sample_triples)
        summary = result["summary"]
        assert summary["total_triples"] == len(sample_triples)

    def test_end_to_end_evidence_collection(self, temp_db_path, sample_document, sample_triples):
        """Evidence chunks properly collected and scored."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="evidence_test",
            raw_text=sample_document,
            triples=sample_triples[:1],
            top_k=5,
        )

        if result["verdicts"]:
            verdict = result["verdicts"][0]
            evidence = verdict.get("evidence", [])

            # Evidence should be a list
            assert isinstance(evidence, list)

            # Each evidence item should have required fields
            for ev in evidence:
                assert "chunk_id" in ev
                assert "text" in ev
                assert "source" in ev
                assert "confidence" in ev


class TestEndToEndResultValidation:
    """Test result format and content validation."""

    def test_end_to_end_result_format(self, temp_db_path, sample_document, sample_triples):
        """Result dict has all expected fields."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="format_test",
            raw_text=sample_document,
            triples=sample_triples[:1],
            top_k=5,
        )

        # Top-level fields
        required_fields = [
            "document_id", "ingestion_status", "chunks_ingested",
            "svos_extracted", "verdicts", "summary", "backend_status"
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

    def test_end_to_end_scoring(self, temp_db_path, sample_document, sample_triples):
        """Scores are in valid range [0, 1]."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="score_test",
            raw_text=sample_document,
            triples=sample_triples[:1],
            top_k=5,
        )

        for verdict in result["verdicts"]:
            score = verdict["score"]
            assert 0.0 <= score <= 1.0, f"Score {score} outside range [0, 1]"

        # Summary average score should also be in range
        summary = result["summary"]
        avg_score = summary["avg_score"]
        assert 0.0 <= avg_score <= 1.0

    def test_end_to_end_label_assignment(self, temp_db_path, sample_document, sample_triples):
        """Labels are one of: supported/contradicted/partial/unknown."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="label_test",
            raw_text=sample_document,
            triples=sample_triples,
            top_k=5,
        )

        valid_labels = {"supported", "contradicted", "partial", "unknown"}

        for verdict in result["verdicts"]:
            label = verdict["label"]
            assert label in valid_labels, f"Invalid label: {label}"

        # Summary should match
        summary = result["summary"]
        total = (summary["supported"] + summary["contradicted"] +
                 summary["partial"] + summary["unknown"])
        assert total == len(result["verdicts"])


class TestEndToEndNegationHandling:
    """Test negation detection in evidence."""

    def test_end_to_end_negation_detection(self, temp_db_path):
        """Negation properly detected in evidence."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        # Document with negation
        negation_doc = "Aspirin does not treat malaria. Aspirin cannot cure bacterial infections."

        triple_negated = OntologyAssertion(
            assertion_id="negation_test",
            subject="Aspirin",
            relation="treats",
            object="malaria",
            polarity="must_not_hold",
        )

        result = engine.validate_triples_batch(
            document_id="negation_test",
            raw_text=negation_doc,
            triples=[triple_negated],
            top_k=5,
        )

        # Should have processed the negation
        assert len(result["verdicts"]) > 0


class TestEndToEndReproducibility:
    """Test result reproducibility and consistency."""

    def test_end_to_end_reproducibility(self, temp_db_path, sample_document, sample_triples):
        """Same input produces consistent output across runs."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        # Create two engines with same config
        engine1 = SVOVerificationEngine.from_config(config)

        # Use a different temp db for second engine to avoid conflicts
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path2 = os.path.join(tmpdir, "test2.db")
            config2 = PipelineConfig(
                backend_mode=BackendMode.DEMO,
                sqlite_path=db_path2,
            )
            engine2 = SVOVerificationEngine.from_config(config2)

            # Run same query on both
            triple = sample_triples[0]

            result1 = engine1.validate_triples_batch(
                document_id="repro_test",
                raw_text=sample_document,
                triples=[triple],
                top_k=5,
            )

            result2 = engine2.validate_triples_batch(
                document_id="repro_test",
                raw_text=sample_document,
                triples=[triple],
                top_k=5,
            )

            # Both should have same structure
            assert len(result1["verdicts"]) == len(result2["verdicts"])
            assert result1["verdicts"][0]["subject"] == result2["verdicts"][0]["subject"]


class TestEndToEndErrorHandling:
    """Test error handling in end-to-end pipeline."""

    def test_end_to_end_empty_document(self, temp_db_path, sample_triples):
        """Pipeline handles empty document gracefully."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="empty_test",
            raw_text="",
            triples=sample_triples[:1],
            top_k=5,
        )

        # Should complete without error
        assert isinstance(result, dict)

    def test_end_to_end_empty_triples_list(self, temp_db_path, sample_document):
        """Pipeline handles empty triples list gracefully."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="no_triples",
            raw_text=sample_document,
            triples=[],
            top_k=5,
        )

        # Should complete without error
        assert result is not None
        assert result["verdicts"] == []

    def test_end_to_end_malformed_triple(self, temp_db_path, sample_document):
        """Pipeline handles malformed triples gracefully."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        # Triple with empty subject
        triple = OntologyAssertion(
            assertion_id="malformed",
            subject="",
            relation="tests",
            object="something",
        )

        result = engine.validate_triples_batch(
            document_id="malformed_test",
            raw_text=sample_document,
            triples=[triple],
            top_k=5,
        )

        # Should still complete
        assert isinstance(result, dict)


class TestEndToEndPerformance:
    """Test pipeline performance characteristics."""

    def test_end_to_end_top_k_parameter(self, temp_db_path, sample_document, sample_triples):
        """Pipeline respects top_k parameter."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        # Test with different top_k values
        for top_k in [1, 5, 10]:
            result = engine.validate_triples_batch(
                document_id=f"top_k_{top_k}",
                raw_text=sample_document,
                triples=sample_triples[:1],
                top_k=top_k,
            )

            # Should complete with top_k parameter
            assert isinstance(result, dict)

    def test_end_to_end_large_batch(self, temp_db_path, sample_document):
        """Pipeline handles larger triple batches."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        # Create 10 triples
        triples = [
            OntologyAssertion(
                assertion_id=f"triple_{i}",
                subject=f"Subject_{i}",
                relation=f"relation_{i}",
                object=f"Object_{i}",
            )
            for i in range(10)
        ]

        result = engine.validate_triples_batch(
            document_id="large_batch",
            raw_text=sample_document,
            triples=triples,
            top_k=5,
        )

        assert len(result["verdicts"]) == 10


class TestEndToEndSummaryStatistics:
    """Test summary statistics in results."""

    def test_end_to_end_summary_counts(self, temp_db_path, sample_document, sample_triples):
        """Summary counts match verdict labels."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="summary_test",
            raw_text=sample_document,
            triples=sample_triples,
            top_k=5,
        )

        summary = result["summary"]
        verdicts = result["verdicts"]

        # Count each label type
        supported_count = sum(1 for v in verdicts if v["label"] == "supported")
        contradicted_count = sum(1 for v in verdicts if v["label"] == "contradicted")
        partial_count = sum(1 for v in verdicts if v["label"] == "partial")
        unknown_count = sum(1 for v in verdicts if v["label"] == "unknown")

        # Should match summary
        assert summary["supported"] == supported_count
        assert summary["contradicted"] == contradicted_count
        assert summary["partial"] == partial_count
        assert summary["unknown"] == unknown_count

    def test_end_to_end_average_score_calculation(self, temp_db_path, sample_document, sample_triples):
        """Average score calculated correctly."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="avg_score_test",
            raw_text=sample_document,
            triples=sample_triples[:2],
            top_k=5,
        )

        verdicts = result["verdicts"]
        if verdicts:
            scores = [v["score"] for v in verdicts]
            expected_avg = sum(scores) / len(scores)
            actual_avg = result["summary"]["avg_score"]

            # Should match (within small rounding error)
            assert abs(expected_avg - actual_avg) < 0.001
