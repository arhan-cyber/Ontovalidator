# Remote Server Validation Guide

Quick reference for validating SVO triples on the GPU-equipped remote server with configurable concept extraction.

## Installation (one-time setup)

```bash
# Clone or pull the repo
cd ~/ontovalidator

# Install Python dependencies
pip install transformers torch elasticsearch pymilvus neo4j

# Make scripts executable
chmod +x scripts/validate_with_config.sh
```

## Basic Usage

### Option 1: Inline text (quickest for testing)
```bash
bash scripts/validate_with_config.sh \
  --doc-text "Your document text here." \
  --triple "subject|relation|object"
```

### Option 2: From file
```bash
bash scripts/validate_with_config.sh \
  --doc document.txt \
  --triple "subject|relation|object"
```

### Option 3: With transformer concept extraction (GPU recommended)
```bash
bash scripts/validate_with_config.sh \
  --doc document.txt \
  --triple "subject|relation|object" \
  --transformer
```

## Real-World Examples

### Example 1: Fast baseline (mock extractors)
```bash
bash scripts/validate_with_config.sh \
  --doc paper.txt \
  --triple "COVID-19|causes|pneumonia"
```

**Output:** Verdict + score + evidence chunks  
**Time:** ~1-2 seconds  
**GPU:** Not needed

---

### Example 2: Better concept extraction (transformer, small model)
```bash
bash scripts/validate_with_config.sh \
  --doc paper.txt \
  --triple "COVID-19|causes|pneumonia" \
  --transformer \
  --model google/flan-t5-small
```

**Output:** Verdict + score + evidence (more relevant chunks due to better concept extraction)  
**Time:** ~2-5 seconds  
**GPU:** Helpful (works on CPU but slow)

---

### Example 3: Best quality (transformer, large model)
```bash
bash scripts/validate_with_config.sh \
  --doc paper.txt \
  --triple "COVID-19|causes|pneumonia" \
  --transformer \
  --model google/flan-t5-large
```

**Output:** Verdict + score + evidence (highest quality concept extraction)  
**Time:** ~5-15 seconds  
**GPU:** Strongly recommended

---

### Example 4: With verbose debugging
```bash
bash scripts/validate_with_config.sh \
  --doc paper.txt \
  --triple "COVID-19|causes|pneumonia" \
  --transformer \
  --verbose
```

Shows detailed extraction steps, retrieval scores, etc.

---

### Example 5: Custom database per run
```bash
bash scripts/validate_with_config.sh \
  --doc paper.txt \
  --triple "COVID-19|causes|pneumonia" \
  --transformer \
  --db validation_run_2025_01.db
```

Creates separate database for this validation (useful for reproducibility).

---

### Example 6: Both concept AND embedding transformers
```bash
bash scripts/validate_with_config.sh \
  --doc paper.txt \
  --triple "COVID-19|causes|pneumonia" \
  --transformer \
  --model google/flan-t5-base \
  --embedding-model transformer
```

**Best quality, slowest.**  
Uses DistilBERT for semantic embeddings + Flan-T5 for concepts.

---

## All Available Options

```bash
bash scripts/validate_with_config.sh [OPTIONS]

Required:
  --doc FILE              Read document from file
  --doc-text TEXT         Or pass inline text
  --triple "S|R|O"       Triple: subject|relation|object

Optional:
  --transformer           Enable transformer concept extraction
  --model NAME            Model choice (default: google/flan-t5-large)
                          - google/flan-t5-small (80M, fast)
                          - google/flan-t5-base (250M, balanced)
                          - google/flan-t5-large (770M, best)
  
  --embedding-model NAME  simple (default, fast) or transformer
  --db PATH              SQLite path (default: svo_data.db)
  --verbose              Show detailed logs
  --help                 Show full help
```

## Interpreting Output

```
Triple: COVID-19|causes|pneumonia
Label: SUPPORTED
Score: 0.95
```

- **SUPPORTED (score 0.80+)**: Evidence strongly backs the triple
- **PARTIAL (score 0.35-0.79)**: Some evidence, but incomplete
- **CONTRADICTED (score <0.75)**: Evidence refutes the triple
- **UNKNOWN (score <0.35)**: Insufficient evidence

## Performance Cheat Sheet

| Config | Concept Extraction | Embeddings | Speed | Quality | GPU |
|--------|-------------------|-----------|-------|---------|-----|
| Mock (default) | Keyword matching | 5-dim hash | ~1s | Baseline | No |
| T5-small | LLM-based | 5-dim hash | ~2s | Good | Optional |
| T5-base | LLM-based | 5-dim hash | ~5s | Better | Recommended |
| T5-large | LLM-based | 5-dim hash | ~10s | Best | Required |
| T5-large + Emb | LLM-based | DistilBERT | ~15s | Excellent | Required |

## Batch Processing Script

To validate multiple triples, create `batch_validate.sh`:

```bash
#!/bin/bash

# CSV format: doc_file,subject,relation,object
INPUT_FILE=$1
USE_TRANSFORMER=${2:-false}
MODEL=${3:-google/flan-t5-small}

while IFS=',' read doc subject relation object; do
    echo "Processing: $subject | $relation | $object"
    
    if [[ "$USE_TRANSFORMER" == "true" ]]; then
        bash scripts/validate_with_config.sh \
          --doc "$doc" \
          --triple "$subject|$relation|$object" \
          --transformer \
          --model "$MODEL"
    else
        bash scripts/validate_with_config.sh \
          --doc "$doc" \
          --triple "$subject|$relation|$object"
    fi
    
    echo "---"
done < "$INPUT_FILE"
```

**Usage:**
```bash
# Batch with mock (fast)
bash batch_validate.sh triples.csv

# Batch with transformer
bash batch_validate.sh triples.csv true google/flan-t5-base
```

Where `triples.csv`:
```csv
covid_paper.txt,COVID-19,causes,pneumonia
malaria_paper.txt,Malaria,spreads_via,mosquitoes
diabetes_paper.txt,Insulin,regulates,blood_glucose
```

## Troubleshooting

### Issue: "transformers not found"
```bash
pip install transformers torch
```

### Issue: Script runs but output is garbled
```bash
# Ensure UTF-8 encoding
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
bash scripts/validate_with_config.sh ...
```

### Issue: Model download takes forever
- First model download is ~2-5 GB (one-time)
- Stored in `~/.cache/huggingface/`
- Use `google/flan-t5-small` for testing (~500MB, much faster first download)

### Issue: GPU out of memory
```bash
# Use smaller model
bash scripts/validate_with_config.sh ... --model google/flan-t5-small

# Or disable GPU
CUDA_VISIBLE_DEVICES="" bash scripts/validate_with_config.sh ...
```

### Issue: Triple not found in evidence
- Document might not mention all triple components
- Try splitting into simpler triples
- Use `--verbose` to see what chunks were retrieved

## Advanced: Direct Python API

If you need more control, use Python directly:

```python
from src.config import PipelineConfig, BackendMode
from src.factories import EngineFactory
from src.models import OntologyAssertion

# Create config with transformer
config = PipelineConfig(
    backend_mode=BackendMode.PRODUCTION,
    sqlite_path="my_data.db",
    concept_extractor_name="transformer",
    concept_extractor_model_name="google/flan-t5-base",
)

# Create engine
engine = EngineFactory.create_verification_engine(config)

# Validate triple
assertion = OntologyAssertion(
    assertion_id="test_1",
    subject="COVID-19",
    relation="causes",
    object="pneumonia",
)

verdict = engine.adjudicate_triple(
    document_text=open("paper.txt").read(),
    assertion=assertion,
    top_k=10
)

print(f"Verdict: {verdict.label}")
print(f"Score: {verdict.score}")
print(f"Evidence: {verdict.evidence}")
```

## See Also

- Full script help: `bash scripts/validate_with_config.sh --help`
- Detailed config: `src/config.py`
- Pipeline architecture: `README.md`
- Development roadmap: `TODO.md`
