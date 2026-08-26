# SVO Verification Pipeline

A modular system for validating Subject-Verb-Object (SVO) triples against source documents, using multi-modal retrieval, score fusion, and LLM-assisted adjudication. Includes a FastAPI backend and a React frontend with an adjustable trace-detail view.

## What it does

Given a raw document and a set of SVO triples, the pipeline:

1. **Ingests** the document (chunks it, embeds each chunk, extracts SVOs and concepts).
2. **Retrieves** relevant evidence via three retrievers — lexical, semantic, graph — gated by a query router (`MoERouter`).
3. **Fuses** the three retrievers' scores into one ranked list.
4. **Adjudicates** each triple against the retrieved evidence, with an LM judge available for uncertain/conflicting cases.
5. **Returns**, per triple: a label (`supported` / `contradicted` / `partial` / `unknown`), a 0–1 confidence score, the evidence chunks with retrieval provenance, and a human-readable rationale.

```python
result = engine.validate_triples_batch(
    document_id="my_paper",
    raw_text="Aspirin treats headache. Aspirin reduces fever. It does not treat malaria.",
    triples=[
        OntologyAssertion(assertion_id="t1", subject="Aspirin", relation="treats", object="headache"),
        OntologyAssertion(assertion_id="t2", subject="Aspirin", relation="treats", object="malaria"),
    ],
)
# t1: label="supported",    score=0.95
# t2: label="contradicted", score=0.90
```

## Quick start

### Install

```bash
pip install -r requirements-api.txt -r requirements-ml.txt
# Optional, only if you're enabling real Elasticsearch/Neo4j/Milvus backends:
pip install -r requirements-production.txt
```

Copy `.env.example` to `.env` and adjust — every variable there maps directly to a field `PipelineConfig.load_from_env()` reads in `src/config.py`, which is the source of truth if the two ever drift.

### CLI

```bash
python scripts/validate_triples.py \
  --text "Aspirin treats headache and reduces fever." \
  --triple "Aspirin|treats|headache" \
  --triple "Aspirin|treats|malaria" \
  --top-k 5
```

### HTTP API + frontend

```bash
uvicorn api.app:app --host 0.0.0.0 --port 8000
```

`POST /api/validate` takes `{document_id, raw_text, triples, top_k}` and returns the same verdict shape as the Python API below. See `docs/FULL_PRODUCTION_RUN.md` for a fully-verified walkthrough with real backends and transformer models end to end.

The React SPA (`frontend/`) is a separate build — see `frontend/README.md` for setup. Once built (`npm run build`), `api/app.py` serves it directly from `frontend/dist/`, so `GET /` gives you the full UI, including a trace-detail toggle (Verdict → Summary → Detailed → Full trace) for controlling how much of each verdict's retrieval/scoring internals are shown.

### Python API

```python
from src.engine import SVOVerificationEngine
from src.routing import MoERouter
from src.retrieval import SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever
from src.fusion import WeightedFusionEngine
from src.storage import SQLiteChunkStore
from src.validation import MinimalValidator
from src.models import OntologyAssertion

engine = SVOVerificationEngine(
    router=MoERouter(),
    lexical_store=SQLiteLexicalRetriever("svo_data.db"),
    semantic_store=SQLiteSemanticRetriever("svo_data.db"),
    graph_store=SQLiteGraphRetriever("svo_data.db"),
    fusion_engine=WeightedFusionEngine(),
    chunk_store=SQLiteChunkStore("svo_data.db"),
    validator=MinimalValidator(),
)

result = engine.validate_triples_batch(
    document_id="doc1",
    raw_text="Aspirin treats headache. Aspirin reduces fever.",
    triples=[
        OntologyAssertion(assertion_id="t1", subject="Aspirin", relation="treats", object="headache"),
        OntologyAssertion(assertion_id="t2", subject="Aspirin", relation="reduces", object="fever"),
    ],
    top_k=5,
)

for verdict in result["verdicts"]:
    print(f"{verdict['subject']} {verdict['relation']} {verdict['object']}")
    print(f"  {verdict['label']} (score {verdict['score']:.3f}): {verdict['rationale']}")
```

Prefer `SVOVerificationEngine.from_config(PipelineConfig(...))` over constructing every component by hand — see `src/factories.py`.

## Architecture

```
INGESTION: Document -> Chunks -> Embeddings -> SVOs/concepts -> SQLite (+ ES/Milvus/Neo4j)
    |
ROUTING: MoERouter classifies the query, gates which of the 3 retrievers run
    |
    +-------------+-------------+
    |             |             |
 LEXICAL      SEMANTIC        GRAPH
    |             |             |
    +-------------+-------------+
    |
FUSION: 0.3*lexical + 0.5*semantic + 0.2*graph, +0.1 per corroborating source
    |
MATERIALIZATION: load full chunk content for the fused top-k
    |
ADJUDICATION: classify each chunk as supports/refutes/partial/unknown for the triple,
              LM judge resolves uncertain/conflicting cases
    |
VERDICT: score + label + rationale + evidence
```

Full Mermaid diagram: `pipeline_wireframe.md`.

### The three retrievers

Each has a SQLite-backed "demo tier" (zero external dependencies) and a production-backend tier:

| Retriever | Demo tier (SQLite) | Production tier |
|---|---|---|
| Lexical | Token-overlap count | Elasticsearch (BM25) |
| Semantic | Jaccard similarity on token sets | Milvus (dense vector ANN) |
| Graph | BFS over `provides`/`depends_on` concept edges, 0.8 decay/hop, 3-hop limit | Neo4j (Cypher multi-hop) |

The demo tier's "semantic" retriever is lexical (Jaccard on tokens), not embedding-based — it won't catch paraphrases the way the production Milvus tier will. Retrieval is scoped to one `document_id` at a time; only the corpus-wide `verify_with_ontology` API intentionally searches across all ingested documents.

### Model tiers

`ONTO_EMBEDDING_MODEL` / `ONTO_SVO_EXTRACTOR` / `ONTO_CONCEPT_EXTRACTOR` each select between a zero-dependency mock/heuristic implementation and a transformer-backed one (DistilBERT for embeddings, flan-t5 for SVO/concept extraction, few-shot prompted). `TransformerSVOExtractor` falls back to the heuristic extractor whenever the model's output doesn't parse into a clean triple, so it's never silently empty-handed.

## Project structure

```
Ontovalidator/
├── src/                   # Core library
│   ├── engine.py          # SVOVerificationEngine - main orchestrator
│   ├── factories.py       # EngineFactory - builds an engine from PipelineConfig
│   ├── config.py          # PipelineConfig, env var loading
│   ├── routing/           # MoERouter (query -> which retrievers to run)
│   ├── retrieval/         # Lexical / semantic / graph retrievers + fusion
│   ├── fusion/             # WeightedFusionEngine
│   ├── storage/           # SQLiteChunkStore, shared sqlite connection helper
│   ├── validation/         # MinimalValidator, TransformerValidator
│   ├── ingestion/         # Chunking, embedding, SVO/concept extraction
│   ├── classification/    # Evidence-span classifiers, evidence judges
│   ├── cache/              # Embedding/retrieval/verdict caching
│   ├── feedback/           # Correction recording + analysis
│   ├── ontology/           # Enterprise-ontology compliance (conformance + grounding)
│   └── helpers/            # Elasticsearch/Milvus/Neo4j client helpers
├── api/                    # FastAPI app (routes, schemas, dependency-injected engine pool)
├── frontend/                # React SPA (see frontend/README.md)
├── scripts/                 # CLI entry points
│   └── diagnostics/         # Ad hoc diagnostic scripts (not the pytest suite)
├── tests/                   # pytest suite (tests/api/, tests/integration/)
├── docs/                    # Living reference docs (ENHANCEMENTS.md, FULL_PRODUCTION_RUN.md, ONTOLOGY_COMPLIANCE.md)
├── archive/                  # Superseded code and historical planning docs, kept for reference
├── ASSUMPTIONS/              # Documented design assumptions and reasoning tradeoffs
├── examples/                 # Sample input documents
└── docker-compose.yml         # Neo4j + Elasticsearch (no Milvus - see docs/FULL_PRODUCTION_RUN.md)
```

## Ontology compliance

Beyond validating loose SVO triples, the pipeline can validate a whole
**enterprise ontology** on two independent axes:

* **structural conformance** — does the ontology obey its meta-model? (meta-class
  schemas, the edge grammar, the ONT-000..ONT-013 systemic rules)
* **evidential grounding** — do the source process documents support the claims
  it makes? (reuses the retrieval + adjudication engine, with PDF ingestion)

```bash
# Conformance only: no corpus, no models, ~50ms.
python scripts/validate_ontology.py --plane a

# Both planes against a directory of PDFs.
python scripts/validate_ontology.py --documents Documents/ --out report.json

# Adjudicate meta-model-vs-ontology disagreements interactively.
python scripts/validate_ontology.py --plane a --review
```

The two planes are reported separately and never averaged — "conformant but
contradicted by the process manual" is the finding worth surfacing, and a
combined score is exactly what would hide it.

Disagreements between the blueprint and the ontology go to a persistent
adjudication queue (`conflicts.db`) rather than being silently counted as
errors, because some of them are blueprint gaps rather than ontology defects.
Rulings are idempotent across runs.

**Grounding currently needs production backends to be meaningful** — on the
SQLite demo tier `supported` is unreachable by construction, and the report
says so itself (`grounding.confidence: low`). See
`docs/ONTOLOGY_COMPLIANCE.md` for why, and `docs/ONTOLOGY_COMPLIANCE_PLAN.md`
for the design and decision log.

## Configuration

All configuration is environment-variable driven (`ONTO_*` prefix) — see `.env.example` for the common ones and `src/config.py`'s `load_from_env()` for the complete, authoritative list. Key ones:

| Variable | Values | Effect |
|---|---|---|
| `ONTO_BACKEND_MODE` | `demo` / `production` / `auto` | Whether to use SQLite-only or real backends |
| `ONTO_EMBEDDING_MODEL` | `simple` / `transformer` | 5-dim hash vs. DistilBERT |
| `ONTO_SVO_EXTRACTOR` | `mock` / `transformer` | Verb-phrase heuristic vs. few-shot flan-t5 |
| `ONTO_ENABLE_QUERY_ROUTING` | `true` / `false` | Whether the router actually gates retrievers, or all 3 always run |
| `ONTO_ENABLE_LM_JUDGE` | `true` / `false` | Whether an LM judge can override the heuristic verdict on uncertain evidence |

## Documentation

| Doc | Purpose |
|---|---|
| `README.md` | This file — overview and quick start |
| `TODO.md` | Living roadmap — what's done, what's deferred, and why |
| `pipeline_wireframe.md` | Pipeline stages as a Mermaid diagram |
| `docs/FULL_PRODUCTION_RUN.md` | Verified end-to-end guide with real backends and transformer models |
| `docs/ENHANCEMENTS.md` | Reference for the shipped observability/scoring enhancements |
| `frontend/README.md` | Frontend setup, build, and the trace-detail toggle |
| `scripts/README_validate_with_config.md` | Remote-server CLI workflow for configurable-tier validation |
| `ASSUMPTIONS/` | Documented design assumptions and LM-reasoning tradeoffs |
| `archive/` | Superseded code and completed implementation plans, kept for historical reference |

## Testing

```bash
pytest tests/ -q
```

`tests/api/` covers FastAPI routes against a stubbed engine pool; `tests/integration/` builds a real `SVOVerificationEngine`/`EngineFactory` end to end; the rest of `tests/` covers individual components in isolation.

## Contributing

1. Branch from `main`.
2. Make your changes; add tests alongside them.
3. Run `pytest tests/ -q` before committing.
4. Open a PR with a clear description of the change and why.

## License

Provided as-is for research and development purposes.
