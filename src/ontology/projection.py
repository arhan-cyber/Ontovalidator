"""Project the ontology graph into claims the verification engine can check.

The engine validates flat ``(subject, relation, object)`` assertions against
document text. The ontology's unit of truth is a typed node with attributes and
an edge grammar, so something has to translate. That's this module.

Four claim kinds, each traceable back to the node or edge it came from:

===============  ==============================================================
``edge``         a relationship, e.g. "Event Management includes the process
                 Detect & Log Event"
``sipoc``        an Activity's supplier/input/output/customer attributes
``decision``     a Decision Node's branch targets and their conditions
``description``  a node's prose description
===============  ==============================================================

**Verbalization is the highest-leverage knob on grounding precision.** The
engine builds its retrieval query as ``f"{subject} {relation} {object}"``
(``SVOVerificationEngine._build_assertion_query``), so a raw edge type produces
queries like ``filter out event ? triggers Create Event`` — which retrieves
nothing useful from prose written by humans. Every edge type therefore maps to
a natural-language phrase, and node ids are cleaned of their authoring
artefacts (the trailing ``?`` on decision nodes) before they reach a query.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..models import OntologyAssertion
from .models import OntologyEdge, OntologyGraph, OntologyNode


class ClaimKind(str, Enum):
    EDGE = "edge"
    SIPOC = "sipoc"
    DECISION = "decision"
    DESCRIPTION = "description"


ALL_CLAIM_KINDS = tuple(k.value for k in ClaimKind)


# Edge type -> natural-language predicate. Covers all 22 types in the
# blueprint's grammar; an unmapped type falls back to its underscored name
# spelled out, which is worse but never silently empty.
EDGE_PHRASES: Dict[str, str] = {
    "includes_model": "includes the model",
    "governs": "governs",
    "performs": "performs",
    "has_lifecycle_phase": "has the lifecycle phase",
    "includes_process": "includes the process",
    "decomposes_into": "decomposes into",
    "has_subprocess": "has the subprocess",
    "triggers": "triggers",
    "leads_to": "leads to",
    "performs_check": "performs the check",
    "on_success": "on success proceeds to",
    "on_failure": "on failure proceeds to",
    "represents_fact": "represents the fact",
    "connects_to_info": "connects to the information",
    "qualifies": "qualifies",
    "classifies": "classifies",
    "contains": "contains",
    "measured_by": "is measured by",
    "quantifies": "quantifies",
    "constrains": "constrains",
    "executes_via": "is executed via",
    "masters": "masters",
}

# SIPOC attribute -> predicate. `process` is deliberately excluded: it almost
# always restates the node's own name, so it yields a tautological claim.
SIPOC_PHRASES: Dict[str, str] = {
    "supplier": "is supplied by",
    "input": "takes as input",
    "output": "produces the output",
    "customer": "delivers to",
}

_OPERATOR_PHRASES = {
    "==": "equals",
    "!=": "does not equal",
    ">": "is greater than",
    ">=": "is at least",
    "<": "is less than",
    "<=": "is at most",
    "exists": "is present",
    "in": "is one of",
    "not_in": "is not one of",
}


def verbalize_edge(edge_type: str) -> str:
    phrase = EDGE_PHRASES.get(edge_type)
    if phrase:
        return phrase
    return edge_type.replace("_", " ").strip() or edge_type


def clean_node_label(node_id: str) -> str:
    """Strip authoring artefacts from a node id so it reads as prose.

    Decision nodes are named as questions (``"filter out event ?"``,
    ``"reason ?"``). The trailing marker is punctuation in a retrieval query
    and actively hurts lexical overlap, so it goes.
    """
    label = re.sub(r"\s*\?\s*$", "", str(node_id)).strip()
    return label or str(node_id)


def _verbalize_condition(condition: Any) -> str:
    """Render an agent-rules condition object as a readable clause."""
    if condition is None:
        return ""
    if isinstance(condition, str):
        return "by default" if condition == "default" else condition
    if isinstance(condition, dict):
        for junction in ("AND", "OR"):
            if junction in condition and isinstance(condition[junction], list):
                parts = [_verbalize_condition(c) for c in condition[junction]]
                parts = [p for p in parts if p]
                return f" {junction.lower()} ".join(parts)
        prop = condition.get("property")
        if prop is not None:
            # Trim the payload./context. prefix; it's plumbing, not content.
            prop_text = str(prop).split(".", 1)[-1].replace("_", " ")
            operator = _OPERATOR_PHRASES.get(str(condition.get("operator")), str(condition.get("operator", "")))
            value = condition.get("value")
            if str(condition.get("operator")) == "exists":
                return f"{prop_text} {operator}".strip()
            return f"{prop_text} {operator} {value}".strip()
    return str(condition)


@dataclass(frozen=True)
class ClaimProvenance:
    """Where a claim came from, so a verdict can be traced back to the model."""

    kind: ClaimKind
    node_id: Optional[str] = None
    edge_key: Optional[str] = None
    attribute: Optional[str] = None
    edge_type: Optional[str] = None
    original_label: Optional[str] = None
    condition: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "node_id": self.node_id,
            "edge_key": self.edge_key,
            "attribute": self.attribute,
            "edge_type": self.edge_type,
            "original_label": self.original_label,
            "condition": self.condition,
        }


@dataclass(frozen=True)
class ProjectedClaim:
    """An `OntologyAssertion` plus the ontology element it was derived from.

    Kept as a wrapper rather than as extra fields on `OntologyAssertion` so the
    engine's existing contract is untouched.
    """

    assertion: OntologyAssertion
    provenance: ClaimProvenance

    @property
    def assertion_id(self) -> str:
        return self.assertion.assertion_id

    @property
    def query(self) -> str:
        """The text the engine will retrieve on. Useful for eyeballing quality."""
        a = self.assertion
        return f"{a.subject} {a.relation} {a.object}".strip()


def _assertion(
    assertion_id: str,
    subject: str,
    relation: str,
    obj: str,
    kind: ClaimKind,
    provenance: ClaimProvenance,
) -> ProjectedClaim:
    return ProjectedClaim(
        assertion=OntologyAssertion(
            assertion_id=assertion_id,
            subject=subject,
            relation=relation,
            object=obj,
            polarity="must_hold",
            # Carries the claim kind through to the verdict, so a report can
            # group by it without re-deriving from the id.
            rule_type=kind.value,
        ),
        provenance=provenance,
    )


def project_edges(graph: OntologyGraph) -> List[ProjectedClaim]:
    claims: List[ProjectedClaim] = []
    for edge in graph.edges:
        claims.append(_assertion(
            assertion_id=f"edge:{edge.key}",
            subject=clean_node_label(edge.source),
            relation=verbalize_edge(edge.type),
            obj=clean_node_label(edge.target),
            kind=ClaimKind.EDGE,
            provenance=ClaimProvenance(
                kind=ClaimKind.EDGE,
                edge_key=edge.key,
                edge_type=edge.type,
                original_label=edge.original_label,
            ),
        ))
    return claims


def project_sipoc(graph: OntologyGraph) -> List[ProjectedClaim]:
    claims: List[ProjectedClaim] = []
    for node in graph.nodes.values():
        if node.meta_class != "Activity_Class":
            continue
        for attribute, phrase in SIPOC_PHRASES.items():
            # node.attr() strips the ["null"] sentinel, so unpopulated SIPOC
            # fields produce no claim rather than a claim about "null".
            for index, value in enumerate(node.attr(attribute)):
                claims.append(_assertion(
                    assertion_id=f"sipoc:{node.id}|{attribute}|{index}",
                    subject=clean_node_label(node.id),
                    relation=phrase,
                    obj=clean_node_label(value),
                    kind=ClaimKind.SIPOC,
                    provenance=ClaimProvenance(
                        kind=ClaimKind.SIPOC, node_id=node.id, attribute=attribute
                    ),
                ))
    return claims


def project_decisions(graph: OntologyGraph) -> List[ProjectedClaim]:
    claims: List[ProjectedClaim] = []
    for node in graph.nodes.values():
        if node.agent_rules is None:
            continue
        for action in node.agent_rules.execution:
            if action.get("action") != "evaluate_decision":
                continue
            branches = action.get("branches")
            if not isinstance(branches, list):
                continue
            for index, branch in enumerate(branches):
                if not isinstance(branch, dict):
                    continue
                target = branch.get("target")
                if not target:
                    continue
                if str(target) not in graph.nodes:
                    # A branch pointing at something that isn't a node (V4 has
                    # one: `is major incident ?` targets the action name
                    # `trace_back`) can't be grounded in a document, because
                    # there is no ontology element for the document to agree
                    # with. Conformance reports it; grounding skips it.
                    continue
                condition = _verbalize_condition(branch.get("condition"))
                claims.append(_assertion(
                    assertion_id=f"decision:{node.id}|{index}",
                    subject=clean_node_label(node.id),
                    # The condition stays in provenance rather than the
                    # relation. It reads as agent plumbing
                    # (`payload.arrival_delta_mins >= 30`), so folding it into
                    # the retrieval query adds noise tokens that no
                    # human-written process manual will ever match.
                    relation="routes to",
                    obj=clean_node_label(str(target)),
                    kind=ClaimKind.DECISION,
                    provenance=ClaimProvenance(
                        kind=ClaimKind.DECISION, node_id=node.id, condition=condition or None
                    ),
                ))
    return claims


def project_descriptions(graph: OntologyGraph) -> List[ProjectedClaim]:
    claims: List[ProjectedClaim] = []
    for node in graph.nodes.values():
        description = (node.description or "").strip()
        if not description:
            continue
        # "Decision node: Should this event be filtered out as noise?" — the
        # prefix is authoring metadata, not something a process manual says.
        description = re.sub(r"^Decision node:\s*", "", description)
        claims.append(_assertion(
            assertion_id=f"desc:{node.id}",
            subject=clean_node_label(node.id),
            relation="is described as",
            obj=description,
            kind=ClaimKind.DESCRIPTION,
            provenance=ClaimProvenance(kind=ClaimKind.DESCRIPTION, node_id=node.id),
        ))
    return claims


_PROJECTORS = {
    ClaimKind.EDGE: project_edges,
    ClaimKind.SIPOC: project_sipoc,
    ClaimKind.DECISION: project_decisions,
    ClaimKind.DESCRIPTION: project_descriptions,
}


def project_ontology(
    graph: OntologyGraph,
    claim_kinds: Optional[Sequence[str]] = None,
) -> List[ProjectedClaim]:
    """Project the graph into claims of the requested kinds.

    `claim_kinds` defaults to all four; pass a subset (matching the
    `ONTO_ONTOLOGY_CLAIM_KINDS` config) to trade coverage for runtime.
    Unknown kind names raise rather than being silently dropped — a typo in
    config that quietly halves the validated surface is a bad failure mode.
    """
    if claim_kinds is None:
        selected = list(ClaimKind)
    else:
        selected = []
        for name in claim_kinds:
            try:
                selected.append(ClaimKind(str(name).strip()))
            except ValueError:
                raise ValueError(
                    f"unknown claim kind {name!r}; expected any of {ALL_CLAIM_KINDS}"
                ) from None

    claims: List[ProjectedClaim] = []
    for kind in selected:
        claims.extend(_PROJECTORS[kind](graph))

    _assert_unique_ids(claims)
    return claims


def _assert_unique_ids(claims: Iterable[ProjectedClaim]) -> None:
    """Guard the assertion_id uniqueness the verdict cache depends on.

    Verdicts are cached and stored keyed on `assertion_id`; a collision would
    make two different claims silently share one verdict.
    """
    seen: Dict[str, int] = {}
    for claim in claims:
        seen[claim.assertion_id] = seen.get(claim.assertion_id, 0) + 1
    duplicates = sorted(k for k, v in seen.items() if v > 1)
    if duplicates:
        raise ValueError(f"projected claims have duplicate assertion_ids: {duplicates[:10]}")


def claims_to_assertions(claims: Iterable[ProjectedClaim]) -> List[OntologyAssertion]:
    return [c.assertion for c in claims]


def provenance_index(claims: Iterable[ProjectedClaim]) -> Dict[str, ClaimProvenance]:
    return {c.assertion_id: c.provenance for c in claims}
