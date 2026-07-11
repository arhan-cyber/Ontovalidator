"""FastAPI app: lifespan (eager engine pool), CORS, StaticFiles mount, routers."""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import dependencies
from api.errors import register_exception_handlers
from api.routes import config as config_route
from api.routes import health as health_route
from api.routes import validate as validate_route

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


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

app.include_router(validate_route.router)
app.include_router(health_route.router)
app.include_router(config_route.router)

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
