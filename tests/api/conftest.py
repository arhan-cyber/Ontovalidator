"""TestClient fixture with a stubbed engine pool (no real lifespan / heavy models)."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api import dependencies
from api.app import app
from src.config import PipelineConfig


def canned_result(document_id="doc_test", n_verdicts=1):
    return {
        "document_id": document_id,
        "ingestion_status": "success",
        "chunks_ingested": 1,
        "svos_extracted": 1,
        "verdicts": [
            {
                "assertion_id": f"t{i}",
                "subject": "engine",
                "relation": "drives",
                "object": "wheel",
                "label": "supported",
                "score": 0.9,
                "rationale": "matched evidence",
                "evidence": [
                    {
                        "chunk_id": "c1",
                        "text": "The engine drives the wheel.",
                        "source": "lexical",
                        "confidence": 0.9,
                        "match_type": "exact",
                        "matched": {"subject": True, "relation": True, "object": True},
                    }
                ],
                "rule_hits": [],
                "retrieval_sources": ["lexical"],
            }
            for i in range(1, n_verdicts + 1)
        ],
        "summary": {
            "total_triples": n_verdicts,
            "supported": n_verdicts,
            "contradicted": 0,
            "partial": 0,
            "unknown": 0,
            "avg_score": 0.9,
        },
        "backend_status": {
            "lexical": "SQLiteLexicalRetriever",
            "semantic": "SQLiteSemanticRetriever",
            "graph": "SQLiteGraphRetriever",
        },
    }


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.validate_triples_batch.return_value = canned_result()
    engine.get_backend_status.return_value = {
        "lexical": "SQLiteLexicalRetriever",
        "semantic": "SQLiteSemanticRetriever",
        "graph": "SQLiteGraphRetriever",
    }
    return engine


@pytest.fixture(autouse=True)
def stub_engine_pool(mock_engine, monkeypatch):
    """Populate the module-level pool directly so no real engines/models are built."""
    default_config = PipelineConfig()
    pool = {
        ("simple", "mock"): mock_engine,
        ("simple", "transformer"): MagicMock(),
        ("transformer", "mock"): MagicMock(),
        ("transformer", "transformer"): MagicMock(),
    }
    monkeypatch.setattr(dependencies, "ENGINE_POOL", pool)
    monkeypatch.setattr(dependencies, "DEFAULT_CONFIG", default_config)
    monkeypatch.setattr(dependencies, "DEFAULT_KEY", ("simple", "mock"))
    return pool


@pytest.fixture
def client():
    # Not using `with TestClient(app)` on purpose: that would trigger the real
    # lifespan (build_engine_pool), which loads heavy models. Plain instantiation
    # skips lifespan events, so our monkeypatched pool from stub_engine_pool stands.
    return TestClient(app)
