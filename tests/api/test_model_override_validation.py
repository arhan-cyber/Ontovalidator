"""Bug 2 repro tests: unknown embedding_model/svo_extractor overrides must error,
not silently fall back to the default engine.

Reuses the stub_engine_pool/mock_engine/client fixtures from tests/api/conftest.py
(autouse), which populate api.dependencies.ENGINE_POOL with a fixed
{("simple","mock"), ("simple","transformer"), ("transformer","mock"),
("transformer","transformer")} pool and DEFAULT_KEY=("simple","mock").
"""

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


def test_unknown_embedding_model_rejected(client, stub_engine_pool):
    resp = client.post(
        "/api/validate", json=valid_payload(embedding_model="nonexistent")
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["error"] == "unknown_embedding_model"
    assert "nonexistent" in body["error"]["detail"]
    # must not have silently fallen back to the default engine
    stub_engine_pool[("simple", "mock")].validate_triples_batch.assert_not_called()


def test_unknown_svo_extractor_rejected(client, stub_engine_pool):
    resp = client.post(
        "/api/validate", json=valid_payload(svo_extractor="nonexistent")
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["error"] == "unknown_svo_extractor"
    assert "nonexistent" in body["error"]["detail"]
    stub_engine_pool[("simple", "mock")].validate_triples_batch.assert_not_called()


def test_no_overrides_still_falls_back_to_default(client, mock_engine):
    """Both left unspecified: falling back to the default engine is still correct."""
    resp = client.post("/api/validate", json=valid_payload())
    assert resp.status_code == 200
    mock_engine.validate_triples_batch.assert_called_once()


def test_valid_override_still_selects_pooled_engine(client, stub_engine_pool):
    """Sanity: a known-valid override combo still works (not over-corrected into
    rejecting everything)."""
    transformer_engine = stub_engine_pool[("transformer", "transformer")]
    transformer_engine.validate_triples_batch.return_value = canned_result(
        document_id="doc_tt"
    )
    resp = client.post(
        "/api/validate",
        json=valid_payload(embedding_model="transformer", svo_extractor="transformer"),
    )
    assert resp.status_code == 200
    assert resp.json()["document_id"] == "doc_tt"


def test_unbuilt_combination_rejected_not_silently_fallback(client, stub_engine_pool, monkeypatch):
    """A combo whose components are each individually valid but whose specific
    pairing failed to build at startup (missing from ENGINE_POOL) must also
    error rather than silently falling back to the default engine."""
    from api import dependencies

    pool_without_combo = dict(stub_engine_pool)
    del pool_without_combo[("transformer", "mock")]
    monkeypatch.setattr(dependencies, "ENGINE_POOL", pool_without_combo)

    resp = client.post(
        "/api/validate",
        json=valid_payload(embedding_model="transformer", svo_extractor="mock"),
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["error"] == "unavailable_model_combination"
