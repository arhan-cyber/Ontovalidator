"""Configuration system for production-ready SVO verification pipeline."""

import os
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any
from enum import Enum


class BackendMode(Enum):
    """Backend operation mode."""
    DEMO = "demo"  # Uses mock implementations
    PRODUCTION = "production"  # Uses real backends
    AUTO = "auto"  # Auto-detect based on environment


@dataclass
class ElasticsearchConfig:
    """Elasticsearch configuration."""
    enabled: bool = False
    host: str = "localhost"
    port: int = 9200
    index_name: str = "svo_chunks"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MilvusConfig:
    """Milvus configuration."""
    enabled: bool = False
    host: str = "localhost"
    port: int = 19530
    collection_name: str = "svo_embeddings"
    embedding_dim: int = 384

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Neo4jConfig:
    """Neo4j configuration."""
    enabled: bool = False
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "password"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineConfig:
    """Complete pipeline configuration."""

    # Backend mode
    backend_mode: BackendMode = BackendMode.DEMO
    use_production_backends: bool = False
    require_production_backends: bool = False

    # Storage
    sqlite_path: str = "svo_data.db"

    # Backend configurations
    elasticsearch: ElasticsearchConfig = field(default_factory=ElasticsearchConfig)
    milvus: MilvusConfig = field(default_factory=MilvusConfig)
    neo4j: Neo4jConfig = field(default_factory=Neo4jConfig)

    # Model selection
    embedding_model_name: str = "simple"  # "simple" or "transformer"
    svo_extractor_name: str = "mock"  # "mock" or "transformer"
    validator_name: str = "minimal"  # "minimal" or "transformer"

    # Judge
    enable_lm_judge: bool = False
    judge_model_name: Optional[str] = None

    # Backward-compatible classifier flags
    enable_lm_classifier: bool = False
    classifier_model_name: Optional[str] = None

    # Logging and diagnostics
    verbose: bool = False
    log_backend_usage: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "backend_mode": self.backend_mode.value,
            "use_production_backends": self.use_production_backends,
            "require_production_backends": self.require_production_backends,
            "sqlite_path": self.sqlite_path,
            "elasticsearch": self.elasticsearch.to_dict(),
            "milvus": self.milvus.to_dict(),
            "neo4j": self.neo4j.to_dict(),
            "embedding_model_name": self.embedding_model_name,
            "svo_extractor_name": self.svo_extractor_name,
            "validator_name": self.validator_name,
            "enable_lm_judge": self.enable_lm_judge,
            "judge_model_name": self.judge_model_name,
            "enable_lm_classifier": self.enable_lm_classifier,
            "classifier_model_name": self.classifier_model_name,
            "verbose": self.verbose,
            "log_backend_usage": self.log_backend_usage,
        }

    def to_json(self) -> str:
        """Convert config to JSON."""
        return json.dumps(self.to_dict(), indent=2)

    def save_to_file(self, path: str) -> None:
        """Save configuration to file."""
        with open(path, 'w') as f:
            f.write(self.to_json())

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "PipelineConfig":
        """Create config from dictionary."""
        # Handle backend_mode enum
        if isinstance(config_dict.get("backend_mode"), str):
            config_dict["backend_mode"] = BackendMode(config_dict["backend_mode"])

        # Handle nested objects
        if isinstance(config_dict.get("elasticsearch"), dict):
            config_dict["elasticsearch"] = ElasticsearchConfig(**config_dict["elasticsearch"])
        if isinstance(config_dict.get("milvus"), dict):
            config_dict["milvus"] = MilvusConfig(**config_dict["milvus"])
        if isinstance(config_dict.get("neo4j"), dict):
            config_dict["neo4j"] = Neo4jConfig(**config_dict["neo4j"])

        return cls(**config_dict)

    @classmethod
    def from_json(cls, json_str: str) -> "PipelineConfig":
        """Create config from JSON."""
        config_dict = json.loads(json_str)
        return cls.from_dict(config_dict)

    @classmethod
    def from_file(cls, path: str) -> "PipelineConfig":
        """Load configuration from file."""
        with open(path, 'r') as f:
            json_str = f.read()
        return cls.from_json(json_str)

    @classmethod
    def load_from_env(cls) -> "PipelineConfig":
        """Load configuration from environment variables."""
        config = cls()

        # Backend mode
        backend_mode = os.getenv("ONTO_BACKEND_MODE", "auto").lower()
        config.backend_mode = BackendMode(backend_mode)
        config.use_production_backends = os.getenv("ONTO_USE_PRODUCTION_BACKENDS", "false").lower() == "true"
        config.require_production_backends = os.getenv("ONTO_REQUIRE_PRODUCTION_BACKENDS", "false").lower() == "true"

        # Storage
        config.sqlite_path = os.getenv("ONTO_SQLITE_PATH", "svo_data.db")

        # Elasticsearch
        config.elasticsearch.enabled = os.getenv("ONTO_ES_ENABLED", "false").lower() == "true"
        config.elasticsearch.host = os.getenv("ONTO_ES_HOST", "localhost")
        config.elasticsearch.port = int(os.getenv("ONTO_ES_PORT", "9200"))
        config.elasticsearch.index_name = os.getenv("ONTO_ES_INDEX", "svo_chunks")

        # Milvus
        config.milvus.enabled = os.getenv("ONTO_MILVUS_ENABLED", "false").lower() == "true"
        config.milvus.host = os.getenv("ONTO_MILVUS_HOST", "localhost")
        config.milvus.port = int(os.getenv("ONTO_MILVUS_PORT", "19530"))
        config.milvus.collection_name = os.getenv("ONTO_MILVUS_COLLECTION", "svo_embeddings")
        config.milvus.embedding_dim = int(os.getenv("ONTO_MILVUS_DIM", "384"))

        # Neo4j
        config.neo4j.enabled = os.getenv("ONTO_NEO4J_ENABLED", "false").lower() == "true"
        config.neo4j.uri = os.getenv("ONTO_NEO4J_URI", "bolt://localhost:7687")
        config.neo4j.user = os.getenv("ONTO_NEO4J_USER", "neo4j")
        config.neo4j.password = os.getenv("ONTO_NEO4J_PASSWORD", "password")

        # Models
        config.embedding_model_name = os.getenv("ONTO_EMBEDDING_MODEL", "simple")
        config.svo_extractor_name = os.getenv("ONTO_SVO_EXTRACTOR", "mock")
        config.validator_name = os.getenv("ONTO_VALIDATOR", "minimal")

        # Judge
        config.enable_lm_judge = os.getenv("ONTO_ENABLE_LM_JUDGE", "false").lower() == "true"
        config.judge_model_name = os.getenv("ONTO_JUDGE_MODEL", None)

        # Classifier
        config.enable_lm_classifier = os.getenv("ONTO_ENABLE_LM_CLASSIFIER", "false").lower() == "true"
        config.classifier_model_name = os.getenv("ONTO_CLASSIFIER_MODEL", None)

        # Logging
        config.verbose = os.getenv("ONTO_VERBOSE", "false").lower() == "true"
        config.log_backend_usage = os.getenv("ONTO_LOG_BACKEND_USAGE", "false").lower() == "true"

        return config


def load_config_from_env() -> PipelineConfig:
    """Convenience function to load config from environment."""
    return PipelineConfig.load_from_env()


def create_default_config(mode: BackendMode = BackendMode.DEMO) -> PipelineConfig:
    """Create a default configuration."""
    config = PipelineConfig(backend_mode=mode)
    if mode == BackendMode.PRODUCTION:
        config.use_production_backends = True
    return config
