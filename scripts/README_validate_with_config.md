# Triple Validation Script (Remote Server)

Quick bash script to validate SVO triples against documents with configurable concept extraction.

## Installation (one-time setup)

```bash
cd ~/ontovalidator
pip install -r requirements-api.txt -r requirements-ml.txt
# Optional production backends (Elasticsearch/Neo4j/Milvus):
pip install -r requirements-production.txt
chmod +x scripts/validate_with_config.sh
```

## Quick Start

### 1. Fast validation (default: mock extractors, no GPU needed)
```bash
bash scripts/validate_with_config.sh \
  --doc-text "Aspirin treats headache and reduces fever." \
  --triple "Aspirin|treats|headache"
```

### 2. With transformer concept extraction (GPU recommended)
```bash
bash scripts/validate_with_config.sh \
  --doc paper.txt \
  --triple "COVID|causes|respiratory_illness" \
  --transformer
```

### 3. Custom transformer model (trade-off: speed vs. quality)
```bash
# Faster (small model)
bash scripts/validate_with_config.sh \
  --doc paper.txt \
  --triple "COVID|causes|respiratory_illness" \
  --transformer --model google/flan-t5-small

# Slower but better quality (large model) 
bash scripts/validate_with_config.sh \
  --doc paper.txt \
  --triple "COVID|causes|respiratory_illness" \
  --transformer --model google/flan-t5-large
```

## Arguments

| Argument | Purpose | Example |
|----------|---------|---------|
| `--doc FILE` | Read document from file | `--doc paper.txt` |
| `--doc-text TEXT` | Pass document inline | `--doc-text "Aspirin treats..."` |
| `--triple TRIPLE` | Triple to validate (format: `subject\|relation\|object`) | `--triple "Aspirin\|treats\|headache"` |
| `--transformer` | Enable transformer concept extraction | (flag, no value) |
| `--model MODEL` | Concept extraction model | `--model google/flan-t5-base` |
| `--embedding-model NAME` | Embedding model choice | `--embedding-model transformer` |
| `--db PATH` | SQLite database path | `--db my_data.db` |
| `--verbose` | Verbose output | (flag, no value) |
| `--help` | Show help | (flag, no value) |

## What It Does

1. **Reads the document** — from file or inline text
2. **Sets environment variables** — configures which extractors/models to use
3. **Calls validate_triples.py** — runs the actual validation pipeline
4. **Shows results** — displays verdict, score, evidence, etc.

## Performance Guide

### Default (Mock, fastest)
- Concept extraction: keyword matching (instant)
- Embeddings: 5-dim hash-based (instant)
- Best for: quick testing, CI/CD, baseline
- GPU needed: **No**

### Transformer Concept Extractor
- Concept extraction: LLM-based (needs GPU or CPU)
- Model: `google/flan-t5-small` (~80M params, ~2-5s per document)
- Model: `google/flan-t5-base` (~250M params, ~5-10s per document)  
- Model: `google/flan-t5-large` (~770M params, ~10-30s per document)
- Embeddings: still simple by default
- GPU needed: **Yes** (or CPU with patience)

### Transformer Embeddings
- Add `--embedding-model transformer` for better semantic retrieval
- Uses DistilBERT (66M params)
- Slower but higher quality concept matching
- GPU needed: **Yes**

## Examples with Different Configs

### Example 1: Aspirin Demo (local testing)
```bash
bash scripts/validate_with_config.sh \
  --doc-text "Aspirin treats headache and reduces fever. It's a common pain reliever." \
  --triple "Aspirin|treats|headache"
```
**Expected:** Supported (mock extractor finds "treats" keyword)

### Example 2: COVID Paper (transformer + GPU)
```bash
bash scripts/validate_with_config.sh \
  --doc covid_paper.txt \
  --triple "COVID-19|causes|respiratory_distress" \
  --transformer \
  --model google/flan-t5-base
```
**Expected:** Transformer extracts real concepts from the paper, improves graph-based retrieval

### Example 3: Multiple Concepts (verbose debugging)
```bash
bash scripts/validate_with_config.sh \
  --doc biomed_paper.txt \
  --triple "protein_X|regulates|gene_Y" \
  --transformer \
  --model google/flan-t5-large \
  --verbose
```

## Output Interpretation

```
Document: paper.txt
Triple: COVID|causes|respiratory_illness

Config: Concept extraction = transformer (model: google/flan-t5-large)
Config: Embeddings = simple (fast)
Config: Database = svo_data.db

Running validation...

============================================
SVO TRIPLE VALIDATION RESULTS
============================================

Triple: COVID causes respiratory_illness
Label: SUPPORTED
Score: 0.95
Rationale: Evidence contains a direct support match...

Evidence:
  [chunk_001] (lexical, score=0.92): "COVID causes respiratory illness..."
  [chunk_003] (semantic, score=0.88): "respiratory distress from COVID-19"
  
Counter-evidence: None

✓ Validation completed successfully
```

## Troubleshooting

### "Model not found" error
- Ensure transformer library is installed: `pip install transformers torch`
- First run downloads the model (~2-3 GB for flan-t5-large)
- Use `--model google/flan-t5-small` for faster first-run (~500MB)

### Slow on CPU
- Expected: ~10-30s per document with T5-large on CPU
- Solution: Use GPU or smaller model (`--model google/flan-t5-small`)

### OOM (Out of Memory)
- Using too large a model for available VRAM
- Solution: Use smaller model (`--model google/flan-t5-small`)

### "File not found" for document
- Ensure the path to --doc is correct
- Use absolute path if relative path doesn't work
- Or use `--doc-text` for inline testing

## For Batch Processing

To validate multiple triples/documents, write a wrapper script:

```bash
#!/bin/bash

# Read CSV: doc_path,subject,relation,object
while IFS=',' read doc_path subject relation object; do
    bash scripts/validate_with_config.sh \
      --doc "$doc_path" \
      --triple "$subject|$relation|$object" \
      --transformer \
      --model google/flan-t5-base
    echo "---"
done < batch.csv
```

Where `batch.csv` is:
```csv
covid_paper.txt,COVID,causes,respiratory_illness
malaria_paper.txt,Malaria,spreads_via,mosquitoes
diabetes_paper.txt,insulin,regulates,blood_glucose
```

## Performance Cheat Sheet

| Config | Concept Extraction | Embeddings | Speed | Quality | GPU |
|--------|-------------------|-----------|-------|---------|-----|
| Mock (default) | Verb-phrase heuristic | 5-dim hash | ~1s | Baseline | No |
| T5-small | LLM-based | 5-dim hash | ~2s | Good | Optional |
| T5-base | LLM-based | 5-dim hash | ~5s | Better | Recommended |
| T5-large | LLM-based | 5-dim hash | ~10s | Best | Required |
| T5-large + Emb | LLM-based | DistilBERT | ~15s | Excellent | Required |

## Advanced: Direct Python API

If you need more control than the script offers, use Python directly:

```python
from src.config import PipelineConfig, BackendMode
from src.factories import EngineFactory
from src.models import OntologyAssertion

config = PipelineConfig(
    backend_mode=BackendMode.PRODUCTION,
    sqlite_path="my_data.db",
    concept_extractor_name="transformer",
    concept_extractor_model_name="google/flan-t5-base",
)
engine = EngineFactory.create_verification_engine(config)

assertion = OntologyAssertion(
    assertion_id="test_1", subject="COVID-19", relation="causes", object="pneumonia",
)
verdict = engine.adjudicate_triple(
    document_text=open("paper.txt").read(),
    assertion=assertion,
    top_k=10,
)
print(f"Verdict: {verdict.label}  Score: {verdict.score}")
```

## See Also

- Main validation script: `scripts/validate_triples.py`
- Pipeline architecture: `README.md`
- Full production run (real backends, no mocks): `docs/FULL_PRODUCTION_RUN.md`
- Development roadmap: `TODO.md`
