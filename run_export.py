import argparse
import json

from lm_triple_classifier import TripleDatasetWriter
from svo_engine import (
    SVOVerificationEngine,
    MoERouter,
    SQLiteLexicalRetriever,
    SQLiteSemanticRetriever,
    SQLiteGraphRetriever,
    WeightedFusionEngine,
    SQLiteChunkStore,
    OntologyAssertion,
    MinimalValidator,
    run_demo,
)


def parse_assertion(raw_assertion: str, idx: int) -> OntologyAssertion:
    parts = raw_assertion.split("|")
    if len(parts) < 3:
        raise ValueError(
            "Assertions must use subject|relation|object or subject|relation|object|polarity"
        )
    subject, relation, obj = parts[:3]
    polarity = parts[3] if len(parts) > 3 else "must_hold"
    return OntologyAssertion(
        assertion_id=f"cli_{idx}",
        subject=subject,
        relation=relation,
        object=obj,
        polarity=polarity,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export triple adjudications to JSONL training data")
    parser.add_argument("--db-path", default="svo_data.db")
    parser.add_argument("--document-id", default="demo_doc")
    parser.add_argument("--text", default="Aspirin treats headache and reduces pain.")
    parser.add_argument("--out", required=True, help="JSONL output path")
    parser.add_argument(
        "--assertion",
        action="append",
        default=[],
        help="subject|relation|object|polarity, repeatable",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--run-mode", choices=["demo", "full"], default="demo")
    args = parser.parse_args()

    # Ensure the document is present in the local chunk store before adjudication.
    run_demo(db_path=args.db_path, query="What treats headache?", raw_text=args.text, run_mode=args.run_mode)

    engine = SVOVerificationEngine(
        router=MoERouter(),
        lexical_store=SQLiteLexicalRetriever(args.db_path),
        semantic_store=SQLiteSemanticRetriever(args.db_path),
        graph_store=SQLiteGraphRetriever(args.db_path),
        fusion_engine=WeightedFusionEngine(),
        chunk_store=SQLiteChunkStore(args.db_path),
        validator=MinimalValidator(),
    )
    writer = TripleDatasetWriter(args.out)

    assertions = [parse_assertion(raw, idx + 1) for idx, raw in enumerate(args.assertion)]
    verdicts = engine.export_training_examples(
        document_id=args.document_id,
        assertions=assertions,
        writer=writer,
        top_k=args.top_k,
        document_text=None,
    )

    print(json.dumps({"document_id": args.document_id, "exported": len(verdicts), "out": args.out}, indent=2))


if __name__ == "__main__":
    main()
