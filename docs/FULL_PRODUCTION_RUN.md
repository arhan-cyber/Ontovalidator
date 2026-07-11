# Running the Full Pipeline: Real Backends, Real Transformer Models, API + Frontend

This document describes how to run OntoValidator end-to-end with no mock components:
real Elasticsearch (lexical), real Milvus (semantic), real Neo4j (graph), transformer
models throughout (embedding, SVO extraction, concept extraction, validation, evidence
classification, evidence judging), the FastAPI backend, and the frontend.

**Note:** `docs/PRODUCTION_DEPLOYMENT.md` and `.env.example` at the repo root use env
var names (`ELASTICSEARCH_ENABLED`, `NEO4J_URI`, `SQLITE_DB_PATH`, etc.) that do not
match what `src/config.py` actually reads. Do not use them as a source of truth — this
document was verified directly against `src/config.py` and `src/factories.py`.

## 1. Install dependencies

```bash
pip install -r requirements-api.txt -r requirements-ml.txt
pip install elasticsearch neo4j pymilvus sentencepiece
```

`elasticsearch`, `neo4j`, and `pymilvus` are imported directly in `src/helpers/` but are
not listed in any `requirements*.txt` — they must be installed separately. `sentencepiece`
is required by the Flan-T5 tokenizer used for SVO/concept extraction
(`TransformerSVOExtractor`, `TransformerConceptExtractor`); without it those two
extractors will silently fall back to their mock implementations.

## 2. Start backend services

`docker-compose.yml` at the repo root only defines Neo4j and Elasticsearch — **it does
not define Milvus** (a real standalone Milvus deployment also needs etcd + minio
sidecars, which aren't in this repo's compose file either).

```bash
docker-compose up -d   # starts Neo4j (bolt://localhost:7687, neo4j/password)
                        # and Elasticsearch (http://localhost:9200)
```

For Milvus, you have two options:

- **Milvus Lite (embedded, no server to run)**: leave `ONTO_MILVUS_HOST=localhost`.
  `src/helpers/milvus.py` special-cases `localhost` to connect to an embedded
  local-file vector database (`./milvus_demo.db` by default, or `$MILVUS_URI`) instead
  of a network server. This is a real, non-mocked Milvus client — just not a server
  process.
- **Real Milvus server**: stand up Milvus + etcd + minio yourself (add to
  `docker-compose.yml` or run separately), then set `ONTO_MILVUS_HOST` to that host —
  anything other than `localhost` triggers a real gRPC connection on port 19530.

## 3. Environment variables

All verified against `src/config.py::PipelineConfig.load_from_env()`.

```bash
# Backend mode / enforcement
export ONTO_BACKEND_MODE=production
export ONTO_USE_PRODUCTION_BACKENDS=true
export ONTO_REQUIRE_PRODUCTION_BACKENDS=true   # hard-fails engine construction if no
                                                # backend is enabled

# Elasticsearch
export ONTO_ES_ENABLED=true
export ONTO_ES_HOST=localhost
export ONTO_ES_PORT=9200
export ONTO_ES_INDEX=svo_chunks

# Milvus
export ONTO_MILVUS_ENABLED=true
export ONTO_MILVUS_HOST=<your-milvus-host>     # NOT "localhost" if you want a real
                                                # server rather than Milvus Lite
export ONTO_MILVUS_PORT=19530
export ONTO_MILVUS_COLLECTION=svo_embeddings
export ONTO_MILVUS_DIM=768                     # see caveat below — must match the
                                                # embedding model's output dimension

# Neo4j
export ONTO_NEO4J_ENABLED=true
export ONTO_NEO4J_URI=bolt://localhost:7687
export ONTO_NEO4J_USER=neo4j
export ONTO_NEO4J_PASSWORD=password

# Models — "transformer"/"nli" instead of the mock/heuristic defaults
export ONTO_EMBEDDING_MODEL=transformer                 # default: "simple"
export ONTO_SVO_EXTRACTOR=transformer                    # default: "mock"
export ONTO_CONCEPT_EXTRACTOR=transformer                # default: "mock"
export ONTO_CONCEPT_EXTRACTOR_MODEL=google/flan-t5-large # optional override
export ONTO_VALIDATOR=transformer                        # default: "minimal"
export ONTO_EVIDENCE_SPAN_CLASSIFIER=nli                  # default: "heuristic"
export ONTO_EVIDENCE_SPAN_CLASSIFIER_MODEL=typeform/distilbert-base-uncased-mnli  # optional

# LM evidence judge (second-pass adjudication)
export ONTO_ENABLE_LM_JUDGE=true                          # default: false (HeuristicEvidenceJudge)
export ONTO_JUDGE_MODEL=typeform/distilbert-base-uncased-mnli

# Logging/diagnostics — needed to confirm nothing silently fell back to mocks (see §5)
export ONTO_VERBOSE=true
export ONTO_LOG_BACKEND_USAGE=true
```

### Caveat: embedding dimension mismatch

`ONTO_MILVUS_DIM` defaults to 384, but `TransformerEmbeddingModel` (DistilBERT-based)
outputs 768-dim vectors. If you set `ONTO_EMBEDDING_MODEL=transformer` you must also set
`ONTO_MILVUS_DIM=768`, or Milvus writes will fail on dimension mismatch.

### Default HuggingFace models used by each "transformer"/"nli" component

| Config field | Default model when set to non-mock |
|---|---|
| `embedding_model_name=transformer` | `distilbert-base-uncased` |
| `svo_extractor_name=transformer` | `google/flan-t5-small` |
| `concept_extractor_name=transformer` | `google/flan-t5-large` |
| `validator_name=transformer` | `typeform/distilbert-base-uncased-mnli` |
| `evidence_span_classifier_name=nli` | `typeform/distilbert-base-uncased-mnli` |
| LM evidence judge (`enable_lm_judge`) | `typeform/distilbert-base-uncased-mnli` |

## 4. Run the API (also serves the frontend)

```bash
uvicorn api.app:app --port 8000
```

The frontend (`frontend/`) is plain HTML/JS with no build step and no separate dev
server — `api/app.py` mounts the `frontend/` directory as static files at `/`, so
`http://localhost:8000/` *is* the frontend, served by the same process as the API.

`api/dependencies.py` eagerly builds an engine for every combination of
`embedding_model` × `svo_extractor` in `{simple, transformer} × {mock, transformer}`
(4 engines total) from your env config at startup. Only those two fields are
overridable per-request in the `/validate` request body (`embedding_model`,
`svo_extractor`); every other component (concept extractor, validator, evidence
classifier, judge) is fixed at process startup from the environment variables above —
changing them requires restarting `uvicorn`.

## 5. Verify nothing silently fell back to a mock

Every "transformer"/"nli" factory method in `src/factories.py` wraps model
construction in a try/except and **silently degrades to the mock/heuristic
implementation on any failure** (missing dependency, OOM, network error downloading
weights, etc.) — there is no hard-fail for model loading, only for backend
connectivity (`ONTO_REQUIRE_PRODUCTION_BACKENDS`). There is no dedicated flag that
reports model-loading success; you must check the startup logs.

```bash
uvicorn api.app:app --port 8000 2>&1 | tee startup.log
grep -Ei "using (transformer|nli)|failed to create|falling back" startup.log
```

Look for lines like `Using TransformerEmbeddingModel`, `Using TransformerSVOExtractor`,
`Using NLIEvidenceSpanClassifier`, `LM evidence judge enabled` — and the absence of any
`Falling back to ...` lines.

Separately, confirm backend connectivity:

```bash
python scripts/health_check.py --all
curl localhost:8000/config   # resolved config + backend_status (which store each
                              # retrieval channel — lexical/semantic/graph — is using)
```

Note: `scripts/health_check.py`'s Milvus check does not replicate the `localhost` →
Milvus Lite special-casing in `src/helpers/milvus.py` — a "HEALTHY" Milvus result with
`ONTO_MILVUS_HOST=localhost` does not by itself prove you're talking to a real network
Milvus server; only a non-`localhost` host guarantees that, per the engine's actual
client code.

## Summary checklist

- [ ] `pip install -r requirements-api.txt -r requirements-ml.txt elasticsearch neo4j pymilvus sentencepiece`
- [ ] `docker-compose up -d` (Neo4j + Elasticsearch); Milvus server set up separately if not using Milvus Lite
- [ ] All `ONTO_*_ENABLED=true`, model fields set to `transformer`/`nli`, `ONTO_ENABLE_LM_JUDGE=true`
- [ ] `ONTO_MILVUS_DIM=768` if `ONTO_EMBEDDING_MODEL=transformer`
- [ ] `ONTO_VERBOSE=true ONTO_LOG_BACKEND_USAGE=true` set before starting `uvicorn`
- [ ] `uvicorn api.app:app --port 8000`, then grep startup logs for `Using transformer/nli`, not `Falling back`
- [ ] `python scripts/health_check.py --all` and `curl localhost:8000/config` to confirm backend connectivity
