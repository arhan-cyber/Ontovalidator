"""End-to-end demo: ingest document + validate multiple triples at once."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engine import SVOVerificationEngine
from src.routing import MoERouter
from src.retrieval import SQLiteLexicalRetriever, SQLiteSemanticRetriever, SQLiteGraphRetriever
from src.fusion import WeightedFusionEngine
from src.storage import SQLiteChunkStore
from src.validation import MinimalValidator
from src.models import OntologyAssertion


def main():
    parser = argparse.ArgumentParser(description="Validate SVO triples against a document")
    parser.add_argument("--db-path", default="data/demo.db", help="SQLite database path")
    parser.add_argument("--document-id", default="test_doc", help="Document ID for reference")
    parser.add_argument("--text", required=True, help="Document text to validate against")
    parser.add_argument("--triple", action="append", dest="triples", required=True,
                       help="Triple as 'subject|relation|object' (repeatable)")
    parser.add_argument("--top-k", type=int, default=5, help="Top K chunks to consider")
    args = parser.parse_args()

    print("=" * 80)
    print("SVO TRIPLE VALIDATION")
    print("=" * 80)
    print(f"\nDocument: {args.text[:100]}..." if len(args.text) > 100 else f"\nDocument: {args.text}")

    # Parse triples
    triples = []
    for i, triple_str in enumerate(args.triples, 1):
        parts = triple_str.split("|")
        if len(parts) < 3:
            print(f"❌ Skipping malformed triple: {triple_str}")
            continue
        subject, relation, obj = parts[:3]
        triples.append(OntologyAssertion(
            assertion_id=f"t{i}",
            subject=subject.strip(),
            relation=relation.strip(),
            object=obj.strip(),
        ))

    if not triples:
        print("❌ No valid triples to validate")
        sys.exit(1)

    print(f"\nTriples to validate: {len(triples)}")
    for t in triples:
        print(f"  • {t.subject} {t.relation} {t.object}")

    # Create engine
    engine = SVOVerificationEngine(
        router=MoERouter(),
        lexical_store=SQLiteLexicalRetriever(args.db_path),
        semantic_store=SQLiteSemanticRetriever(args.db_path),
        graph_store=SQLiteGraphRetriever(args.db_path),
        fusion_engine=WeightedFusionEngine(),
        chunk_store=SQLiteChunkStore(args.db_path),
        validator=MinimalValidator(),
    )

    # Validate all triples in one call
    print("\n" + "-" * 80)
    print("PROCESSING...")
    print("-" * 80)

    result = engine.validate_triples_batch(
        document_id=args.document_id,
        raw_text=args.text,
        triples=triples,
        top_k=args.top_k
    )

    # Display results
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"\nIngestion Status: {result['ingestion_status']}")
    print(f"Chunks Ingested: {result['chunks_ingested']}")
    print(f"SVOs Extracted: {result['svos_extracted']}")

    print("\nVerdict Summary:")
    summary = result["summary"]
    print(f"  Total Triples: {summary['total_triples']}")
    print(f"  [+] Supported: {summary['supported']}")
    print(f"  [-] Contradicted: {summary['contradicted']}")
    print(f"  [~] Partial: {summary['partial']}")
    print(f"  [?] Unknown: {summary['unknown']}")
    print(f"  Average Score: {summary['avg_score']:.3f}")

    print("\nDetailed Verdicts:")
    print("-" * 80)

    for verdict in result["verdicts"]:
        label_symbol = {"supported": "[+]", "contradicted": "[-]", "partial": "[~]", "unknown": "[?]"}.get(
            verdict["label"], "[?]"
        )
        print(f"\n{label_symbol} {verdict['assertion_id']}: {verdict['subject']} {verdict['relation']} {verdict['object']}")
        print(f"  Label: {verdict['label']}")
        print(f"  Score: {verdict['score']:.3f}")
        print(f"  Rationale: {verdict['rationale']}")

        if verdict["evidence"]:
            print(f"  Evidence ({len(verdict['evidence'])} chunks):")
            for i, evidence in enumerate(verdict["evidence"][:2], 1):  # Show top 2
                print(f"    [{i}] Chunk {evidence['chunk_id'][:8]}... (score: {evidence['confidence']:.3f})")
                print(f"        Type: {evidence['match_type']}, Source: {evidence['source']}")
                print(f"        Text: \"{evidence['text'][:60]}...\"" if len(evidence["text"]) > 60
                      else f"        Text: \"{evidence['text']}\"")

    # Full JSON output option
    if "--json" in sys.argv:
        print("\n" + "=" * 80)
        print("FULL JSON OUTPUT")
        print("=" * 80)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
