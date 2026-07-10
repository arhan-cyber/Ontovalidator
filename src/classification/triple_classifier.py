"""Triple classification models."""

import re
import json
from abc import ABC, abstractmethod
from typing import Optional

from .dataset import AssertionInput, TripleClassificationResult


class BaseTripleClassifier(ABC):
    @abstractmethod
    def classify(self, chunk_text: str, assertion: AssertionInput) -> TripleClassificationResult:
        pass


class HeuristicTripleClassifier(BaseTripleClassifier):
    """Deterministic fallback for triple classification."""

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.lower()).strip()

    def classify(self, chunk_text: str, assertion: AssertionInput) -> TripleClassificationResult:
        text = self._normalize(chunk_text)
        subject = self._normalize(assertion.subject)
        relation = self._normalize(assertion.relation)
        obj = self._normalize(assertion.object)

        has_subject = subject in text if subject else False
        has_relation = relation in text if relation else False
        has_object = obj in text if obj else False
        negation = any(token in text for token in [" not ", "no ", "without ", "never ", "does not", "cannot"])

        if has_subject and has_relation and has_object and not negation:
            return TripleClassificationResult(
                label="supported",
                confidence=0.94,
                rationale="Direct match for subject, relation, and object."
            )
        if has_subject and has_relation and has_object and negation:
            return TripleClassificationResult(
                label="contradicted",
                confidence=0.9,
                rationale="Direct triple match appears with explicit negation."
            )
        if has_subject and (has_relation or has_object):
            return TripleClassificationResult(
                label="partial",
                confidence=0.62,
                rationale="Only part of the triple is present in the chunk."
            )
        return TripleClassificationResult(
            label="unknown",
            confidence=0.18,
            rationale="No meaningful triple match was found."
        )


class PromptTripleClassifier(BaseTripleClassifier):
    """LM-backed triple classifier with heuristic fallback."""

    def __init__(self, model_name: str = "typeform/distilbert-base-uncased-mnli"):
        self.model_name = model_name
        self._fallback = HeuristicTripleClassifier()
        try:
            from transformers import DistilBertTokenizer, AutoModelForSequenceClassification, pipeline
            tokenizer = DistilBertTokenizer.from_pretrained(model_name)
            model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self.classifier = pipeline("zero-shot-classification", model=model, tokenizer=tokenizer)
        except Exception:
            self.classifier = None

    def classify(self, chunk_text: str, assertion: AssertionInput) -> TripleClassificationResult:
        if self.classifier is None:
            return self._fallback.classify(chunk_text, assertion)

        hypothesis = f"This text {{}} the claim: {assertion.subject} {assertion.relation} {assertion.object}"
        try:
            result = self.classifier(
                chunk_text,
                candidate_labels=["supports", "refutes", "is neutral to"],
                hypothesis_template=hypothesis,
            )
            label = result["labels"][0]
            score = float(result["scores"][0])
            mapped_label = {
                "supports": "supported",
                "refutes": "contradicted",
                "is neutral to": "unknown",
            }.get(label, "unknown")
            return TripleClassificationResult(
                label=mapped_label,
                confidence=score,
                rationale=f"Zero-shot classifier selected '{label}'.",
                raw_output=json.dumps(result, ensure_ascii=True),
            )
        except Exception as exc:
            fallback = self._fallback.classify(chunk_text, assertion)
            fallback.raw_output = str(exc)
            return fallback
