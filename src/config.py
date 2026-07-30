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
    concept_extractor_name: str = "mock"  # "mock" or "transformer"
    validator_name: str = "minimal"  # "minimal" or "transformer"

    # Evidence-span classifier
    evidence_span_classifier_name: str = "heuristic"  # "heuristic" or "nli"
    evidence_span_classifier_model_name: Optional[str] = None

    # Judge
    enable_lm_judge: bool = False
    judge_model_name: Optional[str] = None

    # Concept extractor model
    concept_extractor_model_name: Optional[str] = None

    # Backward-compatible classifier flags
    enable_lm_classifier: bool = False
    classifier_model_name: Optional[str] = None

    # Caching
    enable_cache: bool = True
    cache_db_path: str = "cache.db"
    embedding_cache_ttl_days: int = 30
    retrieval_cache_ttl_days: int = 7
    verdict_cache_ttl_days: int = 14
    cache_clear_interval_hours: int = 24

    # Multi-modal ingestion
    enable_table_extraction: bool = True
    enable_list_extraction: bool = True
    enable_ocr: bool = False  # Requires pytesseract
    table_extraction_mode: str = "html"  # "html", "csv", "auto"
    min_ocr_confidence: float = 0.5

    # Temporal reasoning
    enable_temporal_reasoning: bool = True
    outdated_evidence_confidence_penalty: float = 0.6
    future_evidence_confidence_penalty: float = 0.3
    default_temporal_scope_years: int = 5

    # Feedback loop
    enable_feedback: bool = True
    feedback_db_path: str = "feedback.db"

    # Observability payloads on verdicts
    enable_retrieval_pathway: bool = True
    enable_chunk_annotation: bool = True
    enable_scoring_breakdown: bool = True
    enable_rejected_evidence: bool = True

    # Logging and diagnostics
    verbose: bool = False
    log_backend_usage: bool = False

    def __post_init__(self) -> None:
        self._resolve_derived_db_paths()

    def _resolve_derived_db_paths(self) -> None:
        """Keep the derived databases next to the chunk store they describe.

        Without this a config pointed at /tmp/run/svo.db would still drop
        cache.db and feedback.db into the current working directory.
        """
        directory = os.path.dirname(os.path.abspath(self.sqlite_path))
        for field_name, default in (("cache_db_path", "cache.db"), ("feedback_db_path", "feedback.db")):
            if getattr(self, field_name) == default:
                setattr(self, field_name, os.path.join(directory, default))

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
            "concept_extractor_name": self.concept_extractor_name,
            "concept_extractor_model_name": self.concept_extractor_model_name,
            "validator_name": self.validator_name,
            "evidence_span_classifier_name": self.evidence_span_classifier_name,
            "evidence_span_classifier_model_name": self.evidence_span_classifier_model_name,
            "enable_lm_judge": self.enable_lm_judge,
            "judge_model_name": self.judge_model_name,
            "enable_lm_classifier": self.enable_lm_classifier,
            "classifier_model_name": self.classifier_model_name,
            "enable_cache": self.enable_cache,
            "cache_db_path": self.cache_db_path,
            "embedding_cache_ttl_days": self.embedding_cache_ttl_days,
            "retrieval_cache_ttl_days": self.retrieval_cache_ttl_days,
            "verdict_cache_ttl_days": self.verdict_cache_ttl_days,
            "cache_clear_interval_hours": self.cache_clear_interval_hours,
            "enable_table_extraction": self.enable_table_extraction,
            "enable_list_extraction": self.enable_list_extraction,
            "enable_ocr": self.enable_ocr,
            "table_extraction_mode": self.table_extraction_mode,
            "min_ocr_confidence": self.min_ocr_confidence,
            "enable_temporal_reasoning": self.enable_temporal_reasoning,
            "outdated_evidence_confidence_penalty": self.outdated_evidence_confidence_penalty,
            "future_evidence_confidence_penalty": self.future_evidence_confidence_penalty,
            "default_temporal_scope_years": self.default_temporal_scope_years,
            "enable_feedback": self.enable_feedback,
            "feedback_db_path": self.feedback_db_path,
            "enable_retrieval_pathway": self.enable_retrieval_pathway,
            "enable_chunk_annotation": self.enable_chunk_annotation,
            "enable_scoring_breakdown": self.enable_scoring_breakdown,
            "enable_rejected_evidence": self.enable_rejected_evidence,
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
        config.concept_extractor_name = os.getenv("ONTO_CONCEPT_EXTRACTOR", "mock")
        config.concept_extractor_model_name = os.getenv("ONTO_CONCEPT_EXTRACTOR_MODEL", None)
        config.validator_name = os.getenv("ONTO_VALIDATOR", "minimal")
        config.evidence_span_classifier_name = os.getenv("ONTO_EVIDENCE_SPAN_CLASSIFIER", "heuristic")
        config.evidence_span_classifier_model_name = os.getenv("ONTO_EVIDENCE_SPAN_CLASSIFIER_MODEL", None)

        # Judge
        config.enable_lm_judge = os.getenv("ONTO_ENABLE_LM_JUDGE", "false").lower() == "true"
        config.judge_model_name = os.getenv("ONTO_JUDGE_MODEL", None)

        # Classifier
        config.enable_lm_classifier = os.getenv("ONTO_ENABLE_LM_CLASSIFIER", "false").lower() == "true"
        config.classifier_model_name = os.getenv("ONTO_CLASSIFIER_MODEL", None)

        # Caching
        config.enable_cache = os.getenv("ONTO_ENABLE_CACHE", "true").lower() == "true"
        config.cache_db_path = os.getenv("ONTO_CACHE_DB_PATH", "cache.db")
        config.embedding_cache_ttl_days = int(os.getenv("ONTO_EMBEDDING_CACHE_TTL_DAYS", "30"))
        config.retrieval_cache_ttl_days = int(os.getenv("ONTO_RETRIEVAL_CACHE_TTL_DAYS", "7"))
        config.verdict_cache_ttl_days = int(os.getenv("ONTO_VERDICT_CACHE_TTL_DAYS", "14"))
        config.cache_clear_interval_hours = int(os.getenv("ONTO_CACHE_CLEAR_INTERVAL_HOURS", "24"))

        # Multi-modal ingestion
        config.enable_table_extraction = os.getenv("ONTO_ENABLE_TABLE_EXTRACTION", "true").lower() == "true"
        config.enable_list_extraction = os.getenv("ONTO_ENABLE_LIST_EXTRACTION", "true").lower() == "true"
        config.enable_ocr = os.getenv("ONTO_ENABLE_OCR", "false").lower() == "true"
        config.table_extraction_mode = os.getenv("ONTO_TABLE_EXTRACTION_MODE", "html")
        config.min_ocr_confidence = float(os.getenv("ONTO_MIN_OCR_CONFIDENCE", "0.5"))

        # Temporal reasoning
        config.enable_temporal_reasoning = os.getenv("ONTO_ENABLE_TEMPORAL_REASONING", "true").lower() == "true"
        config.outdated_evidence_confidence_penalty = float(os.getenv("ONTO_OUTDATED_EVIDENCE_PENALTY", "0.6"))
        config.future_evidence_confidence_penalty = float(os.getenv("ONTO_FUTURE_EVIDENCE_PENALTY", "0.3"))
        config.default_temporal_scope_years = int(os.getenv("ONTO_DEFAULT_TEMPORAL_SCOPE_YEARS", "5"))

        # Feedback loop
        config.enable_feedback = os.getenv("ONTO_ENABLE_FEEDBACK", "true").lower() == "true"
        config.feedback_db_path = os.getenv("ONTO_FEEDBACK_DB_PATH", "feedback.db")

        # Observability payloads
        config.enable_retrieval_pathway = os.getenv("ONTO_ENABLE_RETRIEVAL_PATHWAY", "true").lower() == "true"
        config.enable_chunk_annotation = os.getenv("ONTO_ENABLE_CHUNK_ANNOTATION", "true").lower() == "true"
        config.enable_scoring_breakdown = os.getenv("ONTO_ENABLE_SCORING_BREAKDOWN", "true").lower() == "true"
        config.enable_rejected_evidence = os.getenv("ONTO_ENABLE_REJECTED_EVIDENCE", "true").lower() == "true"

        # Logging
        config.verbose = os.getenv("ONTO_VERBOSE", "false").lower() == "true"
        config.log_backend_usage = os.getenv("ONTO_LOG_BACKEND_USAGE", "false").lower() == "true"

        # sqlite_path was assigned after __post_init__ ran, so re-anchor the
        # derived paths against the final value.
        config._resolve_derived_db_paths()

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
