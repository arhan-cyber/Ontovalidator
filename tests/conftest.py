"""Pytest configuration and shared fixtures."""

import os
import tempfile
import shutil
import uuid
from pathlib import Path
from contextlib import contextmanager

import pytest

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


@contextmanager
def workspace_tmpdir():
    """Create a temporary directory for tests."""
    path = os.path.abspath(os.path.join(os.getcwd(), f".tmp_test_{uuid.uuid4().hex}"))
    os.makedirs(path, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def tmp_workspace():
    """Pytest fixture for temporary workspace."""
    with workspace_tmpdir() as path:
        yield path


@pytest.fixture
def demo_db_path(tmp_workspace):
    """Create a temporary database for testing."""
    return os.path.join(tmp_workspace, "test.sqlite")


@pytest.fixture
def sample_text():
    """Sample document text for testing."""
    return (
        "Aspirin is a widely used analgesic and antipyretic. "
        "For over a century, doctors have known that Aspirin treats headache and minor body aches.\n\n"
        "Clinical studies demonstrate that it also reduces fever and inflammation. "
        "However, it does not cure or treat malaria, which requires specific anti-malarial therapies."
    )


@pytest.fixture
def ingestion_result(demo_db_path, sample_text):
    """Run ingestion once for all tests to use."""
    from src.ingestion import run_demo as run_ingestion_demo
    return run_ingestion_demo(
        document_id="test_doc",
        raw_text=sample_text,
        db_path=demo_db_path,
        run_mode="demo"
    )


@pytest.fixture
def verification_engine(demo_db_path, ingestion_result):
    """Create a verification engine with demo database."""
    from src.routing import MoERouter
    from src.retrieval import SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever
    from src.fusion import WeightedFusionEngine
    from src.storage import SQLiteChunkStore
    from src.validation import MinimalValidator
    from src.engine import SVOVerificationEngine

    return SVOVerificationEngine(
        router=MoERouter(),
        lexical_store=SQLiteLexicalRetriever(demo_db_path),
        semantic_store=SQLiteSemanticRetriever(demo_db_path),
        graph_store=SQLiteGraphRetriever(demo_db_path),
        fusion_engine=WeightedFusionEngine(),
        chunk_store=SQLiteChunkStore(demo_db_path),
        validator=MinimalValidator(),
    )
