"""End-to-end demo: ingest document + validate multiple triples at once."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config_from_env, BackendMode
from src.factories import EngineFactory
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
    parser.add_argument("--backend-mode", choices=["demo", "production", "auto"], default="auto", help="Backend mode")
    parser.add_argument("--health-check", action="store_true", help="Run health checks before validation")
    parser.add_argument("--embedding-model", choices=["simple", "transformer"], help="Embedding model override")
    parser.add_argument("--svo-extractor", choices=["mock", "transformer"], help="SVO extractor override")
    parser.add_argument("--show-backends", action="store_true", help="Display active backends")
    parser.add_argument("--log-backend-usage", action="store_true", help="Log which backend returned each evidence")
    parser.add_argument("--export-config", help="Save effective config to JSON file")
    parser.add_argument("--top-k", type=int, default=5, help="Top K chunks to consider")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    args = parser.parse_args()

    print("=" * 80)
    print("SVO TRIPLE VALIDATION")
    print("=" * 80)
    print(f"\nDocument: {args.text[:100]}..." if len(args.text) > 100 else f"\nDocument: {args.text}")

    # Load configuration from environment
    config = load_config_from_env()
    config.verbose = args.verbose
    config.sqlite_path = args.db_path
    config.log_backend_usage = args.log_backend_usage

    # Override backend mode from CLI
    if args.backend_mode == "demo":
        config.backend_mode = BackendMode.DEMO
        config.use_production_backends = False
    elif args.backend_mode == "production":
        config.backend_mode = BackendMode.PRODUCTION
        config.require_production_backends = True

    # Override models from CLI
    if args.embedding_model:
        config.embedding_model_name = args.embedding_model
    if args.svo_extractor:
        config.svo_extractor_name = args.svo_extractor

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

    # Export config if requested
    if args.export_config:
        config.save_to_file(args.export_config)
        print(f"Effective config saved to: {args.export_config}")

    # Parse triples
    triples = []
    for i, triple_str in enumerate(args.triples, 1):
        parts = triple_str.split("|")
        if len(parts) < 3:
            print(f"Skipping malformed triple: {triple_str}")
            continue
        subject, relation, obj = parts[:3]
        triples.append(OntologyAssertion(
            assertion_id=f"t{i}",
            subject=subject.strip(),
            relation=relation.strip(),
            object=obj.strip(),
        ))

    if not triples:
        print("Error: No valid triples to validate")
        sys.exit(1)

    print(f"\nTriples to validate: {len(triples)}")
    for t in triples:
        print(f"  • {t.subject} {t.relation} {t.object}")

    # Create engine via factory
    engine = EngineFactory.create_verification_engine(config)

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
    if "backend_status" in result:
        print(f"\nBackend Status:")
        for backend, impl in result["backend_status"].items():
            print(f"  {backend}: {impl}")

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
                backend_info = f", Backend: {evidence['source']}" if args.log_backend_usage else ""
                print(f"        Type: {evidence['match_type']}, Source: {evidence['source']}{backend_info}")
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
