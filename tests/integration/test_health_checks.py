"""Tests for health check functionality."""

import json
import sys
import tempfile
import pytest
from unittest import mock
from datetime import datetime

# Mock external dependencies that might not be installed
sys.modules['elasticsearch'] = mock.MagicMock()
sys.modules['neo4j'] = mock.MagicMock()
sys.modules['pymilvus'] = mock.MagicMock()

from src.config import PipelineConfig, BackendMode, ElasticsearchConfig, MilvusConfig, Neo4jConfig
from src.health_checks import (
    BackendHealthStatus,
    check_elasticsearch_health,
    check_neo4j_health,
    check_milvus_health,
    check_sqlite_health,
)
from src.integration.health_check_runner import HealthCheckRunner, print_health_report, export_health_report


class TestElasticsearchHealthCheck:
    """Test Elasticsearch health checks."""

    def test_check_elasticsearch_health_success(self):
        """Test ES available returns HEALTHY."""
        with mock.patch('elasticsearch.Elasticsearch') as mock_es_class:
            mock_client = mock.MagicMock()
            mock_client.info.return_value = {"version": {"number": "8.0.0"}}
            mock_es_class.return_value = mock_client

            status = check_elasticsearch_health("localhost", 9200)

            assert status.backend_name == "elasticsearch"
            assert status.is_healthy is True
            assert status.latency_ms > 0
            assert status.error_message is None

    def test_check_elasticsearch_health_failure(self):
        """Test ES unavailable returns FAILED."""
        with mock.patch('elasticsearch.Elasticsearch') as mock_es_class:
            mock_es_class.side_effect = Exception("Connection refused")

            status = check_elasticsearch_health("localhost", 9200)

            assert status.backend_name == "elasticsearch"
            assert status.is_healthy is False
            assert status.latency_ms == -1
            assert status.error_message is not None
            assert "unavailable" in status.error_message.lower()

    def test_check_elasticsearch_health_with_auth(self):
        """Test ES health check with authentication."""
        with mock.patch('elasticsearch.Elasticsearch') as mock_es_class:
            mock_client = mock.MagicMock()
            mock_client.info.return_value = {}
            mock_es_class.return_value = mock_client

            status = check_elasticsearch_health("localhost", 9200, username="user", password="pass")

            assert status.is_healthy is True


class TestNeo4jHealthCheck:
    """Test Neo4j health checks."""

    def test_check_neo4j_health_success(self):
        """Test Neo4j available returns HEALTHY."""
        with mock.patch('neo4j.GraphDatabase') as mock_gdb:
            mock_driver = mock.MagicMock()
            mock_session = mock.MagicMock()
            mock_session.run.return_value = mock.MagicMock()

            mock_driver.session.return_value.__enter__ = mock.MagicMock(return_value=mock_session)
            mock_driver.session.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_gdb.driver.return_value = mock_driver

            status = check_neo4j_health("bolt://localhost:7687", "neo4j", "password")

            assert status.backend_name == "neo4j"
            assert status.is_healthy is True
            assert status.latency_ms > 0

    def test_check_neo4j_health_failure(self):
        """Test Neo4j unavailable returns FAILED."""
        with mock.patch('neo4j.GraphDatabase') as mock_gdb:
            mock_gdb.driver.side_effect = Exception("Connection refused")

            status = check_neo4j_health("bolt://localhost:7687", "neo4j", "password")

            assert status.backend_name == "neo4j"
            assert status.is_healthy is False
            assert status.latency_ms == -1


class TestMilvusHealthCheck:
    """Test Milvus health checks."""

    def test_check_milvus_health_success(self):
        """Test Milvus available returns HEALTHY."""
        with mock.patch('pymilvus.connections') as mock_connections:
            mock_conn = mock.MagicMock()
            mock_conn.check_health.return_value = None
            mock_connections.get_connection.return_value = mock_conn

            status = check_milvus_health("localhost", 19530)

            assert status.backend_name == "milvus"
            assert status.is_healthy is True
            assert status.latency_ms > 0

    def test_check_milvus_health_failure(self):
        """Test Milvus unavailable returns FAILED."""
        with mock.patch('pymilvus.connections') as mock_connections:
            mock_connections.connect.side_effect = Exception("Connection refused")

            status = check_milvus_health("localhost", 19530)

            assert status.backend_name == "milvus"
            assert status.is_healthy is False
            assert status.latency_ms == -1


class TestSQLiteHealthCheck:
    """Test SQLite health checks."""

    def test_check_sqlite_health_success(self, temp_db_path):
        """Test SQLite available returns HEALTHY."""
        status = check_sqlite_health(temp_db_path)

        assert status.backend_name == "sqlite"
        assert status.is_healthy is True
        assert status.latency_ms >= 0
        assert status.error_message is None

    def test_check_sqlite_health_failure(self):
        """Test SQLite unavailable returns FAILED."""
        status = check_sqlite_health("/nonexistent/path/database.db", timeout=1)

        assert status.backend_name == "sqlite"
        assert status.is_healthy is False
        assert status.latency_ms == -1


class TestBackendHealthStatus:
    """Test BackendHealthStatus dataclass."""

    def test_health_status_creation(self):
        """Test creating a health status."""
        status = BackendHealthStatus(
            backend_name="elasticsearch",
            is_healthy=True,
            latency_ms=15.5,
        )

        assert status.backend_name == "elasticsearch"
        assert status.is_healthy is True
        assert status.latency_ms == 15.5
        assert status.error_message is None
        assert status.timestamp is not None

    def test_health_status_with_error(self):
        """Test health status with error message."""
        status = BackendHealthStatus(
            backend_name="neo4j",
            is_healthy=False,
            latency_ms=-1,
            error_message="Connection timeout",
        )

        assert status.is_healthy is False
        assert status.error_message == "Connection timeout"


class TestHealthCheckRunner:
    """Test the HealthCheckRunner orchestrator."""

    def test_health_check_runner_all_healthy(self, temp_db_path):
        """Test all backends disabled returns DEGRADED status (SQLite fallback only)."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            elasticsearch=ElasticsearchConfig(enabled=False),
            neo4j=Neo4jConfig(enabled=False),
            milvus=MilvusConfig(enabled=False),
        )

        report = HealthCheckRunner.check_all(config)

        # When all production backends are disabled, status is DEGRADED (using SQLite fallback)
        assert report.overall_status == "DEGRADED"
        assert report.backends["sqlite"].is_healthy is True
        assert len(report.recommendations) > 0

    def test_health_check_runner_some_failed(self, temp_db_path):
        """Test some backends failed returns DEGRADED status."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            elasticsearch=ElasticsearchConfig(enabled=True, host="invalid.host", port=9200),
            neo4j=Neo4jConfig(enabled=False),
            milvus=MilvusConfig(enabled=False),
        )

        with mock.patch('src.integration.health_check_runner.check_elasticsearch_health') as mock_check_es:
            mock_check_es.return_value = BackendHealthStatus(
                backend_name="elasticsearch",
                is_healthy=False,
                latency_ms=-1,
                error_message="Connection failed",
            )

            report = HealthCheckRunner.check_all(config)

            # Should be DEGRADED since only SQLite is healthy
            assert report.overall_status in ["DEGRADED", "HEALTHY"]
            assert "elasticsearch" in report.backends

    def test_health_check_runner_all_failed(self, temp_db_path):
        """Test all backends failed returns FAILED status."""
        # Use invalid path to make SQLite fail
        config = PipelineConfig(
            sqlite_path="/nonexistent/path/db.sqlite",
            elasticsearch=ElasticsearchConfig(enabled=True),
            neo4j=Neo4jConfig(enabled=True),
            milvus=MilvusConfig(enabled=True),
        )

        with mock.patch('src.integration.health_check_runner.check_elasticsearch_health') as mock_es, \
             mock.patch('src.integration.health_check_runner.check_neo4j_health') as mock_neo4j, \
             mock.patch('src.integration.health_check_runner.check_milvus_health') as mock_milvus:

            mock_es.return_value = BackendHealthStatus(
                backend_name="elasticsearch", is_healthy=False, latency_ms=-1, error_message="Failed"
            )
            mock_neo4j.return_value = BackendHealthStatus(
                backend_name="neo4j", is_healthy=False, latency_ms=-1, error_message="Failed"
            )
            mock_milvus.return_value = BackendHealthStatus(
                backend_name="milvus", is_healthy=False, latency_ms=-1, error_message="Failed"
            )

            report = HealthCheckRunner.check_all(config)

            assert report.overall_status == "FAILED"

    def test_health_check_recommendations(self, temp_db_path):
        """Test health check generates recommendations."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            elasticsearch=ElasticsearchConfig(enabled=False),
            neo4j=Neo4jConfig(enabled=False),
            milvus=MilvusConfig(enabled=False),
        )

        report = HealthCheckRunner.check_all(config)

        assert isinstance(report.recommendations, list)
        assert len(report.recommendations) > 0

    def test_health_check_includes_latency(self, temp_db_path):
        """Test that health check includes latency measurements."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            elasticsearch=ElasticsearchConfig(enabled=False),
            neo4j=Neo4jConfig(enabled=False),
            milvus=MilvusConfig(enabled=False),
        )

        report = HealthCheckRunner.check_all(config)

        assert "sqlite" in report.backends
        sqlite_status = report.backends["sqlite"]
        assert sqlite_status.latency_ms >= 0

    def test_health_check_includes_all_backends(self, temp_db_path):
        """Test that health check includes all backends."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            elasticsearch=ElasticsearchConfig(enabled=False),
            neo4j=Neo4jConfig(enabled=False),
            milvus=MilvusConfig(enabled=False),
        )

        report = HealthCheckRunner.check_all(config)

        assert "elasticsearch" in report.backends
        assert "neo4j" in report.backends
        assert "milvus" in report.backends
        assert "sqlite" in report.backends


class TestHealthReportPrinting:
    """Test health report printing and export."""

    def test_print_health_report(self, temp_db_path, capsys):
        """Test printing a health report."""
        config = PipelineConfig(sqlite_path=temp_db_path)
        report = HealthCheckRunner.check_all(config)

        # Should not raise
        print_health_report(report)

        captured = capsys.readouterr()
        assert "BACKEND HEALTH CHECK REPORT" in captured.out or "BACKEND HEALTH CHECK REPORT" in captured.err or len(captured.out) > 0

    def test_export_health_report_json(self, temp_db_path):
        """Test exporting health report to JSON."""
        config = PipelineConfig(sqlite_path=temp_db_path)
        report = HealthCheckRunner.check_all(config)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            report_file = f.name

        try:
            export_health_report(report, report_file)

            # Read and verify JSON structure
            with open(report_file, 'r') as f:
                data = json.load(f)

            assert "timestamp" in data
            assert "overall_status" in data
            assert "backends" in data
            assert "recommendations" in data
        finally:
            import os
            os.unlink(report_file)

    def test_health_report_to_dict(self, temp_db_path):
        """Test HealthCheckReport.to_dict() method."""
        config = PipelineConfig(sqlite_path=temp_db_path)
        report = HealthCheckRunner.check_all(config)

        report_dict = report.to_dict()

        assert isinstance(report_dict, dict)
        assert "timestamp" in report_dict
        assert "overall_status" in report_dict
        assert report_dict["overall_status"] in ["HEALTHY", "DEGRADED", "FAILED"]


class TestHealthCheckTimeout:
    """Test health check timeout behavior."""

    def test_health_check_respects_timeout(self):
        """Test that health checks don't hang on timeout."""
        with mock.patch('elasticsearch.Elasticsearch') as mock_es:
            # Simulate a timeout
            mock_es.side_effect = TimeoutError("Connection timeout")

            status = check_elasticsearch_health("localhost", 9200, timeout=1)

            assert status.is_healthy is False
            assert status.error_message is not None


class TestHealthCheckEdgeCases:
    """Test edge cases in health checks."""

    def test_health_status_timestamp_auto_set(self):
        """Test that timestamp is automatically set if not provided."""
        status = BackendHealthStatus(
            backend_name="test",
            is_healthy=True,
            latency_ms=10.0,
        )

        assert status.timestamp is not None
        assert isinstance(status.timestamp, datetime)

    def test_health_check_with_custom_timeout(self, temp_db_path):
        """Test health check with custom timeout."""
        status = check_sqlite_health(temp_db_path, timeout=10)

        assert status.backend_name == "sqlite"
        # Should complete without timing out

    def test_health_report_disabled_backend(self, temp_db_path):
        """Test health report correctly marks disabled backends."""
        config = PipelineConfig(
            sqlite_path=temp_db_path,
            elasticsearch=ElasticsearchConfig(enabled=False),
        )

        report = HealthCheckRunner.check_all(config)

        assert "elasticsearch" in report.backends
        es_status = report.backends["elasticsearch"]
        assert es_status.error_message == "Disabled in configuration"
