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
  keywords?: string[];
  scope?: string;
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
