"""Main SVO verification engine orchestrator."""

import re
import sqlite3
from typing import List, Dict, Any, Optional

from .models import (
    QueryType,
    Chunk,
    RetrievalResult,
    OntologyAssertion,
    EvidenceSpan,
    TripleVerdict,
)
from .routing import QueryRouter, MoERouter
from .retrieval import BaseRetriever, SQLiteGraphRetriever
from .fusion import FusionEngine, WeightedFusionEngine
from .storage import ChunkStore, SQLiteChunkStore
from .validation import EvidenceValidator, MinimalValidator


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
        triple_classifier: Optional[Any] = None
    ):
        self.router = router
        self.lexical_store = lexical_store
        self.semantic_store = semantic_store
        self.graph_store = graph_store
        self.fusion_engine = fusion_engine
        self.chunk_store = chunk_store
        self.validator = validator
        self.triple_classifier = triple_classifier

    def verify(self, query: str, top_k: int = 10) -> Dict[str, Any]:
        return self.verify_with_ontology(query, top_k=top_k, ontology_assertions=None)

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.lower()).strip()

    def _build_assertion_query(self, assertion: OntologyAssertion) -> str:
        return f"{assertion.subject} {assertion.relation} {assertion.object}"

    def _chunk_evidence_for_assertion(
        self,
        assertion: OntologyAssertion,
        chunk: Chunk,
        source: str,
        retrieval_score: float = 0.0
    ) -> EvidenceSpan:
        text = self._normalize(chunk.text)
        subject = self._normalize(assertion.subject)
        relation = self._normalize(assertion.relation)
        obj = self._normalize(assertion.object)
        matched_subject = bool(subject and subject in text)
        matched_relation = bool(relation and relation in text)
        matched_object = bool(obj and obj in text)
        negation = any(token in text for token in [" not ", "no ", "without ", "never ", "fails to", "does not", "cannot"])

        if matched_subject and matched_relation and matched_object:
            support_type = "refutes" if (negation or assertion.polarity == "must_not_hold") else "supports"
            confidence = 0.95 if support_type == "supports" else 0.9
        elif matched_subject and matched_relation:
            support_type = "partial"
            confidence = 0.7
        elif matched_subject or matched_object:
            support_type = "partial"
            confidence = 0.5
        else:
            support_type = "unknown"
            confidence = 0.2

        confidence = min(1.0, max(confidence, retrieval_score))
        return EvidenceSpan(
            chunk_id=chunk.chunk_id,
            text=chunk.text,
            source=source,
            support_type=support_type,
            confidence=round(confidence, 4),
            matched_subject=matched_subject,
            matched_relation=matched_relation,
            matched_object=matched_object,
        )

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
            )

        supports = [e for e in evidence if e.support_type == "supports"]
        refutes = [e for e in evidence if e.support_type == "refutes"]
        partials = [e for e in evidence if e.support_type == "partial"]
        unknowns = [e for e in evidence if e.support_type == "unknown"]

        support_strength = sum(e.confidence for e in supports)
        refute_strength = sum(e.confidence for e in refutes)
        partial_strength = sum(e.confidence for e in partials)
        agreement_bonus = 0.08 * max(0, len(set(retrieval_sources)) - 1)

        raw_score = 0.2 + 0.6 * support_strength + 0.15 * partial_strength + agreement_bonus - 0.55 * refute_strength
        score = round(max(0.0, min(1.0, raw_score)), 4)

        if refute_strength > support_strength and refute_strength >= 0.6:
            label = "contradicted"
        elif support_strength >= 0.7 and refute_strength == 0:
            label = "supported"
        elif support_strength > 0 or partial_strength > 0:
            label = "partial"
        else:
            label = "unknown"

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

        if label == "supported":
            score = max(score, 0.8)
        elif label == "contradicted":
            score = max(score, 0.75)
        elif label == "partial":
            score = max(score, 0.35)

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
                        embedding_model=SimpleEmbeddingModel(),
                        svo_extractor=MockSVOExtractor(),
                        concept_extractor=MockConceptExtractor(),
                    )
                    temp_ingestor.ingest_document(doc_id, document_text)
            except Exception:
                pass

        query = self._build_assertion_query(assertion)
        query_types = self.router.route(query)
        retrieval_results: List[RetrievalResult] = []
        if QueryType.EXACT_MATCH in query_types:
            retrieval_results.extend(self.lexical_store.retrieve(query, top_k))
        if QueryType.COMPLEX in query_types:
            retrieval_results.extend(self.semantic_store.retrieve(query, top_k))
        if QueryType.MULTI_HOP in query_types or QueryType.ONTOLOGY in query_types:
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

        evidence: List[EvidenceSpan] = []
        retrieval_sources: List[str] = []
        for res in ranked:
            if not res.chunk:
                continue
            retrieval_sources.append(res.source)
            evidence.append(self._chunk_evidence_for_assertion(assertion, res.chunk, res.source, res.score))

        if self.triple_classifier and evidence:
            try:
                from .classification import AssertionInput
                lm_candidates = []
                for res in ranked:
                    if not res.chunk:
                        continue
                    lm_result = self.triple_classifier.classify(
                        res.chunk.text,
                        AssertionInput(
                            assertion_id=assertion.assertion_id,
                            subject=assertion.subject,
                            relation=assertion.relation,
                            object=assertion.object,
                            polarity=assertion.polarity,
                            rule_type=assertion.rule_type,
                        ),
                    )
                    lm_candidates.append((res.chunk.chunk_id, lm_result.label, lm_result.confidence, lm_result.rationale))

                if lm_candidates:
                    strongest = max(lm_candidates, key=lambda item: item[2])
                    if strongest[1] == "supported" and strongest[2] >= 0.8:
                        evidence.append(
                            EvidenceSpan(
                                chunk_id=strongest[0],
                                text=next((r.chunk.text for r in ranked if r.chunk and r.chunk.chunk_id == strongest[0]), ""),
                                source="lm",
                                support_type="supports",
                                confidence=round(float(strongest[2]), 4),
                                matched_subject=True,
                                matched_relation=True,
                                matched_object=True,
                            )
                        )
                    elif strongest[1] == "contradicted" and strongest[2] >= 0.8:
                        evidence.append(
                            EvidenceSpan(
                                chunk_id=strongest[0],
                                text=next((r.chunk.text for r in ranked if r.chunk and r.chunk.chunk_id == strongest[0]), ""),
                                source="lm",
                                support_type="refutes",
                                confidence=round(float(strongest[2]), 4),
                                matched_subject=True,
                                matched_relation=True,
                                matched_object=True,
                            )
                        )
            except Exception:
                pass

        return self._aggregate_triple_verdict(assertion, evidence, retrieval_sources)

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
        query_types = self.router.route(query)
        all_results = []

        if QueryType.EXACT_MATCH in query_types:
            all_results.extend(self.lexical_store.retrieve(query, top_k))
        if QueryType.COMPLEX in query_types:
            all_results.extend(self.semantic_store.retrieve(query, top_k))
        if QueryType.MULTI_HOP in query_types:
            all_results.extend(self.graph_store.retrieve(query, top_k, max_hops=3))
        if QueryType.ONTOLOGY in query_types and ontology_assertions:
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
