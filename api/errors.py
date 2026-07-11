"""Exception handlers mapping errors to JSON bodies."""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exc_handler(request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_exc_handler(request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": "invalid_request", "detail": exc.errors()})

    @app.exception_handler(Exception)
    async def unhandled_exc_handler(request, exc: Exception):
        logger.exception("Unhandled exception")
        return JSONResponse(status_code=500, content={"error": "internal_error"})
