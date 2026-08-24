"""Main SVO verification engine orchestrator."""

import sqlite3
import logging
from typing import List, Dict, Any, Optional, Tuple
from uuid import uuid4

from .models import (
    Chunk,
    ChunkType,
    RetrievalResult,
    OntologyAssertion,
    EvidenceSpan,
    TripleVerdict,
    EvidencePack,
    EvidencePackEntry,
    JudgeVerdict,
)
from .routing import QueryRouter, MoERouter
from .retrieval import BaseRetriever, SQLiteGraphRetriever
from .retrieval.explainer import RetrieverExplainer
from .annotation.annotator import ChunkAnnotator
from .fusion import FusionEngine, WeightedFusionEngine
from .storage import ChunkStore, SQLiteChunkStore
from .validation import EvidenceValidator, MinimalValidator
from .feedback.explainer import RejectionExplainer
from .classification.evidence_judge import BaseEvidenceJudge, HeuristicEvidenceJudge
from .classification.evidence_span_classifier import BaseEvidenceSpanClassifier, HeuristicEvidenceSpanClassifier

logger = logging.getLogger(__name__)

# Verdict scoring constants, named so the breakdown can report them.
BASELINE_SCORE = 0.2
SUPPORT_WEIGHT = 0.6
PARTIAL_WEIGHT = 0.15
REFUTE_WEIGHT = -0.55
AGREEMENT_BONUS_PER_SOURCE = 0.08
CONTRADICTED_REFUTE_THRESHOLD = 0.6
SUPPORTED_SUPPORT_THRESHOLD = 0.7
LABEL_SCORE_FLOORS = {"supported": 0.8, "contradicted": 0.75, "partial": 0.35}


class SVOVerificationEngine:
    """Main verification engine that orchestrates retrieval, fusion, and validation."""

    def __init__(
        self,
        router: QueryRouter,
        lexical_store: BaseRetriever,
        semantic_store: BaseRetriever,
        graph_store: BaseRetriever,
        fusion_engine: FusionEngine,
        chunk_store: ChunkStore,
        validator: EvidenceValidator,
        triple_classifier: Optional[Any] = None,
        evidence_judge: Optional[BaseEvidenceJudge] = None,
        evidence_span_classifier: Optional[BaseEvidenceSpanClassifier] = None,
        svo_extractor: Optional[Any] = None,
        embedding_model: Optional[Any] = None,
        config: Optional[Any] = None,
        cache_engine: Optional[Any] = None,
        feedback_recorder: Optional[Any] = None,
    ):
        self.router = router
        self.lexical_store = lexical_store
        self.semantic_store = semantic_store
        self.graph_store = graph_store
        self.fusion_engine = fusion_engine
        self.chunk_store = chunk_store
        self.validator = validator
        self.triple_classifier = triple_classifier
        self.evidence_judge = evidence_judge or HeuristicEvidenceJudge()
        self.evidence_span_classifier = evidence_span_classifier or HeuristicEvidenceSpanClassifier()
        self.svo_extractor = svo_extractor
        self.embedding_model = embedding_model
        self.config = config
        self.cache_engine = cache_engine
        self.feedback_recorder = feedback_recorder
        self.retriever_explainer = RetrieverExplainer()
        self.chunk_annotator = ChunkAnnotator()
        self.rejection_explainer = RejectionExplainer()

        if config and config.verbose:
            logger.info(f"SVOVerificationEngine initialized with config: backend_mode={config.backend_mode.value}")

    @classmethod
    def from_config(cls, config: "Any") -> "SVOVerificationEngine":
        """
        Factory method to create engine from config.

        Args:
            config: PipelineConfig instance

        Returns:
            Configured SVOVerificationEngine
        """
        from .factories import EngineFactory
        return EngineFactory.create_verification_engine(config)

    def get_backend_status(self) -> Dict[str, str]:
        """Return which backends are actually active."""
        return {
            "lexical": self.lexical_store.__class__.__name__,
            "semantic": self.semantic_store.__class__.__name__,
            "graph": self.graph_store.__class__.__name__,
        }

    def verify(self, query: str, top_k: int = 10) -> Dict[str, Any]:
        return self.verify_with_ontology(query, top_k=top_k, ontology_assertions=None)

    def _build_assertion_query(self, assertion: OntologyAssertion) -> str:
        return f"{assertion.subject} {assertion.relation} {assertion.object}"

    def _chunk_evidence_for_assertion(
        self,
        assertion: OntologyAssertion,
        chunk: Chunk,
        source: str,
        retrieval_score: float = 0.0
    ) -> EvidenceSpan:
        return self.evidence_span_classifier.classify(assertion, chunk, source, retrieval_score)

    def _aggregate_triple_verdict(
        self,
        assertion: OntologyAssertion,
        evidence: List[EvidenceSpan],
        retrieval_sources: List[str],
    ) -> TripleVerdict:
        if not evidence:
            return TripleVerdict(
                assertion_id=assertion.assertion_id,
                subject=assertion.subject,
                relation=assertion.relation,
                object=assertion.object,
                label="unknown",
                score=0.1,
                rationale="No evidence was retrieved for this triple.",
                evidence=[],
                counter_evidence=[],
                retrieval_sources=retrieval_sources,
                rule_hits=["no_evidence"],
                scoring_breakdown={
                    "baseline": BASELINE_SCORE,
                    "raw_score": "no evidence retrieved",
                    "final_score": 0.1,
                    "adjustment_reason": "No evidence retrieved - fixed floor score of 0.1",
                },
                decision_thresholds={
                    "chosen_label": "unknown (no evidence retrieved)",
                },
            )

        supports = [e for e in evidence if e.support_type == "supports"]
        refutes = [e for e in evidence if e.support_type == "refutes"]
        partials = [e for e in evidence if e.support_type == "partial"]
        unknowns = [e for e in evidence if e.support_type == "unknown"]

        support_strength = sum(e.confidence for e in supports)
        refute_strength = sum(e.confidence for e in refutes)
        partial_strength = sum(e.confidence for e in partials)
        distinct_sources = len(set(retrieval_sources))
        agreement_bonus = AGREEMENT_BONUS_PER_SOURCE * max(0, distinct_sources - 1)

        support_component = SUPPORT_WEIGHT * support_strength
        partial_component = PARTIAL_WEIGHT * partial_strength
        refute_component = REFUTE_WEIGHT * refute_strength
        raw_score = (
            BASELINE_SCORE + support_component + partial_component + agreement_bonus + refute_component
        )
        score = round(max(0.0, min(1.0, raw_score)), 4)

        scoring_breakdown: Dict[str, Any] = {
            "baseline": BASELINE_SCORE,
            "support_strength": round(support_strength, 4),
            "support_component": f"{SUPPORT_WEIGHT} x {round(support_strength, 4)} = {round(support_component, 4)}",
            "partial_strength": round(partial_strength, 4),
            "partial_component": f"{PARTIAL_WEIGHT} x {round(partial_strength, 4)} = {round(partial_component, 4)}",
            "refute_strength": round(refute_strength, 4),
            "refute_component": f"{REFUTE_WEIGHT} x {round(refute_strength, 4)} = {round(refute_component, 4)}",
            "agreement_bonus": round(agreement_bonus, 4),
            "agreement_bonus_explanation": (
                f"{AGREEMENT_BONUS_PER_SOURCE} x (distinct retrieval sources {distinct_sources} - 1)"
            ),
            "raw_score": (
                f"{BASELINE_SCORE} + {round(support_component, 4)} + {round(partial_component, 4)} "
                f"+ {round(agreement_bonus, 4)} + {round(refute_component, 4)} = {round(raw_score, 4)}"
            ),
            "raw_score_value": round(raw_score, 4),
            "clipped_score": score,
            "evidence_counts": {
                "supports": len(supports),
                "refutes": len(refutes),
                "partial": len(partials),
                "unknown": len(unknowns),
            },
        }

        if refute_strength > support_strength and refute_strength >= CONTRADICTED_REFUTE_THRESHOLD:
            label = "contradicted"
        elif support_strength >= SUPPORTED_SUPPORT_THRESHOLD and refute_strength == 0:
            label = "supported"
        elif support_strength > 0 or partial_strength > 0:
            label = "partial"
        else:
            label = "unknown"

        decision_thresholds = self._explain_decision(
            label, support_strength, refute_strength, partial_strength
        )

        rule_hits = []
        if supports:
            rule_hits.append("direct_support")
        if refutes:
            rule_hits.append("explicit_negation")
        if partials:
            rule_hits.append("partial_match")
        if unknowns and not (supports or refutes or partials):
            rule_hits.append("insufficient_evidence")

        best_support = supports[0] if supports else None
        best_refute = refutes[0] if refutes else None
        if label == "supported":
            rationale = f"The triple is supported by chunk {best_support.chunk_id} with direct subject, relation, and object matches."
        elif label == "contradicted":
            rationale = f"The triple is contradicted by chunk {best_refute.chunk_id}, which contains the assertion with explicit negation or forbidden polarity."
        elif label == "partial":
            rationale = "The retrieved chunks partially match the triple, but one or more components are missing or incomplete."
        else:
            rationale = "The retrieved evidence is insufficient to determine whether the triple is correct."

        floor = LABEL_SCORE_FLOORS.get(label)
        if floor is not None and score < floor:
            scoring_breakdown["adjustment_reason"] = f"Label is '{label}' -> boost to min {floor}"
            score = floor
        scoring_breakdown["final_score"] = score

        if not self._feature_enabled("enable_scoring_breakdown"):
            scoring_breakdown = None
            decision_thresholds = None

        return TripleVerdict(
            assertion_id=assertion.assertion_id,
            subject=assertion.subject,
            relation=assertion.relation,
            object=assertion.object,
            label=label,
            score=score,
            rationale=rationale,
            evidence=evidence,
            counter_evidence=refutes,
            retrieval_sources=sorted(set(retrieval_sources)),
            rule_hits=rule_hits,
            scoring_breakdown=scoring_breakdown,
            decision_thresholds=decision_thresholds,
        )

    @staticmethod
    def _explain_decision(
        label: str,
        support_strength: float,
        refute_strength: float,
        partial_strength: float,
    ) -> Dict[str, str]:
        """State, for each label the pipeline could have chosen, why it did or did not."""
        support_strength = round(support_strength, 4)
        refute_strength = round(refute_strength, 4)
        partial_strength = round(partial_strength, 4)

        contradicted_fired = (
            refute_strength > support_strength and refute_strength >= CONTRADICTED_REFUTE_THRESHOLD
        )
        supported_fired = support_strength >= SUPPORTED_SUPPORT_THRESHOLD and refute_strength == 0

        if contradicted_fired:
            contradicted = (
                f"triggered: refute_strength ({refute_strength}) > support_strength "
                f"({support_strength}) and >= {CONTRADICTED_REFUTE_THRESHOLD}"
            )
        else:
            contradicted = (
                f"not triggered: refute_strength ({refute_strength}) is not both "
                f"> support_strength ({support_strength}) and >= {CONTRADICTED_REFUTE_THRESHOLD}"
            )

        if supported_fired:
            supported = (
                f"triggered: support_strength ({support_strength}) >= "
                f"{SUPPORTED_SUPPORT_THRESHOLD} and refute_strength == 0"
            )
        else:
            supported = (
                f"not triggered: support_strength ({support_strength}) < "
                f"{SUPPORTED_SUPPORT_THRESHOLD} or refute_strength ({refute_strength}) > 0"
            )

        if support_strength > 0 or partial_strength > 0:
            partial = (
                f"eligible: support_strength ({support_strength}) or partial_strength "
                f"({partial_strength}) is above zero"
            )
        else:
            partial = "not eligible: no supporting or partial evidence"

        return {
            "contradicted_rule": contradicted,
            "supported_rule": supported,
            "partial_rule": partial,
            "unknown_rule": (
                "reached only when no supporting, refuting, or partial evidence survives adjudication"
            ),
            "chosen_label": f"{label} (first matching rule in priority order)",
        }

    def _build_evidence_pack(
        self,
        assertion: OntologyAssertion,
        evidence: List[EvidenceSpan],
        ranked_results: List[RetrievalResult],
    ) -> EvidencePack:
        chunk_by_id = {res.chunk_id: res for res in ranked_results}
        entries = []
        for span in evidence:
            res = chunk_by_id.get(span.chunk_id)
            entries.append(
                EvidencePackEntry(
                    chunk_id=span.chunk_id,
                    text=span.text,
                    source=span.source,
                    retrieval_score=float(res.score if res else 0.0),
                    support_type=span.support_type,
                    matched_subject=span.matched_subject,
                    matched_relation=span.matched_relation,
                    matched_object=span.matched_object,
                )
            )
        graph_summary = []
        for res in ranked_results:
            if not res.chunk:
                continue
            graph_hint = res.chunk.metadata.get("graph_summary") if isinstance(res.chunk.metadata, dict) else None
            if isinstance(graph_hint, str) and graph_hint.strip():
                graph_summary.append(graph_hint.strip())
            elif isinstance(graph_hint, list):
                graph_summary.extend([str(item) for item in graph_hint if str(item).strip()])
        return EvidencePack(
            assertion_id=assertion.assertion_id,
            subject=assertion.subject,
            relation=assertion.relation,
            object=assertion.object,
            polarity=assertion.polarity,
            rule_type=assertion.rule_type,
            evidence=entries,
            graph_summary=graph_summary,
        )

    def _should_run_evidence_judge(self, heuristic_verdict: TripleVerdict, evidence_pack: EvidencePack) -> bool:
        support_count = sum(1 for e in evidence_pack.evidence if e.support_type == "supports")
        refute_count = sum(1 for e in evidence_pack.evidence if e.support_type == "refutes")
        return (
            heuristic_verdict.label in {"partial", "unknown"}
            or (support_count > 0 and refute_count > 0)
            or len(set(heuristic_verdict.retrieval_sources)) > 1
            or any("->" in item or "DEPENDS_ON" in item or "PROVIDES" in item for item in evidence_pack.graph_summary)
            or heuristic_verdict.score < 0.6
        )

    def _merge_verdicts(self, heuristic: TripleVerdict, judge: Optional[JudgeVerdict]) -> TripleVerdict:
        if judge is None:
            return heuristic
        if judge.label == heuristic.label:
            score = max(float(heuristic.score), float(judge.confidence))
        elif judge.label == "supported" and heuristic.label != "contradicted":
            score = max(float(heuristic.score), float(judge.confidence))
        elif judge.label == "contradicted" and heuristic.label != "supported":
            score = max(float(heuristic.score), float(judge.confidence))
        else:
            score = float(heuristic.score)
        final_score = round(min(1.0, max(0.0, score)), 4)
        breakdown = dict(heuristic.scoring_breakdown or {})
        breakdown["lm_judge_label"] = judge.label
        breakdown["lm_judge_confidence"] = round(float(judge.confidence), 4)
        breakdown["final_score"] = final_score
        if judge.label != heuristic.label:
            breakdown["adjustment_reason"] = (
                f"LM judge overrode heuristic label '{heuristic.label}' with '{judge.label}'"
            )

        thresholds = dict(heuristic.decision_thresholds or {})
        thresholds["lm_judge_rule"] = (
            f"LM judge returned '{judge.label}' at confidence {round(float(judge.confidence), 4)}"
        )
        thresholds["chosen_label"] = f"{judge.label} (LM judge)"

        return TripleVerdict(
            assertion_id=heuristic.assertion_id,
            subject=heuristic.subject,
            relation=heuristic.relation,
            object=heuristic.object,
            label=judge.label,
            score=final_score,
            rationale=f"Heuristic: {heuristic.rationale} LM: {judge.rationale}",
            evidence=heuristic.evidence,
            counter_evidence=heuristic.counter_evidence,
            retrieval_sources=heuristic.retrieval_sources,
            rule_hits=heuristic.rule_hits + ["lm_judge"] if judge else heuristic.rule_hits,
            scoring_breakdown=breakdown,
            decision_thresholds=thresholds,
            rejected_evidence=heuristic.rejected_evidence,
            feedback_id=heuristic.feedback_id,
        )

    def adjudicate_triple(
        self,
        document_text: Optional[str],
        assertion: OntologyAssertion,
        top_k: int = 5
    ) -> TripleVerdict:
        if document_text:
            doc_id = f"adjudicate_{abs(hash(document_text))}"
            try:
                from .ingestion import DataIngestor, SimpleEmbeddingModel, MockSVOExtractor, MockConceptExtractor
                if isinstance(self.chunk_store, SQLiteChunkStore):
                    temp_ingestor = DataIngestor(
                        sqlite_conn_path=self.chunk_store.db_path,
                        es_client=None,
                        milvus_collection=None,
                        neo4j_driver=None,
                        embedding_model=self.embedding_model or SimpleEmbeddingModel(),
                        svo_extractor=self.svo_extractor or MockSVOExtractor(),
                        concept_extractor=MockConceptExtractor(),
                        config=self.config,
                    )
                    temp_ingestor.ingest_document(doc_id, document_text)
            except Exception:
                pass

        query = self._build_assertion_query(assertion)
        if self.config and self.config.verbose:
            logger.debug(f"router diagnostics (unused for gating): {self.router.route(query)}")
        retrieval_results: List[RetrievalResult] = []
        retrieval_results.extend(self.lexical_store.retrieve(query, top_k))
        retrieval_results.extend(self.semantic_store.retrieve(query, top_k))
        retrieval_results.extend(self.graph_store.retrieve(query, top_k, max_hops=3))

        if not retrieval_results and isinstance(self.chunk_store, SQLiteChunkStore):
            conn = sqlite3.connect(self.chunk_store.db_path)
            try:
                rows = conn.execute("SELECT chunk_id FROM chunks").fetchall()
                for row in rows:
                    retrieval_results.append(RetrievalResult(chunk_id=row[0], score=0.0, source="fallback"))
            finally:
                conn.close()

        ranked = self.fusion_engine.fuse_and_rank(retrieval_results, top_k)
        materialized = self.chunk_store.get_chunks([r.chunk_id for r in ranked])
        chunk_map = {c.chunk_id: c for c in materialized}
        for res in ranked:
            res.chunk = chunk_map.get(res.chunk_id)

        adjudicated: List[Tuple[RetrievalResult, EvidenceSpan]] = []
        retrieval_sources: List[str] = []
        for res in ranked:
            if not res.chunk:
                continue
            retrieval_sources.extend(res.contributing_sources or [res.source])
            span = self._chunk_evidence_for_assertion(assertion, res.chunk, res.source, res.score)
            self._attach_observability(query, assertion, res, span)
            adjudicated.append((res, span))

        used, rejected = self._split_used_and_rejected(adjudicated)
        evidence = [span for _, span in used]

        heuristic_verdict = self._aggregate_triple_verdict(assertion, evidence, retrieval_sources)
        heuristic_verdict.rejected_evidence = self._describe_rejected(rejected, evidence)
        evidence_pack = self._build_evidence_pack(assertion, evidence, ranked)

        judge_verdict = None
        if self.evidence_judge and self._should_run_evidence_judge(heuristic_verdict, evidence_pack):
            try:
                judge_verdict = self.evidence_judge.judge(evidence_pack)
            except Exception:
                judge_verdict = None

        final_verdict = self._merge_verdicts(heuristic_verdict, judge_verdict)
        if judge_verdict is not None:
            final_verdict.rule_hits = sorted(set(final_verdict.rule_hits + ["heuristic_baseline", "evidence_judge"]))
        final_verdict.feedback_id = uuid4().hex
        return final_verdict

    def _attach_observability(
        self,
        query: str,
        assertion: OntologyAssertion,
        result: RetrievalResult,
        span: EvidenceSpan,
    ) -> None:
        """Populate the retrieval-pathway and annotation payloads on an evidence span."""
        if self._feature_enabled("enable_retrieval_pathway"):
            span.retrieval_pathway = self.retriever_explainer.build_pathway(
                query, result, span.text
            )

        if self._feature_enabled("enable_chunk_annotation"):
            try:
                annotation = self.chunk_annotator.annotate(span.text, assertion, span)
            except Exception as e:
                logger.warning(f"Chunk annotation failed for {span.chunk_id}: {e}")
                return
            span.annotated_html = annotation["annotated_html"]
            span.negation_analysis = annotation["negation_analysis"]
            span.component_matches = annotation["component_matches"]

    def _feature_enabled(self, flag: str) -> bool:
        return bool(getattr(self.config, flag, True)) if self.config else True

    @staticmethod
    def _split_used_and_rejected(
        adjudicated: List[Tuple[RetrievalResult, EvidenceSpan]],
    ) -> Tuple[List[Tuple[RetrievalResult, EvidenceSpan]], List[Tuple[RetrievalResult, EvidenceSpan]]]:
        """Keep evidence that took a stance; set aside the rest as rejected.

        Chunks classified "unknown" contribute nothing to the score, so holding
        them back keeps them out of the judge's prompt while still reporting
        them to the caller. If nothing took a stance, every chunk is kept so
        the verdict is still explained by what was actually retrieved.
        """
        informative = [pair for pair in adjudicated if pair[1].support_type != "unknown"]
        if not informative:
            return adjudicated, []
        rejected = [pair for pair in adjudicated if pair[1].support_type == "unknown"]
        return informative, rejected

    def _describe_rejected(
        self,
        rejected: List[Tuple[RetrievalResult, EvidenceSpan]],
        used_evidence: List[EvidenceSpan],
    ) -> List[Dict[str, Any]]:
        if not rejected or not self._feature_enabled("enable_rejected_evidence"):
            return []
        return [
            {
                "chunk_id": span.chunk_id,
                "text": span.text,
                "retrieval_score": round(float(result.score), 4),
                "adjudication": span.support_type,
                "confidence": round(float(span.confidence), 4),
                "reason_rejected": self.rejection_explainer.explain(span, used_evidence),
            }
            for result, span in rejected
        ]

    def export_triple_adjudication(
        self,
        verdict: TripleVerdict,
        writer: Any,
        document_id: str = "unknown_document",
    ) -> None:
        from .classification import triple_verdict_to_example
        example = triple_verdict_to_example(verdict, document_id=document_id)
        writer.write_example(example)

    def export_training_examples(
        self,
        document_id: str,
        assertions: List[OntologyAssertion],
        writer: Any,
        top_k: int = 5,
        document_text: Optional[str] = None,
    ) -> List[TripleVerdict]:
        verdicts = []
        for assertion in assertions:
            verdict = self.adjudicate_triple(
                document_text=document_text,
                assertion=assertion,
                top_k=top_k,
            )
            self.export_triple_adjudication(verdict, writer, document_id=document_id)
            verdicts.append(verdict)
        return verdicts

    def verify_with_ontology(
        self,
        query: str,
        top_k: int = 10,
        ontology_assertions: Optional[List[OntologyAssertion]] = None
    ) -> Dict[str, Any]:
        if self.config and self.config.verbose:
            logger.debug(f"router diagnostics (unused for gating): {self.router.route(query)}")
        all_results = []
        all_results.extend(self.lexical_store.retrieve(query, top_k))
        all_results.extend(self.semantic_store.retrieve(query, top_k))
        all_results.extend(self.graph_store.retrieve(query, top_k, max_hops=3))

        if ontology_assertions and not all_results and isinstance(self.chunk_store, SQLiteChunkStore):
            conn = sqlite3.connect(self.chunk_store.db_path)
            try:
                chunk_ids = [row[0] for row in conn.execute("SELECT chunk_id FROM chunks").fetchall()]
            finally:
                conn.close()
            all_results.extend([
                RetrievalResult(chunk_id=chunk_id, score=0.0, source="fallback")
                for chunk_id in chunk_ids
            ])

        ranked_results = self.fusion_engine.fuse_and_rank(all_results, top_k)

        chunk_ids = [res.chunk_id for res in ranked_results]
        materialized_chunks = self.chunk_store.get_chunks(chunk_ids)

        chunk_map = {c.chunk_id: c for c in materialized_chunks}
        for res in ranked_results:
            res.chunk = chunk_map.get(res.chunk_id)

        verification_output = self.validator.validate(query, ranked_results, ontology_assertions=ontology_assertions)
        return verification_output

    def validate_triples_batch(
        self,
        document_id: str,
        raw_text: str,
        triples: List[OntologyAssertion],
        top_k: int = 5
    ) -> Dict[str, Any]:
        """
        End-to-end pipeline: ingest document + validate all triples.

        Args:
            document_id: Unique document identifier
            raw_text: Raw document text
            triples: List of OntologyAssertion to validate
            top_k: Number of top chunks to consider per triple

        Returns:
            Dict with ingestion status, verdicts for each triple, and summary statistics
        """
        from .ingestion import DataIngestor, SimpleEmbeddingModel, MockSVOExtractor, MockConceptExtractor

        # Use configured models if available, otherwise fall back to defaults
        if self.svo_extractor is None:
            svo_extractor = MockSVOExtractor()
        else:
            svo_extractor = self.svo_extractor
            if self.config and self.config.verbose:
                logger.info(f"Using configured SVO extractor: {svo_extractor.__class__.__name__}")

        if self.embedding_model is None:
            embedding_model = SimpleEmbeddingModel()
        else:
            embedding_model = self.embedding_model
            if self.config and self.config.verbose:
                logger.info(f"Using configured embedding model: {embedding_model.__class__.__name__}")

        # Create concept extractor from config
        if self.config and self.config.concept_extractor_name == "transformer":
            try:
                from .ingestion.extractors import TransformerConceptExtractor
                concept_extractor = TransformerConceptExtractor(
                    model_name=self.config.concept_extractor_model_name or "google/flan-t5-large"
                )
                if self.config.verbose:
                    logger.info("Using TransformerConceptExtractor")
            except Exception as e:
                logger.warning(f"Failed to create TransformerConceptExtractor: {e}. Using MockConceptExtractor.")
                concept_extractor = MockConceptExtractor()
        else:
            concept_extractor = MockConceptExtractor()

        # Get backend clients from configured retrievers if they're production types
        es_client = None
        milvus_collection = None
        neo4j_driver = None

        # Try to extract clients from production retrievers
        if hasattr(self.lexical_store, 'client'):
            es_client = self.lexical_store.client
        if hasattr(self.semantic_store, 'collection'):
            milvus_collection = self.semantic_store.collection
        if hasattr(self.graph_store, 'driver'):
            neo4j_driver = self.graph_store.driver

        # Step 1: Ingest the document
        ingestor = DataIngestor(
            sqlite_conn_path=self.chunk_store.db_path,
            es_client=es_client,
            milvus_collection=milvus_collection,
            neo4j_driver=neo4j_driver,
            embedding_model=embedding_model,
            svo_extractor=svo_extractor,
            concept_extractor=concept_extractor,
            config=self.config,
        )

        ingestion_result = ingestor.ingest_document(document_id, raw_text)

        # Step 2: Validate each triple, reusing any still-valid cached verdict.
        # The cache key includes a digest of raw_text, so re-posting a changed
        # document under the same id re-runs the pipeline instead of replaying
        # the previous answer.
        document_fingerprint = self._document_fingerprint(raw_text)
        verdicts = []
        cache_hits = 0
        for triple in triples:
            cached = self._cached_verdict(triple.assertion_id, document_id, document_fingerprint)
            if cached is not None:
                cache_hits += 1
                verdicts.append(cached)
                continue

            verdict = self.adjudicate_triple(
                document_text=None,  # Already ingested
                assertion=triple,
                top_k=top_k
            )
            verdict_dict = self._serialize_verdict(verdict)
            self._store_verdict(verdict, verdict_dict, document_id, document_fingerprint)
            verdicts.append(verdict_dict)

        # Step 3: Compute summary statistics
        summary = {
            "total_triples": len(triples),
            "supported": sum(1 for v in verdicts if v["label"] == "supported"),
            "contradicted": sum(1 for v in verdicts if v["label"] == "contradicted"),
            "partial": sum(1 for v in verdicts if v["label"] == "partial"),
            "unknown": sum(1 for v in verdicts if v["label"] == "unknown"),
            "avg_score": sum(v["score"] for v in verdicts) / len(verdicts) if verdicts else 0.0,
            "cache_hits": cache_hits,
        }

        return {
            "document_id": document_id,
            "ingestion_status": ingestion_result["status"],
            "chunks_ingested": ingestion_result.get("chunks", 0),
            "svos_extracted": ingestion_result.get("svos", 0),
            "chunk_types": ingestion_result.get("chunk_types", {}),
            "verdicts": verdicts,
            "summary": summary,
            "backend_status": self.get_backend_status(),
        }

    @staticmethod
    def _document_fingerprint(raw_text: str) -> str:
        from .cache.cache_engine import CacheEngine
        return CacheEngine.fingerprint(raw_text)

    def _cached_verdict(
        self,
        assertion_id: str,
        document_id: str,
        document_fingerprint: str,
    ) -> Optional[Dict[str, Any]]:
        if self.cache_engine is None:
            return None
        return self.cache_engine.get_verdict(assertion_id, document_id, document_fingerprint)

    def _store_verdict(
        self,
        verdict: TripleVerdict,
        verdict_dict: Dict[str, Any],
        document_id: str,
        document_fingerprint: str,
    ) -> None:
        if self.cache_engine is None:
            return
        ttl_days = getattr(self.config, "verdict_cache_ttl_days", 14) if self.config else 14
        self.cache_engine.set_verdict(
            verdict.assertion_id,
            document_id,
            verdict_dict,
            document_fingerprint,
            ttl_seconds=ttl_days * 86400,
        )
        if verdict.feedback_id:
            # Lets POST /feedback/correct resolve a correction back to the
            # original verdict without the client resending it.
            self.cache_engine.set(
                "feedback_verdict",
                {"verdict": verdict_dict, "document_id": document_id},
                verdict.feedback_id,
                ttl_seconds=ttl_days * 86400,
            )

    def _serialize_verdict(self, verdict: TripleVerdict) -> Dict[str, Any]:
        """JSON-serializable form of a verdict, including the transparency payloads."""
        return {
            "assertion_id": verdict.assertion_id,
            "subject": verdict.subject,
            "relation": verdict.relation,
            "object": verdict.object,
            "label": verdict.label,
            "score": float(verdict.score),
            "rationale": verdict.rationale,
            "evidence": [self._serialize_evidence(span) for span in verdict.evidence],
            "rule_hits": verdict.rule_hits,
            "retrieval_sources": sorted(set(verdict.retrieval_sources)),
            "scoring_breakdown": verdict.scoring_breakdown,
            "decision_thresholds": verdict.decision_thresholds,
            "rejected_evidence": verdict.rejected_evidence,
            "feedback_id": verdict.feedback_id,
        }

    @staticmethod
    def _serialize_evidence(span: EvidenceSpan) -> Dict[str, Any]:
        return {
            "chunk_id": span.chunk_id,
            "text": span.text,
            "source": span.source,
            "confidence": float(span.confidence),
            "match_type": span.support_type,
            "matched": {
                "subject": span.matched_subject,
                "relation": span.matched_relation,
                "object": span.matched_object,
            },
            "retrieval_pathway": span.retrieval_pathway,
            "annotated_html": span.annotated_html,
            "negation_analysis": span.negation_analysis,
            "component_matches": span.component_matches,
            "temporal_status": span.temporal_status,
            "chunk_timestamp": span.chunk_timestamp.isoformat() if span.chunk_timestamp else None,
        }

    def record_feedback(
        self,
        verdict: TripleVerdict,
        actual_label: str,
        document_id: str,
        actual_reason: Optional[str] = None,
    ) -> bool:
        """Record a user correction. Returns False when no recorder is configured."""
        if self.feedback_recorder is None:
            return False
        self.feedback_recorder.record_correction(
            verdict=verdict,
            actual_label=actual_label,
            document_id=document_id,
            actual_reason=actual_reason,
        )
        return True
