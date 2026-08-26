import os
from neo4j import GraphDatabase

def get_neo4j_driver(uri: str = None, user: str = None, password: str = None):
    """
    Creates and returns a connection driver to a Neo4j database instance.
    Defaults are loaded from environment variables or typical local Neo4j defaults.
    """
    # Load settings from environment variables, fallback to standard local defaults
    neo4j_uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = user or os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = password or os.environ.get("NEO4J_PASSWORD", "password")

    print(f"Connecting to Neo4j database at {neo4j_uri} as user '{neo4j_user}'...")
    
    # Establish connection driver
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    
    # Test connection immediately to fail fast if config or server is incorrect
    try:
        driver.verify_connectivity()
        print("Successfully verified connection to Neo4j.")
    except Exception as e:
        print(f"Warning: Could not verify connection to Neo4j: {e}")
        print("Make sure your Neo4j instance is running and credentials are correct.")
        
    return driver

def initialize_neo4j_schema(driver):
    """
    Initializes constraints and indexes on the Neo4j graph database to ensure integrity and fast lookups.
    """
    print("Initializing Neo4j schema constraints...")
    try:
        with driver.session() as session:
            session.run("CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE")
            session.run("CREATE CONSTRAINT concept_name_unique IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE")
            
            # Create fulltext index needed for GraphRetriever queries
            session.run("CREATE FULLTEXT INDEX concept_name_index IF NOT EXISTS FOR (n:Concept) ON EACH [n.name]")
            print("Successfully initialized Neo4j schema constraints and fulltext index.")
    except Exception as e:
        print(f"Warning: Could not initialize Neo4j schema constraints: {e}")

