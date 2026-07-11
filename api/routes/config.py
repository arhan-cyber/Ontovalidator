"""GET /config."""

from fastapi import APIRouter

from .. import dependencies

router = APIRouter()


@router.get("/config")
async def get_config():
    config = dependencies.DEFAULT_CONFIG or dependencies.load_config_from_env()
    cfg_dict = config.to_dict()
    cfg_dict["neo4j"]["password"] = "***redacted***"

    engine = dependencies.ENGINE_POOL.get(dependencies.DEFAULT_KEY) if dependencies.DEFAULT_KEY else None
    backend_status = (
        engine.get_backend_status()
        if engine is not None
        else {"lexical": "unknown", "semantic": "unknown", "graph": "unknown"}
    )

    return {
        "backend_mode": cfg_dict["backend_mode"],
        "sqlite_path": cfg_dict["sqlite_path"],
        "embedding_model_name": cfg_dict["embedding_model_name"],
        "svo_extractor_name": cfg_dict["svo_extractor_name"],
        "validator_name": cfg_dict["validator_name"],
        "enable_lm_judge": cfg_dict["enable_lm_judge"],
        "enable_lm_classifier": cfg_dict["enable_lm_classifier"],
        "backend_status": backend_status,
        "available_embedding_models": list(dependencies.EMBEDDING_MODELS),
        "available_svo_extractors": list(dependencies.SVO_EXTRACTORS),
    }
