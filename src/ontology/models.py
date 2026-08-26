"""Typed models for the enterprise ontology and its meta-model.

Two file formats are represented here:

* the **meta-model** (`Final_Ontology_meta_model.json`) — the abstract
  blueprint: meta-classes, their mandatory attributes, the edge grammar, and
  the systemic ONT-* rules;
* the **ontology** (`Ontology_V4_description.json`) — a concrete instance:
  nodes, relationships, and its own copy of the systemic rules.

Two conventions in those files are easy to get wrong, and both are handled
here rather than in each caller:

1. ``["null"]`` is the files' sentinel for "empty" — a one-element list holding
   the *string* ``"null"``, not JSON ``null``. Code that treats it as a real
   value makes ONT-001 (SIPOC completeness) pass on every Activity, silently.
   :func:`normalize_attr_list` strips it.
2. A node has **two kinds**: its ``meta_class`` (``Activity_Class``) and its
   ``attributes.type`` (``Domain Activity``). The edge grammar's ``valid_from``
   / ``valid_to`` mix both vocabularies freely — ``performs`` is expressed in
   meta-classes, ``has_lifecycle_phase`` in attribute types. Membership must be
   tested against the union, which is what :attr:`OntologyNode.kinds` returns.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

# The string the source files use inside a list to mean "no value here".
NULL_SENTINEL = "null"


def normalize_attr_list(value: Any) -> List[str]:
    """Coerce a raw attribute value to a list of real strings.

    Drops the ``"null"`` sentinel, so ``["null"]`` becomes ``[]``. A bare
    string is wrapped; ``None`` becomes ``[]``.

    An attribute whose genuine value is the literal text "null" is
    indistinguishable from the sentinel and would be dropped. No such value
    exists in the shipped ontology, and the files offer no way to escape it.
    """
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return [str(value)]

    out: List[str] = []
    for item in items:
        if item is None:
            continue
        text = str(item).strip()
        if not text or text.lower() == NULL_SENTINEL:
            continue
        out.append(text)
    return out


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


# Ordered worst-first, for threshold comparisons.
SEVERITY_ORDER = (Severity.ERROR, Severity.WARNING, Severity.INFO)


def severity_at_least(severity: Severity, threshold: Severity) -> bool:
    """True when `severity` is at least as severe as `threshold`."""
    return SEVERITY_ORDER.index(severity) <= SEVERITY_ORDER.index(threshold)


class SubjectKind(str, Enum):
    NODE = "node"
    EDGE = "edge"
    GRAPH = "graph"


class CheckType(str, Enum):
    """Whether a rule is a real static property or a stand-in for one.

    Several ONT-* rules describe *agent runtime behaviour* (traversal order,
    blocking on an async call) which no static pass can decide. Those are
    implemented as ``STATIC_PROXY``: a necessary-but-not-sufficient structural
    check, upgradeable by the traversal simulator.
    """

    STATIC = "static"
    STATIC_PROXY = "static_proxy"
    RUNTIME = "runtime"


@dataclass(frozen=True)
class ConformanceFinding:
    """One violation of one rule by one part of the ontology."""

    rule_id: str
    severity: Severity
    subject_kind: SubjectKind
    subject_id: str
    message: str
    evidence: Optional[str] = None
    remediation: Optional[str] = None
    # Set when the rule fired at a reduced severity because the meta-class it
    # governs has no instances (see SystemicRuleSpec.degrades_when_empty).
    degraded: bool = False
    # Why it was degraded, kept separate so `evidence` stays byte-stable - the
    # conformance baseline is hash-pinned, and appending the reason to
    # `evidence` would move every degraded finding's text.
    degraded_reason: Optional[str] = None
    # Machine-readable detail for consumers that need more than prose. The
    # conflict registry builds meta-model amendment proposals from this;
    # without it, it has to regex the `remediation` string, which is a
    # contract no checker is obliged to honour.
    # `compare=False` keeps the dataclass hashable despite holding a dict.
    metadata: Optional[Dict[str, Any]] = field(default=None, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "subject_kind": self.subject_kind.value,
            "subject_id": self.subject_id,
            "message": self.message,
            "evidence": self.evidence,
            "remediation": self.remediation,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "metadata": self.metadata,
        }


# --------------------------------------------------------------------------
# Meta-model
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AttributeSpec:
    """A mandatory attribute declared on a meta-class.

    The blueprint expresses these two ways: as a list of permitted values
    (``"type": ["Enterprise Root", "Domain Root"]``) or as a prose description
    (``"supplier": "Array of strings or ['null']"``). The first constrains the
    value, the second only requires the key to be present.
    """

    name: str
    allowed_values: Optional[Set[str]] = None
    description: Optional[str] = None

    @property
    def is_enumerated(self) -> bool:
        return self.allowed_values is not None


@dataclass
class MetaClassSpec:
    name: str
    description: str = ""
    mandatory_attributes: Dict[str, AttributeSpec] = field(default_factory=dict)
    mandatory_rules: Dict[str, Any] = field(default_factory=dict)
    optional_rules: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def requires_agent_rules(self) -> bool:
        return "agent_rules" in self.mandatory_rules

    @property
    def type_values(self) -> Set[str]:
        """Permitted `attributes.type` values, i.e. this class's sub-kinds."""
        spec = self.mandatory_attributes.get("type")
        return set(spec.allowed_values) if spec and spec.allowed_values else set()


@dataclass(frozen=True)
class EdgeRule:
    """One row of the edge grammar.

    `valid_from` / `valid_to` hold a mix of meta-class names and attribute-type
    names; test them against `OntologyNode.kinds`, never against `meta_class`
    alone.
    """

    type: str
    valid_from: Set[str]
    valid_to: Set[str]


@dataclass(frozen=True)
class SystemicRuleSpec:
    """An ONT-* rule as declared in one (or both) of the source files."""

    rule_id: str
    description: str
    logic: str
    # Which file(s) declared it: {"metamodel"}, {"ontology"}, or both.
    sources: frozenset = frozenset()


@dataclass
class AgentRulesSchema:
    """The `Agent_Rules_Schema` block, i.e. the contract ONT-013 enforces.

    The blueprint states its two vocabularies in different registers, and the
    difference is load-bearing:

    * ``"on_fail": ["skip", "block"]`` is a JSON list — a **closed** set. A
      third value is unambiguously a violation.
    * ``"execution": "Array of action objects (e.g., traverse_dfs, ...)"`` is
      prose, and *e.g.* means "for example" — an **open** set. An action the
      blueprint didn't happen to list is undocumented, not illegal.

    Treating the second as closed would report V4's seven extra verbs as hard
    errors on the strength of an abbreviation. They're recorded as open here so
    the checker can say "undocumented" instead of "forbidden".
    """

    on_fail_allowed: Set[str] = field(default_factory=set)
    execution_actions: Set[str] = field(default_factory=set)
    postcondition_actions: Set[str] = field(default_factory=set)
    required_sections: Set[str] = field(default_factory=set)
    # False only when the blueprint enumerates the vocabulary as a JSON list.
    execution_vocabulary_open: bool = True
    postcondition_vocabulary_open: bool = True
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MetaModel:
    version: str = ""
    description: str = ""
    meta_classes: Dict[str, MetaClassSpec] = field(default_factory=dict)
    edge_rules: Dict[str, EdgeRule] = field(default_factory=dict)
    systemic_rules: Dict[str, SystemicRuleSpec] = field(default_factory=dict)
    agent_rules_schema: AgentRulesSchema = field(default_factory=AgentRulesSchema)
    source_path: Optional[str] = None

    def type_to_meta_class(self) -> Dict[str, str]:
        """Reverse index from an `attributes.type` value to its meta-class."""
        out: Dict[str, str] = {}
        for name, spec in self.meta_classes.items():
            for value in spec.type_values:
                out[value] = name
        return out


# --------------------------------------------------------------------------
# Ontology instance
# --------------------------------------------------------------------------


@dataclass
class AgentRules:
    """A node's `agent_rules` block, parsed leniently.

    Structural validation is the conformance engine's job, not the loader's —
    a malformed block must survive loading so it can be *reported*. Anything
    unparseable is preserved in `raw`.
    """

    precondition_conditions: List[Dict[str, Any]] = field(default_factory=list)
    on_fail: Optional[str] = None
    delegation_role: Optional[str] = None
    execution: List[Dict[str, Any]] = field(default_factory=list)
    postcondition: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def sections(self) -> Set[str]:
        return set(self.raw.keys())

    @property
    def execution_actions(self) -> List[str]:
        return [a.get("action") for a in self.execution if isinstance(a, dict) and a.get("action")]

    @property
    def postcondition_actions(self) -> List[str]:
        return [a.get("action") for a in self.postcondition if isinstance(a, dict) and a.get("action")]

    def has_action(self, action: str) -> bool:
        return action in self.execution_actions


@dataclass
class OntologyNode:
    id: str
    description: str = ""
    meta_class: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    agent_rules: Optional[AgentRules] = None
    next_pointer: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def attr(self, name: str) -> List[str]:
        """Normalized attribute value, with the `["null"]` sentinel stripped."""
        return normalize_attr_list(self.attributes.get(name))

    def has_attr_key(self, name: str) -> bool:
        """Whether the key is present at all, regardless of its value.

        Distinct from a non-empty `attr()`: an Activity can declare
        `"input": ["null"]` and thereby satisfy "the key exists" while failing
        ONT-001's "must define input".
        """
        return name in self.attributes

    @property
    def types(self) -> List[str]:
        return self.attr("type")

    @property
    def primary_type(self) -> Optional[str]:
        types = self.types
        return types[0] if types else None

    @property
    def kinds(self) -> Set[str]:
        """Every name this node answers to in the edge grammar.

        The union of its meta-class and its attribute types — see the module
        docstring for why testing `meta_class` alone gives wrong answers in
        both directions.
        """
        kinds = set(self.types)
        if self.meta_class:
            kinds.add(self.meta_class)
        return kinds


@dataclass(frozen=True)
class OntologyEdge:
    source: str
    target: str
    type: str
    original_label: Optional[str] = None

    @property
    def key(self) -> str:
        """Stable identifier, used as a conflict-registry subject_id."""
        return f"{self.source}|{self.type}|{self.target}"

    def __str__(self) -> str:
        return f"{self.source} --{self.type}--> {self.target}"


@dataclass
class OntologyGraph:
    version: str = ""
    description: str = ""
    nodes: Dict[str, OntologyNode] = field(default_factory=dict)
    edges: List[OntologyEdge] = field(default_factory=list)
    systemic_rules: Dict[str, SystemicRuleSpec] = field(default_factory=dict)
    source_path: Optional[str] = None

    _out: Dict[str, List[OntologyEdge]] = field(default_factory=dict, repr=False)
    _in: Dict[str, List[OntologyEdge]] = field(default_factory=dict, repr=False)

    def reindex(self) -> None:
        self._out = {}
        self._in = {}
        for edge in self.edges:
            self._out.setdefault(edge.source, []).append(edge)
            self._in.setdefault(edge.target, []).append(edge)

    def out_edges(self, node_id: str, types: Optional[Set[str]] = None) -> List[OntologyEdge]:
        edges = self._out.get(node_id, [])
        return [e for e in edges if e.type in types] if types else list(edges)

    def in_edges(self, node_id: str, types: Optional[Set[str]] = None) -> List[OntologyEdge]:
        edges = self._in.get(node_id, [])
        return [e for e in edges if e.type in types] if types else list(edges)

    def by_meta_class(self, meta_class: str) -> List[OntologyNode]:
        return [n for n in self.nodes.values() if n.meta_class == meta_class]

    def by_type(self, type_value: str) -> List[OntologyNode]:
        return [n for n in self.nodes.values() if type_value in n.types]

    def kinds_of(self, node_id: str) -> Set[str]:
        """Kind set of a node, or empty if the id is dangling."""
        node = self.nodes.get(node_id)
        return node.kinds if node else set()

    def has_instances_of(self, kind: str) -> bool:
        """Whether any node answers to `kind` (meta-class or attribute type)."""
        return any(kind in n.kinds for n in self.nodes.values())
