"""POST /feedback/correct and GET /feedback/analysis."""

import os

import pytest

from src.cache import CacheEngine
from src.feedback import FeedbackRecorder


@pytest.fixture
def recorder(tmp_workspace):
    return FeedbackRecorder(os.path.join(tmp_workspace, "feedback.db"))


@pytest.fixture
def cache(tmp_workspace):
    return CacheEngine(os.path.join(tmp_workspace, "cache.db"))


@pytest.fixture
def wired_engine(mock_engine, recorder, cache):
    mock_engine.feedback_recorder = recorder
    mock_engine.cache_engine = cache
    return mock_engine


@pytest.fixture
def cached_verdict(cache):
    feedback_id = "fb-123"
    cache.set(
        "feedback_verdict",
        {
            "verdict": {
                "assertion_id": "t1",
                "subject": "Aspirin",
                "relation": "treats",
                "object": "headache",
                "label": "supported",
                "score": 0.9,
                "rationale": "matched",
                "retrieval_sources": ["lexical"],
                "rule_hits": ["direct_support"],
            },
            "document_id": "doc1",
        },
        feedback_id,
    )
    return feedback_id


class TestSubmitCorrection:
    def test_a_cached_verdict_can_be_corrected_by_id_alone(self, client, wired_engine, recorder, cached_verdict):
        response = client.post(
            "/feedback/correct",
            json={"feedback_id": cached_verdict, "actual_label": "partial", "reason": "too strong"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "recorded"
        assert response.json()["predicted_label"] == "supported"

        stored = recorder.get_corrections()[0]
        assert stored["actual_label"] == "partial"
        assert stored["subject"] == "Aspirin"

    def test_the_verdict_can_be_resent_when_the_cache_has_expired(self, client, wired_engine, recorder):
        response = client.post(
            "/feedback/correct",
            json={
                "feedback_id": "gone",
                "actual_label": "unknown",
                "document_id": "doc1",
                "assertion_id": "t9",
                "subject": "Aspirin",
                "relation": "treats",
                "object": "malaria",
                "predicted_label": "partial",
                "predicted_score": 0.4,
            },
        )

        assert response.status_code == 200
        assert recorder.get_corrections()[0]["assertion_id"] == "t9"

    def test_an_unresolvable_verdict_is_a_404(self, client, wired_engine):
        response = client.post("/feedback/correct", json={"feedback_id": "gone", "actual_label": "partial"})

        assert response.status_code == 404
        assert response.json()["error"]["error"] == "verdict_not_found"

    def test_an_unknown_label_is_rejected(self, client, wired_engine, cached_verdict):
        response = client.post(
            "/feedback/correct",
            json={"feedback_id": cached_verdict, "actual_label": "definitely-not-a-label"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["error"] == "invalid_label"

    def test_a_missing_label_is_rejected_by_validation(self, client, wired_engine):
        assert client.post("/feedback/correct", json={"feedback_id": "x"}).status_code == 422

    def test_feedback_disabled_reports_service_unavailable(self, client, mock_engine):
        mock_engine.feedback_recorder = None

        response = client.post("/feedback/correct", json={"feedback_id": "x", "actual_label": "partial"})

        assert response.status_code == 503
        assert response.json()["error"]["error"] == "feedback_disabled"


class TestAnalysis:
    def test_empty_feedback_returns_an_empty_report(self, client, wired_engine):
        response = client.get("/feedback/analysis")

        assert response.status_code == 200
        assert response.json()["summary"]["total_corrections"] == 0
        assert response.json()["recommendations"] == []

    def test_recorded_corrections_appear_in_the_analysis(self, client, wired_engine, cached_verdict):
        client.post("/feedback/correct", json={"feedback_id": cached_verdict, "actual_label": "partial"})

        body = client.get("/feedback/analysis").json()

        assert body["summary"]["total_corrections"] == 1
        assert body["error_analysis"]["confusion_matrix"] == {"supported": {"partial": 1}}

    def test_the_window_is_configurable(self, client, wired_engine):
        assert client.get("/feedback/analysis?days=7").json()["summary"]["window_days"] == 7

    def test_a_nonsensical_window_is_rejected(self, client, wired_engine):
        assert client.get("/feedback/analysis?days=0").status_code == 400
