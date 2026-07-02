# Elasticsearch Implementation Requirements

This document outlines the concrete technical requirements and schema definitions for replacing the mock Elasticsearch database layer with a production-ready implementation.

---

## 1. Index Configuration & Settings

* **Index Name**: `svo_chunks`
* **Shards & Replicas**:
  * **Development**: 1 primary shard, 0 replicas.
  * **Production**: 3+ primary shards, 1+ replicas (configurable via environment variables).
* **Similarity Algorithm**: BM25 (default parameter settings: $k_1 = 1.2$, $b = 0.75$).

---

## 2. Schema Mappings

To support lexical queries with auto-fuzziness and exact document filtering, the index must enforce the following field mappings:

| Field Name | Elasticsearch Data Type | Purpose / Capabilities |
| :--- | :--- | :--- |
| `document_id` | `keyword` | Supports exact matching and document-level filtering without tokenization. |
| `text` | `text` | Main text field. Must use the standard `english` analyzer (enabling stemming, stopword removal, and lowercasing) to optimize BM25 search relevance. |
| `metadata` | `object` (Dynamic: `true`) | Stores structured metadata (e.g., `provides`, `depends_on`, `source`, `word_count`). |

### JSON Schema Mapping Payload

```json
{
  "settings": {
    "index": {
      "number_of_shards": 1,
      "number_of_replicas": 0
    }
  },
  "mappings": {
    "properties": {
      "document_id": {
        "type": "keyword"
      },
      "text": {
        "type": "text",
        "analyzer": "english"
      },
      "metadata": {
        "type": "object",
        "dynamic": true
      }
    }
  }
}
```

---

## 3. Database Ingestion Pipeline Requirements

* **Index Creation Check**:
  * Before indexing chunks, the ingestor must check if the index exists using:
    ```python
    if not es_client.indices.exists(index="svo_chunks"):
        # Create index with the schema mapping payload defined above
    ```
* **Bulk API Ingestion**:
  * Use the official `elasticsearch.helpers.bulk` generator instead of raw `client.bulk()` arrays. This handles chunking, automatic retries, and yields detailed reports on success/failure counts.
  * Ensure document IDs in Elasticsearch match the chunk UUIDs (`c.chunk_id`) for consistent references across stores.

---

## 4. Connection & Error Handling

* **Client Setup**:
  * Support authentication protocols (username/password Basic Auth or API Keys).
  * Configure secure connections (SSL/TLS cert validation) and fallback configurations for local self-signed setups.
* **Resilience**:
  * Implement connection retries with exponential backoff.
  * Handle standard client exceptions (`ConnectionError`, `RequestError`, `NotFoundError`) gracefully, printing logs/warnings without crashing the main pipeline thread.
