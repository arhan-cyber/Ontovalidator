from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from api.routes import health as health_route


def fake_report():
    report = MagicMock()
    report.to_dict.return_value = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_status": "DEGRADED",
        "backends": {
            "sqlite": {
                "backend_name": "sqlite",
                "is_healthy": True,
                "latency_ms": 1.2,
                "error_message": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
        "recommendations": ["Enable Elasticsearch for better lexical search"],
    }
    return report


def test_health_shape(client):
    health_route._cache = None
    with patch.object(health_route.HealthCheckRunner, "check_all", return_value=fake_report()) as mock_check:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_status"] == "DEGRADED"
    assert "sqlite" in body["backends"]
    assert body["recommendations"]
    mock_check.assert_called_once()


def test_health_cached_within_ttl(client):
    health_route._cache = None
    with patch.object(health_route.HealthCheckRunner, "check_all", return_value=fake_report()) as mock_check:
        client.get("/health")
        client.get("/health")
    assert mock_check.call_count == 1


def test_health_force_bypasses_cache(client):
    health_route._cache = None
    with patch.object(health_route.HealthCheckRunner, "check_all", return_value=fake_report()) as mock_check:
        client.get("/health")
        client.get("/health?force=true")
    assert mock_check.call_count == 2
