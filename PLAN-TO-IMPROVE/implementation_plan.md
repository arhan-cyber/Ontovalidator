# Ontovalidator Enhancement Implementation Plan

**Date:** July 31, 2026  
**Status:** Planning Phase  
**Owner:** Product & Engineering Team  

---

## Executive Summary

This plan outlines implementation of 6 major enhancements to the Ontovalidator pipeline across two dimensions:

**Observable Improvements (User-Facing):**
- Retrieval Pathway Visualization + Chunk Annotation
- Scoring Transparency + Rejected Evidence Audit Trail

**Architectural Improvements (System Capability):**
- Learning from User Feedback Loop
- Caching & Optimization
- Multi-Modal Evidence Ingestion
- Temporal Reasoning

**Timeline:** 8-10 weeks across 3 phases  
**Resource Requirements:** 1-2 engineers, 1 DevOps (for caching layer)  
**Priority:** Observable improvements in Phase 1 (high user impact), Architectural in Phase 2-3 (long-term capability)

---

## Phase 1: Observable Improvements (Weeks 1-3)

### 1.1: Retrieval Pathway + Chunk Annotation

#### What This Does
Currently, users see:
```json
{
  "verdict": "supported",
  "score": 0.95,
  "evidence": [{"chunk_id": "abc123", "text": "..."}]
}
```

After implementation, users will see:
```json
{
  "verdict": "supported",
  "score": 0.95,
  "evidence": [
    {
      "chunk_id": "abc123",
      "text": "...",
      "retrieval_pathway": {
        "lexical": {"rank": 2, "score": 0.85, "reason": "..."},
        "semantic": {"rank": 1, "score": 0.92, "reason": "..."},
        "graph": {"rank": 5, "score": 0.60, "reason": "..."},
        "fusion_score": 0.88,
        "fusion_explanation": "..."
      },
      "annotated_html": "<p><mark class='subject'>Aspirin</mark>...</p>",
      "negation_analysis": {...}
    }
  ]
}
```

#### Implementation Details

**Step 1: Modify RetrievalResult Dataclass**
- **File:** `src/models.py`
- **Change:** Add fields to store retriever-specific scores before fusion

```python
@dataclass
class RetrievalResult:
    chunk_id: str
    chunk: Optional[Chunk] = None
    score: float = 0.0  # Final fused score
    source: str = "unknown"
    
    # NEW FIELDS:
    lexical_score: Optional[float] = None
    lexical_rank: Optional[int] = None
    semantic_score: Optional[float] = None
    semantic_rank: Optional[int] = None
    graph_score: Optional[float] = None
    graph_rank: Optional[int] = None
    retriever_sources: List[str] = field(default_factory=list)  # Which retrievers found this
```

**Step 2: Modify WeightedFusionEngine**
- **File:** `src/fusion/engine.py`
- **Change:** Store per-retriever scores before fusion

```python
def fuse_and_rank(self, results_by_source: Dict[str, List[RetrievalResult]], top_k: int = 10):
    # Store original scores from each retriever
    for lexical_result in results_by_source.get("lexical", []):
        lexical_result.lexical_score = lexical_result.score
        lexical_result.lexical_rank = rank_index
    
    # Repeat for semantic, graph
    # Then compute fusion
    # Track which sources found each chunk
```

**Step 3: Add Retrieval Explanation Generator**
- **File:** `src/retrieval/explainer.py` (NEW)
- **Purpose:** Generate human-readable explanations for each retriever's score

```python
class RetrieverExplainer:
    def explain_lexical(self, query: str, score: float, rank: int) -> str:
        # "BM25 match on 'aspirin' + 'treats' (2/3 components)"
        pass
    
    def explain_semantic(self, query: str, score: float, rank: int) -> str:
        # "Vector similarity 0.92 (chunk embedding close to query)"
        pass
    
    def explain_graph(self, query: str, score: float, rank: int) -> str:
        # "2-hop traversal from concept graph"
        pass
    
    def explain_fusion(self, lexical: float, semantic: float, graph: float, 
                       final_score: float) -> str:
        # "Weighted: 0.3×0.85 + 0.5×0.92 + 0.2×0.60 + 0.1 cross_source_boost"
        pass
```

**Step 4: Modify SVOVerificationEngine.validate_triples_batch()**
- **File:** `src/engine.py`
- **Change:** Collect retriever scores and generate explanations

```python
def validate_triples_batch(self, document_text: str, assertions: List[OntologyAssertion]):
    # ... existing code ...
    
    ranked_results = self.fusion_engine.fuse_and_rank(results_by_source)
    
    # NEW: Build retrieval pathway for each result
    for result in ranked_results:
        result.retrieval_pathway = {
            "lexical": {
                "rank": result.lexical_rank,
                "score": result.lexical_score,
                "reason": retriever_explainer.explain_lexical(...)
            },
            "semantic": {...},
            "graph": {...},
            "fusion_score": result.score,
            "fusion_explanation": retriever_explainer.explain_fusion(...)
        }
```

**Step 5: Add Chunk Annotation Generator**
- **File:** `src/annotation/annotator.py` (NEW)
- **Purpose:** Generate HTML with marked-up matches

```python
class ChunkAnnotator:
    def annotate(self, chunk_text: str, assertion: OntologyAssertion,
                 span_classifier: BaseEvidenceSpanClassifier) -> Dict:
        
        # Classify the chunk
        evidence_span = span_classifier.classify(assertion, chunk, ...)
        
        # Extract matched spans
        subject_spans = self._find_spans(chunk_text, assertion.subject)
        relation_spans = self._find_spans(chunk_text, assertion.relation)
        object_spans = self._find_spans(chunk_text, assertion.object)
        
        # Build annotated HTML
        annotated_html = self._build_html_with_marks(
            chunk_text,
            {
                "subject": subject_spans,
                "relation": relation_spans,
                "object": object_spans
            }
        )
        
        return {
            "annotated_html": annotated_html,
            "negation_analysis": {
                "negation_detected": evidence_span.negation_detected,
                "negation_keywords": self._detect_negations(chunk_text),
                "negation_scope": self._compute_scope(chunk_text)
            },
            "component_matches": {
                "subject": evidence_span.matched_subject,
                "relation": evidence_span.matched_relation,
                "object": evidence_span.matched_object
            }
        }
```

**Step 6: Update Response Format**
- **File:** `src/models.py`
- **Change:** Add annotation/pathway fields to EvidenceSpan

```python
@dataclass
class EvidenceSpan:
    # ... existing fields ...
    
    # NEW FIELDS:
    retrieval_pathway: Optional[Dict[str, Any]] = None
    annotated_html: Optional[str] = None
    negation_analysis: Optional[Dict[str, Any]] = None
    component_matches: Optional[Dict[str, bool]] = None
```

**Step 7: Modify Output Serialization**
- **File:** `src/engine.py` (in verdict serialization)
- **Change:** Include all new fields in JSON output

```python
def _serialize_verdict(self, verdict: TripleVerdict) -> Dict:
    return {
        # ... existing fields ...
        "evidence": [
            {
                "chunk_id": span.chunk_id,
                "text": span.text,
                "retrieval_pathway": span.retrieval_pathway,
                "annotated_html": span.annotated_html,
                "negation_analysis": span.negation_analysis,
                "component_matches": span.component_matches,
                "support_type": span.support_type,
                "confidence": span.confidence,
            }
            for span in verdict.evidence
        ]
    }
```

#### Testing Strategy
- Unit test: `tests/test_retriever_explainer.py` — verify explanation text generation
- Unit test: `tests/test_chunk_annotator.py` — verify HTML markup correctness
- Integration test: `tests/test_end_to_end_pathway.py` — full pipeline with annotation
- Manual test: Run on demo data, visually inspect HTML and explanations

#### Success Metrics
- ✅ All evidence includes retrieval_pathway
- ✅ All evidence includes annotated_html
- ✅ HTML renders correctly (no broken markup)
- ✅ Explanations are human-readable and accurate

#### Estimated Time: 3-4 days

---

### 1.2: Scoring Transparency + Rejected Evidence Audit Trail

#### What This Does
Currently, users see:
```json
{
  "verdict": "supported",
  "score": 0.95
}
```

After implementation:
```json
{
  "verdict": "supported",
  "score": 0.95,
  "scoring_breakdown": {
    "baseline": 0.2,
    "support_strength": 0.95,
    "support_component": "0.6 × 0.95 = 0.57",
    "agreement_bonus": 0.08,
    "raw_score": "0.2 + 0.57 + 0.08 = 0.85",
    "final_score": 0.95,
    "adjustment_reason": "Label is 'supported' → boost to min 0.8"
  },
  "decision_thresholds": {
    "why_not_contradicted": "refute_strength (0.0) < 0.6 OR refute_strength <= support_strength",
    "why_not_partial": "support_strength (0.95) >= 0.7 AND refute_strength == 0",
    "why_supported": "Both thresholds passed"
  },
  "rejected_evidence": [
    {
      "chunk_id": "xyz789",
      "text": "...",
      "retrieval_score": 0.72,
      "adjudication": "partial",
      "reason_rejected": "Only 2 components matched (subject + relation, missing object)"
    }
  ]
}
```

#### Implementation Details

**Step 1: Refactor Verdict Aggregation Logic**
- **File:** `src/engine.py::_aggregate_triple_verdict()`
- **Change:** Track all calculations step-by-step

```python
def _aggregate_triple_verdict(self, assertion, evidence, retrieval_sources):
    """
    Now returns not just TripleVerdict but also scoring breakdown.
    """
    
    # Step 1: Categorize evidence
    supports = [e for e in evidence if e.support_type == "supports"]
    refutes = [e for e in evidence if e.support_type == "refutes"]
    partials = [e for e in evidence if e.support_type == "partial"]
    unknowns = [e for e in evidence if e.support_type == "unknown"]
    
    # Step 2: Compute strengths (track each)
    support_strength = sum(e.confidence for e in supports)
    refute_strength = sum(e.confidence for e in refutes)
    partial_strength = sum(e.confidence for e in partials)
    agreement_bonus = 0.08 * max(0, len(set(retrieval_sources)) - 1)
    
    # Step 3: Calculate raw score with breakdown
    baseline = 0.2
    support_component = 0.6 * support_strength
    partial_component = 0.15 * partial_strength
    refute_component = -0.55 * refute_strength
    
    raw_score = baseline + support_component + partial_component + agreement_bonus + refute_component
    
    # Store breakdown
    scoring_breakdown = {
        "baseline": baseline,
        "support_strength": round(support_strength, 4),
        "support_component": f"0.6 × {round(support_strength, 4)} = {round(support_component, 4)}",
        "partial_strength": round(partial_strength, 4),
        "partial_component": f"0.15 × {round(partial_strength, 4)} = {round(partial_component, 4)}",
        "refute_strength": round(refute_strength, 4),
        "refute_component": f"-0.55 × {round(refute_strength, 4)} = {round(refute_component, 4)}",
        "agreement_bonus": round(agreement_bonus, 4),
        "raw_score": f"{baseline} + {round(support_component, 4)} + {round(partial_component, 4)} + {round(agreement_bonus, 4)} + {round(refute_component, 4)} = {round(raw_score, 4)}",
        "raw_score_value": round(raw_score, 4)
    }
    
    # Step 4: Apply clipping and label-based adjustments
    score = round(max(0.0, min(1.0, raw_score)), 4)
    
    if refute_strength > support_strength and refute_strength >= 0.6:
        label = "contradicted"
    elif support_strength >= 0.7 and refute_strength == 0:
        label = "supported"
    elif support_strength > 0 or partial_strength > 0:
        label = "partial"
    else:
        label = "unknown"
    
    # Step 5: Apply label-based boosting
    adjustment_reason = None
    if label == "supported":
        old_score = score
        score = max(score, 0.8)
        if score > old_score:
            adjustment_reason = "Label is 'supported' → boost to min 0.8"
    elif label == "contradicted":
        old_score = score
        score = max(score, 0.75)
        if score > old_score:
            adjustment_reason = "Label is 'contradicted' → boost to min 0.75"
    elif label == "partial":
        old_score = score
        score = max(score, 0.35)
        if score > old_score:
            adjustment_reason = "Label is 'partial' → boost to min 0.35"
    
    if adjustment_reason:
        scoring_breakdown["adjustment_reason"] = adjustment_reason
        scoring_breakdown["final_score"] = score
    
    # Step 6: Generate decision threshold explanations
    decision_thresholds = {
        "why_not_contradicted": f"refute_strength ({refute_strength}) {'< 0.6 OR refute_strength <= support_strength' if not (refute_strength > support_strength and refute_strength >= 0.6) else 'triggers contradicted'}",
        "why_not_partial": f"support_strength ({support_strength}) {'< 0.7 OR refute_strength > 0' if not (support_strength >= 0.7 and refute_strength == 0) else 'triggers supported'}",
        "why_not_unknown": f"evidence exists" if (supports or refutes or partials) else "no evidence",
        "chosen_label": f"{label} (matched all thresholds)"
    }
    
    return {
        "verdict": TripleVerdict(..., label=label, score=score, ...),
        "scoring_breakdown": scoring_breakdown,
        "decision_thresholds": decision_thresholds
    }
```

**Step 2: Add Rejected Evidence Tracking**
- **File:** `src/engine.py::validate_triples_batch()`
- **Change:** Track chunks that were retrieved but not used in final verdict

```python
def validate_triples_batch(self, document_text, assertions):
    # ... ingestion ...
    
    for assertion in assertions:
        # ... retrieval ...
        ranked_results = self.fusion_engine.fuse_and_rank(results_by_source, top_k=10)
        
        # Adjudicate all chunks
        all_evidence = []
        for result in ranked_results:
            chunk = self.chunk_store.get_chunk(result.chunk_id)
            evidence_span = self._chunk_evidence_for_assertion(assertion, chunk, result.source, result.score)
            all_evidence.append((result, evidence_span))
        
        # Categorize: used vs. rejected
        used_evidence = [e for e in all_evidence if e[1].support_type != "unknown" 
                        or len([x for x in all_evidence if x[1].support_type != "unknown"]) == 0]
        rejected_evidence = [e for e in all_evidence if e not in used_evidence]
        
        # Build verdict with breakdown
        verdict_result = self._aggregate_triple_verdict(assertion, [e[1] for e in used_evidence], ...)
        
        # Attach rejected evidence
        verdict_result["rejected_evidence"] = [
            {
                "chunk_id": result.chunk_id,
                "text": result.chunk.text,
                "retrieval_score": result.score,
                "adjudication": evidence_span.support_type,
                "confidence": evidence_span.confidence,
                "reason_rejected": self._explain_rejection(evidence_span, used_evidence)
            }
            for result, evidence_span in rejected_evidence
        ]
```

**Step 3: Add Rejection Explainer**
- **File:** `src/engine.py` (or new `src/explanation/rejection_explainer.py`)

```python
def _explain_rejection(self, rejected_span: EvidenceSpan, used_evidence: List[EvidenceSpan]) -> str:
    """Explain why a chunk wasn't used in the final verdict."""
    
    if rejected_span.support_type == "unknown":
        component_matches = {
            "subject": rejected_span.matched_subject,
            "relation": rejected_span.matched_relation,
            "object": rejected_span.matched_object
        }
        matched_count = sum(component_matches.values())
        return f"Too weak to be used (only {matched_count}/3 components matched)"
    
    elif rejected_span.support_type == "partial":
        if not rejected_span.matched_relation:
            return "Relation component missing"
        elif not rejected_span.matched_subject:
            return "Subject component missing"
        elif not rejected_span.matched_object:
            return "Object component missing"
        else:
            return "Partial match, superceded by stronger evidence"
    
    else:
        # For supports/refutes
        used_with_same_type = [e for e in used_evidence if e.support_type == rejected_span.support_type]
        if used_with_same_type and rejected_span.confidence < max(e.confidence for e in used_with_same_type):
            return f"Lower confidence ({rejected_span.confidence}) than used evidence ({max(e.confidence for e in used_with_same_type)})"
        return "Superceded by stronger evidence"
```

**Step 4: Update TripleVerdict Dataclass**
- **File:** `src/models.py`

```python
@dataclass
class TripleVerdict:
    # ... existing fields ...
    
    # NEW FIELDS:
    scoring_breakdown: Optional[Dict[str, Any]] = None
    decision_thresholds: Optional[Dict[str, str]] = None
    rejected_evidence: List[Dict[str, Any]] = field(default_factory=list)
```

**Step 5: Update Serialization**
- **File:** `src/engine.py::_serialize_verdict()`

```python
def _serialize_verdict(self, verdict: TripleVerdict) -> Dict:
    return {
        # ... existing ...
        "verdict": verdict.label,
        "score": verdict.score,
        "scoring_breakdown": verdict.scoring_breakdown,
        "decision_thresholds": verdict.decision_thresholds,
        "rejected_evidence": verdict.rejected_evidence,
        # ...
    }
```

#### Testing Strategy
- Unit test: `tests/test_scoring_breakdown.py` — verify formula calculations
- Unit test: `tests/test_rejection_explainer.py` — verify rejection reasons
- Integration test: `tests/test_end_to_end_transparency.py` — full pipeline output
- Manual: Inspect output JSON for accuracy

#### Success Metrics
- ✅ Scoring breakdown shows all calculation steps
- ✅ Formula is accurate (raw_score matches manual calculation)
- ✅ Rejected evidence list is complete and reasons are accurate
- ✅ Decision thresholds explain the label decision

#### Estimated Time: 3-4 days

---

## Phase 2: Architecture - Learning & Persistence (Weeks 4-6)

### 2.1: Learning from User Feedback Loop

#### What This Does
**Current State:** Pipeline has no mechanism to learn from corrections

**After Implementation:**
```
User corrects verdict:
  Predicted: "supported" (0.85)
  Actual: "partial"
  
↓ Stored in feedback database
↓ Periodic analysis finds patterns
↓ Suggests router/classifier improvements
↓ Dashboard shows improvement metrics
```

#### Implementation Details

**Step 1: Create Feedback Storage Schema**
- **File:** `scripts/init_feedback_db.py` (NEW)
- **Database:** Add new SQLite table `feedback` or use separate `feedback.db`

```sql
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- Original prediction
    assertion_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    subject TEXT,
    relation TEXT,
    object TEXT,
    
    -- Pipeline's verdict
    predicted_label TEXT,  -- "supported", "contradicted", "partial", "unknown"
    predicted_score REAL,
    
    -- User's correction
    actual_label TEXT,
    actual_reason TEXT,  -- Optional explanation from user
    
    -- Evidence info
    used_evidence_count INTEGER,
    retrieval_sources TEXT,  -- JSON list
    
    -- Diagnostic info
    evidence_json TEXT,  -- Full evidence pack (for debugging)
    
    UNIQUE(assertion_id, document_id)
);

CREATE INDEX idx_feedback_timestamp ON feedback(timestamp);
CREATE INDEX idx_feedback_labels ON feedback(predicted_label, actual_label);
```

**Step 2: Add Feedback Recording API**
- **File:** `src/feedback/recorder.py` (NEW)

```python
from datetime import datetime
import sqlite3
import json

class FeedbackRecorder:
    def __init__(self, feedback_db_path: str = "feedback.db"):
        self.db_path = feedback_db_path
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    assertion_id TEXT,
                    document_id TEXT,
                    subject TEXT,
                    relation TEXT,
                    object TEXT,
                    predicted_label TEXT,
                    predicted_score REAL,
                    actual_label TEXT,
                    actual_reason TEXT,
                    used_evidence_count INTEGER,
                    retrieval_sources TEXT,
                    evidence_json TEXT,
                    UNIQUE(assertion_id, document_id)
                )
            """)
            conn.commit()
    
    def record_correction(
        self,
        verdict: TripleVerdict,
        actual_label: str,
        document_id: str,
        actual_reason: Optional[str] = None
    ):
        """Record when user corrects a verdict."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO feedback 
                (assertion_id, document_id, subject, relation, object,
                 predicted_label, predicted_score, actual_label, actual_reason,
                 used_evidence_count, retrieval_sources, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                verdict.assertion_id,
                document_id,
                verdict.subject,
                verdict.relation,
                verdict.object,
                verdict.label,
                verdict.score,
                actual_label,
                actual_reason,
                len(verdict.evidence),
                json.dumps(sorted(set(verdict.retrieval_sources))),
                json.dumps([
                    {
                        "chunk_id": e.chunk_id,
                        "support_type": e.support_type,
                        "confidence": e.confidence
                    }
                    for e in verdict.evidence
                ])
            ))
            conn.commit()
    
    def get_error_patterns(self, limit_days: int = 30) -> Dict[str, Any]:
        """Analyze patterns in corrections to identify systematic issues."""
        with sqlite3.connect(self.db_path) as conn:
            # Find misclassifications
            cursor = conn.execute("""
                SELECT predicted_label, actual_label, COUNT(*) as count
                FROM feedback
                WHERE datetime(timestamp) > datetime('now', '-' || ? || ' days')
                GROUP BY predicted_label, actual_label
            """, (limit_days,))
            
            confusion_matrix = {}
            for pred, actual, count in cursor.fetchall():
                if pred not in confusion_matrix:
                    confusion_matrix[pred] = {}
                confusion_matrix[pred][actual] = count
            
            return {
                "confusion_matrix": confusion_matrix,
                "total_corrections": sum(
                    sum(v.values()) for v in confusion_matrix.values()
                ),
                "accuracy": self._compute_accuracy(confusion_matrix)
            }
    
    def get_retriever_analysis(self, limit_days: int = 30) -> Dict[str, Any]:
        """Analyze which retriever combinations lead to errors."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT 
                    retrieval_sources,
                    COUNT(*) as total,
                    SUM(CASE WHEN predicted_label = actual_label THEN 1 ELSE 0 END) as correct
                FROM feedback
                WHERE datetime(timestamp) > datetime('now', '-' || ? || ' days')
                GROUP BY retrieval_sources
            """, (limit_days,))
            
            results = []
            for sources_json, total, correct in cursor.fetchall():
                sources = json.loads(sources_json)
                accuracy = correct / total if total > 0 else 0
                results.append({
                    "retrieval_sources": sources,
                    "total_cases": total,
                    "accuracy": accuracy,
                    "error_rate": 1 - accuracy
                })
            
            return sorted(results, key=lambda x: x["error_rate"], reverse=True)
```

**Step 3: Add Feedback REST Endpoints**
- **File:** `api/feedback.py` (NEW) - if using FastAPI

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/feedback", tags=["feedback"])

class CorrectionRequest(BaseModel):
    verdict_id: str
    document_id: str
    actual_label: str  # "supported", "contradicted", "partial", "unknown"
    reason: Optional[str] = None

@router.post("/correct")
async def submit_correction(req: CorrectionRequest):
    """Submit a correction to a verdict."""
    recorder = FeedbackRecorder()
    # Retrieve original verdict from cache or DB
    # Record correction
    return {"status": "recorded", "message": "Thank you for the feedback"}

@router.get("/analysis")
async def get_error_analysis(days: int = 30):
    """Get analysis of error patterns."""
    recorder = FeedbackRecorder()
    return {
        "error_patterns": recorder.get_error_patterns(days),
        "retriever_analysis": recorder.get_retriever_analysis(days)
    }
```

**Step 4: Add Analysis Dashboard Generator**
- **File:** `src/feedback/dashboard.py` (NEW)

```python
class FeedbackDashboard:
    """Generate insights from user corrections."""
    
    def compute_metrics(self, days: int = 30) -> Dict[str, Any]:
        recorder = FeedbackRecorder()
        patterns = recorder.get_error_patterns(days)
        retriever_analysis = recorder.get_retriever_analysis(days)
        
        return {
            "summary": {
                "total_corrections": patterns["total_corrections"],
                "system_accuracy": patterns["accuracy"],
                "trend": self._compute_trend(days)
            },
            "error_analysis": {
                "most_common_error": self._find_most_common_error(patterns),
                "hardest_cases": self._find_hardest_cases(patterns),
                "confusion_matrix": patterns["confusion_matrix"]
            },
            "retriever_performance": {
                "best_combination": retriever_analysis[0] if retriever_analysis else None,
                "worst_combination": retriever_analysis[-1] if retriever_analysis else None,
                "all_combinations": retriever_analysis
            },
            "recommendations": self._generate_recommendations(patterns, retriever_analysis)
        }
    
    def _generate_recommendations(self, patterns: Dict, retriever_analysis: List) -> List[str]:
        """Suggest improvements based on error patterns."""
        recommendations = []
        
        # Check for specific patterns
        if patterns["confusion_matrix"].get("partial", {}).get("supported", 0) > 3:
            recommendations.append("Consider lowering 'partial' threshold or improving negation detection")
        
        if retriever_analysis and retriever_analysis[-1]["error_rate"] > 0.5:
            bad_combo = retriever_analysis[-1]["retrieval_sources"]
            recommendations.append(f"Retriever combination {bad_combo} has high error rate - consider removing or reweighting")
        
        return recommendations
```

**Step 5: Integration with Engine**
- **File:** `src/engine.py`
- **Change:** Make it easy to record feedback

```python
class SVOVerificationEngine:
    def __init__(self, ..., feedback_recorder: Optional[FeedbackRecorder] = None):
        self.feedback_recorder = feedback_recorder or FeedbackRecorder()
    
    def validate_triples_batch(self, document_text, assertions):
        # ... existing code ...
        verdicts = []
        for verdict in verdict_results:
            verdicts.append(verdict)
            # Attach feedback endpoint
            verdict.feedback_id = self._generate_feedback_id()
        
        return {
            "verdicts": verdicts,
            "feedback_endpoint": f"/api/feedback/correct"  # Client can POST to this
        }
```

#### Data Structures
```python
# In src/models.py
@dataclass
class VerdictWithFeedback(TripleVerdict):
    feedback_id: str  # UUID to link corrections back
    can_correct: bool = True
    feedback_endpoint: Optional[str] = None
```

#### Testing Strategy
- Unit test: `tests/test_feedback_recorder.py` — verify DB operations
- Unit test: `tests/test_feedback_analysis.py` — verify pattern detection
- Integration test: `tests/test_feedback_workflow.py` — full correction flow
- Manual: Submit corrections via API, verify they appear in analysis

#### Success Metrics
- ✅ Corrections stored in DB with full context
- ✅ Error analysis correctly identifies patterns
- ✅ Recommendations are actionable
- ✅ Accuracy improves as feedback accumulates

#### Estimated Time: 4-5 days

---

### 2.2: Caching & Optimization

#### What This Does
**Current Performance:** Full pipeline ~1-2 seconds per query

**After Implementation:** 
- Cache hit (90% of queries): ~0.1 seconds
- Cache miss: ~1.5 seconds
- Average: ~0.19 seconds

#### Implementation Details

**Step 1: Create Cache Layer**
- **File:** `src/cache/cache_engine.py` (NEW)

```python
import hashlib
import sqlite3
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

@dataclass
class CacheEntry:
    key: str
    entry_type: str  # "embedding", "retrieval", "verdict", "fusion"
    value: Any
    ttl_seconds: int = 86400 * 7  # 7 days default

class CacheEngine:
    def __init__(self, cache_db_path: str = "cache.db"):
        self.db_path = cache_db_path
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    entry_type TEXT,
                    value BLOB,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    ttl_seconds INTEGER
                )
            """)
            conn.execute("CREATE INDEX idx_cache_type ON cache(entry_type)")
            conn.execute("CREATE INDEX idx_cache_created ON cache(created_at)")
            conn.commit()
    
    def _make_key(self, prefix: str, *args) -> str:
        """Generate cache key from prefix and args."""
        content = f"{prefix}:{'|'.join(str(a) for a in args)}"
        return hashlib.md5(content.encode()).hexdigest()
    
    # Embedding cache
    def get_embedding(self, text: str) -> Optional[List[float]]:
        key = self._make_key("embedding", text)
        return self._get(key)
    
    def set_embedding(self, text: str, embedding: List[float]):
        key = self._make_key("embedding", text)
        self._set(key, embedding, "embedding", ttl_seconds=86400 * 30)  # 30 days
    
    # Retrieval result cache
    def get_retrieval(self, query: str, retriever_type: str, top_k: int) -> Optional[List[Dict]]:
        key = self._make_key("retrieval", query, retriever_type, top_k)
        return self._get(key)
    
    def set_retrieval(self, query: str, retriever_type: str, top_k: int, results: List[Dict]):
        key = self._make_key("retrieval", query, retriever_type, top_k)
        self._set(key, results, "retrieval", ttl_seconds=86400 * 7)  # 7 days
    
    # Verdict cache
    def get_verdict(self, assertion_id: str, document_id: str) -> Optional[Dict]:
        key = self._make_key("verdict", assertion_id, document_id)
        return self._get(key)
    
    def set_verdict(self, assertion_id: str, document_id: str, verdict: Dict):
        key = self._make_key("verdict", assertion_id, document_id)
        self._set(key, verdict, "verdict", ttl_seconds=86400 * 14)  # 14 days
    
    def _get(self, key: str) -> Optional[Any]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT value FROM cache
                WHERE key = ?
                  AND (ttl_seconds IS NULL OR datetime(created_at, '+' || ttl_seconds || ' seconds') > datetime('now'))
            """, (key,))
            row = cursor.fetchone()
            if row:
                return pickle.loads(row[0])
        return None
    
    def _set(self, key: str, value: Any, entry_type: str, ttl_seconds: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO cache (key, entry_type, value, ttl_seconds)
                VALUES (?, ?, ?, ?)
            """, (key, entry_type, pickle.dumps(value), ttl_seconds))
            conn.commit()
    
    def clear_expired(self):
        """Remove expired entries."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                DELETE FROM cache
                WHERE ttl_seconds IS NOT NULL
                  AND datetime(created_at, '+' || ttl_seconds || ' seconds') < datetime('now')
            """)
            conn.commit()
    
    def get_stats(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT entry_type, COUNT(*) FROM cache GROUP BY entry_type")
            by_type = {row[0]: row[1] for row in cursor.fetchall()}
            
            cursor = conn.execute("SELECT COUNT(*) FROM cache")
            total = cursor.fetchone()[0]
            
            return {"total_entries": total, "by_type": by_type}
```

**Step 2: Integrate Cache with Embedding Model**
- **File:** `src/ingestion/embeddings.py`
- **Change:** Wrap embedding calls with caching

```python
class TransformerEmbeddingModel:
    def __init__(self, cache_engine: Optional[CacheEngine] = None):
        self.model = ...
        self.cache = cache_engine
    
    def embed(self, text: str) -> List[float]:
        if self.cache:
            cached = self.cache.get_embedding(text)
            if cached is not None:
                return cached
        
        embedding = self._compute_embedding(text)
        
        if self.cache:
            self.cache.set_embedding(text, embedding)
        
        return embedding
    
    def _compute_embedding(self, text: str) -> List[float]:
        # Actual embedding computation
        pass
```

**Step 3: Integrate Cache with Retrievers**
- **File:** `src/retrieval/base.py` and each retriever implementation
- **Change:** Cache retrieval results

```python
class BaseRetriever(ABC):
    def __init__(self, cache_engine: Optional[CacheEngine] = None):
        self.cache = cache_engine
    
    def retrieve(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
        if self.cache:
            cached = self.cache.get_retrieval(query, self.__class__.__name__, top_k)
            if cached is not None:
                return [RetrievalResult(**r) for r in cached]
        
        results = self._retrieve_impl(query, top_k)
        
        if self.cache:
            self.cache.set_retrieval(
                query,
                self.__class__.__name__,
                top_k,
                [asdict(r) for r in results]
            )
        
        return results
    
    @abstractmethod
    def _retrieve_impl(self, query: str, top_k: int) -> List[RetrievalResult]:
        pass
```

**Step 4: Integrate Cache with Verdict Storage**
- **File:** `src/engine.py`
- **Change:** Cache final verdicts

```python
def validate_triples_batch(self, document_text, assertions):
    # Check cache first
    cached_verdicts = []
    uncached_assertions = []
    
    for assertion in assertions:
        cached = self.cache_engine.get_verdict(
            assertion.assertion_id,
            document_id
        )
        if cached:
            cached_verdicts.append(cached)
        else:
            uncached_assertions.append(assertion)
    
    # Process only uncached
    new_verdicts = self._process_assertions(document_text, uncached_assertions)
    
    # Cache new verdicts
    for verdict in new_verdicts:
        self.cache_engine.set_verdict(
            verdict.assertion_id,
            document_id,
            asdict(verdict)
        )
    
    return cached_verdicts + new_verdicts
```

**Step 5: Batch Embedding Optimization**
- **File:** `src/ingestion/embeddings.py`
- **Change:** Support batched embedding

```python
class TransformerEmbeddingModel:
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts at once (10-100x faster)."""
        # Check cache for each
        embeddings = []
        uncached_texts = []
        uncached_indices = []
        
        for i, text in enumerate(texts):
            cached = self.cache.get_embedding(text)
            if cached:
                embeddings.append(cached)
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)
        
        # Batch embed uncached
        if uncached_texts:
            batch_embeddings = self._batch_embed(uncached_texts)
            for i, text, emb in zip(uncached_indices, uncached_texts, batch_embeddings):
                embeddings.insert(i, emb)
                self.cache.set_embedding(text, emb)
        
        return embeddings
```

#### Configuration
- **File:** `src/config.py`

```python
@dataclass
class PipelineConfig:
    # ... existing fields ...
    
    # Cache configuration
    enable_cache: bool = True
    cache_db_path: str = "cache.db"
    embedding_cache_ttl_days: int = 30
    retrieval_cache_ttl_days: int = 7
    verdict_cache_ttl_days: int = 14
    cache_clear_interval_hours: int = 24
```

#### Testing Strategy
- Unit test: `tests/test_cache_engine.py` — verify cache ops
- Integration test: `tests/test_caching_integration.py` — cache hits and misses
- Performance test: `tests/test_cache_performance.py` — measure speedup
- Manual: Run same query twice, verify second is faster

#### Success Metrics
- ✅ 90%+ cache hit rate on repeated queries
- ✅ Query latency: 0.1s for cache hit, ~1.5s for miss
- ✅ Cache expires correctly
- ✅ Average query time improves by 50%+

#### Estimated Time: 3-4 days

---

### 2.3: Multi-Modal Evidence Ingestion

#### What This Does
**Current State:** Only processes text chunks

**After Implementation:**
```
Document
  ├─ Text → Text Chunks
  ├─ Tables → Table Chunks (structured rows)
  ├─ Lists → List Item Chunks
  ├─ Structured Data → Entity/Relation Chunks
  ├─ Images → OCR'd Chunks
  └─ Knowledge Base → KB Entity Chunks

All indexed separately but retrievable together
```

#### Implementation Details

**Step 1: Define Chunk Types**
- **File:** `src/models.py`

```python
from enum import Enum

class ChunkType(str, Enum):
    TEXT = "text"
    TABLE_ROW = "table_row"
    LIST_ITEM = "list_item"
    ENTITY = "entity"
    RELATION = "relation"
    IMAGE = "image"
    KB_ENTRY = "kb_entry"

@dataclass
class Chunk:
    # ... existing fields ...
    chunk_type: ChunkType = ChunkType.TEXT
    
    # NEW: Type-specific metadata
    type_metadata: Optional[Dict[str, Any]] = None
    # For table_row: {"table_id": "t1", "row_num": 5, "headers": ["Col1", "Col2"]}
    # For entity: {"entity_type": "Drug", "properties": {...}}
    # For relation: {"rel_type": "treats", "source": "entity_id_1", "target": "entity_id_2"}
```

**Step 2: Add Table Extractor**
- **File:** `src/ingestion/table_extractor.py` (NEW)

```python
import pandas as pd
from typing import List, Tuple

class TableExtractor:
    """Extract structured data from tables."""
    
    def extract_from_html(self, html_table: str, table_id: str = None) -> List[Dict]:
        """Extract table data from HTML."""
        try:
            df = pd.read_html(html_table)[0]
        except:
            return []
        
        chunks = []
        headers = list(df.columns)
        
        for row_idx, row in df.iterrows():
            # Create a chunk per row
            row_text = " | ".join(f"{h}: {row[h]}" for h in headers)
            chunks.append({
                "type": ChunkType.TABLE_ROW,
                "text": row_text,
                "type_metadata": {
                    "table_id": table_id or f"table_{id(html_table)}",
                    "row_num": row_idx,
                    "headers": headers,
                    "values": row.to_dict()
                }
            })
        
        return chunks
    
    def extract_from_csv(self, csv_path: str) -> List[Dict]:
        """Extract from CSV file."""
        df = pd.read_csv(csv_path)
        return self._df_to_chunks(df, f"csv_{csv_path}")
    
    def _df_to_chunks(self, df: pd.DataFrame, source_id: str) -> List[Dict]:
        # Similar to extract_from_html
        pass
```

**Step 3: Add List Item Extractor**
- **File:** `src/ingestion/list_extractor.py` (NEW)

```python
import re
from typing import List, Tuple

class ListExtractor:
    """Extract list items as separate chunks."""
    
    LIST_PATTERNS = [
        r'^\s*[-•*]\s+(.+)$',  # Bullet points
        r'^\s*\d+\.\s+(.+)$',  # Numbered lists
        r'^\s*[a-z]\)\s+(.+)$',  # Lettered lists
    ]
    
    def extract_from_text(self, text: str) -> List[Dict]:
        """Find and extract list items."""
        chunks = []
        lines = text.split('\n')
        
        for line in lines:
            for pattern in self.LIST_PATTERNS:
                match = re.match(pattern, line)
                if match:
                    item_text = match.group(1).strip()
                    chunks.append({
                        "type": ChunkType.LIST_ITEM,
                        "text": item_text,
                        "type_metadata": {
                            "original_line": line,
                            "pattern": pattern
                        }
                    })
                    break
        
        return chunks
```

**Step 4: Add OCR for Images**
- **File:** `src/ingestion/image_extractor.py` (NEW)

```python
class ImageExtractor:
    """Extract text from images using OCR."""
    
    def __init__(self):
        try:
            import pytesseract
            self.ocr = pytesseract
        except ImportError:
            self.ocr = None
    
    def extract_from_image(self, image_path: str) -> Optional[Dict]:
        """Extract text from image."""
        if not self.ocr:
            return None
        
        try:
            from PIL import Image
            img = Image.open(image_path)
            text = self.ocr.image_to_string(img)
            
            return {
                "type": ChunkType.IMAGE,
                "text": text,
                "type_metadata": {
                    "image_path": image_path,
                    "confidence": 0.8  # Rough estimate
                }
            }
        except Exception as e:
            return None
```

**Step 5: Modify DataIngestor**
- **File:** `src/ingestion/pipeline.py`
- **Change:** Add multi-modal extraction

```python
class DataIngestor:
    def __init__(self, ..., table_extractor=None, list_extractor=None, image_extractor=None):
        self.text_chunker = ...
        self.table_extractor = table_extractor or TableExtractor()
        self.list_extractor = list_extractor or ListExtractor()
        self.image_extractor = image_extractor or ImageExtractor()
    
    def ingest_document(self, document_text: str, document_id: str, 
                       tables: List[str] = None, images: List[str] = None):
        """Ingest document with multiple modalities."""
        chunks = []
        
        # Text extraction
        text_chunks = self._extract_text_chunks(document_text)
        chunks.extend(text_chunks)
        
        # List extraction
        list_chunks = self.list_extractor.extract_from_text(document_text)
        chunks.extend(list_chunks)
        
        # Table extraction
        if tables:
            for table_html in tables:
                table_chunks = self.table_extractor.extract_from_html(table_html)
                chunks.extend(table_chunks)
        
        # Image extraction
        if images:
            for image_path in images:
                img_chunk = self.image_extractor.extract_from_image(image_path)
                if img_chunk:
                    chunks.append(img_chunk)
        
        # Embed all chunks
        for chunk in chunks:
            chunk.embedding = self.embedding_model.embed(chunk.text)
        
        # Store all chunks (same storage layer handles all types)
        self.chunk_store.store_chunks(chunks, document_id)
        
        return len(chunks)
```

**Step 6: Update Retrievers**
- **Files:** `src/retrieval/lexical.py`, `src/retrieval/semantic.py`, etc.
- **Change:** Handle all chunk types

```python
class SQLiteLexicalRetriever(BaseRetriever):
    def retrieve(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
        """Retrieve from all chunk types."""
        with sqlite3.connect(self.db_path) as conn:
            # Search all chunk types
            cursor = conn.execute("""
                SELECT chunk_id, text, score, chunk_type
                FROM chunks
                WHERE text LIKE ?
                   OR (chunk_type = 'entity' AND metadata LIKE ?)
                   OR (chunk_type = 'table_row' AND text LIKE ?)
                ORDER BY score DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", top_k))
            
            results = []
            for chunk_id, text, score, chunk_type in cursor.fetchall():
                results.append(RetrievalResult(
                    chunk_id=chunk_id,
                    chunk=self.chunk_store.get_chunk(chunk_id),
                    score=score,
                    source="lexical"
                ))
            
            return results
```

#### Configuration
- **File:** `src/config.py`

```python
@dataclass
class PipelineConfig:
    # ... existing ...
    
    # Multi-modal configuration
    enable_table_extraction: bool = True
    enable_list_extraction: bool = True
    enable_ocr: bool = False  # Requires pytesseract
    table_extraction_mode: str = "html"  # "html", "csv", "auto"
    min_ocr_confidence: float = 0.5
```

#### Testing Strategy
- Unit test: `tests/test_table_extractor.py` — verify table parsing
- Unit test: `tests/test_list_extractor.py` — verify list detection
- Integration test: `tests/test_multimodal_ingestion.py` — full ingestion
- Manual: Ingest document with tables/lists, verify retrieval

#### Success Metrics
- ✅ Tables extracted as separate chunks
- ✅ Lists extracted as separate chunks
- ✅ All chunk types retrievable
- ✅ Precision/recall improves for table-based queries

#### Estimated Time: 4-5 days

---

### 2.4: Temporal Reasoning

#### What This Does
**Current State:** All claims treated as timeless

**After Implementation:**
```
Claim: "Aspirin treats headaches" (temporal_scope: ["2000-present"])

Evidence: "Aspirin was approved in 1897 for pain relief"
  → Classified as "outdated_evidence" (before scope)

Evidence: "Aspirin is used today for migraines" (2024)
  → Classified as "current_evidence" (within scope)

Verdict considers temporal alignment
```

#### Implementation Details

**Step 1: Add Temporal Metadata to Models**
- **File:** `src/models.py`

```python
from datetime import datetime
from typing import Optional, Tuple

@dataclass
class TemporalScope:
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    temporal_relation: str = "during"  # "before", "after", "during"
    
    def contains(self, date: datetime) -> bool:
        if self.start_date and date < self.start_date:
            return False
        if self.end_date and date > self.end_date:
            return False
        return True

@dataclass
class OntologyAssertion:
    # ... existing fields ...
    temporal_scope: Optional[TemporalScope] = None

@dataclass
class Chunk:
    # ... existing fields ...
    timestamp: Optional[datetime] = None  # When was this chunk written?
    temporal_metadata: Optional[Dict[str, Any]] = None
    # For statements about time: {"reference_date": "1995-06-15", "certainty": "high"}
```

**Step 2: Add Temporal Extractor**
- **File:** `src/ingestion/temporal_extractor.py` (NEW)

```python
import re
from datetime import datetime

class TemporalExtractor:
    """Extract temporal information from text."""
    
    DATE_PATTERNS = [
        r'\b(?P<year>19\d{2}|20\d{2})\b',  # Year only
        r'\b(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (?P<day>\d{1,2}),? (?P<year>\d{4})\b',
        r'\b(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})\b',
    ]
    
    def extract_dates(self, text: str) -> List[datetime]:
        """Find all dates mentioned in text."""
        dates = []
        for pattern in self.DATE_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                date = self._parse_match(match)
                if date:
                    dates.append(date)
        return dates
    
    def extract_temporal_expressions(self, text: str) -> List[Dict]:
        """Find expressions like 'recently', 'in the 1990s', etc."""
        expressions = [
            {"pattern": r"recently|lately|currently|nowadays", "relative_time": "recent"},
            {"pattern": r"in the (\d+)s", "relative_time": "decade"},
            {"pattern": r"(\d+) years ago", "relative_time": "relative"},
        ]
        
        results = []
        for expr in expressions:
            for match in re.finditer(expr["pattern"], text, re.IGNORECASE):
                results.append({
                    "text": match.group(),
                    "type": expr["relative_time"],
                    "span": match.span()
                })
        
        return results
    
    def infer_document_date(self, text: str) -> Optional[datetime]:
        """Try to infer when document was written."""
        # Look for "Updated: 2024-01-15" or "Published: ..."
        patterns = [
            r"(?:Updated|Published|Written|Date):\s*(\d{4}-\d{2}-\d{2})",
            r"(?:Updated|Published|Written|Date):\s*([A-Za-z]+ \d+, \d{4})"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return self._parse_date_string(match.group(1))
        
        return None
```

**Step 3: Modify DataIngestor**
- **File:** `src/ingestion/pipeline.py`
- **Change:** Extract temporal metadata

```python
class DataIngestor:
    def __init__(self, ..., temporal_extractor=None):
        self.temporal_extractor = temporal_extractor or TemporalExtractor()
    
    def ingest_document(self, document_text: str, document_id: str):
        # ... existing code ...
        
        # Extract document date
        doc_date = self.temporal_extractor.infer_document_date(document_text)
        
        for chunk in chunks:
            # Extract dates mentioned in chunk
            dates = self.temporal_extractor.extract_dates(chunk.text)
            temporal_exprs = self.temporal_extractor.extract_temporal_expressions(chunk.text)
            
            chunk.timestamp = dates[0] if dates else doc_date
            chunk.temporal_metadata = {
                "mentioned_dates": [d.isoformat() for d in dates],
                "temporal_expressions": temporal_exprs,
                "document_date": doc_date.isoformat() if doc_date else None
            }
```

**Step 4: Add Temporal Adjudication**
- **File:** `src/classification/temporal_evidence_classifier.py` (NEW)

```python
from datetime import datetime

class TemporalEvidenceClassifier(BaseEvidenceSpanClassifier):
    """Classify evidence considering temporal scope."""
    
    def classify(self, assertion: OntologyAssertion, chunk: Chunk, 
                 source: str, retrieval_score: float = 0.0) -> EvidenceSpan:
        
        # First, do standard classification
        base_evidence = super().classify(assertion, chunk, source, retrieval_score)
        
        # Then check temporal alignment
        if assertion.temporal_scope and chunk.timestamp:
            if not assertion.temporal_scope.contains(chunk.timestamp):
                # Evidence is outside temporal scope
                temporal_status = self._classify_temporal_mismatch(
                    assertion.temporal_scope,
                    chunk.timestamp
                )
                
                # Adjust confidence
                if temporal_status == "outdated":
                    base_evidence.confidence *= 0.6  # Lower confidence for old evidence
                    base_evidence.temporal_status = "outdated"
                elif temporal_status == "future":
                    base_evidence.confidence *= 0.3  # Very low for future predictions
                    base_evidence.temporal_status = "future"
        
        return base_evidence
    
    def _classify_temporal_mismatch(self, scope: TemporalScope, chunk_date: datetime) -> str:
        if scope.start_date and chunk_date < scope.start_date:
            return "outdated"
        if scope.end_date and chunk_date > scope.end_date:
            return "future"
        return "unknown"
```

**Step 5: Update EvidenceSpan**
- **File:** `src/models.py`

```python
@dataclass
class EvidenceSpan:
    # ... existing fields ...
    temporal_status: Optional[str] = None  # "current", "outdated", "future"
    chunk_timestamp: Optional[datetime] = None
```

#### Configuration
- **File:** `src/config.py`

```python
@dataclass
class PipelineConfig:
    # ... existing ...
    
    # Temporal configuration
    enable_temporal_reasoning: bool = True
    outdated_evidence_confidence_penalty: float = 0.6  # Multiply by this
    future_evidence_confidence_penalty: float = 0.3
    default_temporal_scope_years: int = 5  # If not specified, assume last 5 years
```

#### Testing Strategy
- Unit test: `tests/test_temporal_extractor.py` — date/expression extraction
- Unit test: `tests/test_temporal_classifier.py` — temporal adjudication
- Integration test: `tests/test_temporal_reasoning.py` — full pipeline
- Manual: Test with dated claims and evidence

#### Success Metrics
- ✅ Temporal metadata extracted from documents
- ✅ Outdated evidence correctly identified
- ✅ Confidence adjusted based on temporal alignment
- ✅ Verdict changes when temporal scope is applied

#### Estimated Time: 3-4 days

---

## Phase 3: Summary & Deployment (Weeks 7-10)

### Integration & Testing

**Week 7:** Full integration testing across all improvements
- Cross-feature tests (caching + multimodal, temporal + learning, etc.)
- Performance benchmarking
- End-to-end scenario testing

**Week 8:** Documentation & deployment preparation
- Update API documentation
- Write user guides for feedback system
- Create admin dashboard for cache/feedback analysis

**Week 9:** Pilot with real users
- Beta test with 5-10 domain experts
- Collect feedback
- Fix critical issues

**Week 10:** Production rollout
- Deploy observability improvements first (lowest risk)
- Deploy caching (high impact, no breaking changes)
- Deploy learning system (requires user education)
- Deploy multi-modal and temporal (highest complexity)

---

## Timeline Overview

| Phase | Duration | Focus | Deliverables |
|-------|----------|-------|--------------|
| **Phase 1** | Weeks 1-3 | Observable improvements | Pathway visualization, scoring transparency, rejected evidence |
| **Phase 2** | Weeks 4-6 | Architecture | Feedback loop, caching, multi-modal, temporal |
| **Phase 3** | Weeks 7-10 | Integration & deployment | Testing, docs, pilot, production launch |

---

## Resource Requirements

| Role | Weeks 1-3 | Weeks 4-6 | Weeks 7-10 | Total |
|------|-----------|-----------|-----------|-------|
| Backend Engineer | 3 weeks | 3 weeks | 2 weeks | 8 weeks |
| ML Engineer | 0.5 weeks | 1.5 weeks | 1 week | 3 weeks |
| DevOps/Infrastructure | 0 weeks | 1 week | 1 week | 2 weeks |
| QA/Testing | 1 week | 1.5 weeks | 2 weeks | 4.5 weeks |

---

## Success Metrics (Post-Launch)

1. **Observable Improvements:**
   - 95%+ user satisfaction on transparency features
   - 80%+ adoption of feedback system
   - 0.5% improvement in verdict accuracy from feedback

2. **Architectural Improvements:**
   - 50%+ reduction in average query latency (via caching)
   - 15%+ improvement in accuracy (via multi-modal + temporal)
   - 1-2% accuracy gain per month (via learning loop)

3. **System Health:**
   - <99% uptime
   - Cache hit rate >90%
   - No data corruption from schema changes

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Cache invalidation bugs | Medium | High | Comprehensive testing, clear TTL policies |
| Temporal extraction failures | Medium | Medium | Fallback to heuristic dates, manual override |
| Multi-modal retrieval noise | Medium | Medium | Separate ranking per modality, weights tuning |
| Feedback loop data quality | Low | High | Human review of feedback, validation rules |
| Performance regression | Low | Medium | Benchmarking before each phase, rollback plan |

---

## File Structure Summary

```
src/
├── cache/
│   └── cache_engine.py          ← Caching layer
├── feedback/
│   ├── recorder.py              ← Feedback DB & API
│   ├── dashboard.py             ← Analysis & insights
│   └── explainer.py             ← Rejection reasons
├── ingestion/
│   ├── temporal_extractor.py    ← Date/time extraction
│   ├── table_extractor.py       ← Structured data
│   ├── list_extractor.py        ← List items
│   └── image_extractor.py       ← OCR
├── retrieval/
│   └── explainer.py             ← Retriever score explanations
├── annotation/
│   └── annotator.py             ← HTML markup generation
├── classification/
│   └── temporal_evidence_classifier.py  ← Temporal adjudication
└── models.py                    ← Updated dataclasses

api/
└── feedback.py                  ← REST endpoints for corrections

scripts/
├── init_feedback_db.py          ← Setup feedback DB
└── clear_cache.py               ← Cache maintenance

tests/
├── test_retriever_explainer.py
├── test_chunk_annotator.py
├── test_cache_engine.py
├── test_feedback_recorder.py
├── test_temporal_extractor.py
├── test_table_extractor.py
├── test_multimodal_ingestion.py
└── test_end_to_end_*.py
```

---

## Next Steps

1. **Week 1 (Start):** 
   - Review this plan with team
   - Set up git branches for each workstream
   - Begin Phase 1 implementation

2. **Ongoing:**
   - Daily standups to track progress
   - Weekly review of implementation status
   - Adjust timeline if needed based on learnings

3. **Post-Phase 1:**
   - Collect user feedback
   - Measure observable improvement impact
   - Adjust Phase 2 priorities if needed

---

**Document Version:** 1.0  
**Last Updated:** July 31, 2026  
**Owner:** Engineering Lead  
**Approval Status:** Pending
