# Quick Start Guide (New Structure)

After the refactoring, the codebase is much cleaner. Here's how to use it:

## Installation

```bash
pip install -r requirements.txt  # (create this if needed)
```

## Quick Examples

### 1. Run the demo (one command)
```bash
python scripts/run_demo.py --validator minimal
```

Output:
```
================================================================================
SVO VERIFICATION PIPELINE DEMO
================================================================================

[1/2] INGESTION PHASE
  -> Generated 1 chunks.
  -> Extracted 2 SVO relations and concepts.
  -> Populated SQLite (Late Materialization ChunkStore).
Status: SUCCESS

[2/2] VERIFICATION PHASE
Status: EVIDENCE_GATHERED
Evidence chunks: 1

================================================================================
RESULTS
{
  "query": "What treats headache?",
  "status": "EVIDENCE_GATHERED",
  "evidence": [
    {
      "rank": 1,
      "chunk_id": "...",
      "score": 0.5429,
      "retrieval_source": "fusion",
      "text": "Aspirin treats headache and reduces pain."
    }
  ]
}
```

### 2. Use it in your code
```python
from src import SVOVerificationEngine, MoERouter, SQLiteLexicalRetriever
from src.retrieval import SQLiteSemanticRetriever, SQLiteGraphRetriever
from src.fusion import WeightedFusionEngine
from src.storage import SQLiteChunkStore
from src.validation import MinimalValidator

engine = SVOVerificationEngine(
    router=MoERouter(),
    lexical_store=SQLiteLexicalRetriever("data/demo.db"),
    semantic_store=SQLiteSemanticRetriever("data/demo.db"),
    graph_store=SQLiteGraphRetriever("data/demo.db"),
    fusion_engine=WeightedFusionEngine(),
    chunk_store=SQLiteChunkStore("data/demo.db"),
    validator=MinimalValidator(),
)

result = engine.verify("What treats headache?", top_k=5)
print(result)
```

### 3. Export training data
```bash
python scripts/export_training_data.py \
  --db-path data/demo.db \
  --out training_data.jsonl \
  --assertion "Aspirin|treats|headache|must_hold" \
  --assertion "Aspirin|treats|malaria|must_hold"
```

### 4. Custom queries with transformer validator
```python
from src.validation import TransformerValidator

engine = SVOVerificationEngine(
    ...,
    validator=TransformerValidator(),  # Uses zero-shot NLI
)

result = engine.verify("Does Aspirin prevent malaria?", top_k=5)
```

## Module Organization

### `src/models.py`
All dataclasses: `Chunk`, `SVORelation`, `RetrievalResult`, `OntologyAssertion`, `TripleVerdict`, etc.

### `src/routing/`
**QueryRouter** - Route queries to appropriate retrievers based on query type.

```python
from src.routing import MoERouter

router = MoERouter()
query_types = router.route("What treats headache?")
# Returns: [QueryType.COMPLEX, QueryType.EXACT_MATCH]
```

### `src/retrieval/`
Three retrieval modalities:
- `lexical.py` - BM25 keyword matching (Elasticsearch or SQLite)
- `semantic.py` - Dense vector ANN (Milvus or SQLite Jaccard)
- `graph.py` - Multi-hop graph traversal (Neo4j or SQLite)

```python
from src.retrieval import SQLiteLexicalRetriever

retriever = SQLiteLexicalRetriever("data/demo.db")
results = retriever.retrieve("What treats headache?", top_k=10)
```

### `src/fusion/`
Combine results from multiple retrievers.

```python
from src.fusion import WeightedFusionEngine

engine = WeightedFusionEngine()
# Combine lexical, semantic, graph scores
# Weights: 0.3*lexical + 0.5*semantic + 0.2*graph
# Boost: +0.1 for each additional retrieval source
```

### `src/validation/`
Two validators:
- `MinimalValidator` - Just return ranked chunks
- `TransformerValidator` - Run zero-shot NLI on each chunk
- `OntologyViolationValidator` - Check ontology constraints

```python
from src.validation import TransformerValidator

validator = TransformerValidator()  # Downloads DistilBERT on first use
result = validator.validate("Is Aspirin safe?", chunks)
```

### `src/ingestion/`
Three layers:
- `pipeline.py` - Main `DataIngestor` orchestrator
- `extractors.py` - SVO & concept extraction (mock rules)
- `embeddings.py` - Embedding models (SimpleEmbeddingModel for demo)

```python
from src.ingestion import DataIngestor, SimpleEmbeddingModel, MockSVOExtractor

ingestor = DataIngestor(
    sqlite_conn_path="data/demo.db",
    es_client=None,
    milvus_collection=None,
    neo4j_driver=None,
    embedding_model=SimpleEmbeddingModel(),
    svo_extractor=MockSVOExtractor(),
)

result = ingestor.ingest_document("doc_123", "Aspirin treats headache.")
```

### `src/classification/`
Triple classification for training data export.
- `triple_classifier.py` - Classify triples as `supported/contradicted/partial/unknown`
- `dataset.py` - Export to JSONL for fine-tuning

```python
from src.classification import PromptTripleClassifier, TripleDatasetWriter
from src.classification import AssertionInput

classifier = PromptTripleClassifier()
result = classifier.classify(
    "Aspirin treats headache.",
    AssertionInput(assertion_id="a1", subject="Aspirin", relation="treats", object="headache")
)
# Returns: TripleClassificationResult(label="supported", confidence=0.94, ...)

writer = TripleDatasetWriter("training_data.jsonl")
writer.write_example(example)
```

## Architecture Overview

```
Query
  ↓
[MoE Router] → Decides which retrievers to use
  ↓
[Lexical Retriever] ─┐
[Semantic Retriever]─┼→ [Fusion Engine] → Combine & rank
[Graph Retriever] ───┘
  ↓
[Late Materialization] → Load full chunks from SQLite
  ↓
[Validator] → MinimalValidator or TransformerValidator
  ↓
Evidence JSON
```

## Common Issues

### "No module named 'src'"
Make sure you're running from the project root:
```bash
cd C:\Users\Arhan\Projects\Ontovalidator
python scripts/run_demo.py
```

### "No module named 'transformers'"
The TransformerValidator needs `transformers` library:
```bash
pip install transformers torch
```

### Database errors
Make sure the `data/` folder exists:
```bash
mkdir data
```

## File Locations

| What | Location |
|------|----------|
| New code | `src/` |
| Scripts | `scripts/` |
| Tests | `tests/` |
| Demo data | `data/` |
| Old code | `_archived_old_scripts/` (for reference) |

## Next Steps

1. **Understand the data flow**: Read `REFACTORING.md`
2. **Run examples**: See `examples/` folder (when created)
3. **Check tests**: Run `pytest tests/test_integration.py` (requires pytest)
4. **Customize**: Swap out components (e.g., different validator, retriever, etc.)

---

Happy exploring! 🚀
