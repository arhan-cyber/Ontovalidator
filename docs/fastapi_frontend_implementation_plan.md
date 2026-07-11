# FastAPI Wrapper + Web Frontend for SVO Verification Engine

## Context

The SVO verification engine (`src/engine.py`, `src/factories.py`, `src/config.py`) is currently only usable via CLI scripts (`scripts/validate_triples.py`, `scripts/validate_with_config.sh`). The backend logic is already modular and synchronous/blocking, and is a good fit for a thin HTTP wrapper without touching any existing code. The goal here is to add a FastAPI backend exposing the existing `SVOVerificationEngine` capabilities over HTTP, plus a simple static web frontend so a user can validate triples against a document through a browser instead of the CLI. This is purely additive — no changes to `src/` or `scripts/`.

## Key existing interfaces being wrapped (verified by reading the code)

- `src/config.py`: `load_config_from_env() -> PipelineConfig`. Reads `ONTO_*`-prefixed env vars (`ONTO_SQLITE_PATH`, `ONTO_EMBEDDING_MODEL`, `ONTO_SVO_EXTRACTOR`, etc). Note: `.env.example` at repo root uses stale non-`ONTO_` names — pre-existing inconsistency, not fixed here, just documented in the new API's own docs.
- `src/factories.py`: `EngineFactory.create_verification_engine(config: PipelineConfig) -> SVOVerificationEngine`. Bakes in `embedding_model_name`/`svo_extractor_name`/db path at construction time — must be built once and reused, not rebuilt per request.
- `src/engine.py`: `SVOVerificationEngine.validate_triples_batch(document_id: str, raw_text: str, triples: List[OntologyAssertion], top_k: int = 5) -> Dict[str, Any]`. Synchronous/blocking. Already returns a plain JSON-serializable dict (verified at engine.py:514-560 — no dataclass leakage), shaped as:
  ```python
  {
    "document_id": str, "ingestion_status": str,
    "chunks_ingested": int, "svos_extracted": int,
    "verdicts": [{
        "assertion_id": str, "subject": str, "relation": str, "object": str,
        "label": str, "score": float, "rationale": str,
        "evidence": [{"chunk_id": str, "text": str, "source": str, "confidence": float,
                       "match_type": str, "matched": {"subject": bool, "relation": bool, "object": bool}}],
        "rule_hits": [str], "retrieval_sources": [str],
    }],
    "summary": {"total_triples": int, "supported": int, "contradicted": int,
                "partial": int, "unknown": int, "avg_score": float},
    "backend_status": {"lexical": str, "semantic": str, "graph": str},
  }
  ```
- `src/models.py`: `OntologyAssertion(assertion_id, subject, relation, object, polarity="must_hold", rule_type="constraint")`.
- `src/integration/health_check_runner.py`: `HealthCheckRunner.check_all(config) -> HealthCheckReport`, `.to_dict()` gives JSON-safe `{timestamp, overall_status, backends, recommendations}`. Opens live blocking connections (up to ~5s per backend) — must not run on every request unthrottled.
- `src/config.py`: `PipelineConfig.to_dict()` (existing) for the `/config` endpoint.

## Decisions (confirmed with user)

1. **Engine pool: eager.** At startup, pre-build `SVOVerificationEngine` instances for the full cross product of `embedding_model_name ∈ {"simple", "transformer"} × svo_extractor_name ∈ {"mock", "transformer"}`, keyed by tuple, so every `/validate` request (regardless of requested overrides) hits an already-warm engine. Accept slower startup (possible transformer model loads) for consistently fast requests.
2. **Frontend hosting: same-origin.** FastAPI mounts the static `frontend/` directory via `StaticFiles`, so the API and UI are served from one process/port — no CORS issues in the primary deployment path. Keep CORS middleware configured anyway (harmless, useful if someone opens the HTML directly via `file://` or a separate dev server during iteration).
3. **Docker: deferred.** Run via `uvicorn` directly for now. No `Dockerfile.api` or `docker-compose.yml` changes in this pass.

## File Layout (new files only)

```
Ontovalidator/
├── api/
│   ├── __init__.py
│   ├── app.py                # FastAPI app, lifespan (eager engine pool), CORS, StaticFiles mount
│   ├── schemas.py             # Pydantic request/response models
│   ├── dependencies.py        # get_engine_for_request(), pool lookup
│   ├── errors.py              # exception handlers -> JSON error bodies
│   └── routes/
│       ├── __init__.py
│       ├── validate.py        # POST /validate
│       ├── health.py          # GET /health (TTL-cached)
│       └── config.py          # GET /config
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── requirements-api.txt
└── tests/
    └── api/                    # NEW - no API tests exist yet (verified: tests/ currently has no api/ dir)
        ├── __init__.py
        ├── conftest.py         # TestClient fixture, stubbed/mocked engine pool
        ├── test_validate_route.py
        ├── test_health_route.py
        └── test_config_route.py
```

`api/app.py` imports `src` the same way `scripts/validate_triples.py` does: `sys.path.insert(0, str(Path(__file__).parent.parent))` — no packaging changes needed.

## Endpoints

### `POST /validate`

Request (`ValidateRequest` in `api/schemas.py`):
```python
class TripleIn(BaseModel):
    assertion_id: Optional[str] = None      # auto "t1","t2",... if omitted
    subject: str
    relation: str
    object: str
    polarity: str = "must_hold"
    rule_type: str = "constraint"

class ValidateRequest(BaseModel):
    document_id: Optional[str] = None       # auto uuid4 hex if omitted
    raw_text: str
    triples: List[TripleIn]                 # min 1
    top_k: int = 5
    embedding_model: Optional[str] = None    # "simple" | "transformer" -> selects pooled engine
    svo_extractor: Optional[str] = None      # "mock" | "transformer" -> selects pooled engine
```
Structured JSON triples (not pipe-delimited strings) — avoids ambiguity if a relation contains `|`.

Response (`ValidateResponse`) mirrors `validate_triples_batch`'s dict field-for-field (see shape above) — `EvidenceOut`, `VerdictOut`, `SummaryOut`, `BackendStatusOut`, `ValidateResponse` composed accordingly. Return the dict directly; `response_model` validates/documents it, no manual conversion needed.

Handler logic:
```python
@router.post("/validate", response_model=ValidateResponse)
async def validate(req: ValidateRequest):
    if not req.raw_text.strip():
        raise HTTPException(400, {"error": "raw_text must not be empty"})
    if not req.triples:
        raise HTTPException(400, {"error": "at least one triple is required"})

    engine = get_engine_for_request(req.embedding_model, req.svo_extractor)  # pool lookup, fallback to default key
    document_id = req.document_id or f"doc_{uuid4().hex[:12]}"
    triples = [
        OntologyAssertion(
            assertion_id=t.assertion_id or f"t{i}",
            subject=t.subject, relation=t.relation, object=t.object,
            polarity=t.polarity, rule_type=t.rule_type,
        )
        for i, t in enumerate(req.triples, 1)
    ]
    try:
        result = await run_in_threadpool(
            engine.validate_triples_batch,
            document_id=document_id, raw_text=req.raw_text,
            triples=triples, top_k=req.top_k,
        )
    except Exception as e:
        logger.exception("validate_triples_batch failed")
        raise HTTPException(500, {"error": "validation_failed", "detail": str(e)})
    return result
```
Use `starlette.concurrency.run_in_threadpool` since the engine is fully synchronous.

### `GET /health`

Wraps `HealthCheckRunner.check_all(config).to_dict()`, run in threadpool (blocking, ~5s/backend). Add a module-level TTL cache (30s) in `api/routes/health.py`: `(timestamp, dict)`, serve cached unless `?force=true` or TTL expired.

```python
class HealthResponse(BaseModel):
    timestamp: str
    overall_status: str            # HEALTHY | DEGRADED | FAILED
    backends: Dict[str, BackendHealthOut]
    recommendations: List[str]
```

### `GET /config`

Read-only introspection: returns `PipelineConfig.to_dict()` (default config) with `neo4j.password` redacted, plus current `backend_status`, plus hardcoded dropdown option lists:
```python
class ConfigResponse(BaseModel):
    backend_mode: str
    sqlite_path: str
    embedding_model_name: str
    svo_extractor_name: str
    validator_name: str
    enable_lm_judge: bool
    enable_lm_classifier: bool
    backend_status: BackendStatusOut
    available_embedding_models: List[str]   # ["simple", "transformer"]
    available_svo_extractors: List[str]     # ["mock", "transformer"]
```
The frontend uses `available_*` lists to populate dropdowns rather than hardcoding them twice.

### CORS + Static mount (`api/app.py`)

```python
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
```

### Engine pool + lifespan (`api/app.py` / `api/dependencies.py`)

```python
ENGINE_POOL: Dict[Tuple[str, str], SVOVerificationEngine] = {}
DEFAULT_CONFIG: PipelineConfig = None
DEFAULT_KEY: Tuple[str, str] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global DEFAULT_CONFIG, DEFAULT_KEY
    DEFAULT_CONFIG = load_config_from_env()
    DEFAULT_KEY = (DEFAULT_CONFIG.embedding_model_name, DEFAULT_CONFIG.svo_extractor_name)
    for emb in ("simple", "transformer"):
        for svo in ("mock", "transformer"):
            cfg = replace(DEFAULT_CONFIG, embedding_model_name=emb, svo_extractor_name=svo)
            try:
                ENGINE_POOL[(emb, svo)] = EngineFactory.create_verification_engine(cfg)
            except Exception:
                logger.exception(f"Failed to build engine for ({emb}, {svo})")
    yield
    ENGINE_POOL.clear()

app = FastAPI(lifespan=lifespan)
```
`get_engine_for_request(embedding_model, svo_extractor)` resolves the requested key (falling back to `DEFAULT_KEY` if a component is `None` or the combo failed to build at startup), raising a clear 500 if even the default is missing.

### Error handling (`api/errors.py`)

```python
@app.exception_handler(HTTPException)
async def http_exc_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

@app.exception_handler(RequestValidationError)   # pydantic 422s
async def validation_exc_handler(request, exc):
    return JSONResponse(status_code=422, content={"error": "invalid_request", "detail": exc.errors()})

@app.exception_handler(Exception)                # catch-all, no stack trace to client
async def unhandled_exc_handler(request, exc):
    logger.exception("Unhandled exception")
    return JSONResponse(status_code=500, content={"error": "internal_error"})
```
Missing subject/relation/object on a triple → automatic 422 via Pydantic. Empty `raw_text`/`triples` → explicit 400 in the handler. Engine exceptions → caught, safe 500.

## Dependencies

New `requirements-api.txt` (repo has no existing `requirements.txt`/`pyproject.toml`):
```
fastapi>=0.110
uvicorn[standard]>=0.29
pydantic>=2.6
httpx>=0.27          # required by FastAPI's TestClient for the new unit tests
```

Run: `uvicorn api.app:app --reload --port 8000` from repo root.

## Unit Tests (new — no API tests exist currently)

`tests/api/` did not exist prior to this plan (confirmed: `tests/` currently only has `conftest.py`, `test_integration.py`, `test_evidence_judge.py`, `test_concept_extractor.py`, and an `integration/` subfolder — nothing API-related). Add tests alongside each route as it's implemented, using FastAPI's `TestClient` (`from fastapi.testclient import TestClient`).

`tests/api/conftest.py`:
- A `client` fixture wrapping `TestClient(app)`.
- Since the real engine pool build (step 2 of Sequenced Implementation Steps) can load heavy transformer models, tests should **override the engine pool via dependency injection** rather than running the real `lifespan`: monkeypatch `ENGINE_POOL`/`DEFAULT_CONFIG` in `api/dependencies.py` with a small fake `SVOVerificationEngine`-like stub (or a `unittest.mock.MagicMock` with `validate_triples_batch` returning a canned dict matching the shape in `src/engine.py`) before the app starts, or use FastAPI's `app.dependency_overrides` if `get_engine_for_request` is exposed as a `Depends(...)` callable (recommended — refactor `dependencies.py` so route handlers receive the engine via `Depends`, not by importing the pool directly, purely so it's overridable in tests without touching production code paths).

`tests/api/test_validate_route.py`:
- Happy path: POST with valid `raw_text` + 2 triples, mock engine returns a canned `validate_triples_batch` dict; assert 200 and response body matches `ValidateResponse` shape field-for-field.
- Empty `raw_text` → assert 400 with `{"error": "raw_text must not be empty"}`.
- Empty `triples` list → assert 400.
- Triple missing a required field (e.g. only `subject`) → assert 422 (Pydantic validation, no custom handler logic needed to test beyond the global handler shape).
- Engine raises an exception (mock `side_effect=RuntimeError(...)`) → assert 500 with `{"error": "validation_failed", "detail": ...}` and no raw traceback leaked in the body.
- `embedding_model`/`svo_extractor` overrides select the correct pooled engine — assert the mock corresponding to the requested key was the one invoked (e.g. via separate mocks per pool key and asserting call counts).
- Default `document_id`/`assertion_id` auto-generation when omitted — assert generated IDs are present and well-formed (`doc_` prefix / `t1`, `t2`, ...).

`tests/api/test_health_route.py`:
- Mock `HealthCheckRunner.check_all` to avoid real network calls; assert response shape matches `HealthResponse`.
- Assert second call within TTL window returns cached result (mock call count stays at 1).
- Assert `?force=true` bypasses cache (mock call count increments).

`tests/api/test_config_route.py`:
- Assert response includes `available_embedding_models`/`available_svo_extractors` lists with expected values.
- Assert `neo4j.password` (or equivalent secret field) is redacted/absent from the response body.

Run via: `python -m pytest tests/api/ -v` (mirrors the existing `python -m pytest tests/test_integration.py -v` convention already documented in the root README).

## Frontend

**Static HTML + vanilla JS + fetch(), no build step, no framework.** Justified by small UI surface (one form, one results view) and no existing frontend tooling in the repo.

### Layout (`frontend/index.html`)

```
┌─────────────────────────────────────────────────────────┐
│  SVO Triple Verifier                    [Settings ⚙]    │
├─────────────────────────────────────────────────────────┤
│  Document Text                                           │
│  ┌───────────────────────────────────────────────────┐  │
│  │ <textarea, placeholder "Paste document...">        │  │
│  └───────────────────────────────────────────────────┘  │
│                                                           │
│  Triples to Validate                        [+ Add Row] │
│  ┌───────────┬───────────┬───────────┬───────┐          │
│  │ Subject   │ Relation  │ Object    │ [x]   │          │
│  └───────────┴───────────┴───────────┴───────┘          │
│                                                           │
│  Settings (collapsible): Embedding model ▾  SVO extractor ▾  Top K [5]│
│                                                           │
│              [ Validate Triples ]                        │
├─────────────────────────────────────────────────────────┤
│  RESULTS (hidden until first submit)                      │
│  Summary: Total 4 | Supported 2 | Contradicted 1 |        │
│           Partial 1 | Unknown 0 | Avg score 0.62          │
│  ── Verdict card per triple ──                            │
│  [supported ●] subject relation object     score 0.87     │
│  Rationale: "..."                                          │
│  ▸ Evidence (3 chunks) [expand] — chunk_id, source,        │
│    confidence, matched flags, text                        │
└─────────────────────────────────────────────────────────┘
```

### UI states (`frontend/app.js`)

1. **Idle** — form visible, results hidden, submit enabled.
2. **Loading** — submit disabled + spinner/"Validating…" (can be slow with transformer models), guard against duplicate submits via an `isSubmitting` flag.
3. **Results** — summary dashboard + verdict cards; color-code label: supported=green, contradicted=red, partial=amber, unknown=gray. Evidence collapsed by default (`<details>` per evidence item).
4. **Error** — dismissible banner showing `error`/`detail` from the API's JSON error body; does not clear entered form data.

### JS responsibilities

- Dynamic add/remove triple rows.
- Client-side validation: reject fully-empty rows, require subject/relation/object non-blank.
- On load: `fetch('/config')` to populate dropdown options from `available_embedding_models`/`available_svo_extractors` (no hardcoding).
- On submit: build `ValidateRequest` JSON, `fetch('/validate', {method:'POST', ...})`, render response or error.
- Since same-origin (StaticFiles mount), use relative paths (`/validate`, `/config`, `/health`) — no `API_BASE` constant needed.

## Sequenced Implementation Steps

1. Scaffold `api/__init__.py`, `api/schemas.py`, `requirements-api.txt`, and `tests/api/__init__.py` + `tests/api/conftest.py` (fixture + dependency-override scaffolding, even before routes exist).
2. `api/dependencies.py` — eager engine pool + lifespan wiring, exposed as an overridable `Depends(...)` callable.
3. `api/routes/validate.py` — per spec above, alongside `tests/api/test_validate_route.py`.
4. `api/routes/health.py` — TTL-cached wrapper, alongside `tests/api/test_health_route.py`.
5. `api/routes/config.py` — redacted config + dropdown option lists, alongside `tests/api/test_config_route.py`.
6. `api/app.py` — wire routers, CORS, `api/errors.py` handlers, `StaticFiles` mount.
7. Run `python -m pytest tests/api/ -v` — all unit tests green before moving to manual/frontend work.
8. Backend smoke test (see Verification) with a real running server before building frontend.
9. `frontend/index.html` + `styles.css` (static layout first).
10. `frontend/app.js` (fetch logic, dynamic rows, rendering, state handling).
11. End-to-end browser test (see Verification).
12. Short `api/README.md` or root README section: how to run, `ONTO_*` env vars (note `.env.example` staleness), example curl calls, and how to run `tests/api/`.

## Verification

### Backend (curl)

```bash
curl http://localhost:8000/config
curl http://localhost:8000/health
curl "http://localhost:8000/health?force=true"

curl -X POST http://localhost:8000/validate \
  -H "Content-Type: application/json" \
  -d '{
    "raw_text": "The engine drives the wheel. The wheel does not stop the car.",
    "triples": [
      {"subject": "engine", "relation": "drives", "object": "wheel"},
      {"subject": "wheel", "relation": "stops", "object": "car"}
    ],
    "top_k": 5
  }'

# Error cases
curl -X POST http://localhost:8000/validate -H "Content-Type: application/json" -d '{"raw_text": "", "triples": []}'
# expect 400

curl -X POST http://localhost:8000/validate -H "Content-Type: application/json" -d '{"raw_text": "text", "triples": [{"subject": "a"}]}'
# expect 422 (missing relation/object)
```
Cross-check one response against the field list in `src/engine.py` (lines ~514-560) to confirm no silent field drops.

### Frontend (browser)

1. Run `uvicorn api.app:app --reload --port 8000`, open `http://localhost:8000/`.
2. Confirm settings dropdowns populate from `/config` (check Network tab).
3. Paste sample text, add/remove a few triple rows, submit.
4. Confirm loading state, then results render; verify `supported + contradicted + partial + unknown == total_triples`.
5. Expand an evidence chunk, confirm fields render without console errors.
6. Submit with empty text — confirm 400 error banner shows without clearing entered rows.
7. Submit with a triple missing a field — confirm 422 handled gracefully in the UI.
