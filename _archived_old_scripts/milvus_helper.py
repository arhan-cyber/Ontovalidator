import os
import logging
from typing import Any, List, Dict
from pymilvus import (
    connections,
    utility,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection
)

logger = logging.getLogger("MilvusHelper")

def get_milvus_collection(
    collection_name: str = "svo_chunks",
    dim: int = 5,
    host: str = "localhost",
    port: str = "19530"
) -> Collection:
    """
    Connects to Milvus and returns/creates the collection with the correct schema and index.
    """
    # Load connection settings from env or use defaults
    milvus_host = os.getenv("MILVUS_HOST", host)
    milvus_port = os.getenv("MILVUS_PORT", port)

    # Use Milvus Lite (local file) if host is localhost or specifically a file
    if milvus_host == "localhost" or milvus_host.endswith(".db"):
        milvus_uri = os.getenv("MILVUS_URI", "./milvus_demo.db")
        logger.info(f"Connecting to Milvus Lite at {milvus_uri}")
        connections.connect("default", uri=milvus_uri)
    else:
        logger.info(f"Connecting to Milvus server at {milvus_host}:{milvus_port}")
        connections.connect("default", host=milvus_host, port=milvus_port)

    # Create collection if it does not exist
    if not utility.has_collection(collection_name):
        logger.info(f"Creating Milvus collection '{collection_name}' with dimension {dim}")
        
        fields = [
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
            FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim)
        ]
        
        schema = CollectionSchema(fields, description="SVO chunk semantic vectors")
        collection = Collection(name=collection_name, schema=schema)
        
        # Build index on the embedding field
        index_params = {
            "metric_type": "L2",
            "index_type": "IVF_FLAT",
            "params": {"nlist": 128}
        }
        logger.info(f"Building index on 'embedding' field for collection '{collection_name}'")
        collection.create_index(field_name="embedding", index_params=index_params)
    else:
        logger.info(f"Milvus collection '{collection_name}' already exists.")
        collection = Collection(collection_name)
        
    return collection
