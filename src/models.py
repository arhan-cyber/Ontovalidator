"""Core data models for the SVO verification pipeline."""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    embedding: Optional[List[float]]
    metadata: Dict[str, Any]


@dataclass
class SVORelation:
    subject_id: str
    subject_name_type: str
    relation: str
    object_id: str
    object_name_type: str
    source_chunk_ids: List[str]


@dataclass
class RetrievalResult:
    chunk_id: str
    score: float
    source: str  # 'lexical', 'semantic', 'graph', or 'fusion'
    chunk: Optional[Chunk] = None
    contributing_sources: List[str] = field(default_factory=list)


@dataclass
class OntologyAssertion:
    assertion_id: str
    subject: str
    relation: str
    object: str
    polarity: str = "must_hold"
    rule_type: str = "constraint"


@dataclass
class ViolationRecord:
    assertion_id: str
    chunk_id: str
    violation_type: str
    confidence: float
    evidence: str
    matched_text: str
    source: str = "validator"


@dataclass
class EvidenceSpan:
    chunk_id: str
    text: str
    source: str
    support_type: str
    confidence: float
    matched_subject: bool
    matched_relation: bool
    matched_object: bool


@dataclass
class TripleVerdict:
    assertion_id: str
    subject: str
    relation: str
    object: str
    label: str
    score: float
    rationale: str
    evidence: List[EvidenceSpan]
    counter_evidence: List[EvidenceSpan]
    retrieval_sources: List[str]
    rule_hits: List[str]


@dataclass
class EvidencePackEntry:
    chunk_id: str
    text: str
    source: str
    retrieval_score: float
    support_type: str
    matched_subject: bool
    matched_relation: bool
    matched_object: bool


@dataclass
class EvidencePack:
    assertion_id: str
    subject: str
    relation: str
    object: str
    polarity: str
    rule_type: str
    evidence: List[EvidencePackEntry]
    graph_summary: List[str]


@dataclass
class JudgeVerdict:
    label: str
    confidence: float
    rationale: str
    evidence_chunk_ids: List[str]
    counterevidence_chunk_ids: List[str]
    graph_reasoning: Optional[str] = None


class QueryType(Enum):
    EXACT_MATCH = "exact_match"
    COMPLEX = "complex"
    MULTI_HOP = "multi_hop"
    ONTOLOGY = "ontology"
