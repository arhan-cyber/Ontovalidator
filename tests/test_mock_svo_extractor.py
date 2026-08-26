"""MockSVOExtractor must work on arbitrary text, not just the aspirin/headache demo.

It was previously hardcoded to a handful of keyword substrings from one
demo domain - any other document silently yielded zero SVOs. This is a
verb-phrase heuristic instead: still no real NLP dependency, but it
generalizes across domains.
"""

from src.ingestion.extractors import MockSVOExtractor


def test_original_demo_sentences_still_extract():
    extractor = MockSVOExtractor()

    relations = extractor.extract("Aspirin treats headache.")
    assert len(relations) == 1
    assert relations[0].subject_id == "ent_aspirin"
    assert relations[0].relation == "TREATS"
    assert relations[0].object_id == "ent_headache"

    relations = extractor.extract("Aspirin reduces fever.")
    assert len(relations) == 1
    assert relations[0].relation == "REDUCES"
    assert relations[0].object_id == "ent_fever"


def test_cross_domain_sentences_extract_real_svos():
    extractor = MockSVOExtractor()
    cases = [
        "The compiler optimizes bytecode.",
        "Regulators require quarterly audits.",
        "Photosynthesis produces oxygen.",
    ]
    for sentence in cases:
        relations = extractor.extract(sentence)
        assert len(relations) >= 1, f"expected at least one SVO for: {sentence!r}"
        rel = relations[0]
        assert rel.subject_id.startswith("ent_")
        assert rel.object_id.startswith("ent_")
        assert rel.subject_name_type
        assert rel.object_name_type


def test_sentence_with_no_recognizable_verb_yields_nothing():
    extractor = MockSVOExtractor()
    relations = extractor.extract("Blue green yellow red.")
    assert relations == []


def test_extract_handles_multi_sentence_text():
    extractor = MockSVOExtractor()
    text = "The compiler optimizes bytecode. Regulators require quarterly audits."
    relations = extractor.extract(text)
    assert len(relations) == 2
