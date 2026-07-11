"""Per-chunk evidence-span stance classification (supports/refutes/partial/unknown)."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Optional, Tuple

from ..models import Chunk, EvidenceSpan, OntologyAssertion


class BaseEvidenceSpanClassifier(ABC):
    @abstractmethod
    def classify(
        self,
        assertion: OntologyAssertion,
        chunk: Chunk,
        source: str,
        retrieval_score: float = 0.0,
    ) -> EvidenceSpan:
        raise NotImplementedError


class HeuristicEvidenceSpanClassifier(BaseEvidenceSpanClassifier):
    """Deterministic substring + negation-wordlist classifier (baseline and fallback)."""

    NEGATION_TOKENS = [" not ", "no ", "without ", "never ", "fails to", "does not", "cannot"]

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.lower()).strip()

    @classmethod
    def _compute_match_flags(cls, assertion: OntologyAssertion, text: str) -> Tuple[bool, bool, bool]:
        norm_text = cls._normalize(text)
        subject = cls._normalize(assertion.subject)
        relation = cls._normalize(assertion.relation)
        obj = cls._normalize(assertion.object)
        matched_subject = bool(subject and subject in norm_text)
        matched_relation = bool(relation and relation in norm_text)
        matched_object = bool(obj and obj in norm_text)
        return matched_subject, matched_relation, matched_object

    def classify(
        self,
        assertion: OntologyAssertion,
        chunk: Chunk,
        source: str,
        retrieval_score: float = 0.0,
    ) -> EvidenceSpan:
        text = self._normalize(chunk.text)
        matched_subject, matched_relation, matched_object = self._compute_match_flags(assertion, chunk.text)
        negation = any(token in text for token in self.NEGATION_TOKENS)

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


class NLIEvidenceSpanClassifier(BaseEvidenceSpanClassifier):
    """Textual-entailment-based classifier using a local HF NLI model, with heuristic fallback."""

    def __init__(
        self,
        model_name: str = "typeform/distilbert-base-uncased-mnli",
        neutral_confidence_threshold: float = 0.6,
        nli_pipeline: Optional[Any] = None,
    ):
        self.model_name = model_name
        self.neutral_confidence_threshold = neutral_confidence_threshold
        self._fallback = HeuristicEvidenceSpanClassifier()
        self.nli_pipeline = nli_pipeline
        if self.nli_pipeline is None:
            try:
                from transformers import AutoModelForSequenceClassification, AutoTokenizer

                tokenizer = AutoTokenizer.from_pretrained(model_name)
                model = AutoModelForSequenceClassification.from_pretrained(model_name)
                self.nli_pipeline = (model, tokenizer)
            except Exception:
                self.nli_pipeline = None

    def _entail_scores(self, premise: str, hypothesis: str) -> dict:
        """Run premise/hypothesis through the NLI model, return {label: score}."""
        import torch

        model, tokenizer = self.nli_pipeline
        inputs = tokenizer(premise, hypothesis, return_tensors="pt", truncation=True)
        with torch.no_grad():
            logits = model(**inputs).logits[0]
        probs = torch.softmax(logits, dim=-1).tolist()
        id2label = model.config.id2label
        return {id2label[i].lower(): probs[i] for i in range(len(probs))}

    def classify(
        self,
        assertion: OntologyAssertion,
        chunk: Chunk,
        source: str,
        retrieval_score: float = 0.0,
    ) -> EvidenceSpan:
        if self.nli_pipeline is None:
            return self._fallback.classify(assertion, chunk, source, retrieval_score)

        matched_subject, matched_relation, matched_object = HeuristicEvidenceSpanClassifier._compute_match_flags(
            assertion, chunk.text
        )

        try:
            premise = chunk.text
            hypothesis = f"{assertion.subject} {assertion.relation} {assertion.object}"
            scores = self._entail_scores(premise, hypothesis)
            entailment_score = scores.get("entailment", 0.0)
            contradiction_score = scores.get("contradiction", 0.0)
            neutral_score = scores.get("neutral", 0.0)

            top_label = max(scores, key=scores.get)
            if top_label == "entailment":
                support_type = "refutes" if assertion.polarity == "must_not_hold" else "supports"
                confidence = entailment_score
            elif top_label == "contradiction":
                support_type = "supports" if assertion.polarity == "must_not_hold" else "refutes"
                confidence = contradiction_score
            else:
                if neutral_score >= self.neutral_confidence_threshold:
                    support_type = "unknown"
                    confidence = neutral_score
                else:
                    support_type = "partial"
                    confidence = max(entailment_score, contradiction_score, neutral_score)

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
        except Exception:
            return self._fallback.classify(assertion, chunk, source, retrieval_score)


__all__ = [
    "BaseEvidenceSpanClassifier",
    "HeuristicEvidenceSpanClassifier",
    "NLIEvidenceSpanClassifier",
]
