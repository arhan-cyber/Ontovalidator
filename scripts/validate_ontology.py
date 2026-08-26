"""Validate an enterprise ontology against its meta-model and source documents.

Two planes, independently switchable:

    --plane a      structural conformance only (no documents, no models, fast)
    --plane b      evidential grounding only
    --plane both   default

Examples
--------
    # Conformance only - the fastest useful thing, needs no corpus.
    python scripts/validate_ontology.py --plane a

    # Full run against the process manuals, writing a report.
    python scripts/validate_ontology.py --documents Documents/ --out report.json

    # Work through the conflict review queue interactively.
    python scripts/validate_ontology.py --plane a --review

    # Re-bless the hash-pinned conformance baseline after an ontology revision.
    python scripts/validate_ontology.py --bless-baseline
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config_from_env
from src.engine import SVOVerificationEngine
from src.ontology.compliance import OntologyComplianceValidator
from src.ontology.compliance_config import OntologyComplianceConfig
from src.ontology.conflicts import VALID_STATUSES
from src.ontology.loader import OntologyInputError
from src.ontology.models import Severity
from src.ontology.projection import ALL_CLAIM_KINDS

BASELINE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "ontology_conformance_baseline.json"

# Adjudication choices offered in --review, in menu order.
_REVIEW_CHOICES = [
    ("1", "ontology_defect", "the ontology is wrong - keep as an error"),
    ("2", "metamodel_gap", "the blueprint is too narrow - downgrade to info"),
    ("3", "accepted_exception", "deliberate deviation - suppress from the report"),
    ("s", None, "skip for now"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an ontology against its meta-model and source documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ontology", help="Path to the ontology JSON (env: ONTO_ONTOLOGY_PATH)")
    parser.add_argument("--metamodel", help="Path to the meta-model JSON (env: ONTO_METAMODEL_PATH)")
    parser.add_argument("--documents", help="Directory of source PDFs (env: ONTO_DOCUMENT_CORPUS_PATH)")
    parser.add_argument("--plane", choices=["a", "b", "both"], default="both",
                        help="a=conformance, b=grounding, both=default")
    parser.add_argument("--claim-kinds", help=f"Comma-separated subset of: {','.join(ALL_CLAIM_KINDS)}")
    parser.add_argument("--top-k", type=int, default=5, help="Evidence chunks per claim")
    parser.add_argument("--include-it4it", action="store_true",
                        help="Include the 294-page IT4IT standard in the grounding corpus")
    parser.add_argument("--severity", choices=[s.value for s in Severity], default="info",
                        help="Omit findings less severe than this")
    parser.add_argument("--out", help="Write the full JSON report here")
    parser.add_argument("--review", action="store_true",
                        help="Interactively adjudicate open meta-model conflicts")
    parser.add_argument("--conflict-db", help="Conflict registry path (env: ONTO_CONFLICT_DB_PATH)")
    parser.add_argument("--no-registry", action="store_true", help="Disable the conflict registry")
    parser.add_argument("--bless-baseline", action="store_true",
                        help="Rewrite the hash-pinned conformance baseline fixture")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    parser.add_argument("--fail-on-findings", action="store_true",
                        help="Exit non-zero when the report does not pass (for CI)")
    return parser


def build_config(args) -> OntologyComplianceConfig:
    config = OntologyComplianceConfig.from_env()
    if args.ontology:
        config.ontology_path = args.ontology
    if args.metamodel:
        config.metamodel_path = args.metamodel
    if args.documents:
        config.document_corpus_path = args.documents
    if args.claim_kinds:
        config.claim_kinds = [k.strip() for k in args.claim_kinds.split(",") if k.strip()]
    if args.conflict_db:
        config.conflict_db_path = args.conflict_db
    config.top_k = args.top_k
    config.include_it4it_corpus = args.include_it4it or config.include_it4it_corpus
    config.severity_threshold = args.severity
    config.enable_conformance = args.plane in ("a", "both")
    config.enable_grounding = args.plane in ("b", "both")
    if args.no_registry:
        config.enable_conflict_registry = False
    return config


def review_conflicts(registry, out=sys.stdout) -> int:
    """Walk the open queue. Only `open` conflicts are offered.

    Anything already adjudicated is skipped, so a repeat run asks about new
    disagreements only - which is what keeps the queue worth reading.
    """
    open_rows = registry.open_conflicts()
    if not open_rows:
        print("No open conflicts to review.", file=out)
        return 0

    print(f"\n{len(open_rows)} open conflict(s) to adjudicate.\n", file=out)
    resolved = 0
    for index, row in enumerate(open_rows, start=1):
        print(f"[{index}/{len(open_rows)}] {row['rule_id']}  {row['subject_id']}", file=out)
        print(f"      ontology:  {row['ontology_says']}", file=out)
        print(f"      metamodel: {row['metamodel_says']}", file=out)
        for key, _status, description in _REVIEW_CHOICES:
            print(f"      [{key}] {description}", file=out)
        try:
            answer = input("      choice> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nReview interrupted; decisions so far are saved.", file=out)
            break
        status = dict((k, s) for k, s, _ in _REVIEW_CHOICES).get(answer)
        if status is None:
            print("      skipped\n", file=out)
            continue
        note = input("      note (optional)> ").strip() or None
        registry.resolve(row["conflict_id"], status, note=note, resolved_by="cli")
        resolved += 1
        print(f"      -> {status}\n", file=out)
    return resolved


def write_baseline(report, path: Path) -> None:
    """Freeze the current findings, pinned to the inputs they came from.

    Hashing the inputs is what makes the baseline honest: an ontology revision
    then reads as "the baseline is stale, re-bless it" rather than as an
    inexplicable diff in the findings list.
    """
    import hashlib

    def _digest(file_path):
        if not file_path or not Path(file_path).exists():
            return None
        return hashlib.sha256(Path(file_path).read_bytes()).hexdigest()

    payload = {
        "_comment": (
            "Frozen conformance baseline. The ontology and meta-model inputs are "
            "gitignored, so this fixture is what CI compares against. Regenerate "
            "with: python scripts/validate_ontology.py --bless-baseline"
        ),
        "ontology_sha256": _digest(report.ontology_path),
        "metamodel_sha256": _digest(report.metamodel_path),
        "ontology_version": report.ontology_version,
        "metamodel_version": report.metamodel_version,
        "total_findings": len(report.findings),
        "by_rule": report.findings_by_rule(),
        "by_severity": report.findings_by_severity(),
        "findings": sorted(
            [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity.value,
                    "subject_kind": f.subject_kind.value,
                    "subject_id": f.subject_id,
                    "degraded": f.degraded,
                }
                for f in report.findings
            ],
            key=lambda f: (f["rule_id"], f["subject_id"]),
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = build_parser().parse_args()
    config = build_config(args)

    engine = None
    if config.enable_grounding:
        try:
            engine = SVOVerificationEngine.from_config(load_config_from_env())
        except Exception as exc:  # pragma: no cover - environment dependent
            print(f"[!] could not build the verification engine: {exc}", file=sys.stderr)
            print("    continuing with conformance only", file=sys.stderr)
            config.enable_grounding = False

    def progress(message, index, total):
        if not args.quiet and total:
            print(f"\r  {message} ({index}/{total})", end="", file=sys.stderr)

    validator = OntologyComplianceValidator(config, engine=engine)
    try:
        report = validator.validate(progress=None if args.quiet else progress)
    except OntologyInputError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 2
    if not args.quiet:
        print(file=sys.stderr)

    print("\n".join(report.summary_lines()))

    if args.review and validator.registry is not None:
        resolved = review_conflicts(validator.registry)
        if resolved:
            print(f"\nAdjudicated {resolved} conflict(s). Re-run to see the updated report.")

    if args.bless_baseline:
        write_baseline(report, BASELINE_PATH)
        print(f"\nBaseline written to {BASELINE_PATH}")

    if args.out:
        Path(args.out).write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        print(f"\nFull report written to {args.out}")

    if args.fail_on_findings and not report.passed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
