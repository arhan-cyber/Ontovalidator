from unittest.mock import MagicMock

from api import dependencies
from .conftest import canned_result


def valid_payload(**overrides):
    payload = {
        "raw_text": "The engine drives the wheel.",
        "triples": [
            {"subject": "engine", "relation": "drives", "object": "wheel"},
        ],
    }
    payload.update(overrides)
    return payload


def test_validate_happy_path(client, mock_engine):
    resp = client.post("/validate", json=valid_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == "doc_test"
    assert body["ingestion_status"] == "success"
    assert body["chunks_ingested"] == 1
    assert body["svos_extracted"] == 1
    assert len(body["verdicts"]) == 1
    verdict = body["verdicts"][0]
    assert verdict["label"] == "supported"
    assert verdict["evidence"][0]["matched"] == {"subject": True, "relation": True, "object": True}
    assert body["summary"]["total_triples"] == 1
    assert body["backend_status"]["lexical"] == "SQLiteLexicalRetriever"
    mock_engine.validate_triples_batch.assert_called_once()


def test_validate_empty_raw_text(client):
    resp = client.post("/validate", json=valid_payload(raw_text="   "))
    assert resp.status_code == 400
    assert resp.json() == {"error": {"error": "raw_text must not be empty"}}


def test_validate_empty_triples(client):
    payload = valid_payload()
    payload["triples"] = []
    resp = client.post("/validate", json=payload)
    assert resp.status_code == 422  # min_length=1 rejected by pydantic before handler logic


def test_validate_triple_missing_fields(client):
    payload = valid_payload()
    payload["triples"] = [{"subject": "a"}]
    resp = client.post("/validate", json=payload)
    assert resp.status_code == 422


def test_validate_engine_raises(client, mock_engine):
    mock_engine.validate_triples_batch.side_effect = RuntimeError("boom")
    resp = client.post("/validate", json=valid_payload())
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["error"] == "validation_failed"
    assert "boom" in body["error"]["detail"]


def test_validate_model_override_selects_pooled_engine(client, stub_engine_pool):
    transformer_engine = stub_engine_pool[("transformer", "mock")]
    transformer_engine.validate_triples_batch.return_value = canned_result(document_id="doc_transformer")

    resp = client.post(
        "/validate",
        json=valid_payload(embedding_model="transformer", svo_extractor="mock"),
    )
    assert resp.status_code == 200
    assert resp.json()["document_id"] == "doc_transformer"
    transformer_engine.validate_triples_batch.assert_called_once()
    stub_engine_pool[("simple", "mock")].validate_triples_batch.assert_not_called()


def test_validate_default_id_generation(client, mock_engine):
    payload = valid_payload()
    payload.pop("document_id", None)
    del payload["triples"][0]  # ensure fresh
    payload["triples"] = [
        {"subject": "engine", "relation": "drives", "object": "wheel"},
        {"subject": "wheel", "relation": "stops", "object": "car"},
    ]
    client.post("/validate", json=payload)
    call_kwargs = mock_engine.validate_triples_batch.call_args.kwargs
    assert call_kwargs["document_id"].startswith("doc_")
    assert [t.assertion_id for t in call_kwargs["triples"]] == ["t1", "t2"]
