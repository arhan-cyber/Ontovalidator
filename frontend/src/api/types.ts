export interface TemporalScopeIn {
  start_date?: string | null;
  end_date?: string | null;
  temporal_relation?: string;
}

export interface TripleIn {
  assertion_id?: string | null;
  subject: string;
  relation: string;
  object: string;
  polarity?: string;
  rule_type?: string;
  temporal_scope?: TemporalScopeIn | null;
}

export interface ValidateRequest {
  document_id?: string | null;
  raw_text: string;
  triples: TripleIn[];
  top_k?: number;
  embedding_model?: string | null;
  svo_extractor?: string | null;
}

export interface MatchedOut {
  subject: boolean;
  relation: boolean;
  object: boolean;
}

export interface PathwayRetriever {
  rank: number | null;
  score: number | null;
  reason: string;
}

export interface RetrievalPathway {
  lexical: PathwayRetriever;
  semantic: PathwayRetriever;
  graph: PathwayRetriever;
  retriever_sources: string[];
  fusion_score: number;
  fusion_explanation: string;
}

export interface NegationAnalysis {
  negation_detected?: boolean;
  negation_keywords?: string[];
  negation_scope?: string[];
  [key: string]: unknown;
}

export interface EvidenceOut {
  chunk_id: string;
  text: string;
  source: string;
  confidence: number;
  match_type: string;
  matched: MatchedOut;
  retrieval_pathway?: RetrievalPathway | null;
  annotated_html?: string | null;
  negation_analysis?: NegationAnalysis | null;
  component_matches?: Record<string, boolean> | null;
  temporal_status?: string | null;
  chunk_timestamp?: string | null;
}

export interface RejectedEvidenceOut {
  chunk_id: string;
  text: string;
  retrieval_score: number;
  adjudication: string;
  confidence: number;
  reason_rejected: string;
}

export interface VerdictOut {
  assertion_id: string;
  subject: string;
  relation: string;
  object: string;
  label: "supported" | "contradicted" | "partial" | "unknown" | string;
  score: number;
  rationale: string;
  evidence: EvidenceOut[];
  rule_hits: string[];
  retrieval_sources: string[];
  scoring_breakdown?: Record<string, unknown> | null;
  decision_thresholds?: Record<string, string> | null;
  rejected_evidence: RejectedEvidenceOut[];
  feedback_id?: string | null;
}

export interface SummaryOut {
  total_triples: number;
  supported: number;
  contradicted: number;
  partial: number;
  unknown: number;
  avg_score: number;
  cache_hits: number;
  errors: number;
}

export interface BackendStatusOut {
  lexical: string;
  semantic: string;
  graph: string;
}

export interface ValidateResponse {
  document_id: string;
  ingestion_status: string;
  chunks_ingested: number;
  svos_extracted: number;
  chunk_types: Record<string, number>;
  verdicts: VerdictOut[];
  summary: SummaryOut;
  backend_status: BackendStatusOut;
}

export interface CorrectionRequest {
  feedback_id?: string | null;
  actual_label: string;
  reason?: string | null;
  document_id?: string | null;
  assertion_id?: string | null;
  subject?: string | null;
  relation?: string | null;
  object?: string | null;
  predicted_label?: string | null;
  predicted_score?: number | null;
  retrieval_sources?: string[] | null;
}

export interface CorrectionResponse {
  status: string;
  assertion_id: string;
  document_id: string;
  predicted_label: string;
  actual_label: string;
}

export interface FeedbackSummary {
  total_corrections: number;
  system_accuracy: number;
  window_days: number;
}

export type ConfusionMatrix = Record<string, Record<string, number>>;

export interface MostCommonError {
  predicted: string;
  actual: string;
  count: number;
}

export interface RetrieverCombinationStats {
  retrieval_sources: string[];
  total_cases: number;
  accuracy: number;
  error_rate: number;
}

export interface RetrieverPerformance {
  best_combination: RetrieverCombinationStats | null;
  worst_combination: RetrieverCombinationStats | null;
  all_combinations: RetrieverCombinationStats[];
}

export interface FeedbackAnalysisResponse {
  summary: FeedbackSummary;
  error_analysis: {
    most_common_error: MostCommonError | null;
    confusion_matrix: ConfusionMatrix;
  };
  retriever_performance: RetrieverPerformance;
  recommendations: string[];
}

export interface BackendHealthOut {
  backend_name: string;
  is_healthy: boolean;
  latency_ms?: number | null;
  error_message?: string | null;
  timestamp?: string | null;
}

export interface HealthResponse {
  timestamp: string;
  overall_status: string;
  backends: Record<string, BackendHealthOut>;
  recommendations: string[];
}

export interface ConfigResponse {
  backend_mode: string;
  sqlite_path: string;
  embedding_model_name: string;
  svo_extractor_name: string;
  validator_name: string;
  enable_lm_judge: boolean;
  enable_lm_classifier: boolean;
  backend_status: BackendStatusOut;
  available_embedding_models: string[];
  available_svo_extractors: string[];
}

// --- Ontology compliance ---------------------------------------------------

export type Severity = "error" | "warning" | "info";
export type ConflictStatus =
  | "open"
  | "ontology_defect"
  | "metamodel_gap"
  | "accepted_exception";

export interface ConformanceFinding {
  rule_id: string;
  severity: Severity;
  subject_kind: "node" | "edge" | "graph";
  subject_id: string;
  message: string;
  evidence: string | null;
  remediation: string | null;
  degraded: boolean;
  degraded_reason: string | null;
  metadata: Record<string, unknown> | null;
}

export interface GroundingRollup {
  status: "supported" | "partial" | "contradicted" | "unknown";
  supported: number;
  partial: number;
  contradicted: number;
  unknown: number;
  total: number;
  assertion_ids: string[];
}

export interface VocabularyGap {
  measured: boolean;
  terms_total?: number;
  terms_present?: number;
  terms_absent?: number;
  present_pct?: number;
  absent_terms?: string[];
}

export interface OntologyReport {
  passed: boolean;
  ontology_version: string;
  metamodel_version: string;
  ontology_path: string | null;
  metamodel_path: string | null;
  conformance: {
    passed: boolean;
    by_severity: Record<Severity, number>;
    by_rule: Record<string, number>;
    unreviewed_conflicts: number;
    findings: ConformanceFinding[];
  };
  grounding: {
    ran: boolean;
    passed: boolean;
    /** "low" on the SQLite demo tier: `supported` is unreachable there. */
    confidence: "not_run" | "low" | "normal";
    retrieval_backends: Record<string, string>;
    corpus_documents: string[];
    corpus_fingerprint: string | null;
    by_label: Record<string, number>;
    coverage: {
      nodes_total: number;
      nodes_with_evidence: number;
      nodes_pct: number;
      edges_total: number;
      edges_with_evidence: number;
      edges_pct: number;
    };
    vocabulary_gap: VocabularyGap;
    contradictions: Array<Record<string, unknown>>;
    node_grounding: Record<string, GroundingRollup>;
    edge_grounding: Record<string, GroundingRollup>;
  };
  node_status: Record<
    string,
    { conformance: "pass" | "fail"; failed_rules: string[]; grounding: string }
  >;
}

export interface OntologyValidateRequest {
  plane?: "a" | "b" | "both";
  severity_threshold?: Severity;
  include_it4it?: boolean;
  top_k?: number;
  claim_kinds?: string[];
}

export interface OntologyNode {
  id: string;
  meta_class: string;
  types: string[];
  description: string;
  next_pointer: string[];
}

export interface OntologyEdge {
  source: string;
  target: string;
  type: string;
  key: string;
}

export interface OntologyGraphResponse {
  version: string;
  nodes: OntologyNode[];
  edges: OntologyEdge[];
}

export interface Conflict {
  conflict_id: string;
  first_seen: string;
  last_seen: string;
  rule_id: string;
  subject_kind: string;
  subject_id: string;
  ontology_says: string;
  metamodel_says: string;
  status: ConflictStatus;
  resolution_note: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  occurrences: number;
}

export interface ConflictsResponse {
  conflicts: Conflict[];
  unreviewed: number;
}

export interface Amendment {
  conflict_id: string;
  rule_id: string;
  subject_id: string;
  field: string | null;
  add_value: string;
  changes: Array<{ field: string; add_values: string[]; current_values: string[] }>;
  metamodel_says: string;
  ontology_says: string;
  resolution_note: string | null;
}
