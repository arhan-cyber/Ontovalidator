"""Bug 1 repro tests: 422 validation-error response shape and malformed-body crashes.

Covers api/errors.py's validation_exc_handler and http_exc_handler:
- exc.errors() must be nested under "error" (not a sibling key), matching the shape
  http_exc_handler already uses and that frontend/src/api/client.ts's normalizeError()
  expects (payload.error.error / payload.error.detail).
- a request body that FastAPI hands to Pydantic as raw bytes (missing/wrong
  Content-Type) must not crash JSONResponse's encoding.
- a non-UTF8 body must not crash the handler and must not bypass our handlers to
  fall through to Starlette's bare `{"detail": ...}` default shape.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from api.errors import register_exception_handlers


def _make_app():
    app = FastAPI()
    register_exception_handlers(app)

    class Body(BaseModel):
        x: str

    @app.post("/t")
    async def t(b: Body):
        return {"ok": True}

    return app


def _client():
    return TestClient(_make_app(), raise_server_exceptions=False)


def test_422_nests_detail_under_error():
    client = _client()
    resp = client.post("/t", json={"x": 123})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["error"] == "invalid_request"
    assert isinstance(body["error"]["detail"], list)
    assert body["error"]["detail"][0]["loc"] == ["body", "x"]


def test_missing_content_type_bytes_body_does_not_crash():
    """FastAPI hands Pydantic raw bytes when it can't route the body through JSON
    parsing (e.g. no/incompatible Content-Type). Previously this produced a raw
    `bytes` object inside exc.errors()'s "input" field, which crashed
    JSONResponse's json.dumps with TypeError, itself inside the exception
    handler, and fell through to the generic 500 handler."""
    client = _client()
    resp = client.post("/t", content=b"not a dict body", headers={})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["error"] == "invalid_request"
    assert isinstance(body["error"]["detail"], list)


def test_non_utf8_body_with_json_content_type_does_not_bypass_handler():
    """A non-UTF8 body with Content-Type: application/json raises
    starlette.exceptions.HTTPException(400, "There was an error parsing the
    body") directly from fastapi/routing.py's body-decoding step -- using the
    *base* Starlette HTTPException class, not fastapi's subclass. A handler
    registered only on the fastapi subclass never sees it (MRO lookup only
    walks up, not down), so it fell through to Starlette's default
    `{"detail": ...}` shape entirely bypassing our JSON error contract."""
    client = _client()
    resp = client.post(
        "/t", content=b"\xff\xfe not valid utf8", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    assert "detail" not in body  # not the bare Starlette default shape


def test_http_exception_shape_unaffected():
    """Sanity check: plain HTTPException handling (404, etc.) still nests correctly."""
    client = _client()
    resp = client.get("/does-not-exist")
    assert resp.status_code == 404
    assert resp.json() == {"error": "Not Found"}
