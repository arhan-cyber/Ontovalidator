"""Core data models for the SVO verification pipeline."""

from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class ChunkType(str, Enum):
    """Modality a chunk was derived from. Text is the historical default."""

    TEXT = "text"
    TABLE_ROW = "table_row"
    LIST_ITEM = "list_item"
    ENTITY = "entity"
    RELATION = "relation"
    IMAGE = "image"
    KB_ENTRY = "kb_entry"


@dataclass
class TemporalScope:
    """Window a claim is asserted to hold over."""

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    temporal_relation: str = "during"  # "before", "after", "during"

    def contains(self, date: datetime) -> bool:
        if self.start_date and date < self.start_date:
            return False
        if self.end_date and date > self.end_date:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "temporal_relation": self.temporal_relation,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemporalScope":
        def _parse(value):
            if not value:
                return None
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(str(value))

        return cls(
            start_date=_parse(data.get("start_date")),
            end_date=_parse(data.get("end_date")),
            temporal_relation=data.get("temporal_relation", "during"),
        )


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    embedding: Optional[List[float]]
    metadata: Dict[str, Any]
    chunk_type: ChunkType = ChunkType.TEXT
    # Modality-specific payload, e.g. {"table_id": ..., "row_num": ..., "headers": [...]}
    type_metadata: Optional[Dict[str, Any]] = None
    # When the chunk's content is dated (falls back to the document's inferred date)
    timestamp: Optional[datetime] = None
    temporal_metadata: Optional[Dict[str, Any]] = None


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

    # Per-retriever scores and ranks captured before fusion collapses them.
    lexical_score: Optional[float] = None
    lexical_rank: Optional[int] = None
    semantic_score: Optional[float] = None
    semantic_rank: Optional[int] = None
    graph_score: Optional[float] = None
    graph_rank: Optional[int] = None
    retriever_sources: List[str] = field(default_factory=list)
    # Normalized inputs and weights the fused score was actually computed from.
    fusion_breakdown: Optional[Dict[str, Any]] = None


@dataclass
class OntologyAssertion:
    assertion_id: str
    subject: str
    relation: str
    object: str
    polarity: str = "must_hold"
    rule_type: str = "constraint"
    temporal_scope: Optional[TemporalScope] = None


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

    # Observability payloads attached by the engine after classification.
    retrieval_pathway: Optional[Dict[str, Any]] = None
    annotated_html: Optional[str] = None
    negation_analysis: Optional[Dict[str, Any]] = None
    component_matches: Optional[Dict[str, bool]] = None

    # Temporal adjudication (populated when temporal reasoning is enabled).
    temporal_status: Optional[str] = None  # "current", "outdated", "future"
    chunk_timestamp: Optional[datetime] = None


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

    scoring_breakdown: Optional[Dict[str, Any]] = None
    decision_thresholds: Optional[Dict[str, str]] = None
    rejected_evidence: List[Dict[str, Any]] = field(default_factory=list)
    # Correlation id a client posts back to /feedback/correct.
    feedback_id: Optional[str] = None


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

    # Carried through from EvidenceSpan so downstream judges can see
    # temporal discounting instead of only match booleans (see
    # HeuristicEvidenceJudge.judge).
    confidence: float = 1.0
    temporal_status: Optional[str] = None


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
