"""Feedback dashboard: metrics and the recommendations derived from them."""

import os

import pytest

from src.feedback import FeedbackDashboard, FeedbackRecorder
from tests.test_feedback_recorder import verdict


@pytest.fixture
def recorder(tmp_workspace):
    return FeedbackRecorder(os.path.join(tmp_workspace, "feedback.db"))


def record_many(recorder, count, predicted, actual, prefix="t", sources=("lexical",)):
    for i in range(count):
        recorder.record_correction(
            verdict(f"{prefix}{i}", label=predicted, sources=sources),
            actual_label=actual,
            document_id="doc1",
        )


class TestComputeMetrics:
    def test_empty_feedback_produces_an_empty_report(self, recorder):
        metrics = FeedbackDashboard(recorder).compute_metrics()

        assert metrics["summary"]["total_corrections"] == 0
        assert metrics["error_analysis"]["most_common_error"] is None
        assert metrics["recommendations"] == []

    def test_most_common_error_ignores_the_diagonal(self, recorder):
        record_many(recorder, 5, "supported", "supported", prefix="right")
        record_many(recorder, 2, "supported", "partial", prefix="wrong")

        error = FeedbackDashboard(recorder).compute_metrics()["error_analysis"]["most_common_error"]
        assert error == {"predicted": "supported", "actual": "partial", "count": 2}

    def test_summary_reports_accuracy_over_the_window(self, recorder):
        record_many(recorder, 3, "supported", "supported", prefix="a")
        record_many(recorder, 1, "supported", "partial", prefix="b")

        summary = FeedbackDashboard(recorder).compute_metrics()["summary"]
        assert summary["total_corrections"] == 4
        assert summary["system_accuracy"] == 0.75
        assert summary["window_days"] == 30


class TestRecommendations:
    def test_repeated_supported_to_partial_errors_are_flagged(self, recorder):
        record_many(recorder, 4, "supported", "partial")

        recommendations = FeedbackDashboard(recorder).compute_metrics()["recommendations"]
        assert any("support_strength threshold" in r for r in recommendations)

    def test_missed_contradictions_recommend_reviewing_negation(self, recorder):
        record_many(recorder, 3, "supported", "contradicted")

        recommendations = FeedbackDashboard(recorder).compute_metrics()["recommendations"]
        assert any("negation detection" in r for r in recommendations)

    def test_a_single_error_is_not_enough_to_recommend(self, recorder):
        record_many(recorder, 1, "supported", "partial")

        assert FeedbackDashboard(recorder).compute_metrics()["recommendations"] == []

    def test_bad_retriever_combination_is_flagged_once_there_is_signal(self, recorder):
        record_many(recorder, 4, "supported", "partial", prefix="bad", sources=("graph",))

        recommendations = FeedbackDashboard(recorder).compute_metrics()["recommendations"]
        assert any("['graph']" in r and "error rate" in r for r in recommendations)

    def test_retriever_performance_orders_best_and_worst(self, recorder):
        record_many(recorder, 3, "supported", "partial", prefix="bad", sources=("graph",))
        record_many(recorder, 3, "supported", "supported", prefix="good", sources=("lexical", "semantic"))

        performance = FeedbackDashboard(recorder).compute_metrics()["retriever_performance"]
        assert performance["worst_combination"]["retrieval_sources"] == ["graph"]
        assert performance["best_combination"]["retrieval_sources"] == ["lexical", "semantic"]
