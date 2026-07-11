from unittest.mock import MagicMock, patch

from src.models import EvidencePack, EvidencePackEntry
from src.classification.evidence_judge import PromptEvidenceJudge, HeuristicEvidenceJudge


def _pack():
    return EvidencePack(
        assertion_id="a1",
        subject="Aspirin",
        relation="treats",
        object="headache",
        polarity="must_hold",
        rule_type="constraint",
        evidence=[
            EvidencePackEntry(
                chunk_id="c1",
                text="Aspirin treats headache.",
                source="lexical",
                retrieval_score=0.9,
                support_type="supports",
                matched_subject=True,
                matched_relation=True,
                matched_object=True,
            )
        ],
        graph_summary=["Aspirin -> treats -> headache"],
    )


def _judge_with_classifier(classifier):
    """Bypass __init__'s real transformers loading (which resists simple attribute
    patching due to transformers' lazy-module __getattr__) and inject the classifier
    directly, so we can test .judge()'s parsing/fallback logic in isolation."""
    judge = PromptEvidenceJudge.__new__(PromptEvidenceJudge)
    judge.model_name = "typeform/distilbert-base-uncased-mnli"
    judge._fallback = HeuristicEvidenceJudge()
    judge.classifier = classifier
    return judge


def test_prompt_judge_parses_zero_shot_response():
    fake_pipeline = MagicMock(
        return_value={"labels": ["supported", "partial", "unknown", "contradicted"], "scores": [0.87, 0.08, 0.03, 0.02]}
    )
    judge = _judge_with_classifier(fake_pipeline)

    verdict = judge.judge(_pack())

    assert verdict.label == "supported"
    assert verdict.confidence == 0.87
    assert verdict.evidence_chunk_ids == ["c1"]
    fake_pipeline.assert_called_once()


def test_prompt_judge_falls_back_to_heuristic_when_classifier_unavailable():
    judge = _judge_with_classifier(None)

    verdict = judge.judge(_pack())

    # Heuristic fallback: direct support match -> "supported"
    assert verdict.label == "supported"


def test_prompt_judge_falls_back_on_inference_error():
    fake_pipeline = MagicMock(side_effect=RuntimeError("inference failed"))
    judge = _judge_with_classifier(fake_pipeline)

    verdict = judge.judge(_pack())

    assert verdict.label == "supported"
    assert "LM judge failed" in verdict.rationale


def test_prompt_judge_falls_back_when_transformers_import_fails():
    with patch("builtins.__import__", side_effect=ImportError("no transformers")):
        judge = PromptEvidenceJudge()

    assert judge.classifier is None

    verdict = judge.judge(_pack())

    assert verdict.label == "supported"
