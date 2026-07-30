"""Temporal adjudication: confidence discounts for out-of-scope evidence."""

from datetime import datetime

import pytest

from src.classification.evidence_span_classifier import HeuristicEvidenceSpanClassifier
from src.classification.temporal_evidence_classifier import TemporalEvidenceClassifier
from src.models import Chunk, OntologyAssertion, TemporalScope

TEXT = "Aspirin treats headache."


def chunk(timestamp=None):
    return Chunk(
        chunk_id="c1",
        document_id="doc1",
        text=TEXT,
        embedding=None,
        metadata={},
        timestamp=timestamp,
    )


def assertion(scope=None):
    return OntologyAssertion(
        assertion_id="t1",
        subject="Aspirin",
        relation="treats",
        object="headache",
        temporal_scope=scope,
    )


@pytest.fixture
def classifier():
    return TemporalEvidenceClassifier(HeuristicEvidenceSpanClassifier())


@pytest.fixture
def scope():
    return TemporalScope(start_date=datetime(2000, 1, 1), end_date=datetime(2025, 1, 1))


class TestTemporalScope:
    def test_contains_respects_both_bounds(self, scope):
        assert scope.contains(datetime(2010, 6, 1))
        assert not scope.contains(datetime(1990, 1, 1))
        assert not scope.contains(datetime(2030, 1, 1))

    def test_an_open_scope_contains_everything(self):
        assert TemporalScope().contains(datetime(1800, 1, 1))

    def test_roundtrips_through_a_dict(self, scope):
        assert TemporalScope.from_dict(scope.to_dict()) == scope


class TestTemporalClassification:
    def test_evidence_inside_the_scope_keeps_its_confidence(self, classifier, scope):
        baseline = HeuristicEvidenceSpanClassifier().classify(assertion(scope), chunk(), "fusion")
        span = classifier.classify(assertion(scope), chunk(datetime(2010, 1, 1)), "fusion")

        assert span.temporal_status == "current"
        assert span.confidence == baseline.confidence

    def test_evidence_before_the_scope_is_discounted(self, scope):
        classifier = TemporalEvidenceClassifier(outdated_penalty=0.6)
        baseline = HeuristicEvidenceSpanClassifier().classify(assertion(scope), chunk(), "fusion")

        span = classifier.classify(assertion(scope), chunk(datetime(1897, 1, 1)), "fusion")

        assert span.temporal_status == "outdated"
        assert span.confidence == round(baseline.confidence * 0.6, 4)

    def test_evidence_after_the_scope_is_discounted_harder(self, scope):
        classifier = TemporalEvidenceClassifier(future_penalty=0.3)
        baseline = HeuristicEvidenceSpanClassifier().classify(assertion(scope), chunk(), "fusion")

        span = classifier.classify(assertion(scope), chunk(datetime(2030, 1, 1)), "fusion")

        assert span.temporal_status == "future"
        assert span.confidence == round(baseline.confidence * 0.3, 4)

    def test_the_stance_itself_is_never_changed(self, classifier, scope):
        span = classifier.classify(assertion(scope), chunk(datetime(1897, 1, 1)), "fusion")

        assert span.support_type == "supports"

    def test_an_unscoped_assertion_is_left_alone(self, classifier):
        baseline = HeuristicEvidenceSpanClassifier().classify(assertion(), chunk(), "fusion")
        span = classifier.classify(assertion(), chunk(datetime(1897, 1, 1)), "fusion")

        assert span.temporal_status == "unscoped"
        assert span.confidence == baseline.confidence

    def test_an_undated_chunk_is_left_alone(self, classifier, scope):
        baseline = HeuristicEvidenceSpanClassifier().classify(assertion(scope), chunk(), "fusion")
        span = classifier.classify(assertion(scope), chunk(None), "fusion")

        assert span.temporal_status == "undated"
        assert span.confidence == baseline.confidence

    def test_the_chunk_timestamp_is_reported_on_the_span(self, classifier, scope):
        span = classifier.classify(assertion(scope), chunk(datetime(2010, 3, 2)), "fusion")

        assert span.chunk_timestamp == datetime(2010, 3, 2)

    def test_it_decorates_whichever_classifier_it_wraps(self, scope):
        class AlwaysRefutes(HeuristicEvidenceSpanClassifier):
            def classify(self, assertion, chunk, source, retrieval_score=0.0):
                span = super().classify(assertion, chunk, source, retrieval_score)
                span.support_type = "refutes"
                return span

        classifier = TemporalEvidenceClassifier(AlwaysRefutes())
        span = classifier.classify(assertion(scope), chunk(datetime(2010, 1, 1)), "fusion")

        assert span.support_type == "refutes"
        assert span.temporal_status == "current"
