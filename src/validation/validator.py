"""Evidence validators for query verification."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from ..models import RetrievalResult, OntologyAssertion


class EvidenceValidator(ABC):
    @abstractmethod
    def validate(
        self,
        query: str,
        results: List[RetrievalResult],
        ontology_assertions: Optional[List[OntologyAssertion]] = None
    ) -> Dict[str, Any]:
        pass


class MinimalValidator(EvidenceValidator):
    """Minimal validator that returns ranked chunks without LLM evaluation."""

    def validate(
        self,
        query: str,
        results: List[RetrievalResult],
        ontology_assertions: Optional[List[OntologyAssertion]] = None
    ) -> Dict[str, Any]:
        ranked_evidence = []
        for i, res in enumerate(results):
            evidence_data = {
                "rank": i + 1,
                "chunk_id": res.chunk_id,
                "score": round(res.score, 4),
                "retrieval_source": res.source,
                "text": res.chunk.text if res.chunk else None
            }
            ranked_evidence.append(evidence_data)

        return {
            "query": query,
            "status": "EVIDENCE_GATHERED",
            "message": "Returned ranked chunks. Detailed LLM validation bypassed.",
            "evidence": ranked_evidence
        }


class TransformerValidator(EvidenceValidator):
    """Zero-shot NLI validation using DistilBERT."""

    def __init__(self, model_name: str = "typeform/distilbert-base-uncased-mnli"):
        from transformers import DistilBertTokenizer, AutoModelForSequenceClassification, pipeline
        tokenizer = DistilBertTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.classifier = pipeline("zero-shot-classification", model=model, tokenizer=tokenizer)

    def validate(
        self,
        query: str,
        results: List[RetrievalResult],
        ontology_assertions: Optional[List[OntologyAssertion]] = None
    ) -> Dict[str, Any]:
        from .ontology import OntologyViolationValidator

        if ontology_assertions:
            return OntologyViolationValidator(self.classifier).validate(query, results, ontology_assertions)

        ranked_evidence = []
        for i, res in enumerate(results):
            chunk_text = res.chunk.text if res.chunk else ""
            if chunk_text:
                try:
                    labels = ["supports", "refutes", "is neutral to"]
                    hypothesis = f"This text {{}} the claim: {query}"
                    res_cls = self.classifier(chunk_text, candidate_labels=labels, hypothesis_template=hypothesis)
                    best_label = res_cls["labels"][0]
                    confidence = res_cls["scores"][0]
                except Exception as e:
                    best_label = f"error: {str(e)}"
                    confidence = 0.0
            else:
                best_label = "neutral"
                confidence = 0.0

            ranked_evidence.append({
                "rank": i + 1,
                "chunk_id": res.chunk_id,
                "score": round(res.score, 4),
                "retrieval_source": res.source,
                "text": chunk_text,
                "nli_label": best_label,
                "confidence": round(confidence, 4)
            })

        return {
            "query": query,
            "status": "EVIDENCE_VALIDATED",
            "message": "Evaluated ranked chunks using zero-shot NLI transformer.",
            "evidence": ranked_evidence
        }
