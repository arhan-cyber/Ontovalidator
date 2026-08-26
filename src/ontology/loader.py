"""Parse the meta-model and ontology JSON files into typed models.

The loader is deliberately lenient about *structure* and strict about
*locating* files. A malformed `agent_rules` block or an illegal edge must
survive loading so the conformance engine can report it — a loader that
rejects non-conforming input would make the validator unable to validate
anything worth validating. What the loader does refuse is a missing or
unreadable file, and it says so in terms of the env var to set, because both
input directories are gitignored and a fresh clone has neither.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Set

from .models import (
    AgentRules,
    AgentRulesSchema,
    AttributeSpec,
    EdgeRule,
    MetaClassSpec,
    MetaModel,
    OntologyEdge,
    OntologyGraph,
    OntologyNode,
    SystemicRuleSpec,
    normalize_attr_list,
)

logger = logging.getLogger(__name__)

DEFAULT_METAMODEL_PATH = "Ontology n metamodel/Final_Ontology_meta_model.json"
DEFAULT_ONTOLOGY_PATH = "Ontology n metamodel/Ontology_V4_description.json"

# Top-level wrapper keys the two files use.
_METAMODEL_ROOT_KEY = "Enterprise_Ontology_Meta_Model_Blueprint"
_ONTOLOGY_ROOT_KEY = "Ontology"

# Fallback action vocabulary, used only if the blueprint's prose description
# can't be parsed. Kept in sync with Agent_Rules_Schema.structure.execution.
_FALLBACK_EXECUTION_ACTIONS = {"traverse_dfs", "invoke_tool", "query_graph", "set_payload"}
_FALLBACK_POSTCONDITION_ACTIONS = {"trace_back"}


class OntologyInputError(FileNotFoundError):
    """A required input file is missing or unreadable."""


def _read_json(path: str, what: str, env_var: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise OntologyInputError(
            f"{what} not found at {path!r}. These inputs are not versioned "
            f"(see .gitignore) — supply them and set {env_var} to their location."
        )
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise OntologyInputError(f"{what} at {path!r} is not valid JSON: {exc}") from exc


def _unwrap(payload: Dict[str, Any], expected_key: str) -> Dict[str, Any]:
    """Return the single wrapper object, tolerating its absence."""
    if expected_key in payload:
        return payload[expected_key]
    # Some exports drop the wrapper; accept a lone top-level object.
    if len(payload) == 1:
        only = next(iter(payload.values()))
        if isinstance(only, dict):
            return only
    return payload


def _parse_actions_from_prose(text: Any, fallback: Set[str]) -> Set[str]:
    """Pull an action vocabulary out of an `(e.g., a, b, c)` description.

    The blueprint declares `execution` as prose rather than as a list, so the
    permitted action names are only available embedded in that sentence.
    Parsing keeps the blueprint authoritative; the fallback keeps a reworded
    description from silently emptying the vocabulary.
    """
    if not isinstance(text, str):
        return set(fallback)
    match = re.search(r"e\.g\.,?\s*([^)]*)\)", text)
    if not match:
        return set(fallback)
    actions = {part.strip() for part in match.group(1).split(",")}
    actions = {a for a in actions if a and re.fullmatch(r"[a-z_][a-z0-9_]*", a)}
    return actions or set(fallback)


def _vocabulary_is_open(value: Any) -> bool:
    """Whether a declared vocabulary is exemplary rather than exhaustive.

    A JSON list is a closed enumeration. Prose is open when it hedges with
    "e.g." / "such as" / "including" — the blueprint's `execution` field does
    exactly that, so the four action names it gives are examples, not the
    complete set. Prose with no hedge is treated as closed.
    """
    if isinstance(value, list):
        return False
    if not isinstance(value, str):
        return True
    return bool(re.search(r"\b(?:e\.g\.|such as|including|for example)", value, re.IGNORECASE))


def _parse_attribute_specs(raw: Any) -> Dict[str, AttributeSpec]:
    specs: Dict[str, AttributeSpec] = {}
    if not isinstance(raw, dict):
        return specs
    for name, value in raw.items():
        if isinstance(value, list):
            # A list is an enumeration of permitted values.
            specs[name] = AttributeSpec(name=name, allowed_values={str(v) for v in value})
        else:
            # A string is prose: the key is required, its value unconstrained.
            specs[name] = AttributeSpec(name=name, description=str(value))
    return specs


def _as_dict(value: Any) -> Dict[str, Any]:
    """Normalize a rules block that may be a dict or a bare list of names.

    `Actor_Class.optional_rules` is `["role_hierarchy", "permissions"]` while
    every other class uses a mapping.
    """
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return {str(item): None for item in value}
    return {}


def _parse_agent_rules_schema(raw: Any) -> AgentRulesSchema:
    schema = AgentRulesSchema(raw=raw if isinstance(raw, dict) else {})
    structure = (schema.raw or {}).get("structure")
    if not isinstance(structure, dict):
        return schema

    schema.required_sections = set(structure.keys())

    precondition = structure.get("precondition")
    if isinstance(precondition, dict):
        on_fail = precondition.get("on_fail")
        if isinstance(on_fail, list):
            schema.on_fail_allowed = {str(v) for v in on_fail}
        elif isinstance(on_fail, str):
            schema.on_fail_allowed = {on_fail}

    execution = structure.get("execution")
    postcondition = structure.get("postcondition")
    schema.execution_actions = _parse_actions_from_prose(execution, _FALLBACK_EXECUTION_ACTIONS)
    schema.postcondition_actions = _parse_actions_from_prose(
        postcondition, _FALLBACK_POSTCONDITION_ACTIONS
    )
    schema.execution_vocabulary_open = _vocabulary_is_open(execution)
    schema.postcondition_vocabulary_open = _vocabulary_is_open(postcondition)
    return schema


def _parse_systemic_rules(raw: Any, source: str) -> Dict[str, SystemicRuleSpec]:
    rules: Dict[str, SystemicRuleSpec] = {}
    if not isinstance(raw, list):
        return rules
    for item in raw:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule_id", "")).strip()
        if not rule_id:
            continue
        rules[rule_id] = SystemicRuleSpec(
            rule_id=rule_id,
            description=str(item.get("description", "")),
            logic=str(item.get("logic", "")),
            sources=frozenset({source}),
        )
    return rules


def load_metamodel(path: Optional[str] = None) -> MetaModel:
    """Load `Final_Ontology_meta_model.json` into a :class:`MetaModel`."""
    path = path or DEFAULT_METAMODEL_PATH
    blueprint = _unwrap(_read_json(path, "Meta-model", "ONTO_METAMODEL_PATH"), _METAMODEL_ROOT_KEY)

    meta_classes: Dict[str, MetaClassSpec] = {}
    for name, spec in (blueprint.get("meta_classes") or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        meta_classes[name] = MetaClassSpec(
            name=name,
            description=str(spec.get("description", "")),
            mandatory_attributes=_parse_attribute_specs(spec.get("mandatory_attributes")),
            mandatory_rules=_as_dict(spec.get("mandatory_rules")),
            optional_rules=_as_dict(spec.get("optional_rules")),
            raw=spec,
        )

    edge_rules: Dict[str, EdgeRule] = {}
    for edge in ((blueprint.get("allowed_relationships") or {}).get("edges") or []):
        if not isinstance(edge, dict) or "type" not in edge:
            continue
        edge_type = str(edge["type"])
        incoming = EdgeRule(
            type=edge_type,
            valid_from={str(v) for v in (edge.get("valid_from") or [])},
            valid_to={str(v) for v in (edge.get("valid_to") or [])},
        )
        if edge_type in edge_rules:
            # Duplicate declarations widen rather than replace, so neither
            # half of a split grammar row is silently lost.
            existing = edge_rules[edge_type]
            incoming = EdgeRule(
                type=edge_type,
                valid_from=existing.valid_from | incoming.valid_from,
                valid_to=existing.valid_to | incoming.valid_to,
            )
        edge_rules[edge_type] = incoming

    agent_schema_raw = (blueprint.get("global_schemas") or {}).get("Agent_Rules_Schema")

    return MetaModel(
        version=str(blueprint.get("version", "")),
        description=str(blueprint.get("description", "")),
        meta_classes=meta_classes,
        edge_rules=edge_rules,
        systemic_rules=_parse_systemic_rules(blueprint.get("systemic_rules"), "metamodel"),
        agent_rules_schema=_parse_agent_rules_schema(agent_schema_raw),
        source_path=path,
    )


def _parse_agent_rules(raw: Any) -> Optional[AgentRules]:
    if not isinstance(raw, dict):
        return None

    precondition = raw.get("precondition")
    conditions: List[Dict[str, Any]] = []
    on_fail: Optional[str] = None
    if isinstance(precondition, dict):
        raw_conditions = precondition.get("conditions")
        if isinstance(raw_conditions, list):
            conditions = [c for c in raw_conditions if isinstance(c, dict)]
        value = precondition.get("on_fail")
        # `on_fail` is sometimes a single-element list rather than a string.
        if isinstance(value, list):
            on_fail = str(value[0]) if value else None
        elif value is not None:
            on_fail = str(value)

    delegation = raw.get("delegation")
    role = None
    if isinstance(delegation, dict):
        raw_role = delegation.get("role")
        role = str(raw_role) if raw_role is not None else None

    def _actions(value: Any) -> List[Dict[str, Any]]:
        if isinstance(value, list):
            return [a for a in value if isinstance(a, dict)]
        if isinstance(value, dict):
            return [value]
        return []

    return AgentRules(
        precondition_conditions=conditions,
        on_fail=on_fail,
        delegation_role=role,
        execution=_actions(raw.get("execution")),
        postcondition=_actions(raw.get("postcondition")),
        raw=raw,
    )


def load_ontology(path: Optional[str] = None) -> OntologyGraph:
    """Load `Ontology_V4_description.json` into an :class:`OntologyGraph`."""
    path = path or DEFAULT_ONTOLOGY_PATH
    payload = _unwrap(_read_json(path, "Ontology", "ONTO_ONTOLOGY_PATH"), _ONTOLOGY_ROOT_KEY)

    nodes: Dict[str, OntologyNode] = {}
    duplicate_ids: List[str] = []
    for raw in (payload.get("classes") or []):
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("id", "")).strip()
        if not node_id:
            logger.warning("ontology class without an id, skipped: %r", raw)
            continue
        if node_id in nodes:
            # Kept, not merged: duplicate-id detection is a conformance
            # finding, and last-write-wins at least keeps the graph loadable.
            duplicate_ids.append(node_id)
        attributes = raw.get("attributes")
        nodes[node_id] = OntologyNode(
            id=node_id,
            description=str(raw.get("description", "")),
            meta_class=str(raw.get("meta_class", "")),
            attributes=attributes if isinstance(attributes, dict) else {},
            agent_rules=_parse_agent_rules(raw.get("agent_rules")),
            next_pointer=normalize_attr_list(raw.get("next_pointer")),
            raw=raw,
        )
    if duplicate_ids:
        logger.warning("duplicate ontology class ids (last wins): %s", sorted(set(duplicate_ids)))

    edges: List[OntologyEdge] = []
    for raw in (payload.get("relationships") or []):
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("source", "")).strip()
        target = str(raw.get("target", "")).strip()
        edge_type = str(raw.get("type", "")).strip()
        if not (source and target and edge_type):
            logger.warning("incomplete relationship, skipped: %r", raw)
            continue
        original = raw.get("original_label")
        edges.append(OntologyEdge(
            source=source,
            target=target,
            type=edge_type,
            original_label=str(original) if original is not None else None,
        ))

    graph = OntologyGraph(
        version=str(payload.get("version", "")),
        description=str(payload.get("description", "")),
        nodes=nodes,
        edges=edges,
        systemic_rules=_parse_systemic_rules(payload.get("systemic_rules"), "ontology"),
        source_path=path,
    )
    graph.reindex()
    return graph


def merge_systemic_rules(
    metamodel: MetaModel, ontology: OntologyGraph
) -> Dict[str, SystemicRuleSpec]:
    """Union the two files' ONT-* rule lists, recording each rule's origin.

    Decision D3: neither file is authoritative on its own. The blueprint (v2.1)
    carries ONT-000..006 plus ONT-013; the instance (v2.2) carries
    ONT-000..012. The union is the working rule set, and `sources` preserves
    which file declared what so the divergence can be reported rather than
    silently resolved.
    """
    merged: Dict[str, SystemicRuleSpec] = {}
    for rule_id in set(metamodel.systemic_rules) | set(ontology.systemic_rules):
        from_mm = metamodel.systemic_rules.get(rule_id)
        from_ont = ontology.systemic_rules.get(rule_id)
        primary = from_mm or from_ont
        merged[rule_id] = SystemicRuleSpec(
            rule_id=rule_id,
            description=primary.description,
            logic=primary.logic,
            sources=frozenset().union(
                from_mm.sources if from_mm else frozenset(),
                from_ont.sources if from_ont else frozenset(),
            ),
        )
    return dict(sorted(merged.items()))
