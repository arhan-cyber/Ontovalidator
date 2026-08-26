"""Regression guard on the shipped ontology's conformance findings.

The ontology and meta-model are gitignored (supplied per deployment, and the
IT4IT PDF alone is ~19MB), so this fixture is what CI has instead of the
inputs. Two behaviours matter and are easy to get wrong:

* **Skip loudly when the inputs are absent.** A golden test that silently
  passes on a clean checkout is worse than no test - it reads as green while
  checking nothing.
* **Fail loudly when the inputs are present but changed.** Hash-pinning turns
  an ontology revision into "the baseline is stale, re-bless it" instead of an
  unexplained diff in a 134-line findings list.

Re-bless with: python scripts/validate_ontology.py --plane a --bless-baseline
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from src.ontology import load_metamodel, load_ontology
from src.ontology.conformance import run_conformance
from src.ontology.loader import DEFAULT_METAMODEL_PATH, DEFAULT_ONTOLOGY_PATH

BASELINE_PATH = Path(__file__).parent / "fixtures" / "ontology_conformance_baseline.json"


def _sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def baseline():
    if not BASELINE_PATH.exists():
        pytest.fail(
            f"baseline fixture missing at {BASELINE_PATH}; "
            "regenerate with scripts/validate_ontology.py --bless-baseline"
        )
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def inputs_present():
    missing = [p for p in (DEFAULT_ONTOLOGY_PATH, DEFAULT_METAMODEL_PATH) if not os.path.exists(p)]
    if missing:
        pytest.skip(
            f"ontology inputs not present (gitignored): {', '.join(missing)}. "
            "This test is a no-op on a clean checkout by design."
        )
    return True


@pytest.fixture(scope="module")
def findings(inputs_present):
    return run_conformance(load_ontology(), load_metamodel())


def test_inputs_match_the_hashes_the_baseline_was_blessed_against(baseline, inputs_present):
    """A changed input means the baseline is stale, not that the code broke."""
    for path, key in ((DEFAULT_ONTOLOGY_PATH, "ontology_sha256"),
                      (DEFAULT_METAMODEL_PATH, "metamodel_sha256")):
        expected = baseline.get(key)
        if expected is None:
            pytest.skip(f"baseline has no {key} recorded")
        assert _sha256(path) == expected, (
            f"{path} has changed since the baseline was blessed. "
            f"Re-run: python scripts/validate_ontology.py --plane a --bless-baseline"
        )


def test_total_finding_count_is_unchanged(baseline, findings):
    assert len(findings) == baseline["total_findings"]


def test_finding_counts_per_rule_are_unchanged(baseline, findings):
    actual = {}
    for finding in findings:
        actual[finding.rule_id] = actual.get(finding.rule_id, 0) + 1
    assert actual == baseline["by_rule"]


def test_severity_distribution_is_unchanged(baseline, findings):
    actual = {"error": 0, "warning": 0, "info": 0}
    for finding in findings:
        actual[finding.severity.value] += 1
    assert actual == baseline["by_severity"]


def test_every_individual_finding_is_unchanged(baseline, findings):
    """Catches a rule that swapped which subjects it fires on at equal count."""
    actual = sorted(
        [
            {
                "rule_id": f.rule_id,
                "severity": f.severity.value,
                "subject_kind": f.subject_kind.value,
                "subject_id": f.subject_id,
                "degraded": f.degraded,
            }
            for f in findings
        ],
        key=lambda f: (f["rule_id"], f["subject_id"]),
    )
    assert actual == baseline["findings"]


def test_the_known_defects_are_still_detected(findings):
    """Spot-check the specific defects, independent of the generated fixture.

    Written out longhand so that re-blessing a wrong baseline can't quietly
    bless away a real regression.
    """
    by_rule = {}
    for finding in findings:
        by_rule.setdefault(finding.rule_id, []).append(finding.subject_id)

    assert sorted(by_rule["GRAMMAR"]) == sorted([
        "Log Monitor|executes_via|Cloud Logging",
        "Service Monitor|executes_via|Cloud Watch",
        "Runbook Activity|executes_via|Runbook",
        "Operations|decomposes_into|Business Service",
        "Configuration Data|connects_to_info|Configuration",
        "Handle Duplicate Event|leads_to|Skip",
    ])
    assert by_rule["ONT-003"] == ["reason ?"]
    assert by_rule["CONSISTENCY-NEXT-POINTER"] == ["Escalation"]
    assert len(by_rule["ONT-013"]) == 45          # on_fail: null
    assert len(by_rule["ONT-013-VOCAB"]) == 7     # undocumented action verbs
    assert len(by_rule["ONT-010"]) == 39          # dead-end activities
    assert len(by_rule["ONT-001"]) == 27          # incomplete SIPOC
    assert "ONT-000" not in by_rule               # root singularity is clean
    assert "ONT-011" not in by_rule               # fact classification is clean
    assert "CONSISTENCY-DANGLING-EDGE" not in by_rule
    assert "CONSISTENCY-DUPLICATE-ID" not in by_rule


def test_degraded_findings_are_marked(findings):
    """ONT-010 degrades to warning while the model has no Outcome nodes (D2)."""
    degraded = [f for f in findings if f.degraded]
    assert degraded, "expected ONT-010 to be degraded"
    assert {f.rule_id for f in degraded} == {"ONT-010"}
    assert all(f.severity.value == "warning" for f in degraded)
