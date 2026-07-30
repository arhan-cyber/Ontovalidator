"""Feedback storage: recording corrections and reading them back."""

import os

import pytest

from src.feedback import FeedbackRecorder
from src.models import EvidenceSpan, TripleVerdict


@pytest.fixture
def recorder(tmp_workspace):
    return FeedbackRecorder(os.path.join(tmp_workspace, "feedback.db"))


def verdict(assertion_id="t1", label="supported", score=0.9, sources=("lexical",)):
    return TripleVerdict(
        assertion_id=assertion_id,
        subject="Aspirin",
        relation="treats",
        object="headache",
        label=label,
        score=score,
        rationale="matched",
        evidence=[
            EvidenceSpan(
                chunk_id="c1",
                text="Aspirin treats headache.",
                source="fusion",
                support_type="supports",
                confidence=0.95,
                matched_subject=True,
                matched_relation=True,
                matched_object=True,
            )
        ],
        counter_evidence=[],
        retrieval_sources=list(sources),
        rule_hits=["direct_support"],
    )


class TestRecordCorrection:
    def test_correction_is_persisted_with_full_context(self, recorder):
        recorder.record_correction(verdict(), actual_label="partial", document_id="doc1", actual_reason="too strong")

        rows = recorder.get_corrections()
        assert len(rows) == 1
        assert rows[0]["predicted_label"] == "supported"
        assert rows[0]["actual_label"] == "partial"
        assert rows[0]["actual_reason"] == "too strong"
        assert rows[0]["used_evidence_count"] == 1
        assert rows[0]["document_id"] == "doc1"

    def test_recording_twice_for_one_triple_keeps_only_the_latest(self, recorder):
        recorder.record_correction(verdict(), actual_label="partial", document_id="doc1")
        recorder.record_correction(verdict(), actual_label="unknown", document_id="doc1")

        rows = recorder.get_corrections()
        assert len(rows) == 1
        assert rows[0]["actual_label"] == "unknown"

    def test_same_triple_in_different_documents_is_kept_separately(self, recorder):
        recorder.record_correction(verdict(), actual_label="partial", document_id="doc1")
        recorder.record_correction(verdict(), actual_label="partial", document_id="doc2")

        assert len(recorder.get_corrections()) == 2

    def test_unknown_label_is_rejected(self, recorder):
        with pytest.raises(ValueError):
            recorder.record_correction(verdict(), actual_label="totally-wrong", document_id="doc1")

    def test_reopening_the_database_preserves_records(self, tmp_workspace):
        path = os.path.join(tmp_workspace, "feedback.db")
        FeedbackRecorder(path).record_correction(verdict(), actual_label="partial", document_id="doc1")

        assert len(FeedbackRecorder(path).get_corrections()) == 1


class TestErrorPatterns:
    def test_empty_database_reports_zeroes(self, recorder):
        patterns = recorder.get_error_patterns()

        assert patterns["total_corrections"] == 0
        assert patterns["accuracy"] == 0.0
        assert patterns["confusion_matrix"] == {}

    def test_confusion_matrix_counts_each_cell(self, recorder):
        for i in range(3):
            recorder.record_correction(verdict(f"t{i}"), actual_label="partial", document_id="doc1")
        recorder.record_correction(verdict("t9"), actual_label="supported", document_id="doc1")

        patterns = recorder.get_error_patterns()
        assert patterns["confusion_matrix"]["supported"] == {"partial": 3, "supported": 1}
        assert patterns["total_corrections"] == 4
        assert patterns["accuracy"] == 0.25

    def test_retriever_analysis_ranks_worst_combination_first(self, recorder):
        for i in range(2):
            recorder.record_correction(
                verdict(f"lex{i}", sources=("lexical",)), actual_label="partial", document_id="doc1"
            )
        recorder.record_correction(
            verdict("both", sources=("lexical", "semantic")), actual_label="supported", document_id="doc1"
        )

        analysis = recorder.get_retriever_analysis()
        assert analysis[0]["retrieval_sources"] == ["lexical"]
        assert analysis[0]["error_rate"] == 1.0
        assert analysis[-1]["error_rate"] == 0.0
