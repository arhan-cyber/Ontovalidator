"""FastAPI app: lifespan (eager engine pool), CORS, StaticFiles mount, routers."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api import dependencies
from api.errors import register_exception_handlers
from api.routes import config as config_route
from api.routes import feedback as feedback_route
from api.routes import health as health_route
from api.routes import validate as validate_route

FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    dependencies.build_engine_pool()
    yield
    dependencies.clear_engine_pool()


app = FastAPI(title="SVO Verification API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(validate_route.router, prefix="/api")
app.include_router(health_route.router, prefix="/api")
app.include_router(config_route.router, prefix="/api")
app.include_router(feedback_route.router, prefix="/api")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="static")
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def spa_catch_all(full_path: str, request: Request):
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(FRONTEND_DIR / "index.html")
