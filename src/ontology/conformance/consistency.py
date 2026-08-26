"""Cross-representation checks: the ontology disagreeing with itself.

None of these are ONT-* rules. They exist because the ontology file states the
same graph three times over — as `relationships`, as per-node `next_pointer`
lists, and as decision `branches[].target` — and nothing keeps the three in
step. A disagreement between them is not a meta-model violation; it is a file
that cannot be trusted to mean one thing, which has to be settled before any
rule that reads it means anything.

`next_pointer` is checked in one direction only: a pointer with no matching
relationship is a claim the graph does not support. The reverse — a
relationship absent from `next_pointer` — is normal and not reported, because
`next_pointer` is an agent's traversal plan rather than a mirror of every
edge. V4 has two such edges and both are legitimate.

Also here: the rule-list skew between the two files (finding 7), reported as
`info` rather than resolved, per decision D3.
"""

import json
import logging
import os
from typing import Any, Dict, Iterable, List

from ..loader import merge_systemic_rules
from ..models import ConformanceFinding, Severity, SubjectKind
from .registry import ConformanceRule, RuleContext

logger = logging.getLogger(__name__)


class DuplicateNodeIdRule(ConformanceRule):
    """No two `classes` entries may share an `id`.

    Has to re-read the source file. :class:`OntologyGraph` keys nodes by id, so
    by the time the graph exists a duplicate has already collapsed — the
    loader logs it and keeps the last one, which is the right call for
    loadability but leaves the fact unrecoverable from the model. Skips with a
    log line when `source_path` is unset (a hand-built graph) or unreadable.
    """

    rule_id = "CONSISTENCY-DUPLICATE-ID"
    title = "Node ids are unique"
    severity = Severity.ERROR

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        path = ctx.ontology.source_path
        if not path or not os.path.exists(path):
            logger.info(
                "duplicate-id check skipped: ontology has no readable source_path (%r)", path
            )
            return

        counts: Dict[str, int] = {}
        for raw in _raw_classes(path):
            node_id = str(raw.get("id", "")).strip()
            if node_id:
                counts[node_id] = counts.get(node_id, 0) + 1

        for node_id, count in sorted(counts.items()):
            if count < 2:
                continue
            yield self.finding(
                SubjectKind.NODE,
                node_id,
                f"id {node_id!r} is declared {count} times in `classes`",
                evidence=f"source: {path}",
                remediation="merge or rename the duplicates; only the last one survives loading",
            )


class DanglingEdgeRule(ConformanceRule):
    """Both endpoints of every relationship must name a declared node."""

    rule_id = "CONSISTENCY-DANGLING-EDGE"
    title = "Edge endpoints resolve"
    severity = Severity.ERROR

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for edge in ctx.ontology.edges:
            missing = [
                f"{role} {node_id!r}"
                for role, node_id in (("source", edge.source), ("target", edge.target))
                if node_id not in ctx.ontology.nodes
            ]
            if not missing:
                continue
            yield self.finding(
                SubjectKind.EDGE,
                edge.key,
                f"edge {edge} references undeclared {' and '.join(missing)}",
                evidence=f"{len(ctx.ontology.nodes)} nodes declared",
                remediation="declare the missing node, or delete the relationship",
            )


class UnknownEdgeTypeRule(ConformanceRule):
    """Every relationship type must appear in the blueprint's grammar."""

    rule_id = "CONSISTENCY-UNKNOWN-EDGE"
    title = "Edge types are declared"
    severity = Severity.ERROR

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        known = set(ctx.metamodel.edge_rules)
        offenders: Dict[str, List[str]] = {}
        for edge in ctx.ontology.edges:
            if edge.type not in known:
                offenders.setdefault(edge.type, []).append(edge.key)

        for edge_type, keys in sorted(offenders.items()):
            yield self.finding(
                SubjectKind.GRAPH,
                edge_type,
                f"relationship type {edge_type!r} is not declared in the edge grammar "
                f"({len(keys)} use(s))",
                evidence=f"used by: {ctx.sample(keys)}",
                remediation="add the edge type to allowed_relationships, or retype the edges",
            )


class NextPointerAgreementRule(ConformanceRule):
    """A `next_pointer` target must be backed by an actual relationship."""

    rule_id = "CONSISTENCY-NEXT-POINTER"
    title = "next_pointer agrees with relationships"
    severity = Severity.ERROR

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for node in ctx.ontology.nodes.values():
            if not node.next_pointer:
                continue
            targets = {e.target for e in ctx.ontology.out_edges(node.id)}
            for pointer in node.next_pointer:
                if pointer in targets:
                    continue
                known = pointer in ctx.ontology.nodes
                yield self.finding(
                    SubjectKind.NODE,
                    node.id,
                    f"next_pointer names {pointer!r} but no relationship connects them"
                    + ("" if known else " (and no such node is declared)"),
                    evidence=(
                        f"next_pointer: {ctx.sample(node.next_pointer)}; "
                        f"relationship targets: {ctx.sample(sorted(targets)) or '(none)'}"
                    ),
                    remediation=(
                        "add the missing relationship, or drop the pointer — the two "
                        "representations must describe the same graph"
                    ),
                )


class DecisionBranchTargetRule(ConformanceRule):
    """An `evaluate_decision` branch target must name a declared node.

    Same class of defect as a `next_pointer` with no relationship behind it:
    an agent following the branch has nowhere to land. V4's one instance
    points at `trace_back`, which is a postcondition *action* name — the
    branch was filled in from the wrong vocabulary.
    """

    rule_id = "CONSISTENCY-BRANCH-TARGET"
    title = "Decision branch targets resolve"
    severity = Severity.ERROR

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for node in ctx.ontology.nodes.values():
            if node.agent_rules is None:
                continue
            for action in node.agent_rules.execution:
                branches = action.get("branches")
                if not isinstance(branches, list):
                    continue
                for index, branch in enumerate(branches):
                    if not isinstance(branch, dict):
                        continue
                    target = branch.get("target")
                    if not isinstance(target, str) or target in ctx.ontology.nodes:
                        continue
                    yield self.finding(
                        SubjectKind.NODE,
                        f"{node.id}#branch[{index}]",
                        f"decision branch target {target!r} is not a declared node",
                        evidence=f"node {node.id!r}, condition: {branch.get('condition')!r}",
                        remediation=(
                            "point the branch at a node id; action names are not "
                            "traversal targets"
                        ),
                    )


class RulesetSkewRule(ConformanceRule):
    """The two files declare different ONT-* rule lists (finding 7).

    Reported, not resolved: the registry runs the union, and which file should
    be amended is a human call. Decision D3.
    """

    rule_id = "RULESET-SKEW"
    title = "Systemic rule lists agree across the two files"
    severity = Severity.INFO

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        if not ctx.config.report_ruleset_skew:
            return
        merged = merge_systemic_rules(ctx.metamodel, ctx.ontology)
        ontology_only = sorted(r for r, s in merged.items() if s.sources == frozenset({"ontology"}))
        metamodel_only = sorted(
            r for r, s in merged.items() if s.sources == frozenset({"metamodel"})
        )
        if not ontology_only and not metamodel_only:
            return

        parts = []
        if metamodel_only:
            parts.append(f"only in the meta-model: {', '.join(metamodel_only)}")
        if ontology_only:
            parts.append(f"only in the ontology: {', '.join(ontology_only)}")

        yield self.finding(
            SubjectKind.GRAPH,
            "systemic_rules",
            f"the two files declare different systemic rule sets ({'; '.join(parts)})",
            evidence=(
                f"meta-model v{ctx.metamodel.version or '?'} declares "
                f"{len(ctx.metamodel.systemic_rules)}; ontology v{ctx.ontology.version or '?'} "
                f"declares {len(ctx.ontology.systemic_rules)}; the registry runs the union of "
                f"{len(merged)}"
            ),
            remediation=(
                "reconcile the two rule lists — the registry runs the union, so a rule "
                "missing from one file is still enforced"
            ),
        )


def _raw_classes(path: str) -> List[Dict[str, Any]]:
    """The `classes` array as it appears on disk, wrapper or not."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("could not re-read ontology at %s for duplicate detection: %s", path, exc)
        return []

    if isinstance(payload, dict) and "classes" not in payload:
        for candidate in payload.values():
            if isinstance(candidate, dict) and "classes" in candidate:
                payload = candidate
                break
    classes = payload.get("classes") if isinstance(payload, dict) else None
    return [c for c in classes if isinstance(c, dict)] if isinstance(classes, list) else []


def consistency_rules() -> List[ConformanceRule]:
    return [
        DuplicateNodeIdRule(),
        DanglingEdgeRule(),
        UnknownEdgeTypeRule(),
        NextPointerAgreementRule(),
        DecisionBranchTargetRule(),
        RulesetSkewRule(),
    ]
