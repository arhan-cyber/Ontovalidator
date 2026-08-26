"""Loader must survive non-conforming input and normalize two file conventions.

A loader that rejects malformed input would make the validator unable to
validate anything worth validating - every defect the conformance engine
reports has to survive loading first. The two conventions (the ["null"]
sentinel and the dual meta_class/attributes.type kind vocabulary) are tested
here because getting either wrong silently changes every downstream count.
"""

import json

import pytest

from src.ontology.loader import (
    OntologyInputError,
    load_metamodel,
    load_ontology,
    merge_systemic_rules,
)
from src.ontology.models import normalize_attr_list


# ---------------------------------------------------------------------------
# The ["null"] sentinel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    (["null"], []),
    (["NULL"], []),
    ([], []),
    (None, []),
    (["a", "null", "b"], ["a", "b"]),
    ("bare string", ["bare string"]),
    ([" padded "], ["padded"]),
    ([None, "x"], ["x"]),
])
def test_null_sentinel_is_stripped(raw, expected):
    assert normalize_attr_list(raw) == expected


def test_sentinel_distinguishes_absent_key_from_empty_value(tmp_path):
    """ONT-001 turns on this distinction.

    An Activity declaring `"input": ["null"]` has the key but no value. The
    meta-class check asks "is the key present" (yes); ONT-001 asks "is there a
    real value" (no). Collapsing the two makes ONT-001 pass on every Activity.
    """
    graph = _write_ontology(tmp_path, classes=[{
        "id": "A",
        "meta_class": "Activity_Class",
        "attributes": {"type": ["Process Activity"], "input": ["null"]},
    }])
    node = graph.nodes["A"]
    assert node.has_attr_key("input") is True
    assert node.attr("input") == []
    assert node.has_attr_key("output") is False


# ---------------------------------------------------------------------------
# Kind-set resolution
# ---------------------------------------------------------------------------


def test_kinds_union_both_vocabularies(tmp_path):
    """The edge grammar names nodes by meta-class AND by attribute type."""
    graph = _write_ontology(tmp_path, classes=[{
        "id": "A",
        "meta_class": "Activity_Class",
        "attributes": {"type": ["Domain Activity"]},
    }])
    assert graph.nodes["A"].kinds == {"Activity_Class", "Domain Activity"}
    assert graph.kinds_of("A") == {"Activity_Class", "Domain Activity"}
    assert graph.kinds_of("nonexistent") == set()


def test_has_instances_of_checks_both_vocabularies(tmp_path):
    graph = _write_ontology(tmp_path, classes=[{
        "id": "A", "meta_class": "Activity_Class", "attributes": {"type": ["Domain Activity"]},
    }])
    assert graph.has_instances_of("Activity_Class")
    assert graph.has_instances_of("Domain Activity")
    assert not graph.has_instances_of("Outcome_Class")


# ---------------------------------------------------------------------------
# Leniency: defects must survive loading
# ---------------------------------------------------------------------------


def test_malformed_agent_rules_survive_loading(tmp_path):
    graph = _write_ontology(tmp_path, classes=[
        {"id": "A", "meta_class": "Activity_Class", "agent_rules": {
            "precondition": {"conditions": [], "on_fail": None},
            "execution": [{"action": "not_a_real_action"}],
        }},
        {"id": "B", "meta_class": "Activity_Class", "agent_rules": "not a dict"},
    ])
    assert graph.nodes["A"].agent_rules.on_fail is None
    assert graph.nodes["A"].agent_rules.execution_actions == ["not_a_real_action"]
    assert graph.nodes["B"].agent_rules is None


def test_on_fail_accepts_list_form(tmp_path):
    graph = _write_ontology(tmp_path, classes=[
        {"id": "A", "meta_class": "Activity_Class",
         "agent_rules": {"precondition": {"on_fail": ["block"]}}},
    ])
    assert graph.nodes["A"].agent_rules.on_fail == "block"


def test_illegal_edges_survive_loading(tmp_path):
    graph = _write_ontology(
        tmp_path,
        classes=[{"id": "A", "meta_class": "Activity_Class"}],
        relationships=[{"source": "A", "target": "ghost", "type": "triggers"}],
    )
    assert len(graph.edges) == 1
    assert graph.edges[0].target == "ghost"
    assert "ghost" not in graph.nodes


def test_incomplete_relationship_is_skipped(tmp_path):
    graph = _write_ontology(
        tmp_path,
        classes=[{"id": "A", "meta_class": "Activity_Class"}],
        relationships=[{"source": "A", "type": "triggers"}, {"source": "A", "target": "A", "type": "triggers"}],
    )
    assert len(graph.edges) == 1


def test_duplicate_ids_keep_graph_loadable(tmp_path):
    graph = _write_ontology(tmp_path, classes=[
        {"id": "A", "meta_class": "Activity_Class", "description": "first"},
        {"id": "A", "meta_class": "Activity_Class", "description": "second"},
    ])
    assert graph.nodes["A"].description == "second"


# ---------------------------------------------------------------------------
# Missing inputs
# ---------------------------------------------------------------------------


def test_missing_file_names_the_env_var(tmp_path):
    """Both input dirs are gitignored, so a fresh clone hits this path."""
    with pytest.raises(OntologyInputError) as exc:
        load_ontology(str(tmp_path / "absent.json"))
    assert "ONTO_ONTOLOGY_PATH" in str(exc.value)

    with pytest.raises(OntologyInputError) as exc:
        load_metamodel(str(tmp_path / "absent.json"))
    assert "ONTO_METAMODEL_PATH" in str(exc.value)


def test_invalid_json_is_reported_clearly(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(OntologyInputError) as exc:
        load_ontology(str(path))
    assert "not valid JSON" in str(exc.value)


# ---------------------------------------------------------------------------
# Meta-model parsing
# ---------------------------------------------------------------------------


def test_attribute_specs_distinguish_enum_from_prose(tmp_path):
    path = tmp_path / "mm.json"
    path.write_text(json.dumps({"Enterprise_Ontology_Meta_Model_Blueprint": {
        "meta_classes": {"Activity_Class": {"mandatory_attributes": {
            "type": ["Core Activity", "Domain Activity"],
            "supplier": "Array of strings or ['null']",
        }}},
    }}), encoding="utf-8")
    mm = load_metamodel(str(path))
    spec = mm.meta_classes["Activity_Class"]
    assert spec.mandatory_attributes["type"].is_enumerated
    assert spec.mandatory_attributes["type"].allowed_values == {"Core Activity", "Domain Activity"}
    assert not spec.mandatory_attributes["supplier"].is_enumerated
    assert spec.type_values == {"Core Activity", "Domain Activity"}


def test_actor_class_list_form_optional_rules(tmp_path):
    """Actor_Class uses a list where every other class uses a mapping."""
    path = tmp_path / "mm.json"
    path.write_text(json.dumps({"Enterprise_Ontology_Meta_Model_Blueprint": {
        "meta_classes": {"Actor_Class": {"optional_rules": ["role_hierarchy", "permissions"]}},
    }}), encoding="utf-8")
    mm = load_metamodel(str(path))
    assert set(mm.meta_classes["Actor_Class"].optional_rules) == {"role_hierarchy", "permissions"}


def test_execution_action_vocabulary_parsed_from_prose(tmp_path):
    """The blueprint hides the action vocabulary inside an `(e.g., ...)` clause."""
    path = tmp_path / "mm.json"
    path.write_text(json.dumps({"Enterprise_Ontology_Meta_Model_Blueprint": {
        "global_schemas": {"Agent_Rules_Schema": {"structure": {
            "precondition": {"on_fail": ["skip", "block"]},
            "execution": "Array of action objects (e.g., traverse_dfs, invoke_tool, query_graph)",
            "postcondition": "Array of action objects (e.g., trace_back)",
        }}},
    }}), encoding="utf-8")
    schema = load_metamodel(str(path)).agent_rules_schema
    assert schema.on_fail_allowed == {"skip", "block"}
    assert schema.execution_actions == {"traverse_dfs", "invoke_tool", "query_graph"}
    assert schema.postcondition_actions == {"trace_back"}


def test_unparseable_execution_prose_falls_back(tmp_path):
    """A reworded description must not silently empty the vocabulary."""
    path = tmp_path / "mm.json"
    path.write_text(json.dumps({"Enterprise_Ontology_Meta_Model_Blueprint": {
        "global_schemas": {"Agent_Rules_Schema": {"structure": {
            "execution": "An array of actions, described elsewhere.",
        }}},
    }}), encoding="utf-8")
    schema = load_metamodel(str(path)).agent_rules_schema
    assert "traverse_dfs" in schema.execution_actions


def test_duplicate_edge_rules_widen_rather_than_replace(tmp_path):
    path = tmp_path / "mm.json"
    path.write_text(json.dumps({"Enterprise_Ontology_Meta_Model_Blueprint": {
        "allowed_relationships": {"edges": [
            {"type": "triggers", "valid_from": ["A"], "valid_to": ["B"]},
            {"type": "triggers", "valid_from": ["C"], "valid_to": ["D"]},
        ]},
    }}), encoding="utf-8")
    rule = load_metamodel(str(path)).edge_rules["triggers"]
    assert rule.valid_from == {"A", "C"}
    assert rule.valid_to == {"B", "D"}


# ---------------------------------------------------------------------------
# Rule merge (decision D3)
# ---------------------------------------------------------------------------


def test_merge_records_each_rules_origin(tmp_path):
    mm_path = tmp_path / "mm.json"
    mm_path.write_text(json.dumps({"Enterprise_Ontology_Meta_Model_Blueprint": {
        "systemic_rules": [
            {"rule_id": "ONT-000", "description": "shared", "logic": "x"},
            {"rule_id": "ONT-013", "description": "metamodel only", "logic": "y"},
        ],
    }}), encoding="utf-8")
    graph = _write_ontology(tmp_path, classes=[], systemic_rules=[
        {"rule_id": "ONT-000", "description": "shared", "logic": "x"},
        {"rule_id": "ONT-007", "description": "ontology only", "logic": "z"},
    ])
    merged = merge_systemic_rules(load_metamodel(str(mm_path)), graph)
    assert set(merged) == {"ONT-000", "ONT-007", "ONT-013"}
    assert merged["ONT-000"].sources == frozenset({"metamodel", "ontology"})
    assert merged["ONT-013"].sources == frozenset({"metamodel"})
    assert merged["ONT-007"].sources == frozenset({"ontology"})


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _write_ontology(tmp_path, classes, relationships=None, systemic_rules=None):
    path = tmp_path / f"ont_{len(list(tmp_path.iterdir()))}.json"
    path.write_text(json.dumps({"Ontology": {
        "version": "test",
        "classes": classes,
        "relationships": relationships or [],
        "systemic_rules": systemic_rules or [],
    }}), encoding="utf-8")
    return load_ontology(str(path))
