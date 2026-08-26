"""Conflict registry: idempotent recording, resolution persistence, and the
apply_resolutions read path used by the report.

See docs/ONTOLOGY_COMPLIANCE_PLAN.md §6 (Phase 1b). Idempotence is called out
in the plan as "the property most likely to regress silently" -- a stable
conflict_id is what lets an adjudicated conflict stay adjudicated across runs
instead of re-opening and burying the review queue in noise.
"""

import os

import pytest

from src.ontology.conflicts import ConflictRegistry, VALID_STATUSES, _compute_conflict_id
from src.ontology.models import ConformanceFinding, Severity, SubjectKind


@pytest.fixture
def registry(tmp_path):
    return ConflictRegistry(os.path.join(tmp_path, "conflicts.db"))


def finding(
    rule_id="GRAMMAR",
    subject_id="Log Monitor|executes_via|Cloud Watch",
    subject_kind=SubjectKind.EDGE,
    severity=Severity.ERROR,
    message="executes_via target Cloud Watch is not a valid target kind",
    evidence="target kind: External System",
    remediation="executes_via.valid_to must include External System",
):
    return ConformanceFinding(
        rule_id=rule_id,
        severity=severity,
        subject_kind=subject_kind,
        subject_id=subject_id,
        message=message,
        evidence=evidence,
        remediation=remediation,
    )


class TestConflictIdStability:
    def test_id_depends_only_on_rule_and_subject(self):
        a = _compute_conflict_id("GRAMMAR", "X|edge|Y")
        b = _compute_conflict_id("GRAMMAR", "X|edge|Y")
        assert a == b

    def test_id_ignores_message_severity_and_evidence(self):
        f1 = finding(message="msg one", severity=Severity.ERROR, evidence="ev one")
        f2 = finding(message="totally different", severity=Severity.WARNING, evidence="ev two")
        id1 = _compute_conflict_id(f1.rule_id, f1.subject_id)
        id2 = _compute_conflict_id(f2.rule_id, f2.subject_id)
        assert id1 == id2

    def test_different_subject_gives_different_id(self):
        id1 = _compute_conflict_id("GRAMMAR", "A|edge|B")
        id2 = _compute_conflict_id("GRAMMAR", "A|edge|C")
        assert id1 != id2


class TestIdempotentRecording:
    def test_recording_the_same_finding_twice_inserts_zero_new_rows(self, registry):
        f = finding()

        first = registry.record_many([f])
        assert first == {"new": 1, "seen_again": 0}
        assert len(registry.all_conflicts()) == 1

        second = registry.record_many([f])
        assert second == {"new": 0, "seen_again": 1}
        assert len(registry.all_conflicts()) == 1  # no duplicate row

        row = registry.all_conflicts()[0]
        assert row["occurrences"] == 2

    def test_second_run_prompts_for_zero_new_conflicts(self, registry):
        f = finding()
        registry.record_many([f])
        assert registry.unreviewed_count() == 1

        registry.record_many([f])
        # Still exactly one open conflict -- no duplicate prompt was created.
        assert registry.unreviewed_count() == 1
        assert len(registry.open_conflicts()) == 1

    def test_record_returns_same_conflict_id_across_runs(self, registry):
        f = finding()
        id1 = registry.record(f)
        id2 = registry.record(f)
        assert id1 == id2


class TestResolveSurvivesReRecording:
    def test_resolution_is_not_reset_by_a_later_record(self, registry):
        f = finding()
        conflict_id = registry.record(f)

        registry.resolve(conflict_id, "metamodel_gap", note="genuinely external", resolved_by="arhan")

        # Same finding shows up again on a subsequent run.
        registry.record(f)

        row = registry.get(conflict_id)
        assert row["status"] == "metamodel_gap"
        assert row["resolution_note"] == "genuinely external"
        assert row["resolved_by"] == "arhan"
        assert row["occurrences"] == 2

    def test_resolve_rejects_invalid_status(self, registry):
        f = finding()
        conflict_id = registry.record(f)
        with pytest.raises(ValueError):
            registry.resolve(conflict_id, "not_a_real_status")

    def test_resolve_unknown_conflict_id_raises(self, registry):
        with pytest.raises(KeyError):
            registry.resolve("does-not-exist", "ontology_defect")

    def test_all_valid_statuses_are_accepted(self, registry):
        f = finding()
        conflict_id = registry.record(f)
        for status in VALID_STATUSES:
            registry.resolve(conflict_id, status)
            assert registry.get(conflict_id)["status"] == status


class TestApplyResolutions:
    def test_open_conflict_is_unchanged(self, registry):
        f = finding()
        registry.record(f)

        out = registry.apply_resolutions([f])
        assert len(out) == 1
        assert out[0].severity == f.severity

    def test_ontology_defect_is_kept_as_error(self, registry):
        f = finding(severity=Severity.WARNING)
        conflict_id = registry.record(f)
        registry.resolve(conflict_id, "ontology_defect")

        out = registry.apply_resolutions([f])
        assert len(out) == 1
        assert out[0].severity == Severity.ERROR

    def test_metamodel_gap_is_downgraded_to_info(self, registry):
        f = finding(severity=Severity.ERROR)
        conflict_id = registry.record(f)
        registry.resolve(conflict_id, "metamodel_gap")

        out = registry.apply_resolutions([f])
        assert len(out) == 1
        assert out[0].severity == Severity.INFO
        # Original finding is untouched -- ConformanceFinding is frozen and
        # apply_resolutions must not mutate the caller's list in place.
        assert f.severity == Severity.ERROR

    def test_accepted_exception_is_filtered_out(self, registry):
        f = finding()
        conflict_id = registry.record(f)
        registry.resolve(conflict_id, "accepted_exception")

        out = registry.apply_resolutions([f])
        assert out == []

    def test_unrecorded_finding_passes_through_unchanged(self, registry):
        f = finding(subject_id="Never|seen|Before")
        out = registry.apply_resolutions([f])
        assert len(out) == 1
        assert out[0].severity == f.severity


class TestProposedAmendments:
    def test_only_metamodel_gap_conflicts_are_included(self, registry):
        f1 = finding(subject_id="A|edge|B")
        f2 = finding(subject_id="C|edge|D", rule_id="ONT-005")
        id1 = registry.record(f1)
        registry.record(f2)
        registry.resolve(id1, "metamodel_gap")

        amendments = registry.proposed_amendments()
        assert len(amendments) == 1
        assert amendments[0]["conflict_id"] == id1

    def test_amendment_extracts_field_and_value(self, registry):
        f = finding(
            evidence="External System",
            remediation="executes_via.valid_to must include External System",
        )
        conflict_id = registry.record(f)
        registry.resolve(conflict_id, "metamodel_gap")

        amendments = registry.proposed_amendments()
        assert len(amendments) == 1
        amendment = amendments[0]
        assert amendment["field"] == "executes_via.valid_to"
        assert amendment["add_value"] == "External System"

    def test_amendment_never_touches_the_metamodel_file(self, registry, tmp_path):
        metamodel_path = tmp_path / "Final_Ontology_meta_model.json"
        metamodel_path.write_text('{"untouched": true}')

        f = finding()
        conflict_id = registry.record(f)
        registry.resolve(conflict_id, "metamodel_gap")
        registry.proposed_amendments()

        assert metamodel_path.read_text() == '{"untouched": true}'

    def test_missing_field_pattern_yields_none_not_a_crash(self, registry):
        f = finding(remediation="the target kind is not permitted here")
        conflict_id = registry.record(f)
        registry.resolve(conflict_id, "metamodel_gap")

        amendments = registry.proposed_amendments()
        assert amendments[0]["field"] is None
        assert amendments[0]["metamodel_says"] == "the target kind is not permitted here"
