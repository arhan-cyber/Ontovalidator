"""GET /health, TTL-cached wrapper around HealthCheckRunner."""

import time
from typing import Optional, Tuple

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from src.integration.health_check_runner import HealthCheckRunner

from .. import dependencies

router = APIRouter()

TTL_SECONDS = 30
_cache: Optional[Tuple[float, dict]] = None


@router.get("/health")
async def health(force: bool = False):
    global _cache
    now = time.monotonic()
    if not force and _cache is not None and (now - _cache[0]) < TTL_SECONDS:
        return _cache[1]

    config = dependencies.DEFAULT_CONFIG or dependencies.load_config_from_env()
    report = await run_in_threadpool(HealthCheckRunner.check_all, config)
    result = report.to_dict()
    _cache = (now, result)
    return result
