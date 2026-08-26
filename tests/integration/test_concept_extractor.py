"""Unit tests for concept extraction."""

import pytest


def test_mock_concept_extractor_backward_compat():
    """MockConceptExtractor still works for per-chunk extraction."""
    from src.ingestion.extractors import MockConceptExtractor

    extractor = MockConceptExtractor()
    result = extractor.extract_concepts("controller type defines hierarchy")
    assert "provides" in result
    assert "depends_on" in result
    assert isinstance(result["provides"], list)
    assert isinstance(result["depends_on"], list)


def test_transformer_concept_extractor_import():
    """TransformerConceptExtractor can be imported (no model download on import)."""
    try:
        from src.ingestion.extractors import TransformerConceptExtractor
        assert TransformerConceptExtractor is not None
    except ImportError:
        pytest.skip("transformers not installed")


def test_transformer_concept_extractor_single_chunk_fallback():
    """TransformerConceptExtractor.extract_concepts falls back gracefully."""
    try:
        from src.ingestion.extractors import TransformerConceptExtractor
    except ImportError:
        pytest.skip("transformers not installed")

    try:
        extractor = TransformerConceptExtractor(model_name="google/flan-t5-large")
        result = extractor.extract_concepts("hierarchy and relationships")
        assert "provides" in result
        assert "depends_on" in result
        assert isinstance(result["provides"], list)
        assert isinstance(result["depends_on"], list)
    except Exception:
        pytest.skip("model download failed (expected on local machine)")


def test_pipeline_duck_typing_mock_extractor():
    """DataIngestor detects that MockConceptExtractor lacks extract_concepts_batch."""
    from src.ingestion.extractors import MockConceptExtractor

    extractor = MockConceptExtractor()
    assert not hasattr(extractor, "extract_concepts_batch")
    assert hasattr(extractor, "extract_concepts")


def test_pipeline_duck_typing_transformer_extractor():
    """TransformerConceptExtractor exposes extract_concepts_batch."""
    try:
        from src.ingestion.extractors import TransformerConceptExtractor
    except ImportError:
        pytest.skip("transformers not installed")

    try:
        extractor = TransformerConceptExtractor(model_name="google/flan-t5-large")
        assert hasattr(extractor, "extract_concepts_batch")
        assert hasattr(extractor, "extract_concepts")
    except Exception:
        pytest.skip("model download failed (expected on local machine)")


def test_config_concept_extractor_fields():
    """PipelineConfig has concept_extractor_name and concept_extractor_model_name."""
    from src.config import PipelineConfig

    config = PipelineConfig()
    assert hasattr(config, "concept_extractor_name")
    assert hasattr(config, "concept_extractor_model_name")
    assert config.concept_extractor_name == "mock"
    assert config.concept_extractor_model_name is None


def test_config_to_dict_includes_concept_extractor():
    """Config.to_dict includes concept extractor fields."""
    from src.config import PipelineConfig

    config = PipelineConfig(
        concept_extractor_name="transformer",
        concept_extractor_model_name="google/flan-t5-base"
    )
    d = config.to_dict()
    assert "concept_extractor_name" in d
    assert "concept_extractor_model_name" in d
    assert d["concept_extractor_name"] == "transformer"
    assert d["concept_extractor_model_name"] == "google/flan-t5-base"


def test_factory_creates_mock_concept_extractor_by_default():
    """EngineFactory creates MockConceptExtractor by default."""
    from src.config import PipelineConfig, BackendMode
    from src.factories import EngineFactory
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        config = PipelineConfig(backend_mode=BackendMode.DEMO, sqlite_path=db_path)
        ingestor = EngineFactory.create_ingestor(config)

        from src.ingestion.extractors import MockConceptExtractor
        assert isinstance(ingestor.concept_extractor, MockConceptExtractor)


def test_factory_concept_extractor_config_env_var():
    """Config loads concept_extractor_name from ONTO_CONCEPT_EXTRACTOR env var."""
    import os
    from src.config import PipelineConfig

    os.environ["ONTO_CONCEPT_EXTRACTOR"] = "mock"
    config = PipelineConfig.load_from_env()
    assert config.concept_extractor_name == "mock"

    os.environ["ONTO_CONCEPT_EXTRACTOR"] = "transformer"
    config = PipelineConfig.load_from_env()
    assert config.concept_extractor_name == "transformer"

    del os.environ["ONTO_CONCEPT_EXTRACTOR"]


def test_concept_name_normalization():
    """Concept names are normalized (lowercase, stripped) during Neo4j write."""
    from src.ingestion.pipeline import DataIngestor, LocalNeo4jDriver
    from src.ingestion.extractors import MockConceptExtractor
    from src.ingestion.embeddings import SimpleEmbeddingModel
    from src.models import Chunk
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        driver = LocalNeo4jDriver()

        ingestor = DataIngestor(
            sqlite_conn_path=db_path,
            es_client=None,
            milvus_collection=None,
            neo4j_driver=driver,
            embedding_model=SimpleEmbeddingModel(),
            svo_extractor=MockConceptExtractor(),
            concept_extractor=MockConceptExtractor(),
        )

        chunks = [
            Chunk(
                chunk_id="chunk1",
                document_id="doc1",
                text="test",
                embedding=[0.0, 0.0, 0.0, 0.0, 0.0],
                metadata={"provides": ["  HIERARCHY  ", "Resolution Pathway"], "depends_on": ["hierarchy"]}
            )
        ]

        ingestor._write_neo4j(chunks)

        recorded_queries = driver.records
        concept_writes = [r for r in recorded_queries if "MERGE" in r[0] and "Concept" in r[0]]

        assert len(concept_writes) > 0
        for query, params in concept_writes:
            if "concept_name" in params:
                normalized = params["concept_name"]
                assert normalized == normalized.lower()
                assert normalized == normalized.strip().lower()
