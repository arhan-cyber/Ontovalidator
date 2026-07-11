def test_config_includes_dropdown_lists(client):
    resp = client.get("/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available_embedding_models"] == ["simple", "transformer"]
    assert body["available_svo_extractors"] == ["mock", "transformer"]
    assert "backend_status" in body


def test_config_redacts_neo4j_password(client):
    resp = client.get("/config")
    body = resp.json()
    assert "neo4j" not in body  # neo4j block isn't part of ConfigResponse at all
    assert "password" not in str(body).lower() or "redacted" in str(body).lower()
