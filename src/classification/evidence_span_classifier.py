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
    """Deterministic substring + negation-wordlist classifier (baseline and fallback).

    Negation handling is intentionally a cheap keyword-scan fallback (the
    NLI-backed classifier is the "real" negation-aware path). It does three
    things beyond a flat substring search:

    1. Word-boundary-safe cue matching via regex (``\\bnot\\b`` etc.) instead
       of raw substring checks, so cues like "unable to"/"cannot"/"won't"
       are matched precisely rather than relying on ad-hoc spacing.
    2. Object-span scoping: a negation cue that falls entirely inside the
       matched span of ``assertion.object`` (e.g. the "no" in an object like
       "no major vulnerabilities") does not count as negating the relation —
       it's part of what the object legitimately asserts, not a negation of
       the claim.
    3. Negation-cue parity: since this is a flat keyword scan with no scope
       resolution, we count remaining (non-object-scoped) cues and treat an
       odd count as "negated" and an even count as a wash (double negation
       cancels out). Idiomatic double negatives like "not uncommon" are
       masked out before counting (they read as affirmative, and their
       "un-" half isn't a separate token in our cue list, so left alone they
       would misfire as a single, odd, negation).
    """

    NEGATION_PATTERNS = [
        r"\bnot\b",
        r"\bno\b",
        r"\bwithout\b",
        r"\bnever\b",
        r"\bcannot\b",
        r"\bcan't\b",
        r"\bwon't\b",
        r"\bfails? to\b",
        r"\bfailed to\b",
        r"\bunable to\b",
        r"\bincapable of\b",
    ]
    _NEGATION_RE = re.compile("|".join(NEGATION_PATTERNS))

    # Idiomatic double-negation phrases that read as affirmative (e.g. "not
    # uncommon" == "common"). Masked out before cue-counting so they
    # contribute nothing (an implicit, cancelling pair) rather than being
    # picked up as a single stray "not".
    _NEGATION_CANCEL_RE = re.compile(r"\bnot\s+un\w+\b")

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

    @classmethod
    def _object_span(cls, norm_text: str, assertion: OntologyAssertion) -> Optional[Tuple[int, int]]:
        obj = cls._normalize(assertion.object)
        if not obj:
            return None
        idx = norm_text.find(obj)
        if idx == -1:
            return None
        return idx, idx + len(obj)

    @classmethod
    def _is_negated(cls, norm_text: str, obj_span: Optional[Tuple[int, int]]) -> bool:
        """Count negation cues outside the object span; odd count == negated."""
        masked = cls._NEGATION_CANCEL_RE.sub(lambda m: " " * len(m.group(0)), norm_text)
        count = 0
        for match in cls._NEGATION_RE.finditer(masked):
            if obj_span is not None and obj_span[0] <= match.start() and match.end() <= obj_span[1]:
                # Cue lies entirely inside the object's own matched text -
                # it's part of what the object asserts, not a negation of
                # the relation.
                continue
            count += 1
        return count % 2 == 1

    def classify(
        self,
        assertion: OntologyAssertion,
        chunk: Chunk,
        source: str,
        retrieval_score: float = 0.0,
    ) -> EvidenceSpan:
        text = self._normalize(chunk.text)
        matched_subject, matched_relation, matched_object = self._compute_match_flags(assertion, chunk.text)
        obj_span = self._object_span(text, assertion) if matched_object else None
        negation = self._is_negated(text, obj_span)

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
