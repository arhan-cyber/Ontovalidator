"""Tests for SVOVerificationEngine configuration integration."""

import pytest
from unittest import mock

from src.config import PipelineConfig, BackendMode
from src.engine import SVOVerificationEngine
from src.routing import MoERouter
from src.retrieval import SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever
from src.fusion import WeightedFusionEngine
from src.storage import SQLiteChunkStore
from src.validation import MinimalValidator
from src.models import OntologyAssertion


class TestEngineFromConfig:
    """Test engine creation from configuration."""

    def test_engine_from_config_creates_engine(self, temp_db_path):
        """Test from_config() class method works."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        assert isinstance(engine, SVOVerificationEngine)
        assert engine.config is config

    def test_engine_from_config_with_production_mode(self, temp_db_path):
        """Test from_config() with PRODUCTION mode."""
        config = PipelineConfig(
            backend_mode=BackendMode.PRODUCTION,
            sqlite_path=temp_db_path,
            use_production_backends=False,  # Set to False to avoid actual connections
        )

        engine = SVOVerificationEngine.from_config(config)

        assert isinstance(engine, SVOVerificationEngine)
        assert engine.config.backend_mode == BackendMode.PRODUCTION

    def test_engine_from_config_with_auto_mode(self, temp_db_path):
        """Test from_config() with AUTO mode."""
        config = PipelineConfig(
            backend_mode=BackendMode.AUTO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        assert isinstance(engine, SVOVerificationEngine)
        assert engine.config.backend_mode == BackendMode.AUTO


class TestEngineConfiguration:
    """Test engine configuration storage and usage."""

    def test_engine_stores_config(self, temp_db_path):
        """Test that engine stores config."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            embedding_model_name="transformer",
        )

        engine = SVOVerificationEngine.from_config(config)

        assert engine.config is not None
        assert engine.config.embedding_model_name == "transformer"

    def test_engine_with_configured_svo_extractor(self, temp_db_path):
        """Test engine with configured SVO extractor."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            svo_extractor_name="mock",
        )

        from src.ingestion.extractors import MockSVOExtractor
        mock_extractor = MockSVOExtractor()

        engine = SVOVerificationEngine(
            router=MoERouter(),
            lexical_store=SQLiteLexicalRetriever(temp_db_path),
            semantic_store=SQLiteSemanticRetriever(temp_db_path),
            graph_store=SQLiteGraphRetriever(temp_db_path),
            fusion_engine=WeightedFusionEngine(),
            chunk_store=SQLiteChunkStore(temp_db_path),
            validator=MinimalValidator(),
            svo_extractor=mock_extractor,
            config=config,
        )

        assert engine.svo_extractor is mock_extractor

    def test_engine_with_configured_embedding_model(self, temp_db_path):
        """Test engine with configured embedding model."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            embedding_model_name="simple",
        )

        from src.ingestion.embeddings import SimpleEmbeddingModel
        embedding_model = SimpleEmbeddingModel()

        engine = SVOVerificationEngine(
            router=MoERouter(),
            lexical_store=SQLiteLexicalRetriever(temp_db_path),
            semantic_store=SQLiteSemanticRetriever(temp_db_path),
            graph_store=SQLiteGraphRetriever(temp_db_path),
            fusion_engine=WeightedFusionEngine(),
            chunk_store=SQLiteChunkStore(temp_db_path),
            validator=MinimalValidator(),
            embedding_model=embedding_model,
            config=config,
        )

        assert engine.embedding_model is embedding_model

    def test_engine_backward_compatible(self, temp_db_path):
        """Test old-style __init__ still works."""
        engine = SVOVerificationEngine(
            router=MoERouter(),
            lexical_store=SQLiteLexicalRetriever(temp_db_path),
            semantic_store=SQLiteSemanticRetriever(temp_db_path),
            graph_store=SQLiteGraphRetriever(temp_db_path),
            fusion_engine=WeightedFusionEngine(),
            chunk_store=SQLiteChunkStore(temp_db_path),
            validator=MinimalValidator(),
        )

        assert isinstance(engine, SVOVerificationEngine)
        assert engine.config is None  # No config provided


class TestEngineBackendStatus:
    """Test engine backend status reporting."""

    def test_engine_get_backend_status(self, temp_db_path):
        """Test get_backend_status() returns correct types."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)
        status = engine.get_backend_status()

        assert isinstance(status, dict)
        assert "lexical" in status
        assert "semantic" in status
        assert "graph" in status
        assert isinstance(status["lexical"], str)
        assert isinstance(status["semantic"], str)
        assert isinstance(status["graph"], str)

    def test_engine_backend_status_shows_sqlite_fallback(self, temp_db_path):
        """Test backend status shows SQLite fallback."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)
        status = engine.get_backend_status()

        # In DEMO mode, should use SQLite implementations
        assert "SQLite" in status["lexical"] or "Lexical" in status["lexical"]
        assert "SQLite" in status["semantic"] or "Semantic" in status["semantic"]
        assert "SQLite" in status["graph"] or "Graph" in status["graph"]


class TestValidateTriplesBatch:
    """Test validate_triples_batch with configuration."""

    def test_validate_triples_batch_with_config(self, temp_db_path, sample_document, sample_triples):
        """Test validate_triples_batch uses configured models."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            embedding_model_name="simple",
            svo_extractor_name="mock",
            verbose=False,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="test_doc",
            raw_text=sample_document,
            triples=sample_triples[:2],  # Test with first 2 triples
            top_k=5,
        )

        assert isinstance(result, dict)
        assert "document_id" in result
        assert result["document_id"] == "test_doc"
        assert "verdicts" in result
        assert isinstance(result["verdicts"], list)

    def test_validate_triples_batch_backend_status_in_result(self, temp_db_path, sample_document, sample_triples):
        """Test result includes backend status."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="test_doc",
            raw_text=sample_document,
            triples=sample_triples[:1],
            top_k=5,
        )

        assert "backend_status" in result
        backend_status = result["backend_status"]
        assert isinstance(backend_status, dict)
        assert "lexical" in backend_status
        assert "semantic" in backend_status
        assert "graph" in backend_status

    def test_validate_triples_batch_result_structure(self, temp_db_path, sample_document, sample_triples):
        """Test result has all expected fields."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="test_doc",
            raw_text=sample_document,
            triples=sample_triples[:1],
            top_k=5,
        )

        # Check top-level fields
        assert "document_id" in result
        assert "ingestion_status" in result
        assert "chunks_ingested" in result
        assert "svos_extracted" in result
        assert "verdicts" in result
        assert "summary" in result
        assert "backend_status" in result

        # Check verdict structure
        if result["verdicts"]:
            verdict = result["verdicts"][0]
            assert "assertion_id" in verdict
            assert "subject" in verdict
            assert "relation" in verdict
            assert "object" in verdict
            assert "label" in verdict
            assert "score" in verdict
            assert "evidence" in verdict
            assert "rule_hits" in verdict

        # Check summary structure
        summary = result["summary"]
        assert "total_triples" in summary
        assert "supported" in summary
        assert "contradicted" in summary
        assert "partial" in summary
        assert "unknown" in summary
        assert "avg_score" in summary

    def test_validate_triples_batch_with_custom_models(self, temp_db_path, sample_document, sample_triples):
        """Test batch validation uses configured custom models."""
        from src.ingestion.embeddings import SimpleEmbeddingModel
        from src.ingestion.extractors import MockSVOExtractor

        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            embedding_model_name="simple",
            svo_extractor_name="mock",
        )

        engine = SVOVerificationEngine(
            router=MoERouter(),
            lexical_store=SQLiteLexicalRetriever(temp_db_path),
            semantic_store=SQLiteSemanticRetriever(temp_db_path),
            graph_store=SQLiteGraphRetriever(temp_db_path),
            fusion_engine=WeightedFusionEngine(),
            chunk_store=SQLiteChunkStore(temp_db_path),
            validator=MinimalValidator(),
            embedding_model=SimpleEmbeddingModel(),
            svo_extractor=MockSVOExtractor(),
            config=config,
        )

        result = engine.validate_triples_batch(
            document_id="test_doc",
            raw_text=sample_document,
            triples=sample_triples[:1],
            top_k=5,
        )

        assert isinstance(result, dict)
        assert "verdicts" in result

    def test_validate_triples_batch_multiple_triples(self, temp_db_path, sample_document, sample_triples):
        """Test batch validation with multiple triples."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        result = engine.validate_triples_batch(
            document_id="test_doc",
            raw_text=sample_document,
            triples=sample_triples,  # All 4 triples
            top_k=5,
        )

        assert len(result["verdicts"]) == len(sample_triples)
        summary = result["summary"]
        assert summary["total_triples"] == len(sample_triples)


class TestEngineInheritance:
    """Test engine inherits configuration from factory."""

    def test_engine_from_config_inherits_verbose_setting(self, temp_db_path, caplog):
        """Test engine respects verbose configuration."""
        import logging
        caplog.set_level(logging.INFO)

        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            verbose=True,
        )

        engine = SVOVerificationEngine.from_config(config)

        assert engine.config.verbose is True

    def test_engine_from_config_logging_flag(self, temp_db_path):
        """Test engine logs backend usage when configured."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            log_backend_usage=True,
        )

        engine = SVOVerificationEngine.from_config(config)

        assert engine.config.log_backend_usage is True
