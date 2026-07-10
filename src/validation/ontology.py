"""Ontology constraint validation."""

import re
from typing import List, Dict, Any, Optional, Tuple

from ..models import RetrievalResult, OntologyAssertion, Chunk, ViolationRecord
from .validator import EvidenceValidator


class OntologyViolationValidator(EvidenceValidator):
    """Checks retrieved chunks against ontology assertions."""

    def __init__(self, classifier=None):
        self.classifier = classifier

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.lower()).strip()

    def _score_violation(self, assertion: OntologyAssertion, chunk: Chunk) -> Tuple[str, float, str]:
        text = self._normalize(chunk.text)
        subject = self._normalize(assertion.subject)
        relation = self._normalize(assertion.relation)
        obj = self._normalize(assertion.object)
        has_subject = subject and subject in text
        has_object = obj and obj in text
        has_relation = relation and relation in text
        negation = any(token in text for token in [" not ", "no ", "without ", "never ", "fails to", "does not", "cannot"])

        if has_subject and has_relation and has_object:
            if negation or assertion.polarity in {"forbidden", "must_not_hold"}:
                return "contradiction", 0.94, "Matched assertion but found explicit negation or forbidden polarity."
            return "satisfied", 0.9, "Matched assertion text directly."
        if has_subject and has_relation:
            return "partial_match", 0.65, "Subject and relation matched but object was missing."
        if has_subject or has_object:
            return "candidate_violation", 0.5, "Only a partial ontology match was found."
        return "unmatched", 0.2, "No direct assertion match found in the chunk."

    def validate(
        self,
        query: str,
        results: List[RetrievalResult],
        ontology_assertions: Optional[List[OntologyAssertion]] = None
    ) -> Dict[str, Any]:
        assertions = ontology_assertions or []
        violators: List[ViolationRecord] = []
        evidence: List[Dict[str, Any]] = []

        if not assertions:
            return {
                "query": query,
                "status": "ONTOLOGY_VALIDATION_SKIPPED",
                "message": "No ontology assertions were provided.",
                "violations": [],
                "evidence": []
            }

        for res in results:
            chunk = res.chunk
            if not chunk:
                continue
            for assertion in assertions:
                violation_type, confidence, evidence_text = self._score_violation(assertion, chunk)
                if violation_type in {"contradiction", "partial_match", "candidate_violation"}:
                    violators.append(ViolationRecord(
                        assertion_id=assertion.assertion_id,
                        chunk_id=chunk.chunk_id,
                        violation_type=violation_type,
                        confidence=confidence,
                        evidence=evidence_text,
                        matched_text=chunk.text,
                        source=res.source
                    ))

        violators.sort(key=lambda v: v.confidence, reverse=True)
        for rank, v in enumerate(violators, start=1):
            evidence.append({
                "rank": rank,
                "assertion_id": v.assertion_id,
                "chunk_id": v.chunk_id,
                "violation_type": v.violation_type,
                "confidence": round(v.confidence, 4),
                "source": v.source,
                "evidence": v.evidence,
                "text": v.matched_text
            })

        return {
            "query": query,
            "status": "ONTOLOGY_VALIDATED" if evidence else "ONTOLOGY_VALIDATION_OK",
            "message": "Ontology assertions were checked against ranked evidence chunks.",
            "violations": evidence,
            "evidence": evidence
        }
