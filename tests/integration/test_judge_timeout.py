"""A hung evidence_judge.judge() call must not block a request indefinitely.

`SVOVerificationEngine._call_with_timeout` bounds the caller's wait using a
single-use thread; a call that exceeds `config.judge_timeout_s` is treated
the same as a judge that raised - the heuristic verdict is used instead.
"""

import time

import pytest

from src.config import PipelineConfig, BackendMode
from src.engine import SVOVerificationEngine
from src.models import OntologyAssertion, JudgeVerdict


def test_call_with_timeout_returns_fast_result():
    result = SVOVerificationEngine._call_with_timeout(lambda: "ok", 5.0)
    assert result == "ok"


def test_call_with_timeout_raises_on_slow_call():
    from concurrent.futures import TimeoutError as FutureTimeoutError

    def slow():
        time.sleep(2.0)
        return "too late"

    start = time.monotonic()
    with pytest.raises(FutureTimeoutError):
        SVOVerificationEngine._call_with_timeout(slow, 0.2)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, "caller should not wait for the slow call to finish"


class _SlowJudge:
    def __init__(self, delay_s):
        self.delay_s = delay_s

    def judge(self, evidence_pack):
        time.sleep(self.delay_s)
        return JudgeVerdict(
            label="supported", confidence=0.9, rationale="slow",
            evidence_chunk_ids=[], counterevidence_chunk_ids=[],
        )


class _FastJudge:
    def judge(self, evidence_pack):
        return JudgeVerdict(
            label="supported", confidence=0.9, rationale="fast",
            evidence_chunk_ids=[], counterevidence_chunk_ids=[],
        )


def _engine_with_judge(temp_db_path, judge, timeout_s):
    config = PipelineConfig(
        backend_mode=BackendMode.DEMO,
        sqlite_path=temp_db_path,
        judge_timeout_s=timeout_s,
    )
    engine = SVOVerificationEngine.from_config(config)
    engine.evidence_judge = judge
    return engine


def test_slow_judge_falls_back_to_heuristic_within_timeout(temp_db_path, sample_document, monkeypatch):
    engine = _engine_with_judge(temp_db_path, _SlowJudge(delay_s=2.0), timeout_s=0.3)
    monkeypatch.setattr(engine, "_should_run_evidence_judge", lambda *a, **k: True)

    engine.validate_triples_batch(document_id="doc1", raw_text=sample_document, triples=[], top_k=5)
    triple = OntologyAssertion(
        assertion_id="t1", subject="Aspirin", relation="treats", object="headache",
        polarity="must_hold", rule_type="constraint",
    )

    start = time.monotonic()
    verdict = engine.adjudicate_triple(document_text=None, assertion=triple, document_id="doc1", top_k=5)
    elapsed = time.monotonic() - start

    assert elapsed < 1.5, "adjudication should not wait for the full judge delay"
    assert "evidence_judge" not in verdict.rule_hits


def test_fast_judge_result_is_used_normally(temp_db_path, sample_document, monkeypatch):
    engine = _engine_with_judge(temp_db_path, _FastJudge(), timeout_s=5.0)
    monkeypatch.setattr(engine, "_should_run_evidence_judge", lambda *a, **k: True)

    engine.validate_triples_batch(document_id="doc1", raw_text=sample_document, triples=[], top_k=5)
    triple = OntologyAssertion(
        assertion_id="t1", subject="Aspirin", relation="treats", object="headache",
        polarity="must_hold", rule_type="constraint",
    )

    verdict = engine.adjudicate_triple(document_text=None, assertion=triple, document_id="doc1", top_k=5)
    assert "evidence_judge" in verdict.rule_hits
