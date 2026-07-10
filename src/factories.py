"""Factory methods for creating configured pipeline components."""

import logging
from typing import Optional, Any

from .config import PipelineConfig, BackendMode
from .engine import SVOVerificationEngine
from .routing import MoERouter, QueryRouter
from .retrieval import BaseRetriever, SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever
from .fusion import WeightedFusionEngine, FusionEngine
from .storage import ChunkStore, SQLiteChunkStore
from .validation import MinimalValidator, EvidenceValidator

logger = logging.getLogger(__name__)


class EngineFactory:
    """Factory for creating SVOVerificationEngine with configuration."""

    @staticmethod
    def create_verification_engine(config: PipelineConfig) -> SVOVerificationEngine:
        """
        Create a verification engine from configuration.

        Args:
            config: PipelineConfig instance

        Returns:
            Configured SVOVerificationEngine

        Raises:
            RuntimeError: If production backends required but not available
        """
        if config.verbose:
            logger.info(f"Creating verification engine with backend_mode={config.backend_mode.value}")

        # Validate production requirements
        if config.require_production_backends:
            if not (config.elasticsearch.enabled or config.milvus.enabled or config.neo4j.enabled):
                raise RuntimeError(
                    "Production backends required but none are enabled. "
                    "Set ONTO_ES_ENABLED, ONTO_MILVUS_ENABLED, or ONTO_NEO4J_ENABLED to true"
                )

        # Create router
        router = MoERouter()

        # Create retrievers
        lexical_store = EngineFactory._create_lexical_retriever(config)
        semantic_store = EngineFactory._create_semantic_retriever(config)
        graph_store = EngineFactory._create_graph_retriever(config)

        # Create other components
        fusion_engine = WeightedFusionEngine()
        chunk_store = SQLiteChunkStore(config.sqlite_path)

        # Create validator
        validator = EngineFactory._create_validator(config)

        # Create triple classifier if enabled
        triple_classifier = None
        if config.enable_lm_classifier:
            try:
                from .classification import PromptTripleClassifier
                triple_classifier = PromptTripleClassifier(
                    model_name=config.classifier_model_name or "default"
                )
                if config.verbose:
                    logger.info("LM triple classifier enabled")
            except Exception as e:
                if config.verbose:
                    logger.warning(f"Could not create LM classifier: {e}")

        # Create engine
        engine = SVOVerificationEngine(
            router=router,
            lexical_store=lexical_store,
            semantic_store=semantic_store,
            graph_store=graph_store,
            fusion_engine=fusion_engine,
            chunk_store=chunk_store,
            validator=validator,
            triple_classifier=triple_classifier,
            config=config,
        )

        if config.verbose:
            logger.info("Verification engine created successfully")
            logger.info(f"Backend status: {engine.get_backend_status()}")

        return engine

    @staticmethod
    def _create_lexical_retriever(config: PipelineConfig) -> BaseRetriever:
        """Create lexical retriever based on config."""
        if config.elasticsearch.enabled:
            try:
                from .retrieval.lexical import LexicalRetriever
                from .helpers.elasticsearch import get_elasticsearch_client
                es_client = get_elasticsearch_client(
                    host=config.elasticsearch.host,
                    port=config.elasticsearch.port,
                )
                if config.verbose:
                    logger.info(f"Using Elasticsearch for lexical retrieval at {config.elasticsearch.host}:{config.elasticsearch.port}")
                return LexicalRetriever(
                    es_client=es_client,
                    index_name=config.elasticsearch.index_name,
                )
            except Exception as e:
                logger.warning(f"Failed to create Elasticsearch retriever: {e}. Falling back to SQLite.")

        if config.verbose:
            logger.info("Using SQLite for lexical retrieval")
        return SQLiteLexicalRetriever(config.sqlite_path)

    @staticmethod
    def _create_semantic_retriever(config: PipelineConfig) -> BaseRetriever:
        """Create semantic retriever based on config."""
        if config.milvus.enabled:
            try:
                from .retrieval.semantic import MilvusSemanticRetriever
                embedding_model = EngineFactory._create_embedding_model(config)
                if config.verbose:
                    logger.info(f"Using Milvus for semantic retrieval at {config.milvus.host}:{config.milvus.port}")
                return MilvusSemanticRetriever(
                    collection_name=config.milvus.collection_name,
                    embedding_model=embedding_model,
                )
            except Exception as e:
                logger.warning(f"Failed to create Milvus retriever: {e}. Falling back to SQLite.")

        if config.verbose:
            logger.info("Using SQLite for semantic retrieval")
        return SQLiteSemanticRetriever(config.sqlite_path)

    @staticmethod
    def _create_graph_retriever(config: PipelineConfig) -> BaseRetriever:
        """Create graph retriever based on config."""
        if config.neo4j.enabled:
            try:
                from .retrieval.graph import GraphRetriever
                from .helpers.neo4j import get_neo4j_driver
                driver = get_neo4j_driver(
                    uri=config.neo4j.uri,
                    user=config.neo4j.user,
                    password=config.neo4j.password,
                )
                if config.verbose:
                    logger.info(f"Using Neo4j for graph retrieval at {config.neo4j.uri}")
                return GraphRetriever(driver)
            except Exception as e:
                logger.warning(f"Failed to create Neo4j retriever: {e}. Falling back to SQLite.")

        if config.verbose:
            logger.info("Using SQLite for graph retrieval")
        return SQLiteGraphRetriever(config.sqlite_path)

    @staticmethod
    def _create_validator(config: PipelineConfig) -> EvidenceValidator:
        """Create validator based on config."""
        if config.validator_name == "transformer":
            try:
                from .validation import TransformerValidator
                if config.verbose:
                    logger.info("Using TransformerValidator")
                return TransformerValidator()
            except Exception as e:
                logger.warning(f"Failed to create TransformerValidator: {e}. Falling back to MinimalValidator.")

        if config.verbose:
            logger.info("Using MinimalValidator")
        return MinimalValidator()

    @staticmethod
    def _create_embedding_model(config: PipelineConfig) -> Any:
        """Create embedding model based on config."""
        if config.embedding_model_name == "transformer":
            try:
                from .ingestion.embeddings import TransformerEmbeddingModel
                if config.verbose:
                    logger.info("Using TransformerEmbeddingModel")
                return TransformerEmbeddingModel()
            except Exception as e:
                logger.warning(f"Failed to create TransformerEmbeddingModel: {e}. Falling back to SimpleEmbeddingModel.")

        if config.verbose:
            logger.info("Using SimpleEmbeddingModel")
        from .ingestion.embeddings import SimpleEmbeddingModel
        return SimpleEmbeddingModel()

    @staticmethod
    def create_ingestor(config: PipelineConfig) -> Any:
        """
        Create a DataIngestor with configured backends.

        Args:
            config: PipelineConfig instance

        Returns:
            Configured DataIngestor
        """
        from .ingestion import DataIngestor

        if config.verbose:
            logger.info("Creating DataIngestor with configured backends")

        # Create backend clients
        es_client = None
        milvus_collection = None
        neo4j_driver = None

        if config.elasticsearch.enabled:
            try:
                from .helpers.elasticsearch import get_elasticsearch_client
                es_client = get_elasticsearch_client(
                    host=config.elasticsearch.host,
                    port=config.elasticsearch.port,
                )
                if config.verbose:
                    logger.info(f"Elasticsearch client created: {config.elasticsearch.host}:{config.elasticsearch.port}")
            except Exception as e:
                logger.warning(f"Failed to create Elasticsearch client: {e}")

        if config.milvus.enabled:
            try:
                from .helpers.milvus import get_milvus_collection
                milvus_collection = get_milvus_collection(
                    host=config.milvus.host,
                    port=config.milvus.port,
                    collection_name=config.milvus.collection_name,
                    dim=config.milvus.embedding_dim,
                )
                if config.verbose:
                    logger.info(f"Milvus collection created: {config.milvus.collection_name}")
            except Exception as e:
                logger.warning(f"Failed to create Milvus collection: {e}")

        if config.neo4j.enabled:
            try:
                from .helpers.neo4j import get_neo4j_driver, initialize_neo4j_schema
                neo4j_driver = get_neo4j_driver(
                    uri=config.neo4j.uri,
                    user=config.neo4j.user,
                    password=config.neo4j.password,
                )
                initialize_neo4j_schema(neo4j_driver)
                if config.verbose:
                    logger.info(f"Neo4j driver created: {config.neo4j.uri}")
            except Exception as e:
                logger.warning(f"Failed to create Neo4j driver: {e}")

        # Note: backends can be None if not configured/available
        # DataIngestor should handle None gracefully

        # Create models
        embedding_model = EngineFactory._create_embedding_model(config)

        if config.svo_extractor_name == "transformer":
            try:
                from .ingestion.extractors import TransformerSVOExtractor
                svo_extractor = TransformerSVOExtractor()
                if config.verbose:
                    logger.info("Using TransformerSVOExtractor")
            except Exception as e:
                logger.warning(f"Failed to create TransformerSVOExtractor: {e}. Using MockSVOExtractor.")
                from .ingestion.extractors import MockSVOExtractor
                svo_extractor = MockSVOExtractor()
        else:
            from .ingestion.extractors import MockSVOExtractor
            svo_extractor = MockSVOExtractor()

        from .ingestion.extractors import MockConceptExtractor
        concept_extractor = MockConceptExtractor()

        # Create ingestor
        ingestor = DataIngestor(
            sqlite_conn_path=config.sqlite_path,
            es_client=es_client,
            milvus_collection=milvus_collection,
            neo4j_driver=neo4j_driver,
            embedding_model=embedding_model,
            svo_extractor=svo_extractor,
            concept_extractor=concept_extractor,
            config=config,
        )

        if config.verbose:
            logger.info("DataIngestor created successfully")

        return ingestor
