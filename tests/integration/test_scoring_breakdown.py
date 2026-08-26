"""Scoring transparency: the breakdown must reproduce the score it reports."""

import pytest

from src.engine import (
    AGREEMENT_BONUS_PER_SOURCE,
    BASELINE_SCORE,
    LABEL_SCORE_FLOORS,
    PARTIAL_WEIGHT,
    REFUTE_WEIGHT,
    SUPPORT_WEIGHT,
    SVOVerificationEngine,
)
from src.models import EvidenceSpan, OntologyAssertion


@pytest.fixture
def engine():
    return SVOVerificationEngine(
        router=None,
        lexical_store=None,
        semantic_store=None,
        graph_store=None,
        fusion_engine=None,
        chunk_store=None,
        validator=None,
    )


@pytest.fixture
def assertion():
    return OntologyAssertion(assertion_id="t1", subject="Aspirin", relation="treats", object="headache")


def span(support_type, confidence, chunk_id="c1"):
    matched = support_type in {"supports", "refutes"}
    return EvidenceSpan(
        chunk_id=chunk_id,
        text="Aspirin treats headache.",
        source="fusion",
        support_type=support_type,
        confidence=confidence,
        matched_subject=True,
        matched_relation=matched,
        matched_object=matched,
    )


class TestScoringBreakdown:
    def test_raw_score_matches_the_formula(self, engine, assertion):
        evidence = [span("supports", 0.9), span("partial", 0.5, "c2"), span("refutes", 0.2, "c3")]
        verdict = engine._aggregate_triple_verdict(assertion, evidence, ["lexical", "semantic"])
        breakdown = verdict.scoring_breakdown

        expected = (
            BASELINE_SCORE
            + SUPPORT_WEIGHT * 0.9
            + PARTIAL_WEIGHT * 0.5
            + REFUTE_WEIGHT * 0.2
            + AGREEMENT_BONUS_PER_SOURCE * 1
        )
        assert breakdown["raw_score_value"] == round(expected, 4)
        assert breakdown["support_strength"] == 0.9
        assert breakdown["refute_strength"] == 0.2
        assert breakdown["partial_strength"] == 0.5

    def test_agreement_bonus_scales_with_distinct_sources(self, engine, assertion):
        one_source = engine._aggregate_triple_verdict(assertion, [span("partial", 0.5)], ["lexical"])
        three_sources = engine._aggregate_triple_verdict(
            assertion, [span("partial", 0.5)], ["lexical", "semantic", "graph"]
        )

        assert one_source.scoring_breakdown["agreement_bonus"] == 0.0
        assert three_sources.scoring_breakdown["agreement_bonus"] == round(2 * AGREEMENT_BONUS_PER_SOURCE, 4)

    def test_breakdown_records_the_label_score_floor(self, engine, assertion):
        # A lone partial scores below the 0.35 floor, so the floor must apply and be explained.
        verdict = engine._aggregate_triple_verdict(assertion, [span("partial", 0.2)], ["lexical"])

        assert verdict.label == "partial"
        assert verdict.score == LABEL_SCORE_FLOORS["partial"]
        assert "0.35" in verdict.scoring_breakdown["adjustment_reason"]
        assert verdict.scoring_breakdown["final_score"] == verdict.score

    def test_no_adjustment_reason_when_the_floor_does_not_bind(self, engine, assertion):
        evidence = [span("supports", 0.95), span("supports", 0.9, "c2")]
        verdict = engine._aggregate_triple_verdict(assertion, evidence, ["lexical"])

        assert verdict.score > LABEL_SCORE_FLOORS["supported"]
        assert "adjustment_reason" not in verdict.scoring_breakdown

    def test_final_score_always_matches_the_verdict_score(self, engine, assertion):
        cases = [
            ([span("supports", 0.95)], ["lexical"]),
            ([span("refutes", 0.9)], ["lexical", "graph"]),
            ([span("partial", 0.4)], ["semantic"]),
            ([span("unknown", 0.1)], ["lexical"]),
        ]
        for evidence, sources in cases:
            verdict = engine._aggregate_triple_verdict(assertion, evidence, sources)
            assert verdict.scoring_breakdown["final_score"] == verdict.score

    def test_evidence_counts_are_reported(self, engine, assertion):
        evidence = [span("supports", 0.9), span("partial", 0.5, "c2"), span("partial", 0.4, "c3")]
        verdict = engine._aggregate_triple_verdict(assertion, evidence, ["lexical"])

        assert verdict.scoring_breakdown["evidence_counts"] == {
            "supports": 1, "refutes": 0, "partial": 2, "unknown": 0,
        }

    def test_score_is_clipped_to_one(self, engine, assertion):
        evidence = [span("supports", 1.0), span("supports", 1.0, "c2"), span("supports", 1.0, "c3")]
        verdict = engine._aggregate_triple_verdict(assertion, evidence, ["lexical", "semantic", "graph"])

        assert verdict.scoring_breakdown["raw_score_value"] > 1.0
        assert verdict.score == 1.0

    def test_empty_evidence_still_produces_a_breakdown(self, engine, assertion):
        verdict = engine._aggregate_triple_verdict(assertion, [], [])

        assert verdict.label == "unknown"
        assert verdict.scoring_breakdown["final_score"] == verdict.score
        assert "no evidence" in verdict.decision_thresholds["chosen_label"]


class TestDecisionThresholds:
    def test_supported_rule_reports_as_triggered(self, engine, assertion):
        verdict = engine._aggregate_triple_verdict(assertion, [span("supports", 0.95)], ["lexical"])

        assert verdict.label == "supported"
        assert verdict.decision_thresholds["supported_rule"].startswith("triggered")
        assert verdict.decision_thresholds["contradicted_rule"].startswith("not triggered")
        assert verdict.decision_thresholds["chosen_label"].startswith("supported")

    def test_contradicted_rule_reports_as_triggered(self, engine, assertion):
        verdict = engine._aggregate_triple_verdict(assertion, [span("refutes", 0.9)], ["lexical"])

        assert verdict.label == "contradicted"
        assert verdict.decision_thresholds["contradicted_rule"].startswith("triggered")

    def test_supported_is_blocked_by_any_refutation(self, engine, assertion):
        evidence = [span("supports", 0.95), span("refutes", 0.3, "c2")]
        verdict = engine._aggregate_triple_verdict(assertion, evidence, ["lexical"])

        assert verdict.label == "partial"
        assert "refute_strength (0.3) > 0" in verdict.decision_thresholds["supported_rule"]
