import os
import json
from typing import List

# Import components from the existing codebase
from svo_engine import (
    Chunk,
    SVORelation,
    MoERouter,
    SQLiteLexicalRetriever,
    SQLiteSemanticRetriever,
    SQLiteGraphRetriever,
    WeightedFusionEngine,
    SQLiteChunkStore,
    TransformerValidator,
    QueryType
)
from ingestion_pipeline import (
    DataIngestor,
    TransformerEmbeddingModel,
    TransformerSVOExtractor,
    LocalElasticsearchClient,
    LocalMilvusCollection,
    LocalNeo4jDriver
)

def run_step_by_step_pipeline():
    db_path = "explain_pipeline_demo.sqlite"
    if os.path.exists(db_path):
        os.remove(db_path)

    # Sample multi-paragraph raw document text
    raw_document_id = "doc_101"
    raw_text = (
        "Aspirin treats headache. "
        "The medication is also known to reduce fever."
    )

    print("=" * 80)
    print("PHASE 1: INGESTION PIPELINE (REAL TRANSFORMERS)")
    print("=" * 80)
    print(f"[INPUT] Raw Document ID: {raw_document_id}")
    print(f"[INPUT] Raw Text:\n{raw_text}\n")

    # Initialize Mock Clients and Real Transformer Models
    print("Loading transformer models (distilbert-base-uncased and flan-t5-small)...")
    es_client = LocalElasticsearchClient()
    milvus_collection = LocalMilvusCollection()
    neo4j_driver = LocalNeo4jDriver()
    embedding_model = TransformerEmbeddingModel()
    svo_extractor = TransformerSVOExtractor()

    ingestor = DataIngestor(
        sqlite_conn_path=db_path,
        es_client=es_client,
        milvus_collection=milvus_collection,
        neo4j_driver=neo4j_driver,
        embedding_model=embedding_model,
        svo_extractor=svo_extractor
    )

    # --- STEP 1: CHUNKING ---
    print("-" * 50)
    print("STEP 1: Document Chunking")
    print("-" * 50)
    print(f"  [Action] Splitting raw text into sentence-level chunks...")
    chunks = ingestor.chunk_document(raw_document_id, raw_text)
    for idx, c in enumerate(chunks):
        print(f"  [OUTPUT] Chunk {idx + 1}:")
        print(f"    - ID: {c.chunk_id}")
        print(f"    - Text: \"{c.text}\"")

    # --- STEP 2: EMBEDDING GENERATION ---
    print("\n" + "-" * 50)
    print("STEP 2: Embedding Generation")
    print("-" * 50)
    texts = [c.text for c in chunks]
    print(f"  [INPUT] Texts to encode: {texts}")
    embeddings = embedding_model.encode(texts)
    for c, emb in zip(chunks, embeddings):
        c.embedding = emb
    print(f"  [OUTPUT] Generated {len(embeddings)} vector embeddings (5-dimensional hashes).")
    print(f"  [OUTPUT] Sample Chunk 1 Vector: {chunks[0].embedding}")

    # --- STEP 3: SVO RELATION EXTRACTION ---
    print("\n" + "-" * 50)
    print("STEP 3: SVO Relation Extraction")
    print("-" * 50)
    all_svos: List[SVORelation] = []
    for c in chunks:
        print(f"  [INPUT] Text for SVO extraction: \"{c.text}\"")
        extracted = svo_extractor.extract(c.text)
        for svo in extracted:
            svo.source_chunk_ids = [c.chunk_id]
            all_svos.append(svo)
            print(f"  [OUTPUT] Extracted SVO:")
            print(f"    - Subject: {svo.subject_name_type} (ID: {svo.subject_id})")
            print(f"    - Relation: {svo.relation}")
            print(f"    - Object: {svo.object_name_type} (ID: {svo.object_id})")
            print(f"    - Source Chunk ID: {svo.source_chunk_ids}")

    # --- STEP 4: MULTI-DATABASE STORAGE WRITING ---
    print("\n" + "-" * 50)
    print("STEP 4: Populating Database Stores")
    print("-" * 50)
    
    print("  [Action] Populating SQLite (Late Materialization ChunkStore)...")
    # Show SQLite payload
    sqlite_payload = [
        {"chunk_id": c.chunk_id, "document_id": c.document_id, "text": c.text, "metadata": c.metadata}
        for c in chunks
    ]
    print("    - [Payload] SQLite records:")
    print(json.dumps(sqlite_payload, indent=6))
    ingestor._write_sqlite(chunks)
    print("    - [OUTPUT] SQLite ChunkStore populated successfully.")

    print("\n  [Action] Populating Elasticsearch (Lexical Store)...")
    # Show Elasticsearch payload structure
    es_payload = []
    for c in chunks:
        es_payload.append({"index": {"_index": "svo_chunks", "_id": c.chunk_id}})
        es_payload.append({"document_id": c.document_id, "text": c.text, "metadata": c.metadata})
    print("    - [Payload] Elasticsearch bulk operations:")
    print(json.dumps(es_payload, indent=6))
    ingestor._write_elasticsearch(chunks)
    print("    - [OUTPUT] Elasticsearch Lexical Store populated successfully.")

    print("\n  [Action] Populating Milvus (Semantic Vector Store)...")
    # Show Milvus payload
    milvus_payload = [
        {"chunk_id": c.chunk_id, "embedding": c.embedding, "document_id": c.document_id}
        for c in chunks
    ]
    print("    - [Payload] Milvus insert payload:")
    print(json.dumps(milvus_payload, indent=6))
    ingestor._write_milvus(chunks)
    print("    - [OUTPUT] Milvus Semantic Store populated successfully.")

    print("\n  [Action] Populating Neo4j (Graph Reasoning Store)...")
    # Show Neo4j Cypher and parameters
    print("    - [Payload] Neo4j graph nodes and relations to merge:")
    for chunk in chunks:
        provides = chunk.metadata.get("provides", [])
        depends_on = chunk.metadata.get("depends_on", [])
        print(f"      * Chunk ID: {chunk.chunk_id}")
        print(f"        Text: \"{chunk.text}\"")
        if provides:
            print(f"        PROVIDES Concepts: {provides}")
        if depends_on:
            print(f"        DEPENDS_ON Concepts: {depends_on}")
    ingestor._write_neo4j(chunks)
    print("    - [OUTPUT] Neo4j Graph Store populated successfully.")

    print("\n" + "=" * 80)
    print("PHASE 2: VERIFICATION & RETRIEVAL PIPELINE")
    print("=" * 80)

    # Initialize verification components
    router = MoERouter()
    lexical_store = SQLiteLexicalRetriever(db_path)
    semantic_store = SQLiteSemanticRetriever(db_path)
    graph_store = SQLiteGraphRetriever(db_path)
    fusion_engine = WeightedFusionEngine()
    chunk_store = SQLiteChunkStore(db_path)
    print("Loading transformer model for verification (distilbert-base-uncased-mnli)...")
    validator = TransformerValidator()

    query = "Does Aspirin reduce fever?"
    print(f"[INPUT] Query: \"{query}\"\n")

    # --- STEP 5: QUERY ROUTING ---
    print("-" * 50)
    print("STEP 5: Mixture-of-Experts (MoE) Query Routing")
    print("-" * 50)
    print(f"  [INPUT] Raw Query: \"{query}\"")
    query_types = router.route(query)
    print(f"  [OUTPUT] Routed Query Types: {[qt.value for qt in query_types]}")

    # --- STEP 6: MULTI-MODAL RETRIEVAL ---
    print("\n" + "-" * 50)
    print("STEP 6: Multi-Modal Retrieval")
    print("-" * 50)
    retrieved_results = []
    
    if QueryType.EXACT_MATCH in query_types:
        print("  [Action] Executing Lexical Retrieval...")
        lex_results = lexical_store.retrieve(query, top_k=3)
        retrieved_results.extend(lex_results)
        print(f"    - [OUTPUT] Retrieved: {[(r.chunk_id, r.score, r.source) for r in lex_results]}")
        
    if QueryType.COMPLEX in query_types:
        print("  [Action] Executing Semantic Retrieval...")
        sem_results = semantic_store.retrieve(query, top_k=3)
        retrieved_results.extend(sem_results)
        print(f"    - [OUTPUT] Retrieved: {[(r.chunk_id, r.score, r.source) for r in sem_results]}")
        
    if QueryType.MULTI_HOP in query_types:
        print("  [Action] Executing Graph Retrieval...")
        graph_results = graph_store.retrieve(query, top_k=3)
        retrieved_results.extend(graph_results)
        print(f"    - [OUTPUT] Retrieved: {[(r.chunk_id, r.score, r.source) for r in graph_results]}")

    # --- STEP 7: FUSION AND RANKING ---
    print("\n" + "-" * 50)
    print("STEP 7: Fusion and Ranking (Weighted Fusion)")
    print("-" * 50)
    print(f"  [INPUT] Raw retrieved results to fuse: {len(retrieved_results)} items.")
    ranked_results = fusion_engine.fuse_and_rank(retrieved_results, top_k=3)
    print("  [OUTPUT] Ranked Results:")
    for rank, res in enumerate(ranked_results):
        print(f"    - Rank {rank + 1}: Chunk ID: {res.chunk_id} | Fused Score: {res.score:.4f}")

    # --- STEP 8: LATE MATERIALIZATION ---
    print("\n" + "-" * 50)
    print("STEP 8: Late Materialization Chunk Lookup")
    print("-" * 50)
    chunk_ids = [res.chunk_id for res in ranked_results]
    print(f"  [INPUT] Chunk IDs to fetch: {chunk_ids}")
    materialized_chunks = chunk_store.get_chunks(chunk_ids)
    
    # Map back text to results
    chunk_map = {c.chunk_id: c for c in materialized_chunks}
    for res in ranked_results:
        res.chunk = chunk_map.get(res.chunk_id)
        
    print("  [OUTPUT] Materialized Chunk Texts:")
    for c in materialized_chunks:
        print(f"    - ID: {c.chunk_id} | Text: \"{c.text}\"")

    # --- STEP 9: EVIDENCE VALIDATION ---
    print("\n" + "-" * 50)
    print("STEP 9: Evidence Validation")
    print("-" * 50)
    print(f"  [INPUT] Ranked & materialized results passed to validator...")
    verification_output = validator.validate(query, ranked_results)
    print(f"  [OUTPUT] Final JSON Output:\n{json.dumps(verification_output, indent=2)}")
    
    # Clean up demo database file
    if os.path.exists(db_path):
        os.remove(db_path)

if __name__ == "__main__":
    run_step_by_step_pipeline()
