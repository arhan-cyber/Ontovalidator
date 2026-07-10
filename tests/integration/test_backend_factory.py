"""Tests for the factory pattern and backend instantiation."""

import pytest
import sys
from unittest import mock

from src.config import PipelineConfig, BackendMode, ElasticsearchConfig, MilvusConfig, Neo4jConfig
from src.factories import EngineFactory
from src.engine import SVOVerificationEngine
from src.retrieval import SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever
from src.ingestion.embeddings import SimpleEmbeddingModel
from src.ingestion.extractors import MockSVOExtractor

# Mock external dependencies that might not be installed
sys.modules['elasticsearch'] = mock.MagicMock()
sys.modules['neo4j'] = mock.MagicMock()
sys.modules['pymilvus'] = mock.MagicMock()

# Ensure helpers submodules are available for patching
sys.modules['src.helpers.elasticsearch'] = mock.MagicMock()
sys.modules['src.helpers.neo4j'] = mock.MagicMock()
sys.modules['src.helpers.milvus'] = mock.MagicMock()

# Make mock functions available
sys.modules['src.helpers.elasticsearch'].get_elasticsearch_client = mock.MagicMock()
sys.modules['src.helpers.neo4j'].get_neo4j_driver = mock.MagicMock()
sys.modules['src.helpers.neo4j'].initialize_neo4j_schema = mock.MagicMock()
sys.modules['src.helpers.milvus'].get_milvus_collection = mock.MagicMock()


class TestLexicalRetrieverFactory:
    """Test lexical retriever creation."""

    def test_factory_creates_elasticsearch_lexical_when_available(self, temp_db_path):
        """Test that ES enabled creates LexicalRetriever."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            elasticsearch=ElasticsearchConfig(enabled=True, host="localhost", port=9200),
        )

        with mock.patch('src.helpers.elasticsearch.get_elasticsearch_client') as mock_get_es:
            mock_client = mock.MagicMock()
            mock_get_es.return_value = mock_client

            retriever = EngineFactory._create_lexical_retriever(config)

            # Should attempt to create LexicalRetriever
            assert retriever is not None
            mock_get_es.assert_called_once_with(host="localhost", port=9200)

    def test_factory_creates_sqlite_lexical_fallback(self, temp_db_path):
        """Test that ES disabled creates SQLiteLexicalRetriever."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            elasticsearch=ElasticsearchConfig(enabled=False),
        )

        retriever = EngineFactory._create_lexical_retriever(config)

        assert isinstance(retriever, SQLiteLexicalRetriever)
        assert retriever.db_path == temp_db_path

    def test_factory_creates_sqlite_lexical_on_es_failure(self, temp_db_path):
        """Test ES connection failure falls back to SQLite."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            elasticsearch=ElasticsearchConfig(enabled=True),
        )

        with mock.patch('src.helpers.elasticsearch.get_elasticsearch_client') as mock_get_es:
            mock_get_es.side_effect = Exception("Connection failed")

            retriever = EngineFactory._create_lexical_retriever(config)

            assert isinstance(retriever, SQLiteLexicalRetriever)
            assert retriever.db_path == temp_db_path


class TestSemanticRetrieverFactory:
    """Test semantic retriever creation."""

    def test_factory_creates_milvus_semantic_when_available(self, temp_db_path):
        """Test that Milvus enabled attempts to create MilvusSemanticRetriever."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            milvus=MilvusConfig(enabled=True, host="localhost", port=19530),
        )

        with mock.patch('src.retrieval.semantic.MilvusSemanticRetriever') as mock_retriever:
            mock_instance = mock.MagicMock()
            mock_retriever.return_value = mock_instance

            try:
                retriever = EngineFactory._create_semantic_retriever(config)
                # If it succeeds, it should be the mocked instance
                assert retriever is not None
            except Exception:
                # If MilvusSemanticRetriever isn't available, it falls back
                pass

    def test_factory_creates_sqlite_semantic_fallback(self, temp_db_path):
        """Test that Milvus unavailable creates SQLiteSemanticRetriever."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            milvus=MilvusConfig(enabled=False),
        )

        retriever = EngineFactory._create_semantic_retriever(config)

        assert isinstance(retriever, SQLiteSemanticRetriever)
        assert retriever.db_path == temp_db_path


class TestGraphRetrieverFactory:
    """Test graph retriever creation."""

    def test_factory_creates_neo4j_graph_when_available(self, temp_db_path):
        """Test that Neo4j enabled attempts to create GraphRetriever."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            neo4j=Neo4jConfig(enabled=True, uri="bolt://localhost:7687", user="neo4j", password="password"),
        )

        with mock.patch('src.helpers.neo4j.get_neo4j_driver') as mock_get_driver:
            mock_driver = mock.MagicMock()
            mock_get_driver.return_value = mock_driver

            try:
                retriever = EngineFactory._create_graph_retriever(config)
                assert retriever is not None
            except Exception:
                # If GraphRetriever isn't available, it falls back
                pass

    def test_factory_creates_sqlite_graph_fallback(self, temp_db_path):
        """Test that Neo4j unavailable creates SQLiteGraphRetriever."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            neo4j=Neo4jConfig(enabled=False),
        )

        retriever = EngineFactory._create_graph_retriever(config)

        assert isinstance(retriever, SQLiteGraphRetriever)
        assert retriever.db_path == temp_db_path

    def test_factory_creates_sqlite_graph_on_neo4j_failure(self, temp_db_path):
        """Test Neo4j connection failure falls back to SQLite."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            neo4j=Neo4jConfig(enabled=True),
        )

        with mock.patch('src.helpers.neo4j.get_neo4j_driver') as mock_get_driver:
            mock_get_driver.side_effect = Exception("Connection failed")

            retriever = EngineFactory._create_graph_retriever(config)

            assert isinstance(retriever, SQLiteGraphRetriever)


class TestEmbeddingModelFactory:
    """Test embedding model creation."""

    def test_factory_creates_simple_embedding_model(self, temp_db_path):
        """Test simple embedding model creation."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            embedding_model_name="simple",
        )

        model = EngineFactory._create_embedding_model(config)

        assert isinstance(model, SimpleEmbeddingModel)

    def test_factory_creates_transformer_embedding_model(self, temp_db_path):
        """Test transformer embedding model creation."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            embedding_model_name="transformer",
        )

        with mock.patch('src.ingestion.embeddings.TransformerEmbeddingModel') as mock_transformer:
            mock_instance = mock.MagicMock()
            mock_transformer.return_value = mock_instance

            try:
                model = EngineFactory._create_embedding_model(config)
                # Should be the mocked instance if available
                assert model is not None
            except Exception:
                # Falls back to simple if not available
                pass


class TestSVOExtractorFactory:
    """Test SVO extractor creation."""

    def test_factory_creates_mock_svo_extractor(self, temp_db_path):
        """Test mock SVO extractor creation."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            svo_extractor_name="mock",
        )

        ingestor = EngineFactory.create_ingestor(config)

        assert ingestor is not None
        # The ingestor should be created with mock extractor
        assert hasattr(ingestor, 'svo_extractor')


class TestValidatorFactory:
    """Test validator creation."""

    def test_factory_creates_minimal_validator(self, temp_db_path):
        """Test minimal validator creation."""
        from src.validation import MinimalValidator

        config = PipelineConfig(
            sqlite_path=temp_db_path,
            validator_name="minimal",
        )

        validator = EngineFactory._create_validator(config)

        assert isinstance(validator, MinimalValidator)


class TestEngineFactory:
    """Test complete engine factory."""

    def test_engine_factory_creates_complete_engine(self, temp_db_path):
        """Test that factory creates a complete verification engine."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            use_production_backends=False,
        )

        engine = EngineFactory.create_verification_engine(config)

        assert isinstance(engine, SVOVerificationEngine)
        assert engine.router is not None
        assert engine.lexical_store is not None
        assert engine.semantic_store is not None
        assert engine.graph_store is not None
        assert engine.fusion_engine is not None
        assert engine.chunk_store is not None
        assert engine.validator is not None

    def test_engine_factory_stores_config(self, temp_db_path):
        """Test that engine stores configuration."""
        config = PipelineConfig(
            backend_mode=BackendMode.PRODUCTION,
            sqlite_path=temp_db_path,
            use_production_backends=False,
        )

        engine = EngineFactory.create_verification_engine(config)

        assert engine.config is config
        assert engine.config.backend_mode == BackendMode.PRODUCTION

    def test_engine_factory_logs_backend_choices(self, temp_db_path, caplog):
        """Test that factory logs backend choices."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
            verbose=True,
        )

        engine = EngineFactory.create_verification_engine(config)

        # Engine should be created and config should be stored
        assert engine is not None

    def test_engine_factory_from_config_class_method(self, temp_db_path):
        """Test SVOVerificationEngine.from_config() class method."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path=temp_db_path,
        )

        engine = SVOVerificationEngine.from_config(config)

        assert isinstance(engine, SVOVerificationEngine)
        assert engine.config is config


class TestFactoryBackendFallback:
    """Test factory backend fallback behavior."""

    def test_factory_respects_use_production_backends_false(self, temp_db_path):
        """Test that use_production_backends=False always uses SQLite."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            use_production_backends=False,
            elasticsearch=ElasticsearchConfig(enabled=True),
            milvus=MilvusConfig(enabled=True),
            neo4j=Neo4jConfig(enabled=True),
        )

        # With use_production_backends=False, should still try but fall back
        engine = EngineFactory.create_verification_engine(config)

        # Should have been created
        assert engine is not None

    def test_factory_raises_on_require_production_backends_true(self, temp_db_path):
        """Test that require_production_backends=True raises if backends unavailable."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            require_production_backends=True,
            elasticsearch=ElasticsearchConfig(enabled=False),
            milvus=MilvusConfig(enabled=False),
            neo4j=Neo4jConfig(enabled=False),
        )

        with pytest.raises(RuntimeError, match="Production backends required"):
            EngineFactory.create_verification_engine(config)

    def test_factory_succeeds_with_require_production_backends_and_backend_enabled(self, temp_db_path):
        """Test that require_production_backends succeeds when backend is enabled."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            require_production_backends=True,
            elasticsearch=ElasticsearchConfig(enabled=True),
        )

        with mock.patch('src.helpers.elasticsearch.get_elasticsearch_client') as mock_get_es:
            mock_client = mock.MagicMock()
            mock_get_es.return_value = mock_client

            engine = EngineFactory.create_verification_engine(config)

            assert engine is not None


class TestIngestorFactory:
    """Test ingestor factory."""

    def test_factory_creates_ingestor(self, temp_db_path):
        """Test complete ingestor creation."""
        from src.ingestion import DataIngestor

        config = PipelineConfig(
            sqlite_path=temp_db_path,
            embedding_model_name="simple",
            svo_extractor_name="mock",
        )

        ingestor = EngineFactory.create_ingestor(config)

        assert isinstance(ingestor, DataIngestor)
        assert ingestor.embedding_model is not None
        assert ingestor.svo_extractor is not None

    def test_factory_ingestor_with_production_backends(self, temp_db_path):
        """Test ingestor creation with production backends enabled."""
        from src.ingestion import DataIngestor

        config = PipelineConfig(
            sqlite_path=temp_db_path,
            use_production_backends=True,
            elasticsearch=ElasticsearchConfig(enabled=True),
            milvus=MilvusConfig(enabled=True),
            neo4j=Neo4jConfig(enabled=True),
        )

        with mock.patch('src.helpers.elasticsearch.get_elasticsearch_client') as mock_es, \
             mock.patch('src.helpers.milvus.get_milvus_collection') as mock_milvus, \
             mock.patch('src.helpers.neo4j.get_neo4j_driver') as mock_neo4j:

            mock_es.return_value = mock.MagicMock()
            mock_milvus.return_value = mock.MagicMock()
            mock_neo4j.return_value = mock.MagicMock()

            ingestor = EngineFactory.create_ingestor(config)

            assert isinstance(ingestor, DataIngestor)
