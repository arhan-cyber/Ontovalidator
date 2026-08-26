"""Rejected-evidence audit trail: reasons and the used/rejected split."""

import pytest

from src.engine import SVOVerificationEngine
from src.feedback.explainer import RejectionExplainer
from src.models import EvidenceSpan, RetrievalResult


def span(support_type, confidence, subject=True, relation=True, obj=True, chunk_id="c1"):
    return EvidenceSpan(
        chunk_id=chunk_id,
        text="chunk text",
        source="fusion",
        support_type=support_type,
        confidence=confidence,
        matched_subject=subject,
        matched_relation=relation,
        matched_object=obj,
    )


@pytest.fixture
def explainer():
    return RejectionExplainer()


class TestRejectionExplainer:
    def test_unknown_reports_how_many_components_matched(self, explainer):
        reason = explainer.explain(span("unknown", 0.2, subject=True, relation=False, obj=False), [])
        assert "1/3 components matched" in reason

    def test_unknown_with_no_matches_reports_zero(self, explainer):
        reason = explainer.explain(span("unknown", 0.2, False, False, False), [])
        assert "0/3 components matched" in reason

    @pytest.mark.parametrize(
        "subject,relation,obj,expected",
        [
            (True, False, True, "Relation component missing"),
            (False, True, True, "Subject component missing"),
            (True, True, False, "Object component missing"),
        ],
    )
    def test_partial_names_the_missing_component(self, explainer, subject, relation, obj, expected):
        reason = explainer.explain(span("partial", 0.5, subject, relation, obj), [])
        assert reason == expected

    def test_partial_with_all_components_is_superseded(self, explainer):
        assert explainer.explain(span("partial", 0.5), []) == "Partial match, superseded by stronger evidence"

    def test_supports_rejection_cites_the_confidence_gap(self, explainer):
        used = [span("supports", 0.95, chunk_id="used")]
        reason = explainer.explain(span("supports", 0.6, chunk_id="rejected"), used)

        assert "0.6" in reason and "0.95" in reason

    def test_supports_at_equal_confidence_falls_back_to_supersession(self, explainer):
        used = [span("supports", 0.6, chunk_id="used")]
        assert explainer.explain(span("supports", 0.6), used) == "Superseded by stronger evidence"


class TestUsedRejectedSplit:
    def _pair(self, support_type, chunk_id):
        return RetrievalResult(chunk_id=chunk_id, score=0.5, source="fusion"), span(
            support_type, 0.5, chunk_id=chunk_id
        )

    def test_unknown_chunks_are_rejected_when_informative_evidence_exists(self):
        adjudicated = [
            self._pair("supports", "a"),
            self._pair("unknown", "b"),
            self._pair("partial", "c"),
        ]
        used, rejected = SVOVerificationEngine._split_used_and_rejected(adjudicated)

        assert [span.chunk_id for _, span in used] == ["a", "c"]
        assert [span.chunk_id for _, span in rejected] == ["b"]

    def test_all_chunks_are_kept_when_none_took_a_stance(self):
        adjudicated = [self._pair("unknown", "a"), self._pair("unknown", "b")]
        used, rejected = SVOVerificationEngine._split_used_and_rejected(adjudicated)

        assert len(used) == 2
        assert rejected == []

    def test_describe_rejected_reports_every_required_field(self):
        engine = SVOVerificationEngine(
            router=None, lexical_store=None, semantic_store=None, graph_store=None,
            fusion_engine=None, chunk_store=None, validator=None,
        )
        rejected = [self._pair("unknown", "b")]
        described = engine._describe_rejected(rejected, [span("supports", 0.9)])

        assert len(described) == 1
        assert set(described[0]) == {
            "chunk_id", "text", "retrieval_score", "adjudication", "confidence", "reason_rejected",
        }
        assert described[0]["adjudication"] == "unknown"
