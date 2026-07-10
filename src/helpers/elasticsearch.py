"""Elasticsearch search helpers."""

import os
import logging
from typing import List, Dict, Any, Optional
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from elasticsearch.exceptions import ConnectionError, RequestError, NotFoundError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ElasticsearchHelper")

INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "document_id": {"type": "keyword"},
            "text": {"type": "text", "analyzer": "english"},
            "metadata": {"type": "object", "dynamic": True}
        }
    }
}


def get_elasticsearch_client(
    hosts: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    verify_certs: bool = True,
    ca_certs: Optional[str] = None
) -> Elasticsearch:
    """Initialize and return an Elasticsearch client."""
    if not hosts:
        hosts = os.getenv("ELASTICSEARCH_HOSTS", "http://localhost:9200").split(",")

    connection_kwargs: Dict[str, Any] = {
        "hosts": hosts,
        "verify_certs": verify_certs,
        "retry_on_timeout": True,
        "max_retries": 5
    }

    if ca_certs:
        connection_kwargs["ca_certs"] = ca_certs

    if api_key:
        connection_kwargs["api_key"] = api_key
    elif username and password:
        connection_kwargs["basic_auth"] = (username, password)
    elif os.getenv("ELASTICSEARCH_API_KEY"):
        connection_kwargs["api_key"] = os.getenv("ELASTICSEARCH_API_KEY")
    elif os.getenv("ELASTICSEARCH_USERNAME") and os.getenv("ELASTICSEARCH_PASSWORD"):
        connection_kwargs["basic_auth"] = (
            os.getenv("ELASTICSEARCH_USERNAME"),
            os.getenv("ELASTICSEARCH_PASSWORD")
        )

    logger.info(f"Initializing Elasticsearch client with hosts: {hosts}")
    return Elasticsearch(**connection_kwargs)


def initialize_index(es_client: Elasticsearch, index_name: str = "svo_chunks") -> None:
    """Create index with settings and mappings if it doesn't exist."""
    try:
        if not es_client.indices.exists(index=index_name):
            shards = int(os.getenv("ELASTICSEARCH_SHARDS", "1"))
            replicas = int(os.getenv("ELASTICSEARCH_REPLICAS", "0"))

            index_body = {
                "settings": {
                    "index": {
                        "number_of_shards": shards,
                        "number_of_replicas": replicas
                    }
                },
                **INDEX_MAPPING
            }

            logger.info(f"Creating index '{index_name}' with {shards} shards and {replicas} replicas.")
            es_client.indices.create(index=index_name, body=index_body)
        else:
            logger.info(f"Index '{index_name}' already exists.")
    except RequestError as e:
        logger.error(f"Failed to create index: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error when checking/creating index: {e}")
        raise


def generate_bulk_actions(chunks: List[Any], index_name: str) -> Any:
    """Generate bulk index operations from chunk objects."""
    for chunk in chunks:
        yield {
            "_index": index_name,
            "_id": chunk.chunk_id,
            "_source": {
                "document_id": chunk.document_id,
                "text": chunk.text,
                "metadata": chunk.metadata
            }
        }


def bulk_ingest_chunks(es_client: Elasticsearch, chunks: List[Any], index_name: str = "svo_chunks") -> Dict[str, Any]:
    """Ingest chunks into Elasticsearch using bulk API."""
    initialize_index(es_client, index_name)

    if not chunks:
        return {"success": 0, "failed": 0}

    actions = generate_bulk_actions(chunks, index_name)

    try:
        success, failed_items = bulk(
            client=es_client,
            actions=actions,
            stats_only=False,
            raise_on_error=False
        )
        failed_count = len(failed_items) if isinstance(failed_items, list) else failed_items
        logger.info(f"Bulk ingestion completed. Successes: {success}, Failures: {failed_count}")
        if failed_count > 0:
            logger.warning(f"Failed items details: {failed_items}")
        return {"success": success, "failed": failed_count}
    except ConnectionError as e:
        logger.error(f"Elasticsearch connection failed during bulk ingestion: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during bulk ingestion: {e}")

    return {"success": 0, "failed": len(chunks)}
