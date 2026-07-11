from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import torch

from src.models import EvidencePack, EvidencePackEntry
from src.classification.evidence_judge import FewShotPromptEvidenceJudge, HeuristicEvidenceJudge


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


class FakeTokenizer:
    def __init__(self, decoded_text="supported"):
        self.decoded_text = decoded_text

    def __call__(self, prompt, return_tensors=None, truncation=None, max_length=None):
        return {"input_ids": torch.tensor([[1, 2, 3]])}

    def decode(self, ids, skip_special_tokens=True):
        return self.decoded_text


def _fake_generate_output(vocab_size=10, n_new_tokens=1, decoded_text="supported"):
    scores = [torch.zeros(1, vocab_size) for _ in range(n_new_tokens)]
    for step in scores:
        step[0, 5] = 10.0  # high logit -> confident token
    sequences = torch.tensor([[0] + [5] * n_new_tokens])
    return SimpleNamespace(sequences=sequences, scores=scores)


def _judge_with_model(model, tokenizer):
    """Bypass __init__'s real transformers loading (mirrors the PromptEvidenceJudge
    test pattern) and inject the model/tokenizer directly."""
    judge = FewShotPromptEvidenceJudge.__new__(FewShotPromptEvidenceJudge)
    judge.model_name = "google/flan-t5-large"
    judge._fallback = HeuristicEvidenceJudge()
    judge.model = model
    judge.tokenizer = tokenizer
    return judge


def test_few_shot_judge_includes_worked_examples_in_prompt():
    judge = _judge_with_model(MagicMock(), FakeTokenizer())
    prompt = judge._build_few_shot_prompt(_pack())

    assert "Example 1:" in prompt
    assert "Example 4:" in prompt
    assert "Now classify the following:" in prompt
    assert "Aspirin treats headache" in prompt


def test_few_shot_judge_parses_generated_label():
    fake_model = MagicMock()
    fake_model.generate.return_value = _fake_generate_output(decoded_text="supported")
    judge = _judge_with_model(fake_model, FakeTokenizer(decoded_text="supported"))

    verdict = judge.judge(_pack())

    assert verdict.label == "supported"
    assert 0.0 < verdict.confidence <= 1.0
    assert verdict.evidence_chunk_ids == ["c1"]
    fake_model.generate.assert_called_once()


def test_few_shot_judge_parses_label_embedded_in_extra_text():
    fake_model = MagicMock()
    fake_model.generate.return_value = _fake_generate_output(decoded_text="Label: contradicted")
    judge = _judge_with_model(fake_model, FakeTokenizer(decoded_text="Label: contradicted"))

    verdict = judge.judge(_pack())

    assert verdict.label == "contradicted"


def test_few_shot_judge_parses_paraphrased_label_via_alias():
    fake_model = MagicMock()
    fake_model.generate.return_value = _fake_generate_output(decoded_text="insufficient")
    judge = _judge_with_model(fake_model, FakeTokenizer(decoded_text="insufficient"))

    verdict = judge.judge(_pack())

    assert verdict.label == "unknown"


def test_few_shot_judge_falls_back_on_unparsable_output():
    fake_model = MagicMock()
    fake_model.generate.return_value = _fake_generate_output(decoded_text="I am not sure about this at all")
    judge = _judge_with_model(fake_model, FakeTokenizer(decoded_text="I am not sure about this at all"))

    verdict = judge.judge(_pack())

    # Heuristic fallback: direct support match -> "supported"
    assert verdict.label == "supported"
    assert "unparsable output" in verdict.rationale


def test_few_shot_judge_falls_back_when_model_unavailable():
    judge = _judge_with_model(None, None)

    verdict = judge.judge(_pack())

    assert verdict.label == "supported"


def test_few_shot_judge_falls_back_on_generation_error():
    fake_model = MagicMock()
    fake_model.generate.side_effect = RuntimeError("generation failed")
    judge = _judge_with_model(fake_model, FakeTokenizer())

    verdict = judge.judge(_pack())

    assert verdict.label == "supported"
    assert "Few-shot LM judge failed" in verdict.rationale


def test_few_shot_judge_falls_back_when_transformers_import_fails():
    with patch("builtins.__import__", side_effect=ImportError("no transformers")):
        judge = FewShotPromptEvidenceJudge()

    assert judge.model is None
    assert judge.tokenizer is None

    verdict = judge.judge(_pack())

    assert verdict.label == "supported"
