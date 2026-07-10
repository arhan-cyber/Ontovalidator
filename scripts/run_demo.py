"""Unified demo script for ingestion and verification."""

import argparse
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

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
    parser.add_argument("--run-mode", choices=["demo", "full"], default="demo", help="'demo' (mock) or 'full' (real DBs)")
    parser.add_argument("--validator", choices=["minimal", "transformer"], default="minimal", help="Validator type")
    parser.add_argument("--top-k", type=int, default=5, help="Top K results to return")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    args = parser.parse_args()

    print("=" * 80)
    print("SVO VERIFICATION PIPELINE DEMO")
    print("=" * 80)

    # 1. Ingestion
    print("\n[1/2] INGESTION PHASE")
    print("-" * 80)
    ingestion_result = run_ingestion_demo(
        document_id=args.document_id,
        raw_text=args.text,
        db_path=args.db_path,
        run_mode=args.run_mode
    )
    print(f"Status: {ingestion_result['status']}")
    print(f"Chunks: {ingestion_result['chunks']}, SVOs: {ingestion_result['svos']}")

    # 2. Verification
    print("\n[2/2] VERIFICATION PHASE")
    print("-" * 80)

    # Select validator
    if args.validator == "transformer":
        try:
            validator = TransformerValidator()
        except Exception as e:
            print(f"Warning: TransformerValidator failed ({e}). Falling back to MinimalValidator.")
            validator = MinimalValidator()
    else:
        validator = MinimalValidator()

    # Build engine
    engine = SVOVerificationEngine(
        router=MoERouter(),
        lexical_store=SQLiteLexicalRetriever(args.db_path),
        semantic_store=SQLiteSemanticRetriever(args.db_path),
        graph_store=SQLiteGraphRetriever(args.db_path),
        fusion_engine=WeightedFusionEngine(),
        chunk_store=SQLiteChunkStore(args.db_path),
        validator=validator,
    )

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
