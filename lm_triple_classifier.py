from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Iterable
import json
import re
from pathlib import Path


@dataclass
class AssertionInput:
    assertion_id: str
    subject: str
    relation: str
    object: str
    polarity: str = "must_hold"
    rule_type: str = "constraint"


@dataclass
class TripleClassificationExample:
    example_id: str
    task: str
    document_id: str
    chunk_id: str
    input: Dict[str, Any]
    output: Dict[str, Any]

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=True)


class TripleDatasetWriter:
    """
    Minimal JSONL writer for QLoRA-style training data.
    Keeps records append-only so adjudication runs can be logged safely.
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_example(self, example: TripleClassificationExample) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(example.to_jsonl() + "\n")

    def write_examples(self, examples: Iterable[TripleClassificationExample]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            for example in examples:
                handle.write(example.to_jsonl() + "\n")


@dataclass
class TripleClassificationResult:
    label: str
    confidence: float
    rationale: str
    raw_output: Optional[str] = None


class BaseTripleClassifier:
    def classify(self, chunk_text: str, assertion: AssertionInput) -> TripleClassificationResult:
        raise NotImplementedError


class HeuristicTripleClassifier(BaseTripleClassifier):
    """
    A deterministic fallback that can be used when no LM is available.
    This is intentionally lightweight so the pipeline always has a safe default.
    """

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
    """
    Optional LM-backed classifier. If transformers is unavailable, it falls back
    to the deterministic heuristic classifier.
    """

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


def triple_training_example(
    example_id: str,
    document_id: str,
    chunk_id: str,
    chunk_text: str,
    assertion: Dict[str, Any],
    label: str,
    score_bucket: str,
    rationale: str,
) -> TripleClassificationExample:
    return TripleClassificationExample(
        example_id=example_id,
        task="triple_classification",
        document_id=document_id,
        chunk_id=chunk_id,
        input={
            "chunk_text": chunk_text,
            "assertion": assertion,
        },
        output={
            "label": label,
            "score_bucket": score_bucket,
            "rationale": rationale,
        },
    )


def score_bucket_from_confidence(confidence: float) -> str:
    if confidence >= 0.9:
        return "very_high"
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.5:
        return "medium"
    if confidence >= 0.25:
        return "low"
    return "very_low"


def triple_verdict_to_example(
    verdict: Any,
    document_id: str = "unknown_document",
    chunk_id: Optional[str] = None,
) -> TripleClassificationExample:
    """
    Convert a TripleVerdict into a single supervised training example.
    """
    top_evidence = verdict.evidence[0] if getattr(verdict, "evidence", None) else None
    chosen_chunk_id = chunk_id or getattr(top_evidence, "chunk_id", "unknown_chunk")
    chunk_text = getattr(top_evidence, "text", "")
    return TripleClassificationExample(
        example_id=f"ex_{getattr(verdict, 'assertion_id', 'unknown')}_{chosen_chunk_id}",
        task="triple_classification",
        document_id=document_id,
        chunk_id=chosen_chunk_id,
        input={
            "chunk_text": chunk_text,
            "assertion": {
                "assertion_id": getattr(verdict, "assertion_id", ""),
                "subject": getattr(verdict, "subject", ""),
                "relation": getattr(verdict, "relation", ""),
                "object": getattr(verdict, "object", ""),
                "polarity": "must_hold",
                "rule_type": "constraint",
            },
        },
        output={
            "label": getattr(verdict, "label", "unknown"),
            "score_bucket": score_bucket_from_confidence(float(getattr(verdict, "score", 0.0))),
            "rationale": getattr(verdict, "rationale", ""),
            "retrieval_sources": getattr(verdict, "retrieval_sources", []),
            "rule_hits": getattr(verdict, "rule_hits", []),
        },
    )
