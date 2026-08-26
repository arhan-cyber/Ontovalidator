"""Static conformance checks, each against a purpose-built minimal ontology.

Every test here builds the smallest graph that can express one violation and
asserts that exactly the intended rule fires. That is deliberately *not* how
the golden baseline works: V4 exercises the checkers against incidental,
overlapping defects, which proves the engine reproduces a known result but not
that any individual rule is looking at the right thing. A rule that silently
never fires passes a golden test as long as V4 happens to be clean for it.
"""

import json
import os

import pytest

from src.ontology import load_metamodel, load_ontology
from src.ontology.conformance import (
    ConformanceConfig,
    ConformanceRule,
    RuleContext,
    Severity,
    SubjectKind,
    SystemicRuleRegistry,
    build_registry,
    run_conformance,
)
from src.ontology.models import CheckType


# --------------------------------------------------------------------------
# Fixture construction
# --------------------------------------------------------------------------

# A faithfully-shaped but trimmed blueprint: same wrapper, same prose-encoded
# action vocabulary, same mixed meta-class/type edge grammar. Shape fidelity
# matters more than coverage — the loader's quirks are what the checkers see.
METAMODEL_PAYLOAD = {
    "Enterprise_Ontology_Meta_Model_Blueprint": {
        "version": "2.1-test",
        "description": "Trimmed blueprint for conformance tests.",
        "global_schemas": {
            "Agent_Rules_Schema": {
                "structure": {
                    "precondition": {
                        "conditions": "Array of logical evaluation objects",
                        "on_fail": ["skip", "block"],
                    },
                    "delegation": {"role": "String (Agent Persona) or null"},
                    "execution": (
                        "Array of action objects (e.g., traverse_dfs, invoke_tool, "
                        "query_graph, set_payload)"
                    ),
                    "postcondition": "Array of action objects (e.g., trace_back)",
                }
            }
        },
        "meta_classes": {
            "Ontology_Root_Class": {
                "mandatory_attributes": {"type": ["Enterprise Root", "Domain Root"]},
                "mandatory_rules": {"agent_rules": "$ref: Agent_Rules_Schema"},
            },
            "Actor_Class": {
                "mandatory_attributes": {"type": ["Human Actor", "System Actor"]},
            },
            "Activity_Class": {
                "mandatory_attributes": {
                    "type": [
                        "Core Activity",
                        "Domain Activity",
                        "Process Activity",
                        "Sub_Process Activity",
                    ],
                    "supplier": "Array of strings or ['null']",
                    "input": "Array of strings or ['null']",
                    "process": "Array of strings",
                    "output": "Array of strings or ['null']",
                    "customer": "Array of strings or ['null']",
                },
                "mandatory_rules": {"agent_rules": "$ref: Agent_Rules_Schema"},
            },
            "Decision_Class": {
                "mandatory_attributes": {
                    "type": ["Decision Node"],
                    "classification": ["Binary", "Multiclass", "RuleBased"],
                },
                "mandatory_rules": {"agent_rules": "$ref: Agent_Rules_Schema"},
            },
            "Outcome_Class": {
                "mandatory_attributes": {"type": ["State", "Outcome Event"]},
            },
            "Information_Class": {
                "mandatory_attributes": {
                    "type": ["Dimension", "Fact", "Measure", "Information_Abstraction"]
                },
                "mandatory_rules": {"agent_rules": "$ref: Agent_Rules_Schema"},
            },
            "Systems_Class": {
                "mandatory_attributes": {
                    "type": ["Data Service", "Abstracted Enterprise Entity", "External System"]
                },
                "mandatory_rules": {"agent_rules": "$ref: Agent_Rules_Schema"},
            },
        },
        "allowed_relationships": {
            "edges": [
                {
                    "type": "includes_model",
                    "valid_from": ["Ontology_Root_Class"],
                    "valid_to": ["Activity_Class", "Information_Class", "Systems_Class"],
                },
                {"type": "performs", "valid_from": ["Actor_Class"], "valid_to": ["Activity_Class"]},
                {
                    "type": "has_lifecycle_phase",
                    "valid_from": ["Core Activity"],
                    "valid_to": ["Domain Activity"],
                },
                {
                    "type": "has_subprocess",
                    "valid_from": ["Process Activity"],
                    "valid_to": ["Sub_Process Activity"],
                },
                {
                    "type": "decomposes_into",
                    "valid_from": ["Process Activity"],
                    "valid_to": ["Process Activity"],
                },
                {
                    "type": "triggers",
                    "valid_from": ["Process Activity", "Sub_Process Activity", "Decision Node"],
                    "valid_to": [
                        "Process Activity",
                        "Sub_Process Activity",
                        "Decision Node",
                        "Outcome_Class",
                    ],
                },
                {"type": "leads_to", "valid_from": ["Activity_Class"], "valid_to": ["Outcome_Class"]},
                {
                    "type": "performs_check",
                    "valid_from": ["Activity_Class"],
                    "valid_to": ["Decision Node"],
                },
                {"type": "classifies", "valid_from": ["Dimension"], "valid_to": ["Fact"]},
                {
                    "type": "measured_by",
                    "valid_from": ["Dimension", "Outcome_Class"],
                    "valid_to": ["Measure"],
                },
                {
                    "type": "executes_via",
                    "valid_from": ["Activity_Class"],
                    "valid_to": ["Data Service"],
                },
                {
                    "type": "masters",
                    "valid_from": ["Data Service"],
                    "valid_to": ["Abstracted Enterprise Entity"],
                },
            ]
        },
        "systemic_rules": [
            {"rule_id": "ONT-000", "description": "Root Singularity", "logic": "..."},
            {"rule_id": "ONT-013", "description": "Agent Rule Contract", "logic": "..."},
        ],
    }
}


def agent_rules(on_fail="skip", execution=None, postcondition=None, drop_sections=()):
    """A conforming `agent_rules` block, minus whatever a test wants broken."""
    block = {
        "precondition": {"conditions": [], "on_fail": on_fail},
        "delegation": {"role": None},
        "execution": execution if execution is not None else [{"action": "traverse_dfs"}],
        "postcondition": (
            postcondition if postcondition is not None else [{"action": "trace_back"}]
        ),
    }
    for section in drop_sections:
        block.pop(section, None)
    return block


def activity(node_id, type_="Process Activity", sipoc=True, **overrides):
    """An Activity carrying all five SIPOC keys.

    `sipoc=False` writes the `["null"]` sentinel rather than omitting the keys,
    which is the distinction ONT-001 turns on: present but empty.
    """
    value = ["x"] if sipoc else ["null"]
    node = {
        "id": node_id,
        "description": node_id,
        "meta_class": "Activity_Class",
        "attributes": {
            "type": [type_],
            "supplier": list(value),
            "input": list(value),
            "process": [node_id],
            "output": list(value),
            "customer": list(value),
        },
        "agent_rules": agent_rules(),
        "next_pointer": [],
    }
    node.update(overrides)
    return node


def node(node_id, meta_class, type_, **overrides):
    payload = {
        "id": node_id,
        "description": node_id,
        "meta_class": meta_class,
        "attributes": {"type": [type_]},
        "agent_rules": agent_rules(),
        "next_pointer": [],
    }
    payload.update(overrides)
    return payload


def decision(node_id, branches=None, classification="Binary", **overrides):
    execution = [{"action": "evaluate_decision", "branches": branches or [
        {"condition": {"property": "p", "operator": "==", "value": 1}, "target": "A"},
        {"condition": "default", "target": "B"},
    ]}]
    payload = node(node_id, "Decision_Class", "Decision Node")
    payload["attributes"]["classification"] = [classification]
    payload["agent_rules"] = agent_rules(execution=execution)
    payload.update(overrides)
    return payload


def edge(source, type_, target):
    return {"source": source, "target": target, "type": type_}


def build(tmp_workspace, classes, relationships=(), systemic_rules=None, name="ont"):
    """Write a synthetic ontology + meta-model and load them back.

    Round-tripping through the loader rather than constructing the dataclasses
    directly keeps the tests honest about the two file conventions — the
    `["null"]` sentinel and the meta-class/type kind split are normalised
    there, not in the checkers.
    """
    ontology_path = os.path.join(tmp_workspace, f"{name}.json")
    metamodel_path = os.path.join(tmp_workspace, f"{name}_meta.json")
    with open(ontology_path, "w", encoding="utf-8") as fh:
        json.dump({
            "Ontology": {
                "version": "test",
                "description": "synthetic",
                "classes": list(classes),
                "relationships": list(relationships),
                "systemic_rules": (
                    systemic_rules
                    if systemic_rules is not None
                    else [{"rule_id": "ONT-000", "description": "Root Singularity", "logic": "."}]
                ),
            }
        }, fh)
    with open(metamodel_path, "w", encoding="utf-8") as fh:
        json.dump(METAMODEL_PAYLOAD, fh)
    return load_ontology(ontology_path), load_metamodel(metamodel_path)


def findings_for(rule_id, ontology, metamodel, config=None):
    return [f for f in run_conformance(ontology, metamodel, config) if f.rule_id == rule_id]


ROOT = node("Enterprise", "Ontology_Root_Class", "Enterprise Root")


# --------------------------------------------------------------------------
# Registry mechanics
# --------------------------------------------------------------------------


class _AlwaysFires(ConformanceRule):
    rule_id = "TEST-FIRES"
    severity = Severity.ERROR
    degrades_when_empty = ("Outcome_Class",)

    def check(self, ctx):
        yield self.finding(SubjectKind.GRAPH, "x", "boom", evidence="because")


class _Explodes(ConformanceRule):
    rule_id = "TEST-EXPLODES"

    def check(self, ctx):
        raise RuntimeError("checker bug")


def test_registry_rejects_duplicate_rule_ids():
    registry = SystemicRuleRegistry()
    registry.register(_AlwaysFires())
    with pytest.raises(ValueError, match="duplicate rule_id"):
        registry.register(_AlwaysFires())


def test_default_registry_covers_ont_000_through_013():
    ids = set(build_registry().rule_ids())
    for n in range(14):
        assert f"ONT-{n:03d}" in ids, f"ONT-{n:03d} is not registered"


def test_every_registered_rule_declares_a_check_type():
    for rule in build_registry():
        assert isinstance(rule.check_type, CheckType)
        assert rule.check_type is not CheckType.RUNTIME, (
            f"{rule.rule_id} is registered as a runtime check but Phase 1 is static-only"
        )


def test_degradation_demotes_one_step_and_flags_the_finding(tmp_workspace):
    ontology, metamodel = build(tmp_workspace, [ROOT, activity("A")])
    registry = SystemicRuleRegistry()
    registry.register(_AlwaysFires())

    findings = registry.run(RuleContext(ontology, metamodel, ConformanceConfig()))
    assert [f.severity for f in findings] == [Severity.WARNING]
    assert findings[0].degraded is True
    assert "no Outcome_Class instances" in findings[0].evidence


def test_degradation_lifts_once_the_meta_class_is_populated(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace, [ROOT, node("Closed", "Outcome_Class", "State")]
    )
    registry = SystemicRuleRegistry()
    registry.register(_AlwaysFires())

    findings = registry.run(RuleContext(ontology, metamodel, ConformanceConfig()))
    assert [f.severity for f in findings] == [Severity.ERROR]
    assert findings[0].degraded is False


def test_a_crashing_rule_reports_rather_than_reading_as_clean(tmp_workspace):
    ontology, metamodel = build(tmp_workspace, [ROOT])
    registry = SystemicRuleRegistry()
    registry.register(_Explodes())

    findings = registry.run(RuleContext(ontology, metamodel, ConformanceConfig()))
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "failed to run" in findings[0].message


def test_config_filters_by_rule_and_by_severity(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace, [ROOT, activity("A", sipoc=False, next_pointer=["B"]), activity("B")]
    )
    only = ConformanceConfig(include_rules={"ONT-001"})
    assert {f.rule_id for f in run_conformance(ontology, metamodel, only)} == {"ONT-001"}

    without = ConformanceConfig(exclude_rules={"ONT-001"})
    assert "ONT-001" not in {f.rule_id for f in run_conformance(ontology, metamodel, without)}

    errors_only = ConformanceConfig(severity_threshold=Severity.ERROR)
    assert all(
        f.severity is Severity.ERROR for f in run_conformance(ontology, metamodel, errors_only)
    )


def test_findings_are_ordered_deterministically(tmp_workspace):
    classes = [ROOT] + [activity(f"A{i}", sipoc=False, next_pointer=["A0"]) for i in range(6)]
    ontology, metamodel = build(tmp_workspace, classes)
    first = [f.to_dict() for f in run_conformance(ontology, metamodel)]
    second = [f.to_dict() for f in run_conformance(ontology, metamodel)]
    assert first == second


# --------------------------------------------------------------------------
# Schema (meta-class attributes, enums, ONT-013)
# --------------------------------------------------------------------------


def test_unknown_meta_class_is_reported(tmp_workspace):
    stray = node("Ghost", "Imaginary_Class", "Whatever")
    ontology, metamodel = build(tmp_workspace, [ROOT, stray])
    findings = findings_for("SCHEMA-META-CLASS", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["Ghost"]


def test_missing_mandatory_attribute_is_reported(tmp_workspace):
    broken = activity("A")
    del broken["attributes"]["customer"]
    ontology, metamodel = build(tmp_workspace, [ROOT, broken])
    findings = findings_for("SCHEMA-ATTR", ontology, metamodel)
    assert len(findings) == 1
    assert "customer" in findings[0].message


def test_null_sentinel_satisfies_presence_but_not_completeness(tmp_workspace):
    """The trap: `["null"]` is a value to `has_attr_key`, nothing to `attr`."""
    hollow = activity("A", sipoc=False, next_pointer=["B"])
    ontology, metamodel = build(tmp_workspace, [ROOT, hollow, activity("B")])

    assert findings_for("SCHEMA-ATTR", ontology, metamodel) == []
    sipoc = findings_for("ONT-001", ontology, metamodel)
    assert [f.subject_id for f in sipoc] == ["A"]
    for field in ("supplier", "input", "output", "customer"):
        assert field in sipoc[0].message


def test_enumerated_attribute_out_of_range_is_reported(tmp_workspace):
    wrong = activity("A")
    wrong["attributes"]["type"] = ["Imaginary Activity"]
    ontology, metamodel = build(tmp_workspace, [ROOT, wrong])
    findings = findings_for("SCHEMA-TYPE", ontology, metamodel)
    assert len(findings) == 1
    assert "Imaginary Activity" in findings[0].message


def test_enumerated_attribute_present_but_empty_is_reported(tmp_workspace):
    hollow = activity("A")
    hollow["attributes"]["type"] = ["null"]
    ontology, metamodel = build(tmp_workspace, [ROOT, hollow])
    findings = findings_for("SCHEMA-TYPE", ontology, metamodel)
    assert len(findings) == 1
    assert "carries no value" in findings[0].message


def test_ont_013_flags_on_fail_outside_the_enumeration(tmp_workspace):
    null_fail = activity("A", agent_rules=agent_rules(on_fail=None))
    bogus_fail = activity("B", agent_rules=agent_rules(on_fail="retry"))
    ontology, metamodel = build(tmp_workspace, [ROOT, null_fail, bogus_fail, activity("C")])
    findings = findings_for("ONT-013", ontology, metamodel)
    assert {f.subject_id for f in findings} == {"A", "B"}
    assert all("on_fail" in f.message for f in findings)


def test_ont_013_flags_missing_agent_rules_sections(tmp_workspace):
    truncated = activity("A", agent_rules=agent_rules(drop_sections=("postcondition",)))
    ontology, metamodel = build(tmp_workspace, [ROOT, truncated])
    findings = findings_for("ONT-013", ontology, metamodel)
    assert len(findings) == 1
    assert "postcondition" in findings[0].message


def test_ont_013_flags_a_node_missing_agent_rules_entirely(tmp_workspace):
    bare = activity("A")
    del bare["agent_rules"]
    ontology, metamodel = build(tmp_workspace, [ROOT, bare])
    findings = findings_for("ONT-013", ontology, metamodel)
    assert len(findings) == 1
    assert "mandates agent_rules" in findings[0].message


def test_ont_013_aggregates_undocumented_actions_by_name_not_by_use(tmp_workspace):
    users = [
        activity(f"A{i}", agent_rules=agent_rules(execution=[{"action": "fill_missing_value"}]))
        for i in range(3)
    ]
    ontology, metamodel = build(tmp_workspace, [ROOT] + users)
    findings = [
        f for f in findings_for("ONT-013-VOCAB", ontology, metamodel)
        if f.subject_kind is SubjectKind.GRAPH
    ]
    assert len(findings) == 1, "one finding per undocumented verb, not per call site"
    assert findings[0].subject_id == "fill_missing_value"
    assert "used 3 time(s)" in findings[0].message


def test_ont_013_flags_undocumented_postcondition_actions(tmp_workspace):
    odd = activity("A", agent_rules=agent_rules(postcondition=[{"action": "phone_home"}]))
    ontology, metamodel = build(tmp_workspace, [ROOT, odd])
    findings = [
        f for f in findings_for("ONT-013-VOCAB", ontology, metamodel)
        if f.subject_id == "phone_home"
    ]
    assert len(findings) == 1
    assert "postcondition action" in findings[0].message


def test_undocumented_actions_are_warnings_when_the_blueprint_says_e_g(tmp_workspace):
    """"e.g." means "for example" - an open set, not a closed enumeration.

    The blueprint declares `execution` as prose hedged with "e.g.", so an
    action it doesn't happen to name is undocumented, not forbidden. Reporting
    those as hard errors would fail the model on the strength of an
    abbreviation. `on_fail` is a JSON list and stays an error.
    """
    odd = activity("A", agent_rules=agent_rules(execution=[{"action": "invented_verb"}]))
    ontology, metamodel = build(tmp_workspace, [ROOT, odd])

    vocab = findings_for("ONT-013-VOCAB", ontology, metamodel)
    assert [f.severity for f in vocab] == [Severity.WARNING]
    assert "not among the examples" in vocab[0].message
    # The strict half of ONT-013 is unaffected.
    assert not any(f.rule_id == "ONT-013" and f.subject_id == "invented_verb"
                   for f in run_conformance(ontology, metamodel))


def test_undocumented_actions_are_errors_when_the_vocabulary_is_a_closed_list(tmp_workspace):
    """A blueprint that enumerates actions as a JSON list closes the set."""
    odd = activity("A", agent_rules=agent_rules(execution=[{"action": "invented_verb"}]))
    ontology, metamodel = build(tmp_workspace, [ROOT, odd])
    # Close the vocabulary the way a stricter blueprint revision would.
    metamodel.agent_rules_schema.execution_vocabulary_open = False

    findings = [f for f in run_conformance(ontology, metamodel)
                if f.subject_id == "invented_verb"]
    assert len(findings) == 1
    assert findings[0].rule_id == "ONT-013"
    assert findings[0].severity is Severity.ERROR
    assert "not permitted by" in findings[0].message


# --------------------------------------------------------------------------
# Edge grammar
# --------------------------------------------------------------------------


def test_grammar_flags_an_illegal_target(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A"), node("Cloud Watch", "Systems_Class", "External System")],
        [edge("A", "executes_via", "Cloud Watch")],
    )
    findings = findings_for("GRAMMAR", ontology, metamodel)
    assert len(findings) == 1
    assert findings[0].subject_id == "A|executes_via|Cloud Watch"
    assert "valid_to" in findings[0].message


def test_grammar_accepts_a_legal_target(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A"), node("Svc", "Systems_Class", "Data Service")],
        [edge("A", "executes_via", "Svc")],
    )
    assert findings_for("GRAMMAR", ontology, metamodel) == []


def test_grammar_resolves_meta_class_phrased_rules(tmp_workspace):
    """`performs` is written in meta-classes; the source has no matching type."""
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, node("Operator", "Actor_Class", "Human Actor"), activity("A")],
        [edge("Operator", "performs", "A")],
    )
    assert findings_for("GRAMMAR", ontology, metamodel) == []


def test_grammar_resolves_type_phrased_rules(tmp_workspace):
    """`has_lifecycle_phase` is written in attribute types; both ends are Activity_Class."""
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("Core", "Core Activity"), activity("Domain", "Domain Activity")],
        [edge("Core", "has_lifecycle_phase", "Domain")],
    )
    assert findings_for("GRAMMAR", ontology, metamodel) == []

    bad_ontology, bad_metamodel = build(
        tmp_workspace,
        [ROOT, activity("Core", "Core Activity"), activity("Sub", "Sub_Process Activity")],
        [edge("Core", "has_lifecycle_phase", "Sub")],
        name="ont2",
    )
    assert len(findings_for("GRAMMAR", bad_ontology, bad_metamodel)) == 1


def test_grammar_defers_dangling_and_unknown_edges(tmp_workspace):
    """Neither is a grammar violation; each has its own, more precise, rule."""
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A")],
        [edge("A", "executes_via", "Nowhere"), edge("A", "teleports_to", "A")],
    )
    assert findings_for("GRAMMAR", ontology, metamodel) == []
    assert len(findings_for("CONSISTENCY-DANGLING-EDGE", ontology, metamodel)) == 1
    assert len(findings_for("CONSISTENCY-UNKNOWN-EDGE", ontology, metamodel)) == 1


# --------------------------------------------------------------------------
# Systemic rules
# --------------------------------------------------------------------------


def test_ont_000_flags_a_second_root(tmp_workspace):
    other = node("Enterprise 2", "Ontology_Root_Class", "Enterprise Root")
    ontology, metamodel = build(tmp_workspace, [ROOT, other])
    findings = findings_for("ONT-000", ontology, metamodel)
    assert any("exactly one" in f.message for f in findings)


def test_ont_000_flags_an_unreachable_node(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A"), activity("Orphan")],
        [edge("Enterprise", "includes_model", "A")],
    )
    findings = findings_for("ONT-000", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["Orphan"]


def test_ont_001_ignores_an_activity_with_no_transition(tmp_workspace):
    ontology, metamodel = build(tmp_workspace, [ROOT, activity("A", sipoc=False)])
    assert findings_for("ONT-001", ontology, metamodel) == []


def test_ont_001_is_a_warning_not_an_error(tmp_workspace):
    """A population gap across the whole model, not N independent defects."""
    ontology, metamodel = build(
        tmp_workspace, [ROOT, activity("A", sipoc=False, next_pointer=["B"]), activity("B")]
    )
    findings = findings_for("ONT-001", ontology, metamodel)
    assert [f.severity for f in findings] == [Severity.WARNING]


def test_ont_002_is_quiet_without_a_constraint_model(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("P"), activity("C")],
        [edge("P", "decomposes_into", "C")],
    )
    assert findings_for("ONT-002", ontology, metamodel) == []


def test_ont_002_fires_once_constraints_exist(tmp_workspace):
    parent = activity("P")
    parent["attributes"]["global_constraints"] = ["gdpr"]
    ontology, metamodel = build(
        tmp_workspace, [ROOT, parent, activity("C")], [edge("P", "decomposes_into", "C")]
    )
    findings = findings_for("ONT-002", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["C"]
    assert "gdpr" in findings[0].message


def test_ont_003_flags_a_decision_with_no_performs_check(tmp_workspace):
    ontology, metamodel = build(tmp_workspace, [ROOT, activity("A"), decision("d ?")])
    findings = findings_for("ONT-003", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["d ?"]

    linked_ontology, linked_metamodel = build(
        tmp_workspace,
        [ROOT, activity("A"), decision("d ?")],
        [edge("A", "performs_check", "d ?")],
        name="ont2",
    )
    assert findings_for("ONT-003", linked_ontology, linked_metamodel) == []


def test_ont_003_flags_a_decision_that_acts(tmp_workspace):
    acting = decision("d ?")
    acting["agent_rules"] = agent_rules(execution=[{"action": "invoke_tool"}])
    ontology, metamodel = build(
        tmp_workspace, [ROOT, activity("A"), acting], [edge("A", "performs_check", "d ?")]
    )
    findings = findings_for("ONT-003", ontology, metamodel)
    assert len(findings) == 1
    assert "non-evaluative" in findings[0].message


def test_ont_004_flags_a_non_activity_entry_point(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A"), node("Dim", "Information_Class", "Dimension")],
        [edge("Enterprise", "includes_model", "A")],
    )
    findings = findings_for("ONT-004", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["Dim"]


def test_ont_004_exempts_the_root(tmp_workspace):
    ontology, metamodel = build(tmp_workspace, [ROOT])
    assert findings_for("ONT-004", ontology, metamodel) == []


def test_ont_005_flags_execution_against_a_non_data_service(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A"), node("Runbook", "Systems_Class", "Abstracted Enterprise Entity")],
        [edge("A", "executes_via", "Runbook")],
    )
    findings = findings_for("ONT-005", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["A|executes_via|Runbook"]


def test_ont_005_flags_mastering_by_a_non_data_service(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [
            ROOT,
            node("Ext", "Systems_Class", "External System"),
            node("KEDB", "Systems_Class", "Abstracted Enterprise Entity"),
        ],
        [edge("Ext", "masters", "KEDB")],
    )
    findings = findings_for("ONT-005", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["Ext|masters|KEDB"]


def test_ont_006_flags_an_unmeasured_outcome_at_full_severity(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace, [ROOT, node("Closed", "Outcome_Class", "State")]
    )
    findings = findings_for("ONT-006", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["Closed"]
    # Outcomes exist, so the rule does not degrade.
    assert findings[0].severity is Severity.ERROR
    assert findings[0].degraded is False


def test_ont_006_is_silent_when_the_outcome_is_measured(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, node("Closed", "Outcome_Class", "State"), node("MTTR", "Information_Class", "Measure")],
        [edge("Closed", "measured_by", "MTTR")],
    )
    assert findings_for("ONT-006", ontology, metamodel) == []


def test_ont_007_flags_a_horizontal_exit_over_an_unexecutable_child(tmp_workspace):
    stuck = activity("Child", "Sub_Process Activity", agent_rules=agent_rules(execution=[]))
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("Parent"), stuck, activity("Next")],
        [edge("Parent", "has_subprocess", "Child"), edge("Parent", "triggers", "Next")],
    )
    findings = findings_for("ONT-007", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["Parent"]


def test_ont_007_is_silent_when_children_are_executable(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("Parent"), activity("Child", "Sub_Process Activity"), activity("Next")],
        [edge("Parent", "has_subprocess", "Child"), edge("Parent", "triggers", "Next")],
    )
    assert findings_for("ONT-007", ontology, metamodel) == []


def test_ont_008_flags_a_tier_crossing_trigger(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("P", "Process Activity"), activity("S", "Sub_Process Activity")],
        [edge("P", "triggers", "S")],
    )
    findings = findings_for("ONT-008", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["P|triggers|S"]


def test_ont_008_exempts_decision_nodes(tmp_workspace):
    """A decision routes between peers; it is not a rung on the tier ladder."""
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A"), decision("d ?"), activity("S", "Sub_Process Activity")],
        [edge("d ?", "triggers", "S")],
    )
    assert findings_for("ONT-008", ontology, metamodel) == []


def test_ont_009_flags_a_decision_with_no_default_branch(tmp_workspace):
    branches = [
        {"condition": {"property": "p", "operator": "==", "value": 1}, "target": "A"},
        {"condition": {"property": "p", "operator": "==", "value": 2}, "target": "A"},
    ]
    ontology, metamodel = build(
        tmp_workspace, [ROOT, activity("A"), decision("d ?", branches=branches)]
    )
    findings = findings_for("ONT-009", ontology, metamodel)
    assert len(findings) == 1
    assert "0 default branches" in findings[0].message


def test_ont_009_flags_two_default_branches(tmp_workspace):
    branches = [
        {"condition": "default", "target": "A"},
        {"is_default": True, "target": "A"},
    ]
    ontology, metamodel = build(
        tmp_workspace, [ROOT, activity("A"), decision("d ?", branches=branches)]
    )
    findings = findings_for("ONT-009", ontology, metamodel)
    assert len(findings) == 1
    assert "2 default branches" in findings[0].message


def test_ont_009_accepts_exactly_one_default(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace, [ROOT, activity("A"), activity("B"), decision("d ?")]
    )
    assert findings_for("ONT-009", ontology, metamodel) == []


def test_ont_010_flags_a_dead_end_activity_and_degrades_without_outcomes(tmp_workspace):
    ontology, metamodel = build(tmp_workspace, [ROOT, activity("A")])
    findings = findings_for("ONT-010", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["A"]
    assert findings[0].severity is Severity.WARNING
    assert findings[0].degraded is True


def test_ont_010_escalates_to_error_once_outcomes_exist(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A"), activity("B"), node("Closed", "Outcome_Class", "State")],
        [edge("A", "leads_to", "Closed")],
    )
    findings = findings_for("ONT-010", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["B"]
    assert findings[0].severity is Severity.ERROR
    assert findings[0].degraded is False


def test_ont_010_flags_a_loop_with_no_exit_and_no_decision(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A", "Sub_Process Activity"), activity("B", "Sub_Process Activity")],
        [edge("A", "triggers", "B"), edge("B", "triggers", "A")],
    )
    findings = findings_for("ONT-010", ontology, metamodel)
    loops = [f for f in findings if f.subject_kind is SubjectKind.GRAPH]
    assert len(loops) == 1
    assert loops[0].subject_id == "A -> B"


def test_ont_010_accepts_a_loop_broken_by_a_decision(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A", "Sub_Process Activity"), decision("d ?")],
        [edge("A", "triggers", "d ?"), edge("d ?", "triggers", "A")],
    )
    loops = [
        f for f in findings_for("ONT-010", ontology, metamodel)
        if f.subject_kind is SubjectKind.GRAPH
    ]
    assert loops == []


def test_ont_011_flags_an_unclassified_fact(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace, [ROOT, node("Incident Count", "Information_Class", "Fact")]
    )
    findings = findings_for("ONT-011", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["Incident Count"]


def test_ont_011_accepts_a_fact_classified_by_a_dimension(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [
            ROOT,
            node("Incident Count", "Information_Class", "Fact"),
            node("Time", "Information_Class", "Dimension"),
        ],
        [edge("Time", "classifies", "Incident Count")],
    )
    assert findings_for("ONT-011", ontology, metamodel) == []


def test_ont_012_flags_a_delegate_that_cannot_acknowledge(tmp_workspace):
    silent = node(
        "Svc", "Systems_Class", "Data Service", agent_rules=agent_rules(execution=[
            {"action": "query_graph"}
        ])
    )
    ontology, metamodel = build(
        tmp_workspace, [ROOT, activity("A"), silent], [edge("A", "executes_via", "Svc")]
    )
    findings = findings_for("ONT-012", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["A|executes_via|Svc"]
    assert "invoke_tool" in findings[0].message


def test_ont_012_flags_a_caller_that_never_traces_back(tmp_workspace):
    caller = activity("A", agent_rules=agent_rules(postcondition=[]))
    delegate = node(
        "Svc", "Systems_Class", "Data Service",
        agent_rules=agent_rules(execution=[{"action": "invoke_tool"}]),
    )
    ontology, metamodel = build(
        tmp_workspace, [ROOT, caller, delegate], [edge("A", "executes_via", "Svc")]
    )
    findings = findings_for("ONT-012", ontology, metamodel)
    assert len(findings) == 1
    assert "trace_back" in findings[0].message


def test_ont_012_accepts_a_well_formed_delegation(tmp_workspace):
    delegate = node(
        "Svc", "Systems_Class", "Data Service",
        agent_rules=agent_rules(execution=[{"action": "invoke_tool"}]),
    )
    ontology, metamodel = build(
        tmp_workspace, [ROOT, activity("A"), delegate], [edge("A", "executes_via", "Svc")]
    )
    assert findings_for("ONT-012", ontology, metamodel) == []


# --------------------------------------------------------------------------
# Cross-representation consistency
# --------------------------------------------------------------------------


def test_next_pointer_without_a_relationship_is_reported(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A", next_pointer=["B"]), activity("B")],
    )
    findings = findings_for("CONSISTENCY-NEXT-POINTER", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["A"]
    assert "'B'" in findings[0].message


def test_a_relationship_without_a_next_pointer_is_not_reported(tmp_workspace):
    """`next_pointer` is a traversal plan, not a mirror of every edge."""
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A"), activity("B", "Sub_Process Activity")],
        [edge("A", "has_subprocess", "B")],
    )
    assert findings_for("CONSISTENCY-NEXT-POINTER", ontology, metamodel) == []


def test_dangling_decision_branch_target_is_reported(tmp_workspace):
    """V4's instance points a branch at `trace_back`, a postcondition action."""
    branches = [
        {"condition": {"property": "p", "operator": "==", "value": 1}, "target": "A"},
        {"condition": "default", "target": "trace_back"},
    ]
    ontology, metamodel = build(
        tmp_workspace, [ROOT, activity("A"), decision("d ?", branches=branches)]
    )
    findings = findings_for("CONSISTENCY-BRANCH-TARGET", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["d ?#branch[1]"]
    assert "trace_back" in findings[0].message


def test_resolvable_branch_targets_are_not_reported(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace, [ROOT, activity("A"), activity("B"), decision("d ?")]
    )
    assert findings_for("CONSISTENCY-BRANCH-TARGET", ontology, metamodel) == []


def test_duplicate_node_ids_are_reported(tmp_workspace):
    ontology, metamodel = build(tmp_workspace, [ROOT, activity("A"), activity("A")])
    findings = findings_for("CONSISTENCY-DUPLICATE-ID", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["A"]
    assert "2 times" in findings[0].message


def test_duplicate_check_skips_a_graph_with_no_source_file(tmp_workspace):
    ontology, metamodel = build(tmp_workspace, [ROOT, activity("A")])
    ontology.source_path = None
    assert findings_for("CONSISTENCY-DUPLICATE-ID", ontology, metamodel) == []


def test_unknown_edge_type_is_reported_once_per_type(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT, activity("A"), activity("B")],
        [edge("A", "teleports_to", "B"), edge("B", "teleports_to", "A")],
    )
    findings = findings_for("CONSISTENCY-UNKNOWN-EDGE", ontology, metamodel)
    assert [f.subject_id for f in findings] == ["teleports_to"]
    assert "2 use(s)" in findings[0].message


def test_ruleset_skew_is_reported_as_info(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT],
        systemic_rules=[
            {"rule_id": "ONT-000", "description": "Root Singularity", "logic": "."},
            {"rule_id": "ONT-012", "description": "Async Ack", "logic": "."},
        ],
    )
    findings = findings_for("RULESET-SKEW", ontology, metamodel)
    assert len(findings) == 1
    assert findings[0].severity is Severity.INFO
    # ONT-013 is blueprint-only, ONT-012 instance-only.
    assert "ONT-013" in findings[0].message
    assert "ONT-012" in findings[0].message


def test_ruleset_skew_is_silent_when_the_lists_agree(tmp_workspace):
    ontology, metamodel = build(
        tmp_workspace,
        [ROOT],
        systemic_rules=[
            {"rule_id": "ONT-000", "description": "Root Singularity", "logic": "."},
            {"rule_id": "ONT-013", "description": "Agent Rule Contract", "logic": "."},
        ],
    )
    assert findings_for("RULESET-SKEW", ontology, metamodel) == []


def test_ruleset_skew_can_be_switched_off(tmp_workspace):
    ontology, metamodel = build(tmp_workspace, [ROOT])
    config = ConformanceConfig(report_ruleset_skew=False)
    assert findings_for("RULESET-SKEW", ontology, metamodel, config) == []


# --------------------------------------------------------------------------
# A clean ontology stays clean
# --------------------------------------------------------------------------


def test_a_conforming_ontology_produces_no_errors_or_warnings(tmp_workspace):
    """The one fixture that must come back empty, so a rule that fires on
    everything cannot hide behind the per-rule tests above."""
    classes = [
        node("Enterprise", "Ontology_Root_Class", "Enterprise Root", next_pointer=["Run"]),
        activity("Run", "Process Activity", next_pointer=["Step", "Closed"]),
        activity("Step", "Sub_Process Activity", next_pointer=["Closed"]),
        node("Closed", "Outcome_Class", "State", next_pointer=["MTTR"]),
        node("MTTR", "Information_Class", "Measure"),
    ]
    relationships = [
        edge("Enterprise", "includes_model", "Run"),
        edge("Run", "has_subprocess", "Step"),
        edge("Run", "leads_to", "Closed"),
        edge("Step", "leads_to", "Closed"),
        edge("Closed", "measured_by", "MTTR"),
    ]
    ontology, metamodel = build(
        tmp_workspace,
        classes,
        relationships,
        systemic_rules=[
            {"rule_id": "ONT-000", "description": "Root Singularity", "logic": "."},
            {"rule_id": "ONT-013", "description": "Agent Rule Contract", "logic": "."},
        ],
    )
    findings = run_conformance(ontology, metamodel)
    assert findings == [], "\n".join(f"{f.rule_id} {f.subject_id}: {f.message}" for f in findings)
