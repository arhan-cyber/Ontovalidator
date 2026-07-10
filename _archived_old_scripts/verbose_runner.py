import logging
import json
import uuid
import sys
import os

# 1. Setup Maximum Verbosity Logging
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout, format='\n[%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger("VerboseRunner")

# 2. Hardcoded Document & Query
DOCUMENT_TEXT = """Title: The Global Impact of Climate-Resilient Agricultural Policies (2023-2028)

Introduction
------------
In the wake of the unprecedented heatwave of 2022 that devastated wheat yields across the Mid-Continental United States, the United Nations Food and Agriculture Organization (FAO) convened a special summit in Geneva to draft a series of climate-resilient agricultural policies. The summit’s flagship proposal, “Green Harvest 2025,” combined three core pillars: (1) the adoption of drought-tolerant crop varieties, (2) the subsidization of precision irrigation technologies, and (3) the establishment of regional carbon-credit markets for farming practices.

Cross-Domain Interactions & Contradictions
-----------------------------------------
- The drought-tolerant wheat (Aqua-Wheat-X1) requires higher nitrogen fertilizer to achieve optimal grain protein, potentially offsetting the carbon savings from reduced irrigation.
- The sorghum-tree intercropping system improves nitrogen fixation, yet the associated increase in leaf litter has been linked to higher methane emissions during decomposition in tropical soils.
"""

QUERY = "Considering the policies, does Aqua-Wheat-X1 require more fertilizer?"

# 3. Import pipeline components
from svo_engine import SVOVerificationEngine, MoERouter, LexicalRetriever, MilvusSemanticRetriever, GraphRetriever, WeightedFusionEngine, SQLiteChunkStore, MinimalValidator
from svo_engine import SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever
from ingestion_pipeline import DataIngestor, SimpleEmbeddingModel, MockSVOExtractor, MockConceptExtractor, LocalElasticsearchClient, LocalMilvusCollection, LocalNeo4jDriver

# Monkey patch MoERouter to explicitly show its decision making
original_route = MoERouter.route
def verbose_route(self, query):
    logger.info(f"Analyzing query for MoE routing: '{query}'")
    routes = original_route(self, query)
    logger.info(f"MoE Router explicitly selected the following pathways: {[r.value for r in routes]}")
    return routes
MoERouter.route = verbose_route

# Monkey patch FusionEngine to show how it combines evidence
original_fuse = WeightedFusionEngine.fuse_and_rank
def verbose_fuse(self, results, top_k):
    logger.info(f"FusionEngine received {len(results)} raw results from all retrieval paths.")
    fused = original_fuse(self, results, top_k)
    for i, res in enumerate(fused):
        logger.debug(f"Fused Rank {i+1} | Chunk: {res.chunk_id} | Final Score: {res.score:.4f} | Source: {res.source}")
    return fused
WeightedFusionEngine.fuse_and_rank = verbose_fuse

def main():
    logger.info("=== STARTING VERBOSE PIPELINE RUNNER ===")
    
    db_path = "verbose_store.sqlite"
    
    # 4. Initialize Databases
    logger.info("=== INITIALIZING DATABASES ===")
    
    # Neo4j
    logger.info("Attempting to initiate Neo4j Graph Database...")
    try:
        from neo4j_helper import get_neo4j_driver, initialize_neo4j_schema
        neo4j_driver = get_neo4j_driver()
        initialize_neo4j_schema(neo4j_driver)
        graph_store = GraphRetriever(neo4j_driver)
        logger.info("Neo4j successfully initiated!")
    except Exception as e:
        logger.warning(f"Neo4j real server not found ({e}). Falling back to LocalNeo4jDriver mock.")
        neo4j_driver = LocalNeo4jDriver()
        graph_store = SQLiteGraphRetriever(db_path)
        
    # Elasticsearch
    logger.info("Attempting to initiate Elasticsearch Lexical Store...")
    try:
        from ElasticSearch.es_helper import get_elasticsearch_client, initialize_index
        es_client = get_elasticsearch_client()
        initialize_index(es_client, "svo_chunks")
        lexical_store = LexicalRetriever(es_client)
        logger.info("Elasticsearch successfully initiated!")
    except Exception as e:
        logger.warning(f"Elasticsearch real server not found ({e}). Falling back to LocalElasticsearchClient mock.")
        es_client = LocalElasticsearchClient()
        lexical_store = SQLiteLexicalRetriever(db_path)
        
    # Milvus
    logger.info("Attempting to initiate Milvus Semantic Vector Database...")
    embedding_model = SimpleEmbeddingModel()
    try:
        from milvus_helper import get_milvus_collection
        # This will use Milvus Lite (local file) if localhost is specified
        milvus_collection = get_milvus_collection(dim=5, host="localhost") 
        semantic_store = MilvusSemanticRetriever("svo_chunks", embedding_model)
        logger.info("Milvus database successfully initiated!")
    except Exception as e:
        logger.warning(f"Milvus initiation failed ({e}). Falling back to LocalMilvusCollection mock.")
        milvus_collection = LocalMilvusCollection()
        semantic_store = SQLiteSemanticRetriever(db_path)

    # 5. Ingestion Pipeline
    logger.info("=== STARTING INGESTION PIPELINE ===")
    ingestor = DataIngestor(
        sqlite_conn_path=db_path,
        es_client=es_client,
        milvus_collection=milvus_collection,
        neo4j_driver=neo4j_driver,
        embedding_model=embedding_model,
        svo_extractor=MockSVOExtractor(),
        concept_extractor=MockConceptExtractor(),
    )
    
    doc_id = "doc_" + str(uuid.uuid4())[:8]
    logger.info(f"Ingesting new document with ID: {doc_id}")
    ingest_result = ingestor.ingest_document(doc_id, DOCUMENT_TEXT)
    logger.info("Document ingested successfully across all stores.")

    # 6. Verification Pipeline
    logger.info("=== STARTING SVO QUERY & VERIFICATION PIPELINE ===")
    
    engine = SVOVerificationEngine(
        router=MoERouter(),
        lexical_store=lexical_store,
        semantic_store=semantic_store,
        graph_store=graph_store,
        fusion_engine=WeightedFusionEngine(),
        chunk_store=SQLiteChunkStore(db_path),
        validator=MinimalValidator(),
    )
    
    logger.info(f"Executing Query: '{QUERY}'")
    verification_output = engine.verify(QUERY, top_k=3)
    
    logger.info("=== PIPELINE COMPLETE ===")
    print("\nFINAL OUTPUT JSON:")
    print(json.dumps(verification_output, indent=2))

if __name__ == '__main__':
    main()
