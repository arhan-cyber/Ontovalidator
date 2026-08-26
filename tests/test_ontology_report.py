"""The report keeps the two planes separate and lets contradiction dominate.

Both properties exist to stop the report hiding its most useful finding. An
averaged score would bury "conformant but contradicted by the source
document", and a roll-up that let three supported claims outvote one
contradiction would bury it again one level down.
"""

import pytest

from src.ontology.models import ConformanceFinding, Severity, SubjectKind
from src.ontology.projection import ClaimKind, ClaimProvenance
from src.ontology.report import ComplianceReport, rollup_grounding


def _finding(rule_id="ONT-005", severity=Severity.ERROR, subject_id="X", kind=SubjectKind.NODE):
    return ConformanceFinding(
        rule_id=rule_id, severity=severity, subject_kind=kind,
        subject_id=subject_id, message="m",
    )


def _verdict(assertion_id, label, score=0.9):
    return {"assertion_id": assertion_id, "label": label, "score": score}


# ---------------------------------------------------------------------------
# Roll-up precedence
# ---------------------------------------------------------------------------


def test_contradiction_outranks_supporting_claims():
    """One contradiction must not be outvoted by three supports."""
    provenance = {f"a{i}": ClaimProvenance(kind=ClaimKind.SIPOC, node_id="N") for i in range(4)}
    verdicts = [_verdict("a0", "supported"), _verdict("a1", "supported"),
                _verdict("a2", "supported"), _verdict("a3", "contradicted")]

    rolled = rollup_grounding(verdicts, provenance)["nodes"]["N"]
    assert rolled.status == "contradicted"
    assert rolled.supported == 3 and rolled.contradicted == 1
    assert rolled.total == 4


@pytest.mark.parametrize("labels,expected", [
    (["supported", "partial"], "supported"),
    (["partial", "unknown"], "partial"),
    (["unknown"], "unknown"),
    (["contradicted", "supported"], "contradicted"),
])
def test_rollup_status_precedence(labels, expected):
    provenance = {f"a{i}": ClaimProvenance(kind=ClaimKind.SIPOC, node_id="N") for i in range(len(labels))}
    verdicts = [_verdict(f"a{i}", label) for i, label in enumerate(labels)]
    assert rollup_grounding(verdicts, provenance)["nodes"]["N"].status == expected


def test_edge_claims_roll_up_to_edges_not_nodes():
    provenance = {"e1": ClaimProvenance(kind=ClaimKind.EDGE, edge_key="A|triggers|B")}
    rolled = rollup_grounding([_verdict("e1", "supported")], provenance)
    assert rolled["edges"]["A|triggers|B"].status == "supported"
    assert rolled["nodes"] == {}


def test_verdict_without_known_provenance_is_ignored():
    rolled = rollup_grounding([_verdict("orphan", "supported")], {})
    assert rolled["nodes"] == {} and rolled["edges"] == {}


def test_unexpected_label_counts_as_unknown():
    provenance = {"a": ClaimProvenance(kind=ClaimKind.SIPOC, node_id="N")}
    rolled = rollup_grounding([_verdict("a", "some_new_label")], provenance)
    assert rolled["nodes"]["N"].unknown == 1


# ---------------------------------------------------------------------------
# Plane A pass/fail (decision D2)
# ---------------------------------------------------------------------------


def test_only_errors_fail_conformance():
    report = ComplianceReport(findings=[
        _finding(severity=Severity.WARNING), _finding(severity=Severity.INFO),
    ])
    assert report.conformance_passed

    report.findings.append(_finding(severity=Severity.ERROR))
    assert not report.conformance_passed


def test_severity_threshold_filters_findings():
    report = ComplianceReport(findings=[
        _finding(severity=Severity.ERROR), _finding(severity=Severity.WARNING, subject_id="Y"),
        _finding(severity=Severity.INFO, subject_id="Z"),
    ])
    assert len(report.filter_findings(Severity.ERROR)) == 1
    assert len(report.filter_findings(Severity.WARNING)) == 2
    assert len(report.filter_findings(Severity.INFO)) == 3


def test_findings_grouped_by_rule_and_severity():
    report = ComplianceReport(findings=[
        _finding(rule_id="ONT-005"), _finding(rule_id="ONT-005", subject_id="Y"),
        _finding(rule_id="ONT-013", severity=Severity.WARNING, subject_id="Z"),
    ])
    assert report.findings_by_rule() == {"ONT-005": 2, "ONT-013": 1}
    assert report.findings_by_severity() == {"error": 2, "warning": 1, "info": 0}


# ---------------------------------------------------------------------------
# Plane B pass/fail (decision D5)
# ---------------------------------------------------------------------------


def test_only_contradiction_fails_grounding():
    """No evidence is a coverage gap, not a defect."""
    report = ComplianceReport(grounding_ran=True, verdicts=[
        _verdict("a", "unknown"), _verdict("b", "partial"), _verdict("c", "supported"),
    ])
    assert report.grounding_passed

    report.verdicts.append(_verdict("d", "contradicted"))
    assert not report.grounding_passed


def test_grounding_passes_vacuously_when_not_run():
    assert ComplianceReport(grounding_ran=False).grounding_passed


def test_contradictions_are_surfaced_separately():
    report = ComplianceReport(grounding_ran=True, verdicts=[
        _verdict("a", "supported"), _verdict("b", "contradicted"),
    ])
    assert [v["assertion_id"] for v in report.contradictions()] == ["b"]


def test_coverage_counts_contradicted_as_covered():
    """A contradicted claim IS evidence - the document spoke to it."""
    report = ComplianceReport(total_nodes=4, total_edges=0, grounding_ran=True)
    provenance = {
        "a": ClaimProvenance(kind=ClaimKind.SIPOC, node_id="N1"),
        "b": ClaimProvenance(kind=ClaimKind.SIPOC, node_id="N2"),
        "c": ClaimProvenance(kind=ClaimKind.SIPOC, node_id="N3"),
    }
    verdicts = [_verdict("a", "supported"), _verdict("b", "contradicted"), _verdict("c", "unknown")]
    report.node_grounding = rollup_grounding(verdicts, provenance)["nodes"]

    coverage = report.coverage()
    assert coverage["nodes_with_evidence"] == 2
    assert coverage["nodes_pct"] == 50.0


def test_coverage_handles_an_empty_ontology():
    assert ComplianceReport().coverage()["nodes_pct"] == 0.0


# ---------------------------------------------------------------------------
# The two planes stay separate
# ---------------------------------------------------------------------------


def test_node_status_reports_both_axes_independently():
    """The case worth surfacing: legally wired, contradicted by the manual."""
    report = ComplianceReport(grounding_ran=True)
    report.findings = [_finding(rule_id="ONT-005", subject_id="BadNode")]
    provenance = {
        "a": ClaimProvenance(kind=ClaimKind.SIPOC, node_id="GoodNode"),
        "b": ClaimProvenance(kind=ClaimKind.SIPOC, node_id="BadNode"),
    }
    report.node_grounding = rollup_grounding(
        [_verdict("a", "contradicted"), _verdict("b", "supported")], provenance
    )["nodes"]

    status = report.node_status()
    assert status["GoodNode"] == {
        "conformance": "pass", "failed_rules": [], "grounding": "contradicted",
    }
    assert status["BadNode"] == {
        "conformance": "fail", "failed_rules": ["ONT-005"], "grounding": "supported",
    }


def test_overall_pass_requires_both_planes():
    report = ComplianceReport(grounding_ran=True, verdicts=[_verdict("a", "supported")])
    assert report.passed

    report.findings = [_finding(severity=Severity.ERROR)]
    assert not report.passed

    report.findings = []
    report.verdicts = [_verdict("a", "contradicted")]
    assert not report.passed


def test_edge_findings_do_not_appear_in_node_status():
    report = ComplianceReport(findings=[
        _finding(subject_id="A|triggers|B", kind=SubjectKind.EDGE),
    ])
    assert "A|triggers|B" not in report.node_status()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_to_dict_is_json_serializable():
    import json

    report = ComplianceReport(
        ontology_version="2.2", metamodel_version="2.1", grounding_ran=True,
        total_nodes=1, total_edges=1,
        findings=[_finding(severity=Severity.WARNING)],
        verdicts=[_verdict("a", "supported")],
    )
    payload = json.loads(json.dumps(report.to_dict()))
    assert payload["conformance"]["by_severity"]["warning"] == 1
    assert payload["grounding"]["by_label"]["supported"] == 1
    assert payload["passed"] is True


def test_summary_lines_mention_unreviewed_conflicts():
    report = ComplianceReport(unreviewed_conflicts=6)
    assert any("unreviewed conflicts: 6" in line for line in report.summary_lines())
    assert not any("unreviewed" in line for line in ComplianceReport().summary_lines())
