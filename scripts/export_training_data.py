"""Export triple adjudications as JSONL for training."""

import argparse
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion import run_demo as run_ingestion_demo
from src.routing import MoERouter
from src.retrieval import SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever
from src.fusion import WeightedFusionEngine
from src.storage import SQLiteChunkStore
from src.validation import MinimalValidator
from src.classification import TripleDatasetWriter
from src.models import OntologyAssertion
from src.engine import SVOVerificationEngine


def main():
    parser = argparse.ArgumentParser(description="Export triple adjudications as JSONL")
    parser.add_argument("--db-path", default="svo_data.db", help="SQLite database path")
    parser.add_argument("--document-id", default="demo_doc", help="Document ID")
    parser.add_argument("--text", default="Aspirin treats headache and reduces pain.", help="Text to ingest")
    parser.add_argument("--out", required=True, help="Output JSONL file path")
    parser.add_argument("--assertion", action="append", default=[], help="Assertion as subject|relation|object|polarity")
    parser.add_argument("--run-mode", choices=["demo", "full"], default="demo", help="Run mode")
    args = parser.parse_args()

    print("=" * 80)
    print("TRIPLE ADJUDICATION EXPORT")
    print("=" * 80)

    # 1. Ingest document
    print("\n[1/2] INGESTION")
    print("-" * 80)
    ingestion_result = run_ingestion_demo(
        document_id=args.document_id,
        raw_text=args.text,
        db_path=args.db_path,
        run_mode=args.run_mode
    )
    print(f"Status: {ingestion_result['status']}")

    # 2. Setup engine
    print("\n[2/2] ADJUDICATION & EXPORT")
    print("-" * 80)
    engine = SVOVerificationEngine(
        router=MoERouter(),
        lexical_store=SQLiteLexicalRetriever(args.db_path),
        semantic_store=SQLiteSemanticRetriever(args.db_path),
        graph_store=SQLiteGraphRetriever(args.db_path),
        fusion_engine=WeightedFusionEngine(),
        chunk_store=SQLiteChunkStore(args.db_path),
        validator=MinimalValidator(),
    )

    # Parse assertions
    assertions = []
    for raw_assertion in args.assertion:
        parts = raw_assertion.split("|")
        if len(parts) < 3:
            print(f"Warning: Skipping malformed assertion: {raw_assertion}")
            continue
        subject, relation, obj = parts[:3]
        polarity = parts[3] if len(parts) > 3 else "must_hold"
        assertions.append(OntologyAssertion(
            assertion_id=f"claim_{len(assertions)+1}",
            subject=subject,
            relation=relation,
            object=obj,
            polarity=polarity,
        ))

    if not assertions:
        print("Error: No valid assertions provided. Use --assertion subject|relation|object|polarity (repeatable)")
        sys.exit(1)

    # Write training data
    writer = TripleDatasetWriter(args.out)
    verdicts = engine.export_training_examples(
        document_id=args.document_id,
        assertions=assertions,
        writer=writer,
        top_k=5,
        document_text=args.text,
    )

    print(f"Exported {len(verdicts)} adjudication examples to {args.out}")
    print("\nSample adjudications:")
    for v in verdicts[:3]:
        print(f"  - {v.assertion_id}: {v.subject} {v.relation} {v.object} → {v.label} (score: {v.score})")


if __name__ == "__main__":
    main()
