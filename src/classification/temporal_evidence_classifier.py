"""Discounts evidence that sits outside the claim's temporal scope."""

from datetime import datetime
from typing import Optional

from ..models import Chunk, EvidenceSpan, OntologyAssertion, TemporalScope
from .evidence_span_classifier import BaseEvidenceSpanClassifier, HeuristicEvidenceSpanClassifier


class TemporalEvidenceClassifier(BaseEvidenceSpanClassifier):
    """Wraps another span classifier and adjusts its confidence for time alignment.

    This decorates rather than subclasses a concrete classifier so temporal
    reasoning composes with whichever stance classifier is configured
    (heuristic today, NLI tomorrow) instead of forking each of them.
    """

    def __init__(
        self,
        base_classifier: Optional[BaseEvidenceSpanClassifier] = None,
        outdated_penalty: float = 0.6,
        future_penalty: float = 0.3,
    ):
        self.base_classifier = base_classifier or HeuristicEvidenceSpanClassifier()
        self.outdated_penalty = outdated_penalty
        self.future_penalty = future_penalty

    def classify(
        self,
        assertion: OntologyAssertion,
        chunk: Chunk,
        source: str,
        retrieval_score: float = 0.0,
    ) -> EvidenceSpan:
        span = self.base_classifier.classify(assertion, chunk, source, retrieval_score)
        span.chunk_timestamp = chunk.timestamp

        scope = getattr(assertion, "temporal_scope", None)
        timestamp = chunk.timestamp
        if scope is None or timestamp is None:
            span.temporal_status = "unscoped" if scope is None else "undated"
            return span

        if scope.contains(timestamp):
            span.temporal_status = "current"
            return span

        status = self._classify_temporal_mismatch(scope, timestamp)
        span.temporal_status = status
        penalty = self.outdated_penalty if status == "outdated" else self.future_penalty
        span.confidence = round(span.confidence * penalty, 4)
        return span

    @staticmethod
    def _classify_temporal_mismatch(scope: TemporalScope, chunk_date: datetime) -> str:
        if scope.start_date and chunk_date < scope.start_date:
            return "outdated"
        if scope.end_date and chunk_date > scope.end_date:
            return "future"
        return "unknown"


__all__ = ["TemporalEvidenceClassifier"]
