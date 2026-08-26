"""The combined compliance report: structural conformance plus grounding.

A node can pass one plane and fail the other, and the two failures mean
completely different things:

* **conformance fail** — well-formed prose, illegally wired. The model
  contradicts its own blueprint.
* **grounding fail** — legally wired, but the process manual says otherwise
  (or says nothing).

So the report never collapses them into a single score. It reports each axis
on its own and gives the per-node cross-product, because "conformant but
contradicted by the source document" is the finding a reviewer most wants to
see and is exactly what an averaged score would hide.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .models import ConformanceFinding, Severity, severity_at_least
from .projection import ClaimProvenance, ProjectedClaim

# Verdict labels the engine emits, worst-first for roll-up precedence.
GROUNDING_LABELS = ("contradicted", "unknown", "partial", "supported")


@dataclass
class GroundingRollup:
    """Per-element grounding status, aggregated from its claims' verdicts."""

    status: str = "unknown"
    supported: int = 0
    partial: int = 0
    contradicted: int = 0
    unknown: int = 0
    assertion_ids: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.supported + self.partial + self.contradicted + self.unknown

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "supported": self.supported,
            "partial": self.partial,
            "contradicted": self.contradicted,
            "unknown": self.unknown,
            "total": self.total,
            "assertion_ids": self.assertion_ids,
        }


def _rollup_status(counts: "GroundingRollup") -> str:
    """One status for an element from its claims' verdicts.

    Contradiction wins over everything. A source document that actively
    disagrees with one claim about a node is the signal worth surfacing, and
    averaging it against three supported claims would erase it.
    """
    if counts.contradicted:
        return "contradicted"
    if counts.supported:
        return "supported"
    if counts.partial:
        return "partial"
    return "unknown"


@dataclass
class ComplianceReport:
    """Everything the validator concluded, in one serializable object."""

    ontology_version: str = ""
    metamodel_version: str = ""
    ontology_path: Optional[str] = None
    metamodel_path: Optional[str] = None

    # Plane A
    findings: List[ConformanceFinding] = field(default_factory=list)
    unreviewed_conflicts: int = 0

    # Plane B
    verdicts: List[Dict[str, Any]] = field(default_factory=list)
    corpus_documents: List[str] = field(default_factory=list)
    corpus_fingerprint: Optional[str] = None
    grounding_ran: bool = False

    node_grounding: Dict[str, GroundingRollup] = field(default_factory=dict)
    edge_grounding: Dict[str, GroundingRollup] = field(default_factory=dict)

    # node id -> whether its label occurs anywhere in the ingested corpus.
    # Separates the two very different reasons a claim comes back `unknown`.
    vocabulary_presence: Dict[str, bool] = field(default_factory=dict)

    # Which retriever tier produced the evidence. Governs how much the
    # grounding numbers can bear - see `grounding_confidence`.
    retrieval_backends: Dict[str, str] = field(default_factory=dict)

    total_nodes: int = 0
    total_edges: int = 0

    # ---- Plane A summaries -------------------------------------------------

    def findings_by_severity(self) -> Dict[str, int]:
        counts = Counter(f.severity.value for f in self.findings)
        return {s.value: counts.get(s.value, 0) for s in Severity}

    def findings_by_rule(self) -> Dict[str, int]:
        return dict(sorted(Counter(f.rule_id for f in self.findings).items()))

    def filter_findings(self, threshold: Severity) -> List[ConformanceFinding]:
        return [f for f in self.findings if severity_at_least(f.severity, threshold)]

    @property
    def conformance_passed(self) -> bool:
        """Errors fail conformance. Warnings and info do not.

        Decision D2: while the model is a work in progress, rules governing
        meta-classes with zero instances degrade to warnings, so a
        work-in-progress model can still pass rather than drowning the report
        in failures it already knows about.
        """
        return not any(f.severity is Severity.ERROR for f in self.findings)

    # ---- Plane B summaries -------------------------------------------------

    @property
    def grounding_passed(self) -> bool:
        """Decision D5: only contradiction fails.

        A node with no evidence is a coverage gap, not a defect - structural
        nodes like `Enterprise` will never appear verbatim in a process manual.
        """
        if not self.grounding_ran:
            return True
        return not any(v.get("label") == "contradicted" for v in self.verdicts)

    def grounding_by_label(self) -> Dict[str, int]:
        counts = Counter(v.get("label", "unknown") for v in self.verdicts)
        return {label: counts.get(label, 0) for label in GROUNDING_LABELS}

    def coverage(self) -> Dict[str, Any]:
        """How much of the ontology the corpus actually speaks to."""
        grounded_nodes = sum(
            1 for r in self.node_grounding.values() if r.status in ("supported", "contradicted")
        )
        grounded_edges = sum(
            1 for r in self.edge_grounding.values() if r.status in ("supported", "contradicted")
        )
        return {
            "nodes_total": self.total_nodes,
            "nodes_with_evidence": grounded_nodes,
            "nodes_pct": round(100.0 * grounded_nodes / self.total_nodes, 1) if self.total_nodes else 0.0,
            "edges_total": self.total_edges,
            "edges_with_evidence": grounded_edges,
            "edges_pct": round(100.0 * grounded_edges / self.total_edges, 1) if self.total_edges else 0.0,
        }

    def contradictions(self) -> List[Dict[str, Any]]:
        """The interesting bucket: claims the source documents disagree with."""
        return [v for v in self.verdicts if v.get("label") == "contradicted"]

    @property
    def grounding_confidence(self) -> str:
        """How much weight the grounding verdicts can carry.

        `low` on the SQLite demo tier, and that is not a hedge - the demo
        "semantic" retriever is Jaccard over token sets, not embeddings, so a
        claim phrased differently from the source prose cannot be retrieved at
        all. On top of that the heuristic span classifier decides
        `matched_relation` by literal substring, and a verbalized predicate
        like "includes the process" essentially never appears verbatim in a
        human-written manual. Both ceilings have to lift together before
        `supported` is reachable, which needs the Elasticsearch/Milvus tier.

        Read `low` as: trust `conformance`, treat `grounding` as a smoke test.
        """
        if not self.grounding_ran:
            return "not_run"
        demo_markers = ("SQLite", "Local")
        if any(
            any(marker in name for marker in demo_markers)
            for name in self.retrieval_backends.values()
        ):
            return "low"
        return "normal"

    def vocabulary_gap(self) -> Dict[str, Any]:
        """Which ontology terms the corpus never mentions.

        Without this, every `unknown` verdict looks the same. It isn't: a term
        the corpus never uses is a *corpus* problem (wrong documents, or a
        term the model invented), whereas a term that is present but still
        wasn't matched is a *retrieval* problem. Those have opposite fixes, and
        a reviewer staring at 123 `unknown` rows has no way to tell them apart.
        """
        if not self.vocabulary_presence:
            return {"measured": False}
        absent = sorted(k for k, present in self.vocabulary_presence.items() if not present)
        total = len(self.vocabulary_presence)
        return {
            "measured": True,
            "terms_total": total,
            "terms_present": total - len(absent),
            "terms_absent": len(absent),
            "present_pct": round(100.0 * (total - len(absent)) / total, 1) if total else 0.0,
            "absent_terms": absent,
        }

    # ---- Combined ----------------------------------------------------------

    def node_status(self) -> Dict[str, Dict[str, Any]]:
        """Per-node cross-product of the two planes."""
        failing: Dict[str, List[str]] = {}
        for finding in self.findings:
            if finding.subject_kind.value == "node":
                failing.setdefault(finding.subject_id, []).append(finding.rule_id)

        out: Dict[str, Dict[str, Any]] = {}
        for node_id in set(self.node_grounding) | set(failing):
            rollup = self.node_grounding.get(node_id)
            out[node_id] = {
                "conformance": "fail" if node_id in failing else "pass",
                "failed_rules": sorted(set(failing.get(node_id, []))),
                "grounding": rollup.status if rollup else "unknown",
            }
        return dict(sorted(out.items()))

    @property
    def passed(self) -> bool:
        return self.conformance_passed and self.grounding_passed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "ontology_version": self.ontology_version,
            "metamodel_version": self.metamodel_version,
            "ontology_path": self.ontology_path,
            "metamodel_path": self.metamodel_path,
            "conformance": {
                "passed": self.conformance_passed,
                "by_severity": self.findings_by_severity(),
                "by_rule": self.findings_by_rule(),
                "unreviewed_conflicts": self.unreviewed_conflicts,
                "findings": [f.to_dict() for f in self.findings],
            },
            "grounding": {
                "ran": self.grounding_ran,
                "passed": self.grounding_passed,
                "corpus_documents": self.corpus_documents,
                "corpus_fingerprint": self.corpus_fingerprint,
                "by_label": self.grounding_by_label(),
                "coverage": self.coverage(),
                "contradictions": self.contradictions(),
                "confidence": self.grounding_confidence,
                "retrieval_backends": self.retrieval_backends,
                "vocabulary_gap": self.vocabulary_gap(),
                "node_grounding": {k: v.to_dict() for k, v in sorted(self.node_grounding.items())},
                "edge_grounding": {k: v.to_dict() for k, v in sorted(self.edge_grounding.items())},
            },
            "node_status": self.node_status(),
        }

    def summary_lines(self) -> List[str]:
        """Terse human-readable summary, for CLI output."""
        sev = self.findings_by_severity()
        lines = [
            f"Ontology {self.ontology_version} vs meta-model {self.metamodel_version}",
            f"  conformance: {'PASS' if self.conformance_passed else 'FAIL'}"
            f"  ({sev['error']} error, {sev['warning']} warning, {sev['info']} info)",
        ]
        if self.unreviewed_conflicts:
            lines.append(f"  unreviewed conflicts: {self.unreviewed_conflicts} (run with --review)")
        if self.grounding_ran:
            labels = self.grounding_by_label()
            coverage = self.coverage()
            lines.append(
                f"  grounding:   {'PASS' if self.grounding_passed else 'FAIL'}"
                f"  ({labels['supported']} supported, {labels['partial']} partial, "
                f"{labels['contradicted']} contradicted, {labels['unknown']} unknown)"
            )
            lines.append(
                f"  coverage:    {coverage['nodes_with_evidence']}/{coverage['nodes_total']} nodes "
                f"({coverage['nodes_pct']}%), {coverage['edges_with_evidence']}/{coverage['edges_total']} edges "
                f"({coverage['edges_pct']}%)"
            )
            if self.grounding_confidence == "low":
                lines.append(
                    "  [!] demo-tier retrieval: 'supported' is not reachable "
                    "(lexical-only retrieval + substring relation matching). "
                    "Treat grounding as a smoke test, not a measurement."
                )
            gap = self.vocabulary_gap()
            if gap.get("measured"):
                lines.append(
                    f"  vocabulary:  {gap['terms_present']}/{gap['terms_total']} node labels "
                    f"appear in the corpus ({gap['present_pct']}%); "
                    f"{gap['terms_absent']} never mentioned"
                )
        else:
            lines.append("  grounding:   skipped")
        return lines


def rollup_grounding(
    verdicts: Iterable[Dict[str, Any]],
    provenance: Dict[str, ClaimProvenance],
) -> Dict[str, Dict[str, GroundingRollup]]:
    """Aggregate per-claim verdicts up to the nodes and edges they came from.

    A claim about an edge rolls up to that edge; a claim about a node's SIPOC
    attributes, decision branches, or description rolls up to that node.
    """
    nodes: Dict[str, GroundingRollup] = {}
    edges: Dict[str, GroundingRollup] = {}

    for verdict in verdicts:
        assertion_id = verdict.get("assertion_id")
        source = provenance.get(assertion_id)
        if source is None:
            continue
        if source.edge_key:
            bucket = edges.setdefault(source.edge_key, GroundingRollup())
        elif source.node_id:
            bucket = nodes.setdefault(source.node_id, GroundingRollup())
        else:
            continue

        label = verdict.get("label", "unknown")
        if label in ("supported", "partial", "contradicted", "unknown"):
            setattr(bucket, label, getattr(bucket, label) + 1)
        else:
            bucket.unknown += 1
        bucket.assertion_ids.append(assertion_id)

    for bucket in list(nodes.values()) + list(edges.values()):
        bucket.status = _rollup_status(bucket)
    return {"nodes": nodes, "edges": edges}
