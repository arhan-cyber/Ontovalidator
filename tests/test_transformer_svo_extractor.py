"""TransformerSVOExtractor must never be a silent no-op on ordinary text.

Zero-shot prompting on flan-t5-small ignored the requested comma-separated
format entirely, so the parser's `len(parts) >= 3` guard discarded every
sentence and the extractor returned [] on all real-world text without ever
raising. A few-shot prompt improved this but is still unreliable roughly
half the time (small seq2seq model), so the extractor now falls back to the
deterministic `MockSVOExtractor` heuristic whenever the LM's output doesn't
parse into a clean triple - these tests assert that fallback actually fires
and produces something, not that the LM itself is reliable.
"""

import pytest

from src.ingestion.embeddings import TransformerSVOExtractor


@pytest.fixture(scope="module")
def extractor():
    return TransformerSVOExtractor()


def test_ordinary_sentences_never_come_back_empty(extractor):
    # These are exactly the sentences that returned [] for every one of them
    # before this fix (confirmed via direct repro during stress testing).
    sentences = [
        "Aspirin reduces fever effectively in clinical trials.",
        "The compiler optimizes bytecode.",
        "Regulators require quarterly audits.",
        "Photosynthesis produces oxygen.",
    ]
    for sentence in sentences:
        relations = extractor.extract(sentence)
        assert relations, f"expected at least one SVO relation for {sentence!r}, got none"
        rel = relations[0]
        assert rel.subject_id.startswith("ent_")
        assert rel.object_id.startswith("ent_")


def test_empty_and_degenerate_text_returns_empty_not_a_crash(extractor):
    assert extractor.extract("") == []
    assert extractor.extract("   ") == []
    assert extractor.extract("Blue green yellow red.") == []  # no recognizable verb


def test_lm_failure_falls_back_to_heuristic(monkeypatch, extractor):
    def broken_generate(*args, **kwargs):
        raise RuntimeError("simulated model failure")

    monkeypatch.setattr(extractor.model, "generate", broken_generate)
    relations = extractor.extract("Aspirin treats headache.")
    assert len(relations) == 1
    assert relations[0].relation == "TREATS"
