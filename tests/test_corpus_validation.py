"""Corpus-scoped adjudication, for claims spread across several documents.

`validate_triples_batch` couples one ingest to one document. The ontology
plane can't use that: its claims come from a model built over a corpus of
process manuals, and any single claim may only be evidenced in one of them.
"""

import json

import pytest

from src.config import PipelineConfig
from src.engine import SVOVerificationEngine
from src.models import OntologyAssertion


@pytest.fixture
def engine(tmp_path):
    config = PipelineConfig(
        sqlite_path=str(tmp_path / "svo.db"),
        cache_db_path=str(tmp_path / "cache.db"),
        feedback_db_path=str(tmp_path / "feedback.db"),
        enable_cache=True,
    )
    return SVOVerificationEngine.from_config(config)


def _ingest(engine, document_id, text):
    engine.validate_triples_batch(document_id, text, [], top_k=3)


def _assertion(assertion_id, subject, relation, obj):
    return OntologyAssertion(
        assertion_id=assertion_id, subject=subject, relation=relation, object=obj
    )


def test_evidence_is_found_across_separate_documents(engine):
    """The point of corpus mode: one claim per manual, both grounded."""
    _ingest(engine, "manual_event", "Event Management includes the process Detect and Log Event.")
    _ingest(engine, "manual_incident", "Incident Management includes the process Classification.")

    result = engine.validate_assertions_corpus([
        _assertion("a1", "Event Management", "includes the process", "Detect and Log Event"),
        _assertion("a2", "Incident Management", "includes the process", "Classification"),
    ], top_k=3)

    labels = {v["assertion_id"]: v["label"] for v in result["verdicts"]}
    assert labels["a1"] == "supported"
    assert labels["a2"] == "supported"
    assert result["summary"]["errors"] == 0


def test_claim_absent_from_the_corpus_is_not_supported(engine):
    _ingest(engine, "manual", "Event Management includes the process Detect and Log Event.")
    result = engine.validate_assertions_corpus(
        [_assertion("ghost", "Event Management", "includes the process", "Ghost Activity")],
        top_k=3,
    )
    assert result["verdicts"][0]["label"] != "supported"


def test_verdicts_replay_from_cache_on_an_unchanged_corpus(engine):
    _ingest(engine, "manual", "Event Management includes the process Detect and Log Event.")
    claims = [_assertion("a1", "Event Management", "includes the process", "Detect and Log Event")]

    assert engine.validate_assertions_corpus(claims, top_k=3)["summary"]["cache_hits"] == 0
    assert engine.validate_assertions_corpus(claims, top_k=3)["summary"]["cache_hits"] == 1


def test_growing_the_corpus_invalidates_cached_verdicts(engine):
    """A verdict adjudicated against a smaller corpus must not be replayed.

    Corpus mode has no raw-text digest to key on the way single-document mode
    does, so the fingerprint is over what is ingested. If it didn't move here,
    adding a document that contradicts a claim would never change its verdict.
    """
    _ingest(engine, "manual", "Event Management includes the process Detect and Log Event.")
    claims = [_assertion("a1", "Event Management", "includes the process", "Detect and Log Event")]

    engine.validate_assertions_corpus(claims, top_k=3)
    before = engine.corpus_fingerprint()

    _ingest(engine, "manual_2", "Incident Management handles incidents.")
    after = engine.corpus_fingerprint()

    assert before != after
    assert engine.validate_assertions_corpus(claims, top_k=3)["summary"]["cache_hits"] == 0


def test_corpus_verdicts_do_not_collide_with_single_document_ones(engine):
    """Corpus verdicts live in their own cache namespace."""
    text = "Event Management includes the process Detect and Log Event."
    triple = _assertion("a1", "Event Management", "includes the process", "Detect and Log Event")
    engine.validate_triples_batch("manual", text, [triple], top_k=3)

    # Same assertion_id, corpus scope: must adjudicate rather than replay the
    # single-document verdict.
    assert engine.validate_assertions_corpus([triple], top_k=3)["summary"]["cache_hits"] == 0


def test_progress_callback_reports_every_assertion(engine):
    _ingest(engine, "manual", "Event Management includes the process Detect and Log Event.")
    claims = [_assertion(f"a{i}", "Event Management", "includes", f"Thing {i}") for i in range(4)]

    seen = []
    engine.validate_assertions_corpus(claims, top_k=3, progress_callback=lambda i, t, a: seen.append((i, t, a)))

    assert [s[0] for s in seen] == [1, 2, 3, 4]
    assert all(s[1] == 4 for s in seen)
    assert [s[2] for s in seen] == [c.assertion_id for c in claims]


def test_broken_progress_callback_does_not_abort_the_run(engine):
    _ingest(engine, "manual", "Event Management includes the process Detect and Log Event.")

    def explode(index, total, assertion_id):
        raise RuntimeError("reporter is broken")

    result = engine.validate_assertions_corpus(
        [_assertion("a1", "Event Management", "includes the process", "Detect and Log Event")],
        top_k=3, progress_callback=explode,
    )
    assert result["summary"]["total_triples"] == 1
    assert result["summary"]["errors"] == 0


def test_empty_assertion_list_is_handled(engine):
    _ingest(engine, "manual", "Some text.")
    result = engine.validate_assertions_corpus([], top_k=3)
    assert result["summary"]["total_triples"] == 0
    assert result["summary"]["avg_score"] == 0.0
    assert result["verdicts"] == []


def test_single_document_batch_behaviour_is_unchanged(engine):
    """Regression guard: the new path must not have disturbed the old one."""
    result = engine.validate_triples_batch(
        "doc1",
        "Aspirin treats headache. Aspirin reduces fever.",
        [_assertion("t1", "Aspirin", "treats", "headache")],
        top_k=5,
    )
    assert result["document_id"] == "doc1"
    assert result["verdicts"][0]["label"] == "supported"
    assert "corpus_fingerprint" not in result
