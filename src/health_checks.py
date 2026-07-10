"""Health check utilities for backend services."""

import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class BackendHealthStatus:
    """Health status of a backend service."""
    backend_name: str
    is_healthy: bool
    latency_ms: float
    error_message: Optional[str] = None
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


def check_elasticsearch_health(host: str, port: int, username: Optional[str] = None,
                               password: Optional[str] = None, timeout: int = 5) -> BackendHealthStatus:
    """
    Check Elasticsearch health status.

    Args:
        host: Elasticsearch host
        port: Elasticsearch port
        username: Optional username for authentication
        password: Optional password for authentication
        timeout: Connection timeout in seconds

    Returns:
        BackendHealthStatus: Health status of Elasticsearch
    """
    try:
        from elasticsearch import Elasticsearch

        start_time = time.time()

        # Configure ES client
        es_params = {"hosts": [{"host": host, "port": port, "scheme": "http"}]}
        if username and password:
            es_params["basic_auth"] = (username, password)
        es_params["request_timeout"] = timeout

        es_client = Elasticsearch(**es_params)
        es_client.info()

        latency = (time.time() - start_time) * 1000
        return BackendHealthStatus(
            backend_name="elasticsearch",
            is_healthy=True,
            latency_ms=round(latency, 2),
        )
    except Exception as e:
        error_msg = f"Elasticsearch unavailable: {str(e)}"
        logger.warning(error_msg)
        return BackendHealthStatus(
            backend_name="elasticsearch",
            is_healthy=False,
            latency_ms=-1,
            error_message=error_msg,
        )


def check_neo4j_health(uri: str, user: str, password: str, timeout: int = 5) -> BackendHealthStatus:
    """
    Check Neo4j health status.

    Args:
        uri: Neo4j connection URI
        user: Username for Neo4j
        password: Password for Neo4j
        timeout: Connection timeout in seconds

    Returns:
        BackendHealthStatus: Health status of Neo4j
    """
    try:
        from neo4j import GraphDatabase

        start_time = time.time()

        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("RETURN 1")
        driver.close()

        latency = (time.time() - start_time) * 1000
        return BackendHealthStatus(
            backend_name="neo4j",
            is_healthy=True,
            latency_ms=round(latency, 2),
        )
    except Exception as e:
        error_msg = f"Neo4j unavailable: {str(e)}"
        logger.warning(error_msg)
        return BackendHealthStatus(
            backend_name="neo4j",
            is_healthy=False,
            latency_ms=-1,
            error_message=error_msg,
        )


def check_milvus_health(host: str, port: int, timeout: int = 5) -> BackendHealthStatus:
    """
    Check Milvus health status.

    Args:
        host: Milvus host
        port: Milvus port
        timeout: Connection timeout in seconds

    Returns:
        BackendHealthStatus: Health status of Milvus
    """
    try:
        from pymilvus import connections

        start_time = time.time()

        conn_name = "_health_check_"
        connections.connect(
            alias=conn_name,
            host=host,
            port=port,
            connect_timeout=timeout,
        )

        # Simple health check
        connections.get_connection(conn_name).check_health()
        connections.disconnect(conn_name)

        latency = (time.time() - start_time) * 1000
        return BackendHealthStatus(
            backend_name="milvus",
            is_healthy=True,
            latency_ms=round(latency, 2),
        )
    except Exception as e:
        error_msg = f"Milvus unavailable: {str(e)}"
        logger.warning(error_msg)
        return BackendHealthStatus(
            backend_name="milvus",
            is_healthy=False,
            latency_ms=-1,
            error_message=error_msg,
        )


def check_sqlite_health(db_path: str, timeout: int = 5) -> BackendHealthStatus:
    """
    Check SQLite database health status.

    Args:
        db_path: Path to SQLite database file
        timeout: Connection timeout in seconds

    Returns:
        BackendHealthStatus: Health status of SQLite
    """
    try:
        start_time = time.time()

        conn = sqlite3.connect(db_path, timeout=timeout)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()

        latency = (time.time() - start_time) * 1000
        return BackendHealthStatus(
            backend_name="sqlite",
            is_healthy=True,
            latency_ms=round(latency, 2),
        )
    except Exception as e:
        error_msg = f"SQLite unavailable at {db_path}: {str(e)}"
        logger.warning(error_msg)
        return BackendHealthStatus(
            backend_name="sqlite",
            is_healthy=False,
            latency_ms=-1,
            error_message=error_msg,
        )
