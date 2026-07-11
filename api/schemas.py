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


class SummaryOut(BaseModel):
    total_triples: int
    supported: int
    contradicted: int
    partial: int
    unknown: int
    avg_score: float


class BackendStatusOut(BaseModel):
    lexical: str
    semantic: str
    graph: str


class ValidateResponse(BaseModel):
    document_id: str
    ingestion_status: str
    chunks_ingested: int
    svos_extracted: int
    verdicts: List[VerdictOut]
    summary: SummaryOut
    backend_status: BackendStatusOut


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
