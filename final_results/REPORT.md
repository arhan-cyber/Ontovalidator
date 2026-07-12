# OntoValidator — Full-Model Run Report

**Date:** 2026-07-12
**Purpose:** Document a real run of the SVO verification pipeline with every model
component switched from its mock/heuristic default to its real transformer/NLI/LM
implementation, confirm nothing silently fell back to a mock, and capture what the
pipeline actually does end-to-end on real requests.

All raw artifacts referenced below live alongside this file in `final_results/`.

## 1. How it was run

```bash
ONTO_VERBOSE=true ONTO_LOG_BACKEND_USAGE=true \
ONTO_EMBEDDING_MODEL=transformer \
ONTO_SVO_EXTRACTOR=transformer \
ONTO_CONCEPT_EXTRACTOR=transformer \
ONTO_VALIDATOR=transformer \
ONTO_EVIDENCE_SPAN_CLASSIFIER=nli \
ONTO_ENABLE_LM_JUDGE=true \
ONTO_SQLITE_PATH=final_results/onto_run.db \
uvicorn api.app:app --port 8010
```

This is the SQLite-backend configuration from `docs/FULL_PRODUCTION_RUN.md` (no
Elasticsearch/Milvus/Neo4j — those were left disabled, so this run exercises the
default single-database backend, with every *model* component real). Server log:
[`uvicorn.log`](uvicorn.log). Database produced: [`onto_run.db`](onto_run.db).

## 2. What loaded at startup

`api/dependencies.py` eagerly builds **4 engines** at startup — the full cross
product of `embedding_model ∈ {simple, transformer} × svo_extractor ∈ {mock,
transformer}` — because only those two fields are overridable per-request via the
`/validate` body. All other components (concept extractor, validator, evidence
classifier, judge) are fixed once from the environment. This means `flan-t5-large`
and `distilbert-base-uncased-mnli` each got downloaded/loaded **4 times** at startup
(once per engine build), which is most of the ~44s startup time.

Confirmed component resolution per engine build (grep of `uvicorn.log` for
`Using ...` / `Falling back` / `Failed to create`):

| Engine (embedding × svo) | Embedding | SVO extractor | Validator | Evidence classifier | Judge |
|---|---|---|---|---|---|
| simple × mock | SimpleEmbeddingModel | MockSVOExtractor | TransformerValidator | NLIEvidenceSpanClassifier | Few-shot LM judge |
| simple × transformer | SimpleEmbeddingModel | TransformerSVOExtractor | TransformerValidator | NLIEvidenceSpanClassifier | Few-shot LM judge |
| transformer × mock | TransformerEmbeddingModel | MockSVOExtractor | TransformerValidator | NLIEvidenceSpanClassifier | Few-shot LM judge |
| **transformer × transformer (default, used below)** | TransformerEmbeddingModel | TransformerSVOExtractor | TransformerValidator | NLIEvidenceSpanClassifier | Few-shot LM judge |

**No `Falling back to ...` or `Failed to create ...` lines appear anywhere in the
log** — every requested transformer/NLI component loaded successfully; none
silently degraded to its mock/heuristic counterpart.

Backend status (all three retrieval channels, for every engine): all `SQLite*`
(`SQLiteLexicalRetriever`, `SQLiteSemanticRetriever`, `SQLiteGraphRetriever`) — expected,
since ES/Milvus/Neo4j were left disabled.

`GET /config` → [`config_response.json`](config_response.json):
```json
{
  "backend_mode": "auto",
  "embedding_model_name": "transformer",
  "svo_extractor_name": "transformer",
  "validator_name": "transformer",
  "enable_lm_judge": true,
  "enable_lm_classifier": false,
  "backend_status": {"lexical": "SQLiteLexicalRetriever", "semantic": "SQLiteSemanticRetriever", "graph": "SQLiteGraphRetriever"}
}
```

`GET /health` → [`health_response.json`](health_response.json): `overall_status:
DEGRADED` — this is expected/correct, not a bug: ES/Milvus/Neo4j report
`"Disabled in configuration"` (they weren't turned on for this run) and only
`sqlite` reports healthy.

## 3. What happens on each request (`POST /validate`)

Per request, `SVOVerificationEngine.validate_triples_batch` does NOT reuse the
engine's cached models for the concept extractor — it reconstructs
`TransformerConceptExtractor(google/flan-t5-large)` **fresh, from scratch, on every
single call** (`src/engine.py:436-449`). The log shows the full HuggingFace
tokenizer/config HEAD-request sequence and weight-loading repeating on every
`/validate` call, not just at startup. This is why each request below took
**~10-12 seconds** even on a 3-sentence document with only 2-4 triples — most of
that time is re-loading flan-t5-large, not doing the actual retrieval/validation
work. This is the single biggest performance finding of this run: concept-extractor
construction should be cached on the engine/pool, not done per-request.

Pipeline stages observed per request (from `uvicorn.log`):
1. Chunk the document (sentence-level chunks).
2. Embed chunks with `TransformerEmbeddingModel` (real DistilBERT vectors — computed
   but, per the SQLite backend, only ever written to the (disabled) Milvus store, so
   in this run they're computed and then discarded; semantic retrieval below is
   Jaccard token overlap on raw text, not vector search).
3. Run `TransformerSVOExtractor.extract()` per chunk — **returned 0 SVO triples on
   all 3 documents run** (see §4, a real limitation, not a config problem).
4. Run `TransformerConceptExtractor.extract_concepts_batch()` — this **did**
   produce real, non-empty concepts per chunk (verified directly against
   `onto_run.db`, see §5) — populates `chunk.metadata["provides"/"depends_on"]`,
   which is what the graph retriever's concept-BFS walks.
5. Write to SQLite (real) + mock/no-op writes to Elasticsearch/Milvus/Neo4j (all
   disabled, so these are expected no-ops, logged as `[!] ... write failed/skipped`).
6. For each triple: query all three retrievers (lexical, semantic, graph) → fuse →
   per-chunk NLI evidence classification → heuristic verdict → few-shot LM judge
   verdict → merge into final label/score/rationale.

## 4. SVO extraction returned 0 triples — a real limitation

Every one of the 3 ingested documents logged `Extracted 0 SVO relations and
concepts.` even though `TransformerSVOExtractor` (flan-t5-small) loaded and ran
successfully (confirmed via `Using configured SVO extractor: TransformerSVOExtractor`
in the log — not a fallback). The automatic SVO extractor is simply not producing
usable output on plain declarative sentences in this run. Because the `/validate`
API takes triples explicitly in the request body, this doesn't break validation
itself (the triples we asked about were validated fine) — but it means the
"extract triples automatically from text" half of the pipeline is not currently
functioning with the transformer extractor, at least not on inputs like these.
Worth a follow-up investigation into `TransformerSVOExtractor`'s prompt/parsing
(`src/ingestion/extractors.py`).

## 5. Concept extraction and graph retrieval — confirmed working

Directly querying `onto_run.db` after ingestion (not from the API) confirms
`TransformerConceptExtractor` produced real, document-specific concepts, e.g. for
the hash-table document:

| chunk | provides | depends_on |
|---|---|---|
| "A hash table is a data structure..." | `hash table` | `hash table` |
| "A Python dictionary is implemented... using a hash table..." | `dictionary`, `hash table` | `python`, `hash table` |
| "Caching systems...store...in a Python dictionary..." | `caching system`, `python` | `caching`, `python`, `dictionary` |

The shared `hash table` / `dictionary` / `python` concept keys are exactly what lets
`SQLiteGraphRetriever` multi-hop from a query about hash tables into the third
sentence about caching systems, even though that sentence shares no literal query
words — this is the mechanism the pre-existing diagnostic script (`remote server
scripts/verbose_pipeline_trace.py`) documents in detail.

## 6. Sample validation runs

Three requests were sent, chosen to exercise all four verdict labels
(`supported`/`contradicted`/`partial`/`unknown`). Full request/response JSON for
each is saved alongside this report.

### Run 1 — Aspirin document (mixed true/false claims)
[`validate_request_1_aspirin.json`](validate_request_1_aspirin.json) /
[`validate_response_1_aspirin.json`](validate_response_1_aspirin.json) — 12.2s wall time.

| Triple | Label | Score | Note |
|---|---|---|---|
| Aspirin treats headache | **supported** | 0.954 | Heuristic and LM judge agree |
| Aspirin treats malaria | **contradicted** | 0.939 | Explicit negation in text, correctly caught |
| Ibuprofen reduces fever | **contradicted** | 0.893 | ⚠️ Heuristic said *supported* (literal word overlap with the aspirin/fever sentence); the LM judge overrode it to *contradicted*. The document never states or negates this — arguably the correct label is `unknown`, not `contradicted`. |
| Aspirin cures diabetes | **contradicted** | 0.838 | ⚠️ Heuristic correctly said "insufficient evidence" (→ would be `unknown`); LM judge overrode to *contradicted* even though diabetes is never mentioned. |

**Observation:** the few-shot LM judge shows a bias toward `contradicted` when
evidence is merely absent/irrelevant rather than actually contradictory — it
overrode two heuristic verdicts that should plausibly have stayed `unknown`. Worth
checking `FewShotPromptEvidenceJudge`'s few-shot examples for label balance.

### Run 2 — Hash table document (multi-hop concept-graph probe)
[`validate_request_2_hashtable_multihop.json`](validate_request_2_hashtable_multihop.json) /
[`validate_response_2_hashtable_multihop.json`](validate_response_2_hashtable_multihop.json) — 10.2s wall time.

| Triple | Label | Score |
|---|---|---|
| hash table → required for → constant-time lookup | supported | 0.750 |
| caching systems → depends on → hash function | supported | 0.630 |

Both triples retrieved all 3 chunks (document only has 3), including the
caching-systems sentence for the hash-table query and vice versa — consistent with
the concept-graph linking confirmed in §5.

### Run 3 — Climate document (designed to hit `unknown`)
[`validate_request_3_climate_unknown.json`](validate_request_3_climate_unknown.json) /
[`validate_response_3_climate_unknown.json`](validate_response_3_climate_unknown.json) — 9.9s wall time.

| Triple | Label | Score |
|---|---|---|
| quantum computers → solve → climate change | **unknown** | — |
| renewable energy → offsets → emissions | supported | — |

Confirms `unknown` is reachable when the subject/object literally don't appear
anywhere in the document.

## 7. Summary of findings

- ✅ All 6 real model components (transformer embedding, transformer SVO
  extraction, transformer concept extraction, transformer validator, NLI evidence
  classifier, few-shot LM judge) load and run successfully with the given env
  vars — no silent fallback to mocks anywhere in the log.
- ✅ SQLite-only backend confirmed working end-to-end (ingestion → 3 retrievers →
  fusion → evidence classification → dual verdict → merged output).
- ✅ Concept extraction + graph-retriever multi-hop is real and verified directly
  against the database, not just inferred from logs.
- ⚠️ **Performance**: `TransformerConceptExtractor` (flan-t5-large) is rebuilt from
  scratch on every `/validate` call instead of being cached — this is the dominant
  cost (~10s/request on a 3-sentence doc). Fix: cache it on the engine like the
  other components.
- ⚠️ **Correctness/extraction**: `TransformerSVOExtractor` extracted 0 triples on
  every test document — automatic triple extraction is not currently useful with
  the transformer extractor on this kind of input; only explicitly-supplied
  triples got validated.
- ⚠️ **Judge behavior**: the few-shot LM judge twice overrode a heuristic
  "insufficient evidence"/`supported`-by-coincidence verdict to `contradicted`
  for triples where the document simply never mentions the object — arguably
  should be `unknown`. Two examples in Run 1.

## 8. Files in this directory

- `uvicorn.log` — full server log (startup + all 3 requests, verbose mode)
- `onto_run.db` — SQLite database populated during this run
- `config_response.json`, `health_response.json` — `/config`, `/health` output
- `validate_request_*.json`, `validate_response_*.json` — the 3 request/response pairs
- `REPORT.md` — this file
