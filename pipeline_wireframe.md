# SVO Verification Pipeline – Wireframe (Markdown)

The following Mermaid diagram visualises the **flow of data** and **flow of requests** across the two main phases of the system.

```mermaid
flowchart TD

    subgraph ING["Ingestion"]
        A["Raw Document Text"] --> B["Chunker"]
        B --> C["Embedding Model"]
        B --> D["SVO Extractor"]

        C --> E["SQLite Chunk Store"]
        D --> F["Neo4j Graph Store"]
        D --> G["Elasticsearch Lexical Store"]
        D --> H["Milvus Semantic Store"]
    end

    subgraph VER["Verification"]
        I["User Query"] --> J["MoE Router"]

        J -->|Lexical| K["Lexical Retriever"]
        J -->|Semantic| L["Semantic Retriever"]
        J -->|Graph| M["Graph Retriever"]

        K --> N["Fusion Engine"]
        L --> N
        M --> N

        N --> O["Late Materialization: SQLite Chunk Store"]
        O --> P["Validator (Transformer)"]
        P --> Q["Final Evidence JSON"]
    end

    style ING fill:#f9f,stroke:#333,stroke-width:2px
    style VER fill:#bbf,stroke:#333,stroke-width:2px
```

**Explanation**
- **Ingestion Phase**: Raw document text is split into chunks, each chunk is embedded and SVO‑extracted, then persisted to four stores.
- **Verification Phase**: A user query is routed by the MoE router to the appropriate retrievers (lexical, semantic, graph). The results are combined by the Fusion Engine, materialised from SQLite, validated by a Transformer model, and returned as an evidence JSON payload.
