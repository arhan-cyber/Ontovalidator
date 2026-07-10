# Ontovalidator Pipeline - Development Roadmap

**Last Updated:** 2026-07-10  
**Current Status:** B+ (Production-ready architecture, not production-ready features)  
**Time to Ship:** 2-4 weeks (with focused effort on critical items)

---

## ✅ COMPLETED

### Architecture & Design
- [x] Modular design with clean separation of concerns
- [x] Abstract base classes for all components (retrievers, judges, validators)
- [x] Factory pattern for dependency injection
- [x] Environment-based configuration system
- [x] Graceful fallback mechanism (production → SQLite)
- [x] Type hints throughout codebase

### Backend Integration (Code Complete)
- [x] Elasticsearch helper (connection, bulk ingestion, indexing)
- [x] Milvus helper (server and Lite modes)
- [x] Neo4j helper (driver, schema initialization)
- [x] LexicalRetriever (Elasticsearch + SQLite fallback)
- [x] MilvusSemanticRetriever (Milvus + SQLite fallback)
- [x] GraphRetriever (Neo4j + SQLite fallback)
- [x] Factory creates all backends with fallback logic
- [x] Python clients installed (elasticsearch, pymilvus, neo4j)

### Testing
- [x] 103+ integration tests
- [x] Config loading tests (23 tests)
- [x] Backend factory tests (20 tests)
- [x] End-to-end pipeline tests (19 tests)
- [x] Health check tests (6 tests)
- [x] Evidence judge tests (3 tests)
- [x] Engine configuration tests (35 tests)
- [x] Edge case handling (empty docs, malformed triples)

### Evidence Judges
- [x] HeuristicEvidenceJudge (offline, deterministic)
- [x] PromptEvidenceJudge (LLM-based with fallback)
- [x] Fallback mechanism (LLM → Heuristic)

### Configuration System
- [x] Environment variable loading
- [x] Config serialization (to/from JSON)
- [x] Multiple backend modes (DEMO, PRODUCTION, AUTO)
- [x] Per-backend configuration (ES, Milvus, Neo4j)
- [x] CLI argument parsing (validate_triples.py)

### CLI & Scripts
- [x] validate_triples.py (basic functionality)
- [x] health_check.py (backend health monitoring)
- [x] run_demo.py (demo pipeline)
- [x] export_training_data.py

### Core Pipeline Components
- [x] Document ingestion (chunking, embedding, SVO extraction)
- [x] Multi-modal retrieval (lexical, semantic, graph)
- [x] Weighted fusion engine (combining results from multiple sources)
- [x] Triple validation (adjudication logic)
- [x] Result formatting (JSON output)
- [x] Summary statistics (counts, averages)

### Models Implemented
- [x] SimpleEmbeddingModel (CPU-only, 5-dim hash-based)
- [x] TransformerEmbeddingModel (DistilBERT, CPU-friendly)
- [x] MockSVOExtractor (hardcoded, demo-only)
- [x] MockConceptExtractor (hardcoded, demo-only)
- [x] TransformerSVOExtractor (Flan-T5)
- [x] MinimalValidator (simple baseline)
- [x] TransformerValidator (NLI-based)

---

## 🔴 CRITICAL BLOCKERS (Must Fix Before Production)

### 1. Real SVO Extraction
- [ ] Replace MockSVOExtractor with real extraction
  - [ ] Enable TransformerSVOExtractor by default
  - [ ] OR implement domain-specific extraction
  - [ ] Test on real documents (not just Aspirin + fever)
  - [ ] Measure extraction quality (precision/recall)
- [ ] Replace MockConceptExtractor
  - [ ] Implement real concept extraction
  - [ ] Map extracted concepts to knowledge base

**Priority:** CRITICAL  
**Effort:** 4-6 hours  
**Blocker:** Without this, system extracts 0 triples from real data

---

### 2. Line Numbers in Output
- [ ] Modify chunking to track line numbers
  - [ ] Add line_number to Chunk metadata
  - [ ] Add char_offset to Chunk metadata
  - [ ] Add word_offset to Chunk metadata
- [ ] Return line numbers in evidence output
  - [ ] Add line_number field to evidence dict
  - [ ] Add page_number field (if documents have pages)
  - [ ] Add original_text field (full line context)
- [ ] Test with multi-page documents

**Priority:** CRITICAL  
**Effort:** 2-3 hours  
**Blocker:** Users can't verify results without line numbers

---

### 3. Accuracy Metrics & Benchmarking
- [ ] Build evaluation dataset
  - [ ] Collect 100+ documents with human-validated verdicts
  - [ ] Document gold-standard labels
  - [ ] Split into train/val/test sets
- [ ] Measure baseline accuracy
  - [ ] Calculate precision/recall/F1 for heuristic judge
  - [ ] Calculate for LM judge
  - [ ] Compare vs. baseline (majority class, random)
- [ ] Document results
  - [ ] Create benchmarking report
  - [ ] Report accuracy by domain (if multiple)
  - [ ] Report false positive/negative rates

**Priority:** CRITICAL  
**Effort:** 8-12 hours  
**Blocker:** Can't justify to stakeholders without metrics

---

### 4. Show Competing Evidence
- [ ] Modify adjudication to collect ALL evidence
  - [ ] Separate supporting vs. contradicting vs. partial
  - [ ] Don't filter to just supporting evidence
  - [ ] Track which evidence sources disagreed
- [ ] Return full evidence picture
  - [ ] supporting: [all supporting chunks]
  - [ ] contradicting: [all contradicting chunks]
  - [ ] partial: [all partial matches]
  - [ ] alternative: [related claims mentioned]
- [ ] Test with documents having conflicting claims

**Priority:** CRITICAL  
**Effort:** 3-4 hours  
**Blocker:** Users get false confidence in incomplete info

---

## 🟡 HIGH PRIORITY (Do ASAP)

### 5. Caching Layer
- [ ] Implement in-memory cache
  - [ ] Cache chunks by document_id
  - [ ] Cache embeddings by document_id
  - [ ] Cache retrieval results by query
  - [ ] Set TTL (time-to-live) for cache entries
- [ ] OR integrate Redis
  - [ ] Add redis dependency
  - [ ] Implement RedisCache class
  - [ ] Handle cache misses
- [ ] Measure performance improvement
  - [ ] 10x speedup on repeated documents (target)

**Priority:** HIGH  
**Effort:** 2-4 hours  
**Impact:** 500ms → 50ms per repeated query

---

### 6. REST API
- [ ] Build FastAPI application
  - [ ] POST /validate endpoint (single triple)
  - [ ] POST /validate-batch endpoint (multiple triples, one doc)
  - [ ] GET /health endpoint
  - [ ] GET /config endpoint
- [ ] Add request/response validation
  - [ ] Validate input document and triples
  - [ ] Return structured JSON responses
  - [ ] Handle errors gracefully
- [ ] Add authentication (optional)
  - [ ] API key support
  - [ ] Rate limiting

**Priority:** HIGH  
**Effort:** 4-6 hours  
**Impact:** Makes system usable in applications

---

### 7. Audit Trail & Reproducibility
- [ ] Log all validation runs
  - [ ] Timestamp
  - [ ] Document hash (for verification)
  - [ ] Config version/hash
  - [ ] Results and scores
- [ ] Store in database or file
  - [ ] SQLite table for audit logs
  - [ ] Searchable by document_id, timestamp
- [ ] Make results reproducible
  - [ ] Set random seeds (reproducible scoring)
  - [ ] Document configuration exactly
  - [ ] Version all models

**Priority:** HIGH  
**Effort:** 3-4 hours  
**Impact:** Critical for regulated industries (pharma, legal)

---

### 8. Backend Health Checks (Default)
- [ ] Run health checks on startup
  - [ ] Check Elasticsearch connectivity
  - [ ] Check Milvus connectivity
  - [ ] Check Neo4j connectivity
- [ ] Fail fast if required backends unavailable
  - [ ] If require_production_backends=true, fail startup
  - [ ] If backend critical to pipeline, warn loudly
- [ ] Add health check to validate_triples.py
  - [ ] Optional --health-check flag (already exists)
  - [ ] Make it default behavior

**Priority:** HIGH  
**Effort:** 1-2 hours  
**Impact:** Catch silent backend failures before production

---

### 9. Score Documentation
- [ ] Document what each score means
  - [ ] 0.0-0.2: Very low confidence
  - [ ] 0.2-0.4: Low confidence
  - [ ] 0.4-0.6: Uncertain
  - [ ] 0.6-0.8: Confident
  - [ ] 0.8-1.0: Very confident
- [ ] Add confidence level to output
  - [ ] Replace numeric score with descriptive level
  - [ ] Add confidence interval (±tolerance)
- [ ] Document score components
  - [ ] What retrieval score contributes
  - [ ] What match quality contributes
  - [ ] What fusion boosting contributes

**Priority:** HIGH  
**Effort:** 2-3 hours  
**Impact:** Users understand what scores mean

---

## 🟠 MEDIUM PRIORITY (Next Week)

### 10. Batch Processing
- [ ] Add batch validation API
  - [ ] Validate multiple documents with same triples
  - [ ] Validate one document with many triples
  - [ ] Return results in parallel
- [ ] Implement queue system (Celery or Ray)
  - [ ] Background job processing
  - [ ] Progress tracking
  - [ ] Result polling
- [ ] Test with realistic workload (1000+ documents)

**Priority:** MEDIUM  
**Effort:** 6-8 hours  
**Impact:** Production workloads need batch processing

---

### 11. Database Optimization
- [ ] Add indexes to SQLite
  - [ ] Index on chunk_id (primary key)
  - [ ] Index on document_id
  - [ ] Full-text index on text content
- [ ] Measure query performance
  - [ ] Current: 30+ seconds for 1M chunks
  - [ ] After indexes: <100ms target
- [ ] OR migrate to PostgreSQL
  - [ ] Add PostgreSQL support to ChunkStore
  - [ ] Migrate test data
  - [ ] Compare performance

**Priority:** MEDIUM  
**Effort:** 4-6 hours  
**Impact:** ~100x speedup on large datasets

---

### 12. Batch CLI Enhancement
- [ ] Accept file input (JSONL format)
  - [ ] File with one JSON object per line
  - [ ] Each line: {document_id, text, triples}
- [ ] Output to file (JSONL format)
  - [ ] Results appended line-by-line
  - [ ] Progress indicator
  - [ ] Error handling
- [ ] Add --parallel flag for multi-processing

**Priority:** MEDIUM  
**Effort:** 3-4 hours  
**Impact:** Users can validate batches without API

---

### 13. Drill-Down / Exploration UI
- [ ] Add retrieval exploration endpoints
  - [ ] GET /retrieve?query=... (see all chunks found)
  - [ ] GET /retrieve?query=...&filter=source (filter by lexical/semantic/graph)
  - [ ] Show ranking scores and reasons
- [ ] Simple HTML dashboard
  - [ ] Form to enter document + triples
  - [ ] See full retrieval results
  - [ ] See scoring breakdown
  - [ ] See competing evidence

**Priority:** MEDIUM  
**Effort:** 6-8 hours  
**Impact:** Users can debug when results are wrong

---

### 14. Feedback & Learning Mechanism
- [ ] Add endpoint to report incorrect verdicts
  - [ ] POST /feedback {document_id, triple, actual_label, notes}
  - [ ] Store in database
- [ ] Analyze feedback
  - [ ] Which triples are most error-prone?
  - [ ] Which domains need improvement?
  - [ ] False positive vs. false negative rates
- [ ] (Optional) Fine-tune models on feedback

**Priority:** MEDIUM  
**Effort:** 4-6 hours  
**Impact:** System improves over time, users trust it

---

## 🟢 NICE TO HAVE (Later)

### 15. Structured Logging
- [ ] Switch to JSON logging
- [ ] Log to file + stdout
- [ ] Add trace IDs for debugging
- [ ] Ship logs to centralized system (Datadog, ELK)

**Priority:** LOW  
**Effort:** 3-4 hours

---

### 16. Performance Monitoring
- [ ] Track latency per component
- [ ] Track memory usage
- [ ] Track token count (LLM costs)
- [ ] Build dashboard (Grafana/Prometheus)

**Priority:** LOW  
**Effort:** 4-6 hours

---

### 17. Domain-Specific Fine-Tuning
- [ ] Collect domain-specific training data
- [ ] Fine-tune embedding model for domain
- [ ] Fine-tune SVO extractor for domain
- [ ] Fine-tune evidence judge for domain

**Priority:** LOW  
**Effort:** 20+ hours  
**Impact:** Higher accuracy for specific domains

---

### 18. Comparison Feature
- [ ] Compare two claims in same document
  - [ ] "Is claim A or claim B more likely?"
  - [ ] Show evidence for both
  - [ ] Highlight differences
- [ ] Rank claims by confidence
  - [ ] Given 10 claims, rank by support level

**Priority:** LOW  
**Effort:** 3-4 hours

---

### 19. Confidence Intervals
- [ ] Replace point estimates with ranges
  - [ ] Score: 0.90±0.05
  - [ ] Confidence: 95%±10%
- [ ] Use bootstrap or Bayesian methods to estimate uncertainty

**Priority:** LOW  
**Effort:** 4-6 hours

---

### 20. Chunking Strategy Configuration
- [ ] Make chunking strategy configurable
  - [ ] By sentence
  - [ ] By paragraph
  - [ ] By sliding window
  - [ ] By semantic similarity
- [ ] Let users control chunk size
- [ ] Document impact on results

**Priority:** LOW  
**Effort:** 3-4 hours

---

## 📊 SUMMARY

| Category | Count | Status |
|----------|-------|--------|
| **COMPLETED** | 40+ | ✅ Done |
| **CRITICAL BLOCKERS** | 4 | 🔴 Must do |
| **HIGH PRIORITY** | 5 | 🟡 Do ASAP |
| **MEDIUM PRIORITY** | 6 | 🟠 Next week |
| **NICE TO HAVE** | 6 | 🟢 Later |

---

## 🚀 IMMEDIATE ACTION PLAN (Next 3 Days)

### Day 1: Critical Fixes
- [ ] Enable TransformerSVOExtractor (5 min)
- [ ] Add health checks to validation flow (15 min)
- [ ] Add line numbers to chunk metadata (2 hours)
- [ ] Test with real documents (1 hour)

### Day 2: Accuracy & Evidence
- [ ] Start evaluation dataset (3 hours)
- [ ] Modify adjudication to collect all evidence (2 hours)
- [ ] Test competing evidence output (1 hour)

### Day 3: Performance & API
- [ ] Implement basic caching (1 hour)
- [ ] Scaffold FastAPI application (2 hours)
- [ ] Create /validate endpoint (1 hour)
- [ ] Test end-to-end (1 hour)

---

## 📝 NOTES

### Why These Are Prioritized

1. **SVO Extraction**: System is useless without real extraction
2. **Line Numbers**: Users need to verify results
3. **Accuracy Metrics**: Can't justify to stakeholders without data
4. **Competing Evidence**: Users lose trust with incomplete info
5. **Caching**: Performance is critical for user experience
6. **API**: System needs to be usable in applications
7. **Audit Trail**: Required for regulated industries

### What's NOT Blocked

- Architecture is solid—no refactoring needed
- Backend code is correct—just need services running
- Tests are comprehensive—confidence in correctness
- Configuration system works—no design changes needed

### What's Blocked

- Everything else depends on #1 (SVO extraction)
- Most users need #2 (line numbers)
- Business case needs #3 (accuracy metrics)

---

## 🎯 SUCCESS CRITERIA

**Before beta launch (2 weeks):**
- [x] Architecture solid
- [ ] Real SVO extraction working
- [ ] Line numbers in output
- [ ] Accuracy measured (>70% baseline?)
- [ ] Competing evidence shown
- [ ] Health checks default on
- [ ] Caching implemented
- [ ] Basic API working

**Before production launch (4 weeks):**
- [ ] All above, plus:
- [ ] Audit trail complete
- [ ] Batch processing working
- [ ] Database optimized
- [ ] 100+ user validation runs
- [ ] Performance benchmarked
- [ ] Error recovery tested
- [ ] Feedback mechanism working
