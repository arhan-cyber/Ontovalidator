"""End-to-end: the observability payloads reach the serialized verdict."""

import os
import re

import pytest

from src.config import PipelineConfig
from src.factories import EngineFactory
from src.models import OntologyAssertion

DOCUMENT = (
    "Published: 2020-05-14\n\n"
    "Aspirin is a widely used analgesic and antipyretic. "
    "Aspirin treats headache and minor body aches. "
    "Clinical studies show it also reduces fever. "
    "It does not treat malaria, which requires anti-malarial therapy. "
    # Retrieved on the shared 'treats' token but matching no component of the
    # assertions below, so these land in the rejected-evidence trail.
    "Paracetamol treats fever in children. "
    "Ibuprofen treats swelling.\n\n"
    "Known uses:\n"
    "- Aspirin reduces inflammation\n"
)


@pytest.fixture
def engine(tmp_workspace):
    config = PipelineConfig(
        sqlite_path=os.path.join(tmp_workspace, "svo.db"),
        cache_db_path=os.path.join(tmp_workspace, "cache.db"),
        feedback_db_path=os.path.join(tmp_workspace, "feedback.db"),
    )
    return EngineFactory.create_verification_engine(config)


@pytest.fixture
def result(engine):
    return engine.validate_triples_batch(
        "doc1",
        DOCUMENT,
        [
            OntologyAssertion(assertion_id="t1", subject="Aspirin", relation="treats", object="headache"),
            OntologyAssertion(assertion_id="t2", subject="Aspirin", relation="treats", object="malaria"),
            OntologyAssertion(assertion_id="t3", subject="Penicillin", relation="cures", object="scurvy"),
        ],
        top_k=5,
    )


class TestRetrievalPathway:
    def test_every_evidence_span_carries_a_pathway(self, result):
        spans = [span for verdict in result["verdicts"] for span in verdict["evidence"]]

        assert spans
        for span in spans:
            pathway = span["retrieval_pathway"]
            assert set(pathway) >= {"lexical", "semantic", "graph", "fusion_score", "fusion_explanation"}

    def test_pathway_lists_the_retrievers_that_found_the_chunk(self, result):
        span = result["verdicts"][0]["evidence"][0]
        sources = span["retrieval_pathway"]["retriever_sources"]

        assert sources
        assert set(sources) <= {"lexical", "semantic", "graph", "fallback"}

    def test_reported_fusion_score_matches_the_explanation(self, result):
        for verdict in result["verdicts"]:
            for span in verdict["evidence"]:
                pathway = span["retrieval_pathway"]
                assert str(pathway["fusion_score"]) in pathway["fusion_explanation"]


class TestAnnotation:
    def test_supporting_evidence_is_marked_up(self, result):
        verdict = next(v for v in result["verdicts"] if v["assertion_id"] == "t1")
        html = verdict["evidence"][0]["annotated_html"]

        assert html.startswith("<p>") and html.endswith("</p>")
        assert html.count("<mark") == html.count("</mark>")

    def test_annotation_never_alters_the_underlying_text(self, result):
        for verdict in result["verdicts"]:
            for span in verdict["evidence"]:
                assert re.sub(r"<[^>]+>", "", span["annotated_html"]) == span["text"]

    def test_negation_is_reported_for_the_malaria_sentence(self, result):
        verdict = next(v for v in result["verdicts"] if v["assertion_id"] == "t2")
        negations = [
            span["negation_analysis"]
            for span in verdict["evidence"]
            if "malaria" in span["text"].lower()
        ]

        assert any(n["negation_keywords"] for n in negations)

    def test_component_matches_agree_with_the_matched_flags(self, result):
        for verdict in result["verdicts"]:
            for span in verdict["evidence"]:
                assert span["component_matches"] == span["matched"]


class TestScoringTransparency:
    def test_every_verdict_explains_its_score(self, result):
        for verdict in result["verdicts"]:
            assert verdict["scoring_breakdown"]["final_score"] == verdict["score"]
            assert verdict["decision_thresholds"]["chosen_label"].startswith(verdict["label"])

    def test_off_topic_chunks_are_reported_as_rejected_with_a_reason(self, result):
        verdict = next(v for v in result["verdicts"] if v["assertion_id"] == "t1")
        rejected_texts = {r["text"] for r in verdict["rejected_evidence"]}

        assert "Ibuprofen treats swelling." in rejected_texts
        for rejected in verdict["rejected_evidence"]:
            assert rejected["adjudication"] == "unknown"
            assert "components matched" in rejected["reason_rejected"]

    def test_rejected_chunks_do_not_change_the_score(self, result):
        verdict = next(v for v in result["verdicts"] if v["assertion_id"] == "t1")

        assert verdict["rejected_evidence"]
        assert verdict["scoring_breakdown"]["evidence_counts"]["unknown"] == 0

    def test_rejected_chunks_are_not_also_reported_as_used(self, result):
        for verdict in result["verdicts"]:
            used = {span["chunk_id"] for span in verdict["evidence"]}
            rejected = {r["chunk_id"] for r in verdict["rejected_evidence"]}
            assert used.isdisjoint(rejected)


class TestTemporalAndFeedbackWiring:
    def test_chunk_timestamps_reach_the_response(self, result):
        spans = [span for verdict in result["verdicts"] for span in verdict["evidence"]]

        assert all(span["chunk_timestamp"] == "2020-05-14T00:00:00" for span in spans)

    def test_every_verdict_carries_a_feedback_id(self, result):
        ids = [verdict["feedback_id"] for verdict in result["verdicts"]]

        assert all(ids)
        assert len(set(ids)) == len(ids)

    def test_a_correction_can_be_recorded_against_a_verdict(self, engine, result):
        verdict = engine.adjudicate_triple(
            None,
            OntologyAssertion(assertion_id="t1", subject="Aspirin", relation="treats", object="headache"),
        )

        assert engine.record_feedback(verdict, "partial", "doc1", "over-confident") is True
        assert engine.feedback_recorder.get_corrections()[0]["actual_label"] == "partial"

    def test_ingestion_reports_the_chunk_types_it_produced(self, result):
        assert result["chunk_types"]["text"] > 0
        assert result["chunk_types"]["list_item"] == 1
