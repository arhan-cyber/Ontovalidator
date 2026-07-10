"""Comprehensive health check orchestration for backend verification."""

import logging
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional

from src.config import PipelineConfig
from src.health_checks import (
    BackendHealthStatus,
    check_elasticsearch_health,
    check_neo4j_health,
    check_milvus_health,
    check_sqlite_health,
)

logger = logging.getLogger(__name__)


@dataclass
class HealthCheckReport:
    """Complete health check report for the system."""
    timestamp: datetime
    overall_status: str  # "HEALTHY", "DEGRADED", "FAILED"
    backends: Dict[str, BackendHealthStatus]
    recommendations: List[str]

    def to_dict(self) -> dict:
        """Convert report to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "overall_status": self.overall_status,
            "backends": {
                name: {
                    "backend_name": status.backend_name,
                    "is_healthy": status.is_healthy,
                    "latency_ms": status.latency_ms,
                    "error_message": status.error_message,
                    "timestamp": status.timestamp.isoformat() if status.timestamp else None,
                }
                for name, status in self.backends.items()
            },
            "recommendations": self.recommendations,
        }


class HealthCheckRunner:
    """Orchestrates health checks for all backend services."""

    @staticmethod
    def check_all(config: PipelineConfig) -> HealthCheckReport:
        """
        Run all health checks and aggregate results.

        Args:
            config: Pipeline configuration with backend settings

        Returns:
            HealthCheckReport: Complete health report with status and recommendations
        """
        backends: Dict[str, BackendHealthStatus] = {}
        recommendations: List[str] = []

        # Check Elasticsearch
        if config.elasticsearch.enabled:
            logger.info("Checking Elasticsearch...")
            backends["elasticsearch"] = HealthCheckRunner.check_elasticsearch(
                config.elasticsearch.host,
                config.elasticsearch.port,
                timeout=5
            )
            if not backends["elasticsearch"].is_healthy:
                recommendations.append("Elasticsearch is unavailable. Semantic retrieval will be disabled.")
        else:
            logger.info("Elasticsearch is disabled in configuration.")
            backends["elasticsearch"] = BackendHealthStatus(
                backend_name="elasticsearch",
                is_healthy=False,
                latency_ms=-1,
                error_message="Disabled in configuration",
            )

        # Check Neo4j
        if config.neo4j.enabled:
            logger.info("Checking Neo4j...")
            backends["neo4j"] = HealthCheckRunner.check_neo4j(
                config.neo4j.uri,
                config.neo4j.user,
                config.neo4j.password,
                timeout=5
            )
            if not backends["neo4j"].is_healthy:
                recommendations.append("Neo4j is unavailable. Graph-based retrieval will be disabled.")
        else:
            logger.info("Neo4j is disabled in configuration.")
            backends["neo4j"] = BackendHealthStatus(
                backend_name="neo4j",
                is_healthy=False,
                latency_ms=-1,
                error_message="Disabled in configuration",
            )

        # Check Milvus
        if config.milvus.enabled:
            logger.info("Checking Milvus...")
            backends["milvus"] = HealthCheckRunner.check_milvus(
                config.milvus.host,
                config.milvus.port,
                timeout=5
            )
            if not backends["milvus"].is_healthy:
                recommendations.append("Milvus is unavailable. Vector-based retrieval will be disabled.")
        else:
            logger.info("Milvus is disabled in configuration.")
            backends["milvus"] = BackendHealthStatus(
                backend_name="milvus",
                is_healthy=False,
                latency_ms=-1,
                error_message="Disabled in configuration",
            )

        # Check SQLite (fallback database)
        logger.info(f"Checking SQLite at {config.sqlite_path}...")
        backends["sqlite"] = HealthCheckRunner.check_sqlite(config.sqlite_path, timeout=5)

        # Determine overall status
        enabled_backends = {
            name: status for name, status in backends.items()
            if name != "sqlite" and status.error_message != "Disabled in configuration"
        }
        healthy_backends = {name: status for name, status in enabled_backends.items() if status.is_healthy}

        if backends["sqlite"].is_healthy:
            if healthy_backends:
                overall_status = "HEALTHY"
                recommendations.insert(0, "All enabled backends are operational.")
            else:
                overall_status = "DEGRADED"
                recommendations.insert(0, "No production backends available. Using SQLite fallback.")
        else:
            overall_status = "FAILED"
            recommendations.insert(0, "Critical: SQLite is unavailable. Pipeline cannot operate.")

        logger.info(f"Health check complete. Overall status: {overall_status}")

        return HealthCheckReport(
            timestamp=datetime.utcnow(),
            overall_status=overall_status,
            backends=backends,
            recommendations=recommendations,
        )

    @staticmethod
    def check_elasticsearch(host: str, port: int, username: Optional[str] = None,
                           password: Optional[str] = None, timeout: int = 5) -> BackendHealthStatus:
        """Check Elasticsearch health using health_checks module."""
        return check_elasticsearch_health(host, port, username, password, timeout)

    @staticmethod
    def check_neo4j(uri: str, user: str, password: str, timeout: int = 5) -> BackendHealthStatus:
        """Check Neo4j health using health_checks module."""
        return check_neo4j_health(uri, user, password, timeout)

    @staticmethod
    def check_milvus(host: str, port: int, timeout: int = 5) -> BackendHealthStatus:
        """Check Milvus health using health_checks module."""
        return check_milvus_health(host, port, timeout)

    @staticmethod
    def check_sqlite(db_path: str, timeout: int = 5) -> BackendHealthStatus:
        """Check SQLite health using health_checks module."""
        return check_sqlite_health(db_path, timeout)

    @staticmethod
    def _parse_host_port(url: str, default_port: int) -> tuple:
        """Parse host and port from a URL string."""
        # Remove scheme if present
        if "://" in url:
            url = url.split("://", 1)[1]

        # Split host and port
        if ":" in url:
            host, port_str = url.rsplit(":", 1)
            try:
                port = int(port_str)
                return host, port
            except ValueError:
                return url, default_port
        return url, default_port


def print_health_report(report: HealthCheckReport) -> None:
    """
    Pretty-print health report to console with color support.

    Args:
        report: HealthCheckReport to print
    """
    # Color codes
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    # Determine if terminal supports color
    try:
        import sys
        supports_color = sys.stdout.isatty()
    except Exception:
        supports_color = False

    def colorize(text: str, color: str) -> str:
        """Apply color if supported."""
        if supports_color:
            return f"{color}{text}{RESET}"
        return text

    # Header
    print("\n" + "=" * 80)
    print(colorize("BACKEND HEALTH CHECK REPORT", BOLD))
    print("=" * 80)

    # Timestamp and overall status
    timestamp = report.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    status_color = GREEN if report.overall_status == "HEALTHY" else (
        YELLOW if report.overall_status == "DEGRADED" else RED
    )
    print(f"\nReport Time: {timestamp}")
    print(f"Overall Status: {colorize(report.overall_status, status_color)}")

    # Backend status details
    print("\n" + "-" * 80)
    print("Backend Status:")
    print("-" * 80)

    for backend_name in ["elasticsearch", "neo4j", "milvus", "sqlite"]:
        if backend_name in report.backends:
            status = report.backends[backend_name]
            if status.error_message == "Disabled in configuration":
                status_str = colorize("DISABLED", YELLOW)
                print(f"{backend_name:15} {status_str:15}")
            elif status.is_healthy:
                latency_str = f"{status.latency_ms:.2f}ms"
                status_str = colorize("HEALTHY", GREEN)
                print(f"{backend_name:15} {status_str:15} latency: {latency_str}")
            else:
                status_str = colorize("FAILED", RED)
                error_msg = status.error_message[:50] if status.error_message else "Unknown error"
                print(f"{backend_name:15} {status_str:15} {error_msg}...")

    # Recommendations
    if report.recommendations:
        print("\n" + "-" * 80)
        print("Recommendations:")
        print("-" * 80)
        for i, rec in enumerate(report.recommendations, 1):
            print(f"{i}. {rec}")

    # Fallback chain summary
    print("\n" + "-" * 80)
    print("Fallback Chain Summary:")
    print("-" * 80)
    enabled_backends = []
    for name in ["elasticsearch", "neo4j", "milvus"]:
        if name in report.backends:
            status = report.backends[name]
            if status.is_healthy and status.error_message != "Disabled in configuration":
                enabled_backends.append(name)

    if enabled_backends:
        chain = " -> ".join(enabled_backends) + " -> SQLite"
        print(f"Query Chain: {chain}")
    else:
        print("Query Chain: SQLite (fallback only)")

    print("=" * 80 + "\n")


def export_health_report(report: HealthCheckReport, filepath: str) -> None:
    """
    Export health report to JSON file.

    Args:
        report: HealthCheckReport to export
        filepath: Path where JSON file will be written
    """
    try:
        with open(filepath, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
        logger.info(f"Health report exported to {filepath}")
    except Exception as e:
        logger.error(f"Failed to export health report to {filepath}: {e}")
        raise
