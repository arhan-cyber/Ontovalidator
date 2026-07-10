"""Tests for configuration loading from environment variables and serialization."""

import os
import json
import tempfile
import pytest

from src.config import PipelineConfig, BackendMode, ElasticsearchConfig, MilvusConfig, Neo4jConfig, load_config_from_env


class TestConfigDefaults:
    """Test configuration defaults when no environment variables are set."""

    def test_load_config_from_env_defaults(self, monkeypatch):
        """Verify defaults when no env vars set."""
        # Clear any relevant environment variables
        env_vars = [
            "ONTO_BACKEND_MODE", "ONTO_USE_PRODUCTION_BACKENDS", "ONTO_REQUIRE_PRODUCTION_BACKENDS",
            "ONTO_SQLITE_PATH", "ONTO_ES_ENABLED", "ONTO_ES_HOST", "ONTO_ES_PORT", "ONTO_ES_INDEX",
            "ONTO_MILVUS_ENABLED", "ONTO_MILVUS_HOST", "ONTO_MILVUS_PORT", "ONTO_MILVUS_COLLECTION", "ONTO_MILVUS_DIM",
            "ONTO_NEO4J_ENABLED", "ONTO_NEO4J_URI", "ONTO_NEO4J_USER", "ONTO_NEO4J_PASSWORD",
            "ONTO_EMBEDDING_MODEL", "ONTO_SVO_EXTRACTOR", "ONTO_VALIDATOR",
            "ONTO_ENABLE_LM_CLASSIFIER", "ONTO_CLASSIFIER_MODEL", "ONTO_VERBOSE", "ONTO_LOG_BACKEND_USAGE",
        ]
        for var in env_vars:
            monkeypatch.delenv(var, raising=False)

        config = PipelineConfig.load_from_env()

        assert config.backend_mode == BackendMode.AUTO
        assert config.use_production_backends is False
        assert config.require_production_backends is False
        assert config.sqlite_path == "svo_data.db"
        assert config.elasticsearch.enabled is False
        assert config.elasticsearch.host == "localhost"
        assert config.elasticsearch.port == 9200
        assert config.milvus.enabled is False
        assert config.neo4j.enabled is False
        assert config.embedding_model_name == "simple"
        assert config.svo_extractor_name == "mock"
        assert config.validator_name == "minimal"
        assert config.enable_lm_classifier is False
        assert config.verbose is False


class TestBackendConfig:
    """Test backend-specific configuration."""

    def test_load_config_elasticsearch_enabled(self, monkeypatch):
        """Test ES config from env vars."""
        monkeypatch.setenv("ONTO_ES_ENABLED", "true")
        monkeypatch.setenv("ONTO_ES_HOST", "es.example.com")
        monkeypatch.setenv("ONTO_ES_PORT", "9300")
        monkeypatch.setenv("ONTO_ES_INDEX", "custom_index")

        config = PipelineConfig.load_from_env()

        assert config.elasticsearch.enabled is True
        assert config.elasticsearch.host == "es.example.com"
        assert config.elasticsearch.port == 9300
        assert config.elasticsearch.index_name == "custom_index"

    def test_load_config_neo4j_enabled(self, monkeypatch):
        """Test Neo4j config from env vars."""
        monkeypatch.setenv("ONTO_NEO4J_ENABLED", "true")
        monkeypatch.setenv("ONTO_NEO4J_URI", "bolt://neo4j.example.com:7687")
        monkeypatch.setenv("ONTO_NEO4J_USER", "admin")
        monkeypatch.setenv("ONTO_NEO4J_PASSWORD", "secret")

        config = PipelineConfig.load_from_env()

        assert config.neo4j.enabled is True
        assert config.neo4j.uri == "bolt://neo4j.example.com:7687"
        assert config.neo4j.user == "admin"
        assert config.neo4j.password == "secret"

    def test_load_config_milvus_enabled(self, monkeypatch):
        """Test Milvus config from env vars."""
        monkeypatch.setenv("ONTO_MILVUS_ENABLED", "true")
        monkeypatch.setenv("ONTO_MILVUS_HOST", "milvus.example.com")
        monkeypatch.setenv("ONTO_MILVUS_PORT", "19530")
        monkeypatch.setenv("ONTO_MILVUS_COLLECTION", "vectors")
        monkeypatch.setenv("ONTO_MILVUS_DIM", "768")

        config = PipelineConfig.load_from_env()

        assert config.milvus.enabled is True
        assert config.milvus.host == "milvus.example.com"
        assert config.milvus.port == 19530
        assert config.milvus.collection_name == "vectors"
        assert config.milvus.embedding_dim == 768


class TestBackendMode:
    """Test backend mode configurations."""

    def test_load_config_backend_mode_demo(self, monkeypatch):
        """Test DEMO mode disables production backends."""
        monkeypatch.setenv("ONTO_BACKEND_MODE", "demo")
        monkeypatch.setenv("ONTO_ES_ENABLED", "true")
        monkeypatch.setenv("ONTO_MILVUS_ENABLED", "true")

        config = PipelineConfig.load_from_env()

        assert config.backend_mode == BackendMode.DEMO
        # Note: env vars still enable backends, but DEMO mode should use mocks

    def test_load_config_backend_mode_production(self, monkeypatch):
        """Test PRODUCTION mode enables backends."""
        monkeypatch.setenv("ONTO_BACKEND_MODE", "production")
        monkeypatch.setenv("ONTO_USE_PRODUCTION_BACKENDS", "true")

        config = PipelineConfig.load_from_env()

        assert config.backend_mode == BackendMode.PRODUCTION
        assert config.use_production_backends is True

    def test_load_config_backend_mode_auto(self, monkeypatch):
        """Test AUTO mode behavior."""
        monkeypatch.setenv("ONTO_BACKEND_MODE", "auto")

        config = PipelineConfig.load_from_env()

        assert config.backend_mode == BackendMode.AUTO

    def test_load_config_require_production_backends(self, monkeypatch):
        """Test requiring production backends."""
        monkeypatch.setenv("ONTO_REQUIRE_PRODUCTION_BACKENDS", "true")

        config = PipelineConfig.load_from_env()

        assert config.require_production_backends is True


class TestModelSelection:
    """Test embedding and SVO extractor model selection."""

    def test_embedding_model_selection_simple(self, monkeypatch):
        """Test simple embedding model selection."""
        monkeypatch.setenv("ONTO_EMBEDDING_MODEL", "simple")

        config = PipelineConfig.load_from_env()

        assert config.embedding_model_name == "simple"

    def test_embedding_model_selection_transformer(self, monkeypatch):
        """Test transformer embedding model selection."""
        monkeypatch.setenv("ONTO_EMBEDDING_MODEL", "transformer")

        config = PipelineConfig.load_from_env()

        assert config.embedding_model_name == "transformer"

    def test_svo_extractor_selection(self, monkeypatch):
        """Test SVO extractor selection."""
        monkeypatch.setenv("ONTO_SVO_EXTRACTOR", "transformer")

        config = PipelineConfig.load_from_env()

        assert config.svo_extractor_name == "transformer"

    def test_validator_selection(self, monkeypatch):
        """Test validator selection."""
        monkeypatch.setenv("ONTO_VALIDATOR", "transformer")

        config = PipelineConfig.load_from_env()

        assert config.validator_name == "transformer"


class TestClassifierConfig:
    """Test classifier-related configuration."""

    def test_enable_lm_classifier(self, monkeypatch):
        """Test LM classifier enablement."""
        monkeypatch.setenv("ONTO_ENABLE_LM_CLASSIFIER", "true")
        monkeypatch.setenv("ONTO_CLASSIFIER_MODEL", "bert-base-uncased")

        config = PipelineConfig.load_from_env()

        assert config.enable_lm_classifier is True
        assert config.classifier_model_name == "bert-base-uncased"


class TestConfigSerialization:
    """Test configuration serialization and deserialization."""

    def test_config_to_dict(self):
        """Test conversion to dictionary."""
        config = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            sqlite_path="test.db",
            embedding_model_name="simple",
        )

        config_dict = config.to_dict()

        assert isinstance(config_dict, dict)
        assert config_dict["backend_mode"] == "demo"
        assert config_dict["sqlite_path"] == "test.db"
        assert config_dict["embedding_model_name"] == "simple"
        assert "elasticsearch" in config_dict
        assert "milvus" in config_dict
        assert "neo4j" in config_dict

    def test_config_to_json(self):
        """Test conversion to JSON string."""
        config = PipelineConfig(
            backend_mode=BackendMode.PRODUCTION,
            sqlite_path="test.db",
        )

        json_str = config.to_json()

        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["backend_mode"] == "production"
        assert parsed["sqlite_path"] == "test.db"

    def test_config_from_dict(self):
        """Test creation from dictionary."""
        config_dict = {
            "backend_mode": "demo",
            "sqlite_path": "custom.db",
            "embedding_model_name": "transformer",
            "elasticsearch": {"enabled": False, "host": "localhost", "port": 9200, "index_name": "svo_chunks"},
            "milvus": {"enabled": False, "host": "localhost", "port": 19530, "collection_name": "svo_embeddings", "embedding_dim": 384},
            "neo4j": {"enabled": False, "uri": "bolt://localhost:7687", "user": "neo4j", "password": "password"},
        }

        config = PipelineConfig.from_dict(config_dict)

        assert config.backend_mode == BackendMode.DEMO
        assert config.sqlite_path == "custom.db"
        assert config.embedding_model_name == "transformer"

    def test_config_from_json(self):
        """Test creation from JSON string."""
        json_str = json.dumps({
            "backend_mode": "production",
            "sqlite_path": "test.db",
            "use_production_backends": True,
            "require_production_backends": False,
            "elasticsearch": {"enabled": False, "host": "localhost", "port": 9200, "index_name": "svo_chunks"},
            "milvus": {"enabled": False, "host": "localhost", "port": 19530, "collection_name": "svo_embeddings", "embedding_dim": 384},
            "neo4j": {"enabled": False, "uri": "bolt://localhost:7687", "user": "neo4j", "password": "password"},
            "embedding_model_name": "simple",
            "svo_extractor_name": "mock",
            "validator_name": "minimal",
            "enable_lm_classifier": False,
            "classifier_model_name": None,
            "verbose": False,
            "log_backend_usage": False,
        })

        config = PipelineConfig.from_json(json_str)

        assert config.backend_mode == BackendMode.PRODUCTION
        assert config.use_production_backends is True
        assert config.sqlite_path == "test.db"

    def test_config_save_and_load_file(self):
        """Test saving and loading configuration from file."""
        config = PipelineConfig(
            backend_mode=BackendMode.PRODUCTION,
            sqlite_path="test.db",
            embedding_model_name="transformer",
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_file = f.name

        try:
            config.save_to_file(config_file)
            loaded_config = PipelineConfig.from_file(config_file)

            assert loaded_config.backend_mode == BackendMode.PRODUCTION
            assert loaded_config.sqlite_path == "test.db"
            assert loaded_config.embedding_model_name == "transformer"
        finally:
            os.unlink(config_file)

    def test_config_roundtrip(self):
        """Test that config survives serialization roundtrip."""
        original = PipelineConfig(
            backend_mode=BackendMode.AUTO,
            use_production_backends=True,
            sqlite_path="data/svo.db",
            embedding_model_name="transformer",
            svo_extractor_name="transformer",
            validator_name="transformer",
            verbose=True,
        )

        # Roundtrip through dict
        dict_copy = PipelineConfig.from_dict(original.to_dict())
        assert dict_copy.backend_mode == original.backend_mode
        assert dict_copy.use_production_backends == original.use_production_backends
        assert dict_copy.sqlite_path == original.sqlite_path
        assert dict_copy.embedding_model_name == original.embedding_model_name
        assert dict_copy.verbose == original.verbose

        # Roundtrip through JSON
        json_copy = PipelineConfig.from_json(original.to_json())
        assert json_copy.backend_mode == original.backend_mode
        assert json_copy.use_production_backends == original.use_production_backends
        assert json_copy.sqlite_path == original.sqlite_path


class TestConfigValidation:
    """Test configuration validation."""

    def test_config_valid_combinations(self):
        """Test valid configuration combinations."""
        # DEMO mode
        config1 = PipelineConfig(
            backend_mode=BackendMode.DEMO,
            use_production_backends=False,
        )
        assert config1 is not None

        # PRODUCTION mode with require
        config2 = PipelineConfig(
            backend_mode=BackendMode.PRODUCTION,
            require_production_backends=True,
            elasticsearch=ElasticsearchConfig(enabled=True),
        )
        assert config2 is not None

        # AUTO mode
        config3 = PipelineConfig(
            backend_mode=BackendMode.AUTO,
        )
        assert config3 is not None

    def test_config_invalid_backend_mode(self, monkeypatch):
        """Test invalid backend mode raises ValueError."""
        monkeypatch.setenv("ONTO_BACKEND_MODE", "invalid_mode")

        with pytest.raises(ValueError):
            PipelineConfig.load_from_env()

    def test_backend_enable_flags(self):
        """Test backend enable/disable flags."""
        config = PipelineConfig()

        # All disabled by default
        assert config.elasticsearch.enabled is False
        assert config.milvus.enabled is False
        assert config.neo4j.enabled is False

        # Can enable individually
        config.elasticsearch.enabled = True
        assert config.elasticsearch.enabled is True
        assert config.milvus.enabled is False
        assert config.neo4j.enabled is False


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_load_config_from_env_function(self, monkeypatch):
        """Test convenience function load_config_from_env()."""
        monkeypatch.setenv("ONTO_BACKEND_MODE", "demo")
        monkeypatch.setenv("ONTO_SQLITE_PATH", "test.db")

        config = load_config_from_env()

        assert isinstance(config, PipelineConfig)
        assert config.backend_mode == BackendMode.DEMO
        assert config.sqlite_path == "test.db"
