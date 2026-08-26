"""One triple raising inside adjudication must not 500 the whole batch."""

from unittest import mock

import pytest

from src.config import PipelineConfig, BackendMode
from src.engine import SVOVerificationEngine
from src.models import OntologyAssertion


def test_one_bad_triple_does_not_discard_the_rest(temp_db_path, sample_document):
    config = PipelineConfig(backend_mode=BackendMode.DEMO, sqlite_path=temp_db_path)
    engine = SVOVerificationEngine.from_config(config)

    good_triple = OntologyAssertion(
        assertion_id="good",
        subject="Aspirin",
        relation="treats",
        object="headache",
        polarity="must_hold",
        rule_type="constraint",
    )
    bad_triple = OntologyAssertion(
        assertion_id="bad",
        subject="Aspirin",
        relation="reduces",
        object="fever",
        polarity="must_hold",
        rule_type="constraint",
    )

    real_adjudicate = engine.adjudicate_triple

    def flaky_adjudicate(*args, **kwargs):
        assertion = kwargs.get("assertion") or args[1]
        if assertion.assertion_id == "bad":
            raise RuntimeError("boom")
        return real_adjudicate(*args, **kwargs)

    with mock.patch.object(engine, "adjudicate_triple", side_effect=flaky_adjudicate):
        result = engine.validate_triples_batch(
            document_id="doc1",
            raw_text=sample_document,
            triples=[good_triple, bad_triple],
            top_k=5,
        )

    assert len(result["verdicts"]) == 2
    by_id = {v["assertion_id"]: v for v in result["verdicts"]}
    assert by_id["bad"]["label"] == "unknown"
    assert by_id["bad"]["score"] == 0.0
    assert by_id["bad"]["evidence"] == []
    assert by_id["good"]["assertion_id"] == "good"
    assert result["summary"]["errors"] == 1
    assert result["summary"]["total_triples"] == 2
