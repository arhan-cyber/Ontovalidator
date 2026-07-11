from unittest.mock import MagicMock

from src.models import Chunk, OntologyAssertion
from src.classification.evidence_span_classifier import (
    HeuristicEvidenceSpanClassifier,
    NLIEvidenceSpanClassifier,
)


def _chunk(text: str) -> Chunk:
    return Chunk(chunk_id="c1", document_id="doc", text=text, embedding=None, metadata={})


def test_heuristic_classifier_supports_direct_match():
    assertion = OntologyAssertion(assertion_id="a1", subject="Aspirin", relation="treats", object="headache")
    chunk = _chunk("Aspirin treats headache effectively.")

    span = HeuristicEvidenceSpanClassifier().classify(assertion, chunk, source="lexical", retrieval_score=0.5)

    assert span.support_type == "supports"
    assert span.matched_subject and span.matched_relation and span.matched_object


def test_heuristic_classifier_detects_negation_as_refutes():
    assertion = OntologyAssertion(assertion_id="a1", subject="Aspirin", relation="treat", object="malaria")
    chunk = _chunk("Aspirin does not treat malaria.")

    span = HeuristicEvidenceSpanClassifier().classify(assertion, chunk, source="lexical", retrieval_score=0.5)

    assert span.support_type == "refutes"


def test_heuristic_classifier_partial_match():
    assertion = OntologyAssertion(assertion_id="a1", subject="Aspirin", relation="treats", object="fever")
    chunk = _chunk("Aspirin is a common medication.")

    span = HeuristicEvidenceSpanClassifier().classify(assertion, chunk, source="lexical", retrieval_score=0.0)

    assert span.support_type == "partial"
    assert span.matched_subject and not span.matched_object


def test_heuristic_classifier_unknown_when_nothing_matches():
    assertion = OntologyAssertion(assertion_id="a1", subject="Ibuprofen", relation="treats", object="fever")
    chunk = _chunk("This document discusses unrelated topics.")

    span = HeuristicEvidenceSpanClassifier().classify(assertion, chunk, source="lexical", retrieval_score=0.0)

    assert span.support_type == "unknown"


class FakeNLIModel:
    def __init__(self, label_scores):
        # label_scores: dict of label -> score, in id order
        self.config = MagicMock()
        self._labels = list(label_scores.keys())
        self.config.id2label = {i: label for i, label in enumerate(self._labels)}
        self._scores = list(label_scores.values())

    def __call__(self, **kwargs):
        import torch
        logits = MagicMock()
        # softmax over pre-arranged logits that recover self._scores exactly
        # use log so softmax(log(p)) == p (for p summing to 1)
        import math
        raw = torch.tensor([[math.log(max(s, 1e-9)) for s in self._scores]])
        logits.logits = raw
        return logits


class FakeTokenizer:
    def __call__(self, premise, hypothesis, return_tensors=None, truncation=None):
        return {}


def _nli_classifier_with_scores(label_scores):
    model = FakeNLIModel(label_scores)
    tokenizer = FakeTokenizer()
    classifier = NLIEvidenceSpanClassifier(nli_pipeline=(model, tokenizer))
    return classifier


def test_nli_classifier_entailment_maps_to_supports():
    assertion = OntologyAssertion(assertion_id="a1", subject="Aspirin", relation="treats", object="headache")
    chunk = _chunk("Aspirin is known to treat headache.")
    classifier = _nli_classifier_with_scores({"entailment": 0.9, "neutral": 0.08, "contradiction": 0.02})

    span = classifier.classify(assertion, chunk, source="semantic", retrieval_score=0.0)

    assert span.support_type == "supports"
    assert span.confidence >= 0.8


def test_nli_classifier_contradiction_maps_to_refutes():
    assertion = OntologyAssertion(assertion_id="a1", subject="Aspirin", relation="treats", object="malaria")
    chunk = _chunk("Aspirin does not treat malaria at all.")
    classifier = _nli_classifier_with_scores({"contradiction": 0.85, "neutral": 0.1, "entailment": 0.05})

    span = classifier.classify(assertion, chunk, source="semantic", retrieval_score=0.0)

    assert span.support_type == "refutes"


def test_nli_classifier_must_not_hold_polarity_flips_labels():
    assertion = OntologyAssertion(
        assertion_id="a1", subject="Aspirin", relation="treats", object="malaria", polarity="must_not_hold"
    )
    chunk = _chunk("Aspirin is known to treat malaria.")
    classifier = _nli_classifier_with_scores({"entailment": 0.9, "neutral": 0.07, "contradiction": 0.03})

    span = classifier.classify(assertion, chunk, source="semantic", retrieval_score=0.0)

    assert span.support_type == "refutes"


def test_nli_classifier_high_confidence_neutral_is_unknown():
    assertion = OntologyAssertion(assertion_id="a1", subject="Aspirin", relation="treats", object="headache")
    chunk = _chunk("This document discusses unrelated topics.")
    classifier = _nli_classifier_with_scores({"neutral": 0.8, "entailment": 0.15, "contradiction": 0.05})

    span = classifier.classify(assertion, chunk, source="semantic", retrieval_score=0.0)

    assert span.support_type == "unknown"


def test_nli_classifier_falls_back_to_heuristic_when_pipeline_unavailable():
    assertion = OntologyAssertion(assertion_id="a1", subject="Aspirin", relation="treats", object="headache")
    chunk = _chunk("Aspirin treats headache.")
    # Inject a dummy pipeline to skip the real model load, then simulate unavailability.
    classifier = NLIEvidenceSpanClassifier(nli_pipeline=(MagicMock(), FakeTokenizer()))
    classifier.nli_pipeline = None

    span = classifier.classify(assertion, chunk, source="lexical", retrieval_score=0.0)

    assert span.support_type == "supports"


def test_nli_classifier_falls_back_on_inference_error():
    assertion = OntologyAssertion(assertion_id="a1", subject="Aspirin", relation="treats", object="headache")
    chunk = _chunk("Aspirin treats headache.")

    broken_model = MagicMock(side_effect=RuntimeError("boom"))
    classifier = NLIEvidenceSpanClassifier(nli_pipeline=(broken_model, FakeTokenizer()))

    span = classifier.classify(assertion, chunk, source="lexical", retrieval_score=0.0)

    assert span.support_type == "supports"
