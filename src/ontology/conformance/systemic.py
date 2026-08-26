"""One class per ONT-* systemic rule.

Each rule is small, independent, and reads only the graph and the blueprint.
Severity and degradation are declared, not decided here — see
:mod:`.registry`.

Two severity conventions, both deliberate:

* a `STATIC_PROXY` rule reports at `warning`. It is a necessary-but-not-
  sufficient stand-in for a runtime property, so a hit is a strong hint, not a
  proof. Phase 6's traversal simulator upgrades these to real checks, at which
  point they can be promoted.
* ONT-001 reports at `warning` too, for a different reason recorded on the
  class itself.
"""

import logging
from typing import Dict, Iterable, List, Optional, Set

from ..models import CheckType, ConformanceFinding, OntologyNode, Severity, SubjectKind
from .registry import ConformanceRule, RuleContext

logger = logging.getLogger(__name__)

ROOT_TYPE = "Enterprise Root"

# Edges that advance a workflow sideways, between peers.
HORIZONTAL_EDGES = {"triggers", "leads_to", "on_success", "on_failure"}
# Edges that descend the containment hierarchy.
VERTICAL_EDGES = {"has_lifecycle_phase", "includes_process", "decomposes_into", "has_subprocess"}

# The Activity hierarchy, coarse to fine. Only `attributes.type` carries tier;
# Decision Nodes and Outcomes sit outside it and are exempt from ONT-008.
ACTIVITY_TIERS = {
    "Core Activity": 0,
    "Domain Activity": 1,
    "Process Activity": 2,
    "Sub_Process Activity": 3,
}

SIPOC_FIELDS = ("supplier", "input", "output", "customer")

# Actions that change state or move the agent. A Decision Node may evaluate;
# it may not act. Deliberately a deny-list rather than an allow-list: an
# action nobody has seen before should not be assumed to be a violation.
NON_EVALUATIVE_ACTIONS = {
    "traverse_dfs",
    "traverse_dynamic",
    "invoke_tool",
    "set_payload",
    "append_payload",
    "fill_missing_value",
    "extract_and_append",
    "conditional_set",
}

# Attributes that could carry an inheritable constraint set (ONT-002).
CONSTRAINT_ATTRIBUTES = ("global_constraints", "constraints", "conditions")


def _tier(node: OntologyNode) -> Optional[int]:
    for kind in node.kinds:
        if kind in ACTIVITY_TIERS:
            return ACTIVITY_TIERS[kind]
    return None


class RootSingularityRule(ConformanceRule):
    """ONT-000 — exactly one `Enterprise Root`, and everything hangs off it."""

    rule_id = "ONT-000"
    title = "Root Singularity"
    severity = Severity.ERROR
    check_type = CheckType.STATIC

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        roots = ctx.nodes_of_kind(ROOT_TYPE)
        if len(roots) != 1:
            yield self.finding(
                SubjectKind.GRAPH,
                "root",
                f"expected exactly one {ROOT_TYPE!r} node, found {len(roots)}",
                evidence=ctx.sample([r.id for r in roots]) or "(none)",
                remediation=f"designate a single {ROOT_TYPE} node",
            )
            if not roots:
                return

        root = roots[0]
        seen = {root.id}
        frontier = [root.id]
        while frontier:
            current = frontier.pop()
            for edge in ctx.ontology.out_edges(current):
                if edge.target not in seen and edge.target in ctx.ontology.nodes:
                    seen.add(edge.target)
                    frontier.append(edge.target)

        for node_id in sorted(set(ctx.ontology.nodes) - seen):
            yield self.finding(
                SubjectKind.NODE,
                node_id,
                f"node is not reachable from the root {root.id!r}",
                evidence=f"{len(seen)} of {len(ctx.ontology.nodes)} nodes are reachable",
                remediation="connect the node to the enterprise hierarchy, or remove it",
            )


class SipocCompletenessRule(ConformanceRule):
    """ONT-001 — an Activity that transitions must declare its full SIPOC.

    Registered at `warning`, not `error`, and that is a judgement call worth
    stating. Every one of V4's 27 transitioning Activities is missing at least
    one SIPOC field. Twenty-seven for twenty-seven is not twenty-seven
    independent defects — it is one unfinished population pass over a model
    that is explicitly a work in progress. Reported as errors it would swamp
    the six grammar violations, which *are* individually diagnosable, and
    train the reader to skim the report. It escalates to `error` the day the
    ratio stops being 100%.

    `attr()` and not `has_attr_key()`: all 40 Activities carry the five keys,
    so the presence check (SCHEMA-ATTR) passes and the value check is the only
    one with anything to say.
    """

    rule_id = "ONT-001"
    title = "SIPOC Completeness"
    severity = Severity.WARNING
    check_type = CheckType.STATIC

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for node in ctx.ontology.by_meta_class("Activity_Class"):
            if not node.next_pointer:
                continue  # no transition to gate
            missing = [f for f in SIPOC_FIELDS if not node.attr(f)]
            if not missing:
                continue
            yield self.finding(
                SubjectKind.NODE,
                node.id,
                f"Activity declares a transition but leaves {', '.join(missing)} empty",
                evidence=(
                    f"next_pointer: {ctx.sample(node.next_pointer)}; "
                    + "; ".join(f"{f}={node.attributes.get(f)!r}" for f in missing)
                ),
                remediation=f"populate {', '.join(missing)} before the agent may transition",
            )


class ConstraintInheritanceRule(ConformanceRule):
    """ONT-002 — a child's constraint set must include its parent's.

    Weak by necessity: neither file defines a constraint model. The blueprint
    lists `global_constraints` and `conditions` as *optional* attributes and
    V4 declares neither on any node, so this rule has nothing to compare and
    reports nothing. It is registered rather than omitted so the rule set
    stays the union of ONT-000..ONT-013, and it starts working on its own the
    moment constraints are populated.
    """

    rule_id = "ONT-002"
    title = "Hierarchical Constraint Inheritance"
    severity = Severity.WARNING
    check_type = CheckType.STATIC

    @staticmethod
    def _constraints(node: OntologyNode) -> Set[str]:
        values: Set[str] = set()
        for name in CONSTRAINT_ATTRIBUTES:
            values.update(node.attr(name))
        return values

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        constrained = {
            n.id: self._constraints(n)
            for n in ctx.ontology.nodes.values()
            if self._constraints(n)
        }
        if not constrained:
            logger.info(
                "ONT-002 has nothing to check: no node declares any of %s",
                ", ".join(CONSTRAINT_ATTRIBUTES),
            )
            return

        for edge in ctx.ontology.edges:
            if edge.type not in VERTICAL_EDGES:
                continue
            parent = constrained.get(edge.source)
            if not parent:
                continue
            child_node = ctx.ontology.nodes.get(edge.target)
            if child_node is None:
                continue
            missing = parent - self._constraints(child_node)
            if not missing:
                continue
            yield self.finding(
                SubjectKind.NODE,
                edge.target,
                f"child does not inherit constraints from {edge.source!r}: "
                f"{', '.join(sorted(missing))}",
                evidence=f"via {edge}",
                remediation="restate the parent's constraints on the child, or relax the parent",
            )


class DecisionPlacementRule(ConformanceRule):
    """ONT-003 — a Decision Node is a component of an Activity, and only evaluates."""

    rule_id = "ONT-003"
    title = "Decision Node Finality & Placement"
    severity = Severity.ERROR
    check_type = CheckType.STATIC

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for node in ctx.nodes_of_kind("Decision Node"):
            incoming = ctx.ontology.in_edges(node.id, {"performs_check"})
            if not incoming:
                yield self.finding(
                    SubjectKind.NODE,
                    node.id,
                    "Decision Node has no incoming 'performs_check' edge, so it is not a "
                    "component of any Activity",
                    evidence=(
                        "incoming edges: "
                        + (ctx.sample([str(e) for e in ctx.ontology.in_edges(node.id)]) or "(none)")
                    ),
                    remediation="add performs_check from the Activity that owns this decision",
                )

            if node.agent_rules is None:
                continue
            acting = sorted(set(node.agent_rules.execution_actions) & NON_EVALUATIVE_ACTIONS)
            if acting:
                yield self.finding(
                    SubjectKind.NODE,
                    node.id,
                    f"Decision Node performs non-evaluative actions: {', '.join(acting)}",
                    evidence=f"execution: {', '.join(node.agent_rules.execution_actions)}",
                    remediation="move the work to an Activity; a decision may only evaluate",
                )


class TraversalOriginRule(ConformanceRule):
    """ONT-004 (proxy) — an agent may only start inside the Activity model.

    The real rule constrains an agent's runtime entry point, which no static
    pass can observe. The proxy checks the entry points the *graph* offers: a
    node with no incoming edge is somewhere a traversal could begin, so every
    such node other than the singular root must be an `Activity_Class`. The
    root is exempt — it is the sanctioned starting point, and ONT-000 already
    governs it.
    """

    rule_id = "ONT-004"
    title = "Agent Traversal Origin"
    severity = Severity.WARNING
    check_type = CheckType.STATIC_PROXY

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for node in ctx.ontology.nodes.values():
            if ctx.ontology.in_edges(node.id):
                continue
            if ROOT_TYPE in node.kinds or node.meta_class == "Ontology_Root_Class":
                continue
            if node.meta_class == "Activity_Class":
                continue
            yield self.finding(
                SubjectKind.NODE,
                node.id,
                f"{node.meta_class} node has no incoming edge, so it is a traversal entry "
                f"point outside the Activity model",
                evidence=f"kinds: {', '.join(sorted(node.kinds))}",
                remediation="attach it beneath an Activity, or route agents in via an Activity",
            )


class SystemsAbstractionRule(ConformanceRule):
    """ONT-005 — the physical enterprise is only ever touched via a Data Service."""

    rule_id = "ONT-005"
    title = "Systems Abstraction Enforcement"
    severity = Severity.ERROR
    check_type = CheckType.STATIC

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for edge in ctx.ontology.edges:
            if edge.type == "executes_via":
                target_kinds = ctx.ontology.kinds_of(edge.target)
                if target_kinds and "Data Service" not in target_kinds:
                    yield self.finding(
                        SubjectKind.EDGE,
                        edge.key,
                        f"'executes_via' targets {edge.target!r}, which is not a Data Service",
                        evidence=f"{edge.target!r} kinds: {', '.join(sorted(target_kinds))}",
                        remediation="front the entity with a Data Service and delegate through it",
                    )
            elif edge.type == "masters":
                source_kinds = ctx.ontology.kinds_of(edge.source)
                target_kinds = ctx.ontology.kinds_of(edge.target)
                if (
                    target_kinds
                    and "Abstracted Enterprise Entity" in target_kinds
                    and "Data Service" not in source_kinds
                ):
                    yield self.finding(
                        SubjectKind.EDGE,
                        edge.key,
                        f"{edge.source!r} masters an Abstracted Enterprise Entity but is not "
                        f"a Data Service",
                        evidence=f"{edge.source!r} kinds: {', '.join(sorted(source_kinds))}",
                        remediation="only a Data Service may master a physical entity",
                    )


class CrossModelSyncRule(ConformanceRule):
    """ONT-006 — every Outcome is quantified by a Measure.

    `degrades_when_empty` is the point of this rule today: V4 has no
    `Outcome_Class` instances, so the rule is vacuous and any finding it did
    produce would be reported at a reduced severity. When Outcomes land it
    starts firing at full strength with no change here.
    """

    rule_id = "ONT-006"
    title = "Cross-Model Synchronization"
    severity = Severity.ERROR
    check_type = CheckType.STATIC
    degrades_when_empty = ("Outcome_Class",)

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        outcomes = ctx.nodes_of_kind("Outcome_Class")
        if not outcomes:
            logger.info("ONT-006 is vacuous: the ontology has no Outcome_Class instances")
            return
        for node in outcomes:
            measures = [
                e for e in ctx.ontology.out_edges(node.id, {"measured_by"})
                if "Measure" in ctx.ontology.kinds_of(e.target)
            ]
            if measures:
                continue
            yield self.finding(
                SubjectKind.NODE,
                node.id,
                "Outcome has no outgoing 'measured_by' edge to a Measure",
                evidence=(
                    "outgoing: "
                    + (ctx.sample([str(e) for e in ctx.ontology.out_edges(node.id)]) or "(none)")
                ),
                remediation="add measured_by from this Outcome to a Measure in the Information model",
            )


class VerticalEncapsulationRule(ConformanceRule):
    """ONT-007 (proxy) — finish the children before stepping sideways.

    The real rule is about traversal ordering. The static proxy narrows to the
    shape that makes the violation possible at all: a node that has both
    vertical children and a horizontal exit, where one of those children can
    never complete because it declares no execution actions. Anything looser
    would flag ordinary well-formed subtrees, and an over-reporting proxy is
    worse here than one that stays quiet.
    """

    rule_id = "ONT-007"
    title = "Hierarchical Execution Encapsulation"
    severity = Severity.WARNING
    check_type = CheckType.STATIC_PROXY

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for node in ctx.ontology.nodes.values():
            children = ctx.ontology.out_edges(node.id, VERTICAL_EDGES)
            horizontal = ctx.ontology.out_edges(node.id, HORIZONTAL_EDGES)
            if not children or not horizontal:
                continue
            stuck = []
            for edge in children:
                child = ctx.ontology.nodes.get(edge.target)
                if child is None:
                    continue
                if child.agent_rules is None or not child.agent_rules.execution_actions:
                    stuck.append(child.id)
            if not stuck:
                continue
            yield self.finding(
                SubjectKind.NODE,
                node.id,
                f"node has a horizontal exit but {len(stuck)} child(ren) declare no execution, "
                f"so the subtree cannot be completed first",
                evidence=(
                    f"children without execution: {ctx.sample(stuck)}; "
                    f"horizontal: {ctx.sample([str(e) for e in horizontal])}"
                ),
                remediation="give the children executable agent_rules, or drop the horizontal edge",
            )


class BoundaryStrictnessRule(ConformanceRule):
    """ONT-008 — horizontal edges connect peers, not tiers.

    Tier comes from `attributes.type`. Nodes with no Activity tier — Decision
    Nodes, Outcomes, Information and Systems nodes — are exempt rather than
    treated as tier `None` mismatching everything: a Decision Node is a
    routing element that sits between peers, not a rung on the ladder.
    """

    rule_id = "ONT-008"
    title = "Boundary Strictness"
    severity = Severity.ERROR
    check_type = CheckType.STATIC

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for edge in ctx.ontology.edges:
            if edge.type not in {"triggers", "leads_to"}:
                continue
            source = ctx.ontology.nodes.get(edge.source)
            target = ctx.ontology.nodes.get(edge.target)
            if source is None or target is None:
                continue
            source_tier = _tier(source)
            target_tier = _tier(target)
            if source_tier is None or target_tier is None or source_tier == target_tier:
                continue
            yield self.finding(
                SubjectKind.EDGE,
                edge.key,
                f"'{edge.type}' crosses a hierarchical tier: "
                f"{source.primary_type} -> {target.primary_type}",
                evidence=f"{edge}; tiers {source_tier} -> {target_tier}",
                remediation="route the transition through the shared parent, or retier an endpoint",
            )


class DecisionDeterminismRule(ConformanceRule):
    """ONT-009 — exactly one fallback branch per decision.

    Checks the `default` branch only. Pairwise non-overlap of the remaining
    `{property, operator, value}` conditions needs a small solver over that
    DSL and is deferred to Phase 6; a decision with no default is already
    non-deterministic in the way that matters — the agent has nowhere to go.
    """

    rule_id = "ONT-009"
    title = "Decision Path Determinism"
    severity = Severity.WARNING
    check_type = CheckType.STATIC

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for node in ctx.ontology.nodes.values():
            if node.agent_rules is None:
                continue
            for index, action in enumerate(node.agent_rules.execution):
                if action.get("action") != "evaluate_decision":
                    continue
                branches = action.get("branches")
                branches = branches if isinstance(branches, list) else []
                defaults = [b for b in branches if _is_default_branch(b)]
                if len(defaults) == 1:
                    continue
                yield self.finding(
                    SubjectKind.NODE,
                    node.id,
                    f"evaluate_decision (execution[{index}]) has {len(defaults)} default "
                    f"branches, expected exactly 1",
                    evidence=(
                        f"{len(branches)} branch(es), targets: "
                        + (ctx.sample([str(b.get('target')) for b in branches if isinstance(b, dict)])
                           or "(none)")
                    ),
                    remediation=(
                        "add a single default branch so no evaluation can leave the agent "
                        "without a path"
                        if not defaults else
                        "keep exactly one default branch"
                    ),
                )


def _is_default_branch(branch: object) -> bool:
    if not isinstance(branch, dict):
        return False
    if branch.get("is_default") is True:
        return True
    condition = branch.get("condition")
    return isinstance(condition, str) and condition.strip().lower() == "default"


class TerminalReachabilityRule(ConformanceRule):
    """ONT-010 — every horizontal workflow must end at an Outcome.

    Two shapes are reported: an Activity with no horizontal exit that is not
    itself an Outcome (the workflow dead-ends instead of resting), and a
    horizontal cycle with neither an exit nor a Decision Node to break it.

    The dead-end clause fires on 39 of V4's 40 Activities, which is exactly
    the situation `degrades_when_empty` exists for. With zero `Outcome_Class`
    instances in the model there is no legal terminus to point at, so these
    are reported as warnings against an unfinished model rather than as 39
    errors. Populate the Outcomes and the same code reports errors.
    """

    rule_id = "ONT-010"
    title = "Terminal State Reachability"
    severity = Severity.ERROR
    check_type = CheckType.STATIC
    degrades_when_empty = ("Outcome_Class",)

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for node in ctx.ontology.by_meta_class("Activity_Class"):
            if ctx.ontology.out_edges(node.id, HORIZONTAL_EDGES):
                continue
            if "Outcome_Class" in node.kinds:
                continue
            yield self.finding(
                SubjectKind.NODE,
                node.id,
                "Activity has no outgoing horizontal edge, so its workflow dead-ends "
                "instead of terminating at an Outcome_Class",
                evidence=(
                    "outgoing: "
                    + (ctx.sample([str(e) for e in ctx.ontology.out_edges(node.id)]) or "(none)")
                ),
                remediation=(
                    "add a triggers/leads_to edge to the next step, or to an Outcome_Class "
                    "that terminates the workflow"
                ),
            )

        for cycle in self._unbroken_cycles(ctx):
            yield self.finding(
                SubjectKind.GRAPH,
                " -> ".join(cycle),
                "horizontal cycle has neither an exit nor a Decision Node to break it",
                evidence=f"members: {ctx.sample(cycle)}",
                remediation="add a Decision Node break or an edge out of the loop",
            )

    def _unbroken_cycles(self, ctx: RuleContext) -> List[List[str]]:
        """Cyclic components of the horizontal subgraph with no way out.

        Reachability-based rather than Tarjan: the horizontal subgraph is a
        thin slice of the ontology (9 edges of 85 in V4), and the simpler code
        is worth more here than the asymptotics.
        """
        adjacency: Dict[str, Set[str]] = {}
        for edge in ctx.ontology.edges:
            if edge.type in HORIZONTAL_EDGES and edge.target in ctx.ontology.nodes:
                adjacency.setdefault(edge.source, set()).add(edge.target)

        reach: Dict[str, Set[str]] = {}
        for start in adjacency:
            seen: Set[str] = set()
            frontier = list(adjacency[start])
            while frontier:
                current = frontier.pop()
                if current in seen:
                    continue
                seen.add(current)
                frontier.extend(adjacency.get(current, ()))
            reach[start] = seen

        components: Dict[frozenset, List[str]] = {}
        for node_id, reachable in reach.items():
            if node_id not in reachable:
                continue  # not on a cycle
            members = frozenset(
                {node_id} | {m for m in reachable if node_id in reach.get(m, set())}
            )
            components.setdefault(members, sorted(members))

        unbroken: List[List[str]] = []
        for members, ordered in components.items():
            has_exit = any(t not in members for m in members for t in adjacency.get(m, ()))
            has_decision = any(
                "Decision Node" in ctx.ontology.kinds_of(m) for m in members
            )
            if not has_exit and not has_decision:
                unbroken.append(ordered)
        return sorted(unbroken)


class FactClassificationRule(ConformanceRule):
    """ONT-011 — no Fact without a Dimension to give it context."""

    rule_id = "ONT-011"
    title = "Fact Classification Mandate"
    severity = Severity.ERROR
    check_type = CheckType.STATIC

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for node in ctx.nodes_of_kind("Fact"):
            classifiers = [
                e for e in ctx.ontology.in_edges(node.id, {"classifies"})
                if "Dimension" in ctx.ontology.kinds_of(e.source)
            ]
            if classifiers:
                continue
            yield self.finding(
                SubjectKind.NODE,
                node.id,
                "Fact has no incoming 'classifies' edge from a Dimension",
                evidence=(
                    "incoming: "
                    + (ctx.sample([str(e) for e in ctx.ontology.in_edges(node.id)]) or "(none)")
                ),
                remediation="add classifies from the Dimension that gives this Fact context",
            )


class AsyncAcknowledgmentRule(ConformanceRule):
    """ONT-012 (proxy) — a delegated call must be one the agent can wait on.

    Blocking is a runtime property. The structural precondition for it is
    checkable: the delegate reached by `executes_via` has to actually invoke
    something (`invoke_tool`) for there to be an acknowledgment to wait for,
    and the caller has to `trace_back` for the return to be recorded. Neither
    proves the agent blocks; both failing means it certainly cannot.
    """

    rule_id = "ONT-012"
    title = "System Asynchronous Acknowledgment"
    severity = Severity.WARNING
    check_type = CheckType.STATIC_PROXY

    def check(self, ctx: RuleContext) -> Iterable[ConformanceFinding]:
        for edge in ctx.ontology.edges:
            if edge.type != "executes_via":
                continue
            source = ctx.ontology.nodes.get(edge.source)
            target = ctx.ontology.nodes.get(edge.target)
            if source is None or target is None:
                continue

            problems: List[str] = []
            target_actions = target.agent_rules.execution_actions if target.agent_rules else []
            if "invoke_tool" not in target_actions:
                problems.append(
                    f"delegate {edge.target!r} has no 'invoke_tool' execution "
                    f"(has: {', '.join(target_actions) or 'nothing'})"
                )
            caller_post = source.agent_rules.postcondition_actions if source.agent_rules else []
            if "trace_back" not in caller_post:
                problems.append(
                    f"caller {edge.source!r} has no 'trace_back' postcondition "
                    f"(has: {', '.join(caller_post) or 'nothing'})"
                )
            if not problems:
                continue

            yield self.finding(
                SubjectKind.EDGE,
                edge.key,
                f"'executes_via' delegation cannot be acknowledged: {'; '.join(problems)}",
                evidence=str(edge),
                remediation=(
                    "give the delegate an invoke_tool execution and the caller a trace_back "
                    "postcondition, so the blocked traversal has something to resume on"
                ),
            )


def systemic_rules() -> List[ConformanceRule]:
    """Every ONT-* rule except ONT-013, which lives in :mod:`.schema`."""
    return [
        RootSingularityRule(),
        SipocCompletenessRule(),
        ConstraintInheritanceRule(),
        DecisionPlacementRule(),
        TraversalOriginRule(),
        SystemsAbstractionRule(),
        CrossModelSyncRule(),
        VerticalEncapsulationRule(),
        BoundaryStrictnessRule(),
        DecisionDeterminismRule(),
        TerminalReachabilityRule(),
        FactClassificationRule(),
        AsyncAcknowledgmentRule(),
    ]
