"""Pydantic request/response models for the FastAPI wrapper."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TripleIn(BaseModel):
    assertion_id: Optional[str] = None
    subject: str
    relation: str
    object: str
    polarity: str = "must_hold"
    rule_type: str = "constraint"


class ValidateRequest(BaseModel):
    document_id: Optional[str] = None
    raw_text: str
    triples: List[TripleIn] = Field(min_length=1)
    top_k: int = 5
    embedding_model: Optional[str] = None
    svo_extractor: Optional[str] = None


class MatchedOut(BaseModel):
    subject: bool
    relation: bool
    object: bool


class EvidenceOut(BaseModel):
    chunk_id: str
    text: str
    source: str
    confidence: float
    match_type: str
    matched: MatchedOut
    retrieval_pathway: Optional[Dict[str, Any]] = None
    annotated_html: Optional[str] = None
    negation_analysis: Optional[Dict[str, Any]] = None
    component_matches: Optional[Dict[str, bool]] = None
    temporal_status: Optional[str] = None
    chunk_timestamp: Optional[str] = None


class RejectedEvidenceOut(BaseModel):
    chunk_id: str
    text: str
    retrieval_score: float
    adjudication: str
    confidence: float
    reason_rejected: str


class VerdictOut(BaseModel):
    assertion_id: str
    subject: str
    relation: str
    object: str
    label: str
    score: float
    rationale: str
    evidence: List[EvidenceOut]
    rule_hits: List[str]
    retrieval_sources: List[str]
    scoring_breakdown: Optional[Dict[str, Any]] = None
    decision_thresholds: Optional[Dict[str, str]] = None
    rejected_evidence: List[RejectedEvidenceOut] = Field(default_factory=list)
    feedback_id: Optional[str] = None


class SummaryOut(BaseModel):
    total_triples: int
    supported: int
    contradicted: int
    partial: int
    unknown: int
    avg_score: float
    cache_hits: int = 0


class BackendStatusOut(BaseModel):
    lexical: str
    semantic: str
    graph: str


class ValidateResponse(BaseModel):
    document_id: str
    ingestion_status: str
    chunks_ingested: int
    svos_extracted: int
    chunk_types: Dict[str, int] = Field(default_factory=dict)
    verdicts: List[VerdictOut]
    summary: SummaryOut
    backend_status: BackendStatusOut


class CorrectionRequest(BaseModel):
    """A user's correction of a verdict.

    `feedback_id` alone is enough while the original verdict is still cached;
    the remaining fields let a client resend it once the cache has expired.
    """

    feedback_id: Optional[str] = None
    actual_label: str
    reason: Optional[str] = None
    document_id: Optional[str] = None
    assertion_id: Optional[str] = None
    subject: Optional[str] = None
    relation: Optional[str] = None
    object: Optional[str] = None
    predicted_label: Optional[str] = None
    predicted_score: Optional[float] = None
    retrieval_sources: Optional[List[str]] = None


class CorrectionResponse(BaseModel):
    status: str
    assertion_id: str
    document_id: str
    predicted_label: str
    actual_label: str


class FeedbackAnalysisResponse(BaseModel):
    summary: Dict[str, Any]
    error_analysis: Dict[str, Any]
    retriever_performance: Dict[str, Any]
    recommendations: List[str]


class BackendHealthOut(BaseModel):
    backend_name: str
    is_healthy: bool
    latency_ms: Optional[float] = None
    error_message: Optional[str] = None
    timestamp: Optional[str] = None


class HealthResponse(BaseModel):
    timestamp: str
    overall_status: str
    backends: Dict[str, BackendHealthOut]
    recommendations: List[str]


class ConfigResponse(BaseModel):
    backend_mode: str
    sqlite_path: str
    embedding_model_name: str
    svo_extractor_name: str
    validator_name: str
    enable_lm_judge: bool
    enable_lm_classifier: bool
    backend_status: BackendStatusOut
    available_embedding_models: List[str]
    available_svo_extractors: List[str]
