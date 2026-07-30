# Pipeline Enhancements

Reference for the six enhancements from `PLAN-TO-IMPROVE/implementation_plan.md`.
Everything below is additive: existing response fields and call signatures are unchanged.

---

## 1. Retrieval pathway

Every evidence span now reports how each retriever scored the chunk and how fusion combined them.

```json
"retrieval_pathway": {
  "lexical":  {"rank": 1, "score": 3.0,  "reason": "Lexical match on 'aspirin' + 'treats' (2/3 query terms); score 3.0, rank 1."},
  "semantic": {"rank": 2, "score": 0.43, "reason": "Vector similarity 0.4286 between the query embedding and this chunk; rank 2."},
  "graph":    {"rank": null, "score": null, "reason": "Not retrieved by the graph retriever."},
  "retriever_sources": ["lexical", "semantic"],
  "fusion_score": 0.9143,
  "fusion_explanation": "Weighted: 0.3x1.0 + 0.5x0.4286 + 0.2x0.0 = 0.5143, + 0.1 cross-source boost => 0.6143."
}
```

`WeightedFusionEngine` records the pre-fusion scores and per-retriever ranks on each
`RetrievalResult`; `RetrieverExplainer` (`src/retrieval/explainer.py`) renders them.
A `null` score means that retriever did not return the chunk at all.

## 2. Chunk annotation

```json
"annotated_html": "<p><mark class='subject'>Aspirin</mark> <mark class='relation'>treats</mark> <mark class='object'>headache</mark>.</p>",
"negation_analysis": {
  "negation_detected": true,
  "negation_keywords": ["does not"],
  "negation_scope": ["treat malaria"]
},
"component_matches": {"subject": true, "relation": true, "object": false}
```

`ChunkAnnotator` (`src/annotation/annotator.py`) escapes the chunk text before marking it,
so the HTML is safe to render directly. Matching is whole-word and case-insensitive;
overlapping matches are resolved longest-first. `component_matches` mirrors the classifier's
own flags rather than re-deriving them, so it never contradicts `match_type`.

## 3. Scoring transparency

```json
"scoring_breakdown": {
  "baseline": 0.2,
  "support_component": "0.6 x 0.95 = 0.57",
  "partial_component": "0.15 x 0.0 = 0.0",
  "refute_component": "-0.55 x 0.0 = -0.0",
  "agreement_bonus": 0.16,
  "raw_score": "0.2 + 0.57 + 0.0 + 0.16 + -0.0 = 0.93",
  "raw_score_value": 0.93,
  "clipped_score": 0.93,
  "evidence_counts": {"supports": 1, "refutes": 0, "partial": 0, "unknown": 0},
  "final_score": 0.93
},
"decision_thresholds": {
  "contradicted_rule": "not triggered: refute_strength (0) is not both > support_strength (0.95) and >= 0.6",
  "supported_rule": "triggered: support_strength (0.95) >= 0.7 and refute_strength == 0",
  "chosen_label": "supported (first matching rule in priority order)"
}
```

`final_score` always equals the verdict's `score`. When a label floor raises the score,
`adjustment_reason` explains why. If the LM judge overrides the heuristic label, the
breakdown gains `lm_judge_label` / `lm_judge_confidence`.

The scoring constants live at the top of `src/engine.py` (`BASELINE_SCORE`,
`SUPPORT_WEIGHT`, `LABEL_SCORE_FLOORS`, …) so the formula and its explanation cannot drift apart.

## 4. Rejected evidence

Chunks that were retrieved but classified `unknown` no longer enter the verdict (they
contributed nothing to the score anyway, and they diluted the LM judge's prompt). They are
reported separately:

```json
"rejected_evidence": [
  {
    "chunk_id": "…",
    "text": "Ibuprofen treats swelling.",
    "retrieval_score": 0.3143,
    "adjudication": "unknown",
    "confidence": 0.3143,
    "reason_rejected": "Too weak to be used (only 1/3 components matched)"
  }
]
```

If *no* chunk takes a stance, every retrieved chunk is kept as evidence and
`rejected_evidence` is empty — the verdict is still explained by what was actually retrieved.

## 5. Feedback loop

| Endpoint | Purpose |
|---|---|
| `POST /feedback/correct` | Record a corrected label for a verdict |
| `GET /feedback/analysis?days=30` | Confusion matrix, per-retriever accuracy, recommendations |

Each verdict carries a `feedback_id`. While the verdict is still cached, that id alone is
enough to submit a correction:

```json
{"feedback_id": "812520e2…", "actual_label": "partial", "reason": "object not actually matched"}
```

Once the cache entry expires the endpoint returns `404 verdict_not_found`; resend the
verdict's fields (`assertion_id`, `document_id`, `predicted_label`, …) in the same request body.

Corrections land in `feedback.db` (`FeedbackRecorder`), and `FeedbackDashboard` turns them
into metrics. Recommendations only fire once a pattern has at least 3 occurrences, so a
single correction never moves the needle.

```bash
python scripts/init_feedback_db.py --show-stats
```

## 6. Caching

`CacheEngine` (`src/cache/cache_engine.py`) caches embeddings, retrieval results, and verdicts
in `cache.db`.

Every key carries a fingerprint of what the value was derived from:

| Entry | Key includes | Default TTL |
|---|---|---|
| embedding | model id + text | 30 days |
| retrieval | retriever class + query + top_k + corpus state | 7 days |
| verdict | assertion id + document id + **digest of the document text** | 14 days |

The document digest matters: re-posting changed text under a document id that was seen
before re-runs the pipeline instead of replaying the previous answer. Likewise the corpus
fingerprint (row count + max chunk id) invalidates cached retrieval after ingestion.

`summary.cache_hits` on a `/validate` response reports how many verdicts were served from cache.

```bash
python scripts/clear_cache.py --stats     # inspect
python scripts/clear_cache.py             # drop expired entries
python scripts/clear_cache.py --all       # purge
```

## 7. Multi-modal ingestion

`ingest_document(document_id, raw_text, tables=None, images=None)` indexes:

| Modality | Extractor | Chunk type |
|---|---|---|
| Prose sentences | built-in chunker | `text` |
| Bulleted / numbered lists | `ListExtractor` | `list_item` |
| HTML or CSV tables | `TableExtractor` | `table_row` |
| Images (OCR, optional) | `ImageExtractor` | `image` |

Table rows are rendered as `"Header: value | Header: value"` so the existing text retrievers
can match a single row. All modalities share one `chunks` table and are therefore retrievable
together; the ingestion result reports a `chunk_types` histogram.

OCR needs `pytesseract` + `Pillow` and is off by default (`ONTO_ENABLE_OCR=true` to enable).

The `chunks` table gained `chunk_type`, `type_metadata`, `timestamp`, and `temporal_metadata`.
Existing databases are migrated in place on first use (`ensure_chunks_schema`).

## 8. Temporal reasoning

`TemporalExtractor` records dates (1800–2099), relative expressions ("recently", "in the
1990s"), and a document's own `Published:` / `Updated:` header. Each chunk gets a `timestamp`.

`TemporalEvidenceClassifier` wraps — rather than replaces — the configured stance classifier,
so temporal reasoning composes with the heuristic or NLI classifier. Given an
`OntologyAssertion.temporal_scope`, evidence outside that window keeps its stance but loses
confidence:

| `temporal_status` | Meaning | Confidence |
|---|---|---|
| `current` | inside the scope | unchanged |
| `outdated` | before the scope | × 0.6 |
| `future` | after the scope | × 0.3 |
| `unscoped` | the assertion has no scope | unchanged |
| `undated` | the chunk has no timestamp | unchanged |

---

## Configuration

All flags are settable in `PipelineConfig` or via environment variables.

| Env var | Default | Effect |
|---|---|---|
| `ONTO_ENABLE_CACHE` | `true` | Enable the cache layer |
| `ONTO_CACHE_DB_PATH` | `cache.db` | Cache location |
| `ONTO_VERDICT_CACHE_TTL_DAYS` | `14` | Verdict TTL |
| `ONTO_ENABLE_FEEDBACK` | `true` | Enable correction recording |
| `ONTO_FEEDBACK_DB_PATH` | `feedback.db` | Feedback DB location |
| `ONTO_ENABLE_TABLE_EXTRACTION` | `true` | Index table rows |
| `ONTO_ENABLE_LIST_EXTRACTION` | `true` | Index list items |
| `ONTO_ENABLE_OCR` | `false` | Index OCR'd images |
| `ONTO_ENABLE_TEMPORAL_REASONING` | `true` | Extract timestamps, wrap the span classifier |
| `ONTO_OUTDATED_EVIDENCE_PENALTY` | `0.6` | Confidence multiplier for pre-scope evidence |
| `ONTO_FUTURE_EVIDENCE_PENALTY` | `0.3` | Confidence multiplier for post-scope evidence |
| `ONTO_ENABLE_RETRIEVAL_PATHWAY` | `true` | Attach `retrieval_pathway` |
| `ONTO_ENABLE_CHUNK_ANNOTATION` | `true` | Attach `annotated_html` |
| `ONTO_ENABLE_SCORING_BREAKDOWN` | `true` | Attach `scoring_breakdown` |
| `ONTO_ENABLE_REJECTED_EVIDENCE` | `true` | Attach `rejected_evidence` |

`cache_db_path` and `feedback_db_path` are resolved next to `sqlite_path` when left at their
defaults, so pointing the pipeline at `/data/run/svo.db` keeps all three databases together.

---

## Tests

```bash
pytest tests/test_retriever_explainer.py tests/test_chunk_annotator.py \
       tests/test_scoring_breakdown.py tests/test_rejection_explainer.py \
       tests/test_feedback_recorder.py tests/test_feedback_analysis.py \
       tests/test_cache_engine.py tests/test_caching_integration.py \
       tests/test_table_extractor.py tests/test_list_extractor.py \
       tests/test_multimodal_ingestion.py \
       tests/test_temporal_extractor.py tests/test_temporal_classifier.py \
       tests/integration/test_end_to_end_transparency.py \
       tests/api/test_feedback_route.py
```
