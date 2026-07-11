"""Engine pool management + FastAPI dependency for resolving an engine per request."""

import logging
from dataclasses import replace
from typing import Dict, Optional, Tuple

from fastapi import HTTPException

from src.config import PipelineConfig, load_config_from_env  # noqa: F401 (re-exported for routes)
from src.engine import SVOVerificationEngine
from src.factories import EngineFactory

logger = logging.getLogger(__name__)

EMBEDDING_MODELS = ("simple", "transformer")
SVO_EXTRACTORS = ("mock", "transformer")

ENGINE_POOL: Dict[Tuple[str, str], SVOVerificationEngine] = {}
DEFAULT_CONFIG: Optional[PipelineConfig] = None
DEFAULT_KEY: Optional[Tuple[str, str]] = None


def build_engine_pool() -> None:
    """Eagerly build the engine pool for the full model cross-product. Called from lifespan."""
    global DEFAULT_CONFIG, DEFAULT_KEY
    DEFAULT_CONFIG = load_config_from_env()
    DEFAULT_KEY = (DEFAULT_CONFIG.embedding_model_name, DEFAULT_CONFIG.svo_extractor_name)

    for emb in EMBEDDING_MODELS:
        for svo in SVO_EXTRACTORS:
            cfg = replace(DEFAULT_CONFIG, embedding_model_name=emb, svo_extractor_name=svo)
            try:
                ENGINE_POOL[(emb, svo)] = EngineFactory.create_verification_engine(cfg)
            except Exception:
                logger.exception(f"Failed to build engine for ({emb}, {svo})")


def clear_engine_pool() -> None:
    ENGINE_POOL.clear()


def resolve_engine(
    embedding_model: Optional[str], svo_extractor: Optional[str]
) -> SVOVerificationEngine:
    """Resolve the requested (embedding_model, svo_extractor) pool key, falling back to the
    default key for any component left unspecified or whose combo failed to build."""
    key = (embedding_model or DEFAULT_KEY[0], svo_extractor or DEFAULT_KEY[1]) if DEFAULT_KEY else None

    engine = ENGINE_POOL.get(key) if key else None
    if engine is None:
        engine = ENGINE_POOL.get(DEFAULT_KEY) if DEFAULT_KEY else None
    if engine is None:
        raise HTTPException(500, {"error": "no_engine_available", "detail": "Engine pool is not initialized"})
    return engine


def get_engine_for_request(embedding_model: Optional[str] = None, svo_extractor: Optional[str] = None):
    """FastAPI-overridable dependency factory. Routes call this via Depends(...) with the
    request-scoped args bound through a small wrapper (see routes/validate.py)."""
    return resolve_engine(embedding_model, svo_extractor)
