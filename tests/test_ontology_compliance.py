"""The orchestrator: two planes, wired to the conflict registry, merged.

The behaviour worth pinning is the interaction between Plane A and the
registry - findings are recorded first and then re-labelled by any stored
adjudication, so a resolved conflict changes how the report reads without
disappearing from the registry.
"""

import json

import pytest

from src.ontology.compliance import OntologyComplianceValidator
from src.ontology.compliance_config import OntologyComplianceConfig
from src.ontology.models import Severity

from .test_ontology_report import _finding  # noqa: F401  (shared builder)


def _agent_rules():
    return {
        "precondition": {"conditions": [], "on_fail": "skip"},
        "delegation": {"role": None},
        "execution": [{"action": "traverse_dfs", "targets": "next_pointer"}],
        "postcondition": [{"action": "trace_back"}],
    }


METAMODEL = {
    "Enterprise_Ontology_Meta_Model_Blueprint": {
        "version": "test-2.1",
        "global_schemas": {"Agent_Rules_Schema": {"structure": {
            "precondition": {"conditions": "...", "on_fail": ["skip", "block"]},
            "delegation": {"role": "..."},
            "execution": "Array of action objects (e.g., traverse_dfs, invoke_tool)",
            "postcondition": "Array of action objects (e.g., trace_back)",
        }}},
        "meta_classes": {
            "Ontology_Root_Class": {
                "mandatory_attributes": {"type": ["Enterprise Root"]},
                "mandatory_rules": {"agent_rules": "$ref"},
            },
            "Activity_Class": {
                "mandatory_attributes": {
                    "type": ["Process Activity"], "supplier": "A", "input": "A",
                    "process": "A", "output": "A", "customer": "A",
                },
                "mandatory_rules": {"agent_rules": "$ref"},
            },
        },
        "allowed_relationships": {"edges": [
            {"type": "includes_model", "valid_from": ["Ontology_Root_Class"],
             "valid_to": ["Activity_Class"]},
            {"type": "triggers", "valid_from": ["Process Activity"],
             "valid_to": ["Process Activity"]},
        ]},
        "systemic_rules": [{"rule_id": "ONT-000", "description": "Root", "logic": "one"}],
    }
}

ONTOLOGY = {"Ontology": {
    "version": "test-2.2",
    "classes": [
        {"id": "Root", "meta_class": "Ontology_Root_Class",
         "attributes": {"type": ["Enterprise Root"]}, "agent_rules": _agent_rules(),
         "next_pointer": ["A"]},
        {"id": "A", "meta_class": "Activity_Class",
         "attributes": {"type": ["Process Activity"], "supplier": ["s"], "input": ["i"],
                        "process": ["A"], "output": ["o"], "customer": ["c"]},
         "agent_rules": _agent_rules(), "next_pointer": []},
    ],
    # The `triggers` edge is illegal: Root is not a Process Activity.
    "relationships": [
        {"source": "Root", "target": "A", "type": "includes_model"},
        {"source": "Root", "target": "A", "type": "triggers"},
    ],
    "systemic_rules": [{"rule_id": "ONT-000", "description": "Root", "logic": "one"}],
}}


@pytest.fixture
def config(tmp_path):
    ont = tmp_path / "ont.json"
    mm = tmp_path / "mm.json"
    ont.write_text(json.dumps(ONTOLOGY), encoding="utf-8")
    mm.write_text(json.dumps(METAMODEL), encoding="utf-8")
    return OntologyComplianceConfig(
        ontology_path=str(ont), metamodel_path=str(mm),
        conflict_db_path=str(tmp_path / "conflicts.db"),
        enable_grounding=False,
    )


def test_conformance_plane_finds_the_planted_violation(config):
    report = OntologyComplianceValidator(config).validate()
    assert report.findings_by_rule().get("GRAMMAR") == 1
    assert not report.conformance_passed
    assert report.ontology_version == "test-2.2"
    assert report.metamodel_version == "test-2.1"


def test_grounding_is_skipped_without_an_engine(config):
    config.enable_grounding = True
    report = OntologyComplianceValidator(config, engine=None).validate()
    assert report.grounding_ran is False
    assert report.grounding_confidence == "not_run"
    # Skipped, not failed - a missing corpus is not a compliance defect.
    assert report.grounding_passed


def test_conflicts_are_recorded_then_re_labelled_by_their_resolution(config):
    validator = OntologyComplianceValidator(config)
    validator.validate()

    registry = validator.registry
    conflict = registry.open_conflicts()[0]
    registry.resolve(conflict["conflict_id"], "metamodel_gap", note="blueprint too narrow")

    report = validator.validate()
    grammar = [f for f in report.findings if f.rule_id == "GRAMMAR"]
    assert [f.severity for f in grammar] == [Severity.INFO]
    assert report.unreviewed_conflicts == 0


def test_accepted_exceptions_leave_the_report_but_stay_in_the_registry(config):
    validator = OntologyComplianceValidator(config)
    validator.validate()
    registry = validator.registry
    conflict = registry.open_conflicts()[0]
    registry.resolve(conflict["conflict_id"], "accepted_exception")

    report = validator.validate()
    assert not [f for f in report.findings if f.rule_id == "GRAMMAR"]
    assert registry.get(conflict["conflict_id"])["status"] == "accepted_exception"


def test_repeat_runs_do_not_re_open_the_queue(config):
    """The property the whole registry exists for."""
    validator = OntologyComplianceValidator(config)
    validator.validate()
    registry = validator.registry
    before = len(registry.all_conflicts())
    conflict = registry.open_conflicts()[0]
    registry.resolve(conflict["conflict_id"], "ontology_defect")

    for _ in range(3):
        validator.validate()

    assert len(registry.all_conflicts()) == before
    assert registry.get(conflict["conflict_id"])["status"] == "ontology_defect"
    assert registry.get(conflict["conflict_id"])["occurrences"] == 4


def test_registry_can_be_disabled(config):
    config.enable_conflict_registry = False
    validator = OntologyComplianceValidator(config)
    report = validator.validate()
    assert validator.registry is None
    assert report.unreviewed_conflicts == 0
    assert report.findings_by_rule().get("GRAMMAR") == 1


def test_severity_threshold_filters_the_report(config):
    config.severity_threshold = "error"
    config.enable_conflict_registry = False
    report = OntologyComplianceValidator(config).validate()
    assert all(f.severity is Severity.ERROR for f in report.findings)


def test_conformance_plane_can_be_disabled(config):
    config.enable_conformance = False
    report = OntologyComplianceValidator(config).validate()
    assert report.findings == []
    assert report.conformance_passed


class TestIT4ITExclusion:
    """Decision D4: the 294-page reference standard stays out by default."""

    def test_it4it_is_excluded_by_default(self):
        config = OntologyComplianceConfig()
        assert "IT4IT*" in config.effective_exclude_patterns()

    def test_opting_in_removes_the_exclusion(self):
        config = OntologyComplianceConfig(include_it4it_corpus=True)
        assert "IT4IT*" not in config.effective_exclude_patterns()

    def test_explicit_excludes_are_preserved(self):
        config = OntologyComplianceConfig(exclude_patterns=["draft_*.pdf"])
        patterns = config.effective_exclude_patterns()
        assert "draft_*.pdf" in patterns and "IT4IT*" in patterns
