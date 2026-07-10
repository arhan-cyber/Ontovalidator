"""Shared pytest fixtures for integration tests."""

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from src.config import PipelineConfig, BackendMode, ElasticsearchConfig, MilvusConfig, Neo4jConfig
from src.engine import SVOVerificationEngine
from src.models import OntologyAssertion


@pytest.fixture
def config_demo():
    """Create a PipelineConfig in DEMO mode."""
    return PipelineConfig(
        backend_mode=BackendMode.DEMO,
        use_production_backends=False,
        require_production_backends=False,
        embedding_model_name="simple",
        svo_extractor_name="mock",
        validator_name="minimal",
    )


@pytest.fixture
def config_auto():
    """Create a PipelineConfig in AUTO mode."""
    return PipelineConfig(
        backend_mode=BackendMode.AUTO,
        use_production_backends=False,
        require_production_backends=False,
    )


@pytest.fixture
def config_production():
    """Create a PipelineConfig in PRODUCTION mode."""
    return PipelineConfig(
        backend_mode=BackendMode.PRODUCTION,
        use_production_backends=True,
        require_production_backends=False,
        elasticsearch=ElasticsearchConfig(enabled=False),
        milvus=MilvusConfig(enabled=False),
        neo4j=Neo4jConfig(enabled=False),
    )


@pytest.fixture
def temp_db_path():
    """Create a temporary SQLite database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        yield db_path


@pytest.fixture
def sample_document():
    """Create sample document text for testing."""
    return (
        "Aspirin is a widely used analgesic and antipyretic medication. "
        "It has been used for over a century to treat headaches and minor body aches. "
        "Aspirin reduces inflammation and lowers fever in patients. "
        "However, aspirin cannot treat bacterial infections like pneumonia. "
        "Malaria requires specific anti-malarial therapies and aspirin cannot cure it."
    )


@pytest.fixture
def sample_triples():
    """Create sample OntologyAssertion objects for testing."""
    return [
        OntologyAssertion(
            assertion_id="triple_1",
            subject="Aspirin",
            relation="treats",
            object="headache",
            polarity="must_hold",
            rule_type="constraint",
        ),
        OntologyAssertion(
            assertion_id="triple_2",
            subject="Aspirin",
            relation="reduces",
            object="inflammation",
            polarity="must_hold",
            rule_type="constraint",
        ),
        OntologyAssertion(
            assertion_id="triple_3",
            subject="Aspirin",
            relation="treats",
            object="malaria",
            polarity="must_not_hold",
            rule_type="constraint",
        ),
        OntologyAssertion(
            assertion_id="triple_4",
            subject="Aspirin",
            relation="treats",
            object="bacterial_infection",
            polarity="must_not_hold",
            rule_type="constraint",
        ),
    ]


@pytest.fixture
def engine_demo(config_demo, temp_db_path):
    """Create an SVOVerificationEngine in demo mode."""
    config = PipelineConfig(
        backend_mode=BackendMode.DEMO,
        use_production_backends=False,
        sqlite_path=temp_db_path,
        embedding_model_name="simple",
        svo_extractor_name="mock",
        validator_name="minimal",
    )
    return SVOVerificationEngine.from_config(config)


@pytest.fixture
def mock_elasticsearch_client():
    """Create a mocked Elasticsearch client."""
    with mock.patch('elasticsearch.Elasticsearch') as mock_es:
        client = mock.MagicMock()
        client.info.return_value = {"version": {"number": "8.0.0"}}
        client.search.return_value = {"hits": {"hits": []}}
        mock_es.return_value = client
        yield client


@pytest.fixture
def mock_neo4j_driver():
    """Create a mocked Neo4j driver."""
    with mock.patch('neo4j.GraphDatabase.driver') as mock_driver:
        driver = mock.MagicMock()
        session = mock.MagicMock()
        session.run.return_value = mock.MagicMock()
        driver.session.return_value.__enter__ = mock.MagicMock(return_value=session)
        driver.session.return_value.__exit__ = mock.MagicMock(return_value=False)
        mock_driver.return_value = driver
        yield driver


@pytest.fixture
def mock_milvus_collection():
    """Create a mocked Milvus collection."""
    with mock.patch('pymilvus.Collection') as mock_collection:
        collection = mock.MagicMock()
        collection.search.return_value = []
        mock_collection.return_value = collection
        yield collection


@pytest.fixture
def monkeypatch_env(monkeypatch):
    """Provide a monkeypatch fixture for environment variable testing."""
    return monkeypatch
