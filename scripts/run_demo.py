"""Unified demo script for ingestion and verification."""

import argparse
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config_from_env, BackendMode, PipelineConfig
from src.factories import EngineFactory
from src.ingestion import run_demo as run_ingestion_demo
from src.routing import MoERouter
from src.retrieval import SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever
from src.fusion import WeightedFusionEngine
from src.storage import SQLiteChunkStore
from src.validation import MinimalValidator, TransformerValidator
from src.engine import SVOVerificationEngine


def main():
    parser = argparse.ArgumentParser(description="SVO Verification Pipeline Demo")
    parser.add_argument("--db-path", default="svo_data.db", help="SQLite database path")
    parser.add_argument("--document-id", default="demo_doc", help="Document ID for ingestion")
    parser.add_argument("--text", default="Aspirin treats headache and reduces pain.", help="Text to ingest")
    parser.add_argument("--query", default="What treats headache?", help="Query for verification")
    parser.add_argument("--backend-mode", choices=["demo", "production", "auto"], default="auto", help="Backend mode: demo (mocks), production (real), or auto (detect)")
    parser.add_argument("--health-check", action="store_true", help="Run health checks before pipeline")
    parser.add_argument("--embedding-model", choices=["simple", "transformer"], help="Embedding model override")
    parser.add_argument("--svo-extractor", choices=["mock", "transformer"], help="SVO extractor override")
    parser.add_argument("--show-backends", action="store_true", help="Display active backends after setup")
    parser.add_argument("--run-mode", choices=["demo", "full"], help="Deprecated: use --backend-mode instead")
    parser.add_argument("--validator", choices=["minimal", "transformer"], default="minimal", help="Validator type")
    parser.add_argument("--top-k", type=int, default=5, help="Top K results to return")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    args = parser.parse_args()

    print("=" * 80)
    print("SVO VERIFICATION PIPELINE DEMO")
    print("=" * 80)

    # Load configuration from environment
    config = load_config_from_env()
    config.verbose = args.verbose
    config.sqlite_path = args.db_path

    # Override backend mode from CLI
    if args.backend_mode == "demo":
        config.backend_mode = BackendMode.DEMO
        config.use_production_backends = False
    elif args.backend_mode == "production":
        config.backend_mode = BackendMode.PRODUCTION
        config.require_production_backends = True
    # else: auto (default)

    # Override models from CLI
    if args.embedding_model:
        config.embedding_model_name = args.embedding_model
    if args.svo_extractor:
        config.svo_extractor_name = args.svo_extractor

    # Override validator from CLI
    config.validator_name = args.validator

    # Handle deprecated run_mode parameter
    if args.run_mode and not args.backend_mode:
        if args.run_mode == "full":
            config.backend_mode = BackendMode.PRODUCTION
            config.use_production_backends = True

    # Run health checks if requested
    if args.health_check:
        from src.integration.health_check_runner import HealthCheckRunner, print_health_report
        if args.verbose:
            print("\n[HEALTH CHECK PHASE]")
            print("-" * 80)
        health_report = HealthCheckRunner.check_all(config)
        print_health_report(health_report)
        if health_report.overall_status == "FAILED":
            print("Error: Health check failed. Aborting.")
            sys.exit(1)

    # Show active backends if requested
    if args.show_backends:
        print("\nActive Backends:")
        print(f"  Lexical: {'Elasticsearch' if config.elasticsearch.enabled else 'SQLite'}")
        print(f"  Semantic: {'Milvus' if config.milvus.enabled else 'SQLite'}")
        print(f"  Graph: {'Neo4j' if config.neo4j.enabled else 'SQLite'}")
        print()

    # 1. Ingestion
    print("[1/2] INGESTION PHASE")
    print("-" * 80)
    ingestion_result = run_ingestion_demo(
        document_id=args.document_id,
        raw_text=args.text,
        db_path=args.db_path,
        config=config
    )
    print(f"Status: {ingestion_result['status']}")
    print(f"Chunks: {ingestion_result['chunks']}, SVOs: {ingestion_result['svos']}")

    # 2. Verification
    print("\n[2/2] VERIFICATION PHASE")
    print("-" * 80)

    # Create engine via factory
    engine = EngineFactory.create_verification_engine(config)

    # Run verification
    verification_result = engine.verify(args.query, top_k=args.top_k)

    # Output results
    print(f"Status: {verification_result['status']}")
    print(f"Evidence chunks: {len(verification_result.get('evidence', []))}")

    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(json.dumps(verification_result, indent=2, default=str))


if __name__ == "__main__":
    main()
