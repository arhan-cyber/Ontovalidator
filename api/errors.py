"""Exception handlers mapping errors to JSON bodies."""

import logging

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    # Registered on starlette.exceptions.HTTPException (the base class) rather
    # than fastapi.exceptions.HTTPException (a subclass): FastAPI's own body
    # -parsing code (fastapi/routing.py) raises the *starlette* base class
    # directly for non-JSONDecodeError body-parsing failures (e.g. a
    # non-UTF8 body). Starlette's handler lookup walks the MRO of the raised
    # exception's type looking for a registered ancestor, so a handler keyed
    # on the subclass never matches a base-class instance and those errors
    # fell through to Starlette's default `{"detail": ...}` shape, bypassing
    # our handler (and the frontend's `error`-key parser) entirely. Keying on
    # the base class matches both the base class and the fastapi subclass
    # raised elsewhere in this codebase (e.g. `raise HTTPException(400, ...)`
    # in routes), since subclass instances still have the base class in
    # their MRO.
    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_exc_handler(request, exc: RequestValidationError):
        # exc.errors() can embed non-JSON-serializable values (e.g. raw bytes
        # for a body that failed decoding before Pydantic ever saw it as
        # text). jsonable_encoder coerces those into something serializable
        # (bytes -> repr'd/lossy-decoded str) so JSONResponse's json.dumps
        # doesn't crash inside this handler itself.
        safe_errors = jsonable_encoder(
            exc.errors(), custom_encoder={bytes: lambda o: o.decode("utf-8", errors="replace")}
        )
        return JSONResponse(
            status_code=422,
            content={"error": {"error": "invalid_request", "detail": safe_errors}},
        )

    @app.exception_handler(Exception)
    async def unhandled_exc_handler(request, exc: Exception):
        logger.exception("Unhandled exception")
        return JSONResponse(status_code=500, content={"error": "internal_error"})
