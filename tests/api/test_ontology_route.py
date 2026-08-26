"""Ontology compliance endpoints.

Tests are built on synthetic ontology/meta-model files written to tmp_path,
not on the shipped inputs - those are gitignored, so anything depending on
them is a no-op on a clean checkout.
"""

import json

import pytest

MINIMAL_METAMODEL = {
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
                "mandatory_attributes": {"type": ["Enterprise Root", "Domain Root"]},
                "mandatory_rules": {"agent_rules": "$ref: Agent_Rules_Schema"},
            },
            "Activity_Class": {
                "mandatory_attributes": {
                    "type": ["Core Activity", "Domain Activity", "Process Activity",
                             "Sub_Process Activity"],
                    "supplier": "Array", "input": "Array", "process": "Array",
                    "output": "Array", "customer": "Array",
                },
                "mandatory_rules": {"agent_rules": "$ref: Agent_Rules_Schema"},
            },
        },
        "allowed_relationships": {"edges": [
            {"type": "includes_model", "valid_from": ["Ontology_Root_Class"],
             "valid_to": ["Activity_Class"]},
            {"type": "triggers", "valid_from": ["Process Activity"],
             "valid_to": ["Process Activity"]},
        ]},
        "systemic_rules": [
            {"rule_id": "ONT-000", "description": "Root Singularity", "logic": "one root"},
        ],
    }
}


def _agent_rules():
    return {
        "precondition": {"conditions": [], "on_fail": "skip"},
        "delegation": {"role": None},
        "execution": [{"action": "traverse_dfs", "targets": "next_pointer"}],
        "postcondition": [{"action": "trace_back"}],
    }


def _ontology(extra_edges=None):
    return {"Ontology": {
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
        "relationships": [{"source": "Root", "target": "A", "type": "includes_model"}]
                         + (extra_edges or []),
        "systemic_rules": [
            {"rule_id": "ONT-000", "description": "Root Singularity", "logic": "one root"},
        ],
    }}


@pytest.fixture
def paths(tmp_path, monkeypatch):
    ont = tmp_path / "ont.json"
    mm = tmp_path / "mm.json"
    # One deliberate grammar violation: Root is not a Process Activity.
    ont.write_text(json.dumps(_ontology(
        [{"source": "Root", "target": "A", "type": "triggers"}]
    )), encoding="utf-8")
    mm.write_text(json.dumps(MINIMAL_METAMODEL), encoding="utf-8")
    monkeypatch.setenv("ONTO_ONTOLOGY_PATH", str(ont))
    monkeypatch.setenv("ONTO_METAMODEL_PATH", str(mm))
    monkeypatch.setenv("ONTO_CONFLICT_DB_PATH", str(tmp_path / "conflicts.db"))
    return {"ontology": str(ont), "metamodel": str(mm)}


class TestGraph:
    def test_returns_nodes_and_edges(self, client, paths):
        response = client.get("/api/ontology/graph")
        assert response.status_code == 200
        body = response.json()
        assert body["version"] == "test-2.2"
        assert {n["id"] for n in body["nodes"]} == {"Root", "A"}
        assert body["edges"][0]["key"] == "Root|includes_model|A"

    def test_missing_input_is_a_400_not_a_500(self, client, monkeypatch):
        """Errors nest under "error", the shape client.ts normalizeError expects."""
        monkeypatch.setenv("ONTO_ONTOLOGY_PATH", "/nonexistent/ont.json")
        response = client.get("/api/ontology/graph")
        assert response.status_code == 400
        assert response.json()["error"]["error"] == "ontology_input_missing"
        assert "ONTO_ONTOLOGY_PATH" in response.json()["error"]["detail"]


class TestValidate:
    def test_conformance_plane_reports_the_planted_violation(self, client, paths):
        response = client.post("/api/ontology/validate", json={"plane": "a"})
        assert response.status_code == 200
        body = response.json()
        assert body["conformance"]["by_rule"].get("GRAMMAR") == 1
        assert body["passed"] is False
        assert body["grounding"]["ran"] is False

    def test_severity_threshold_filters(self, client, paths):
        errors_only = client.post(
            "/api/ontology/validate", json={"plane": "a", "severity_threshold": "error"}
        ).json()
        everything = client.post(
            "/api/ontology/validate", json={"plane": "a", "severity_threshold": "info"}
        ).json()
        assert len(errors_only["conformance"]["findings"]) <= len(everything["conformance"]["findings"])
        assert all(f["severity"] == "error" for f in errors_only["conformance"]["findings"])

    def test_missing_input_is_a_400(self, client, paths):
        response = client.post(
            "/api/ontology/validate", json={"plane": "a", "ontology_path": "/nope.json"}
        )
        assert response.status_code == 400


class TestConflictQueue:
    def test_validation_populates_the_queue(self, client, paths):
        client.post("/api/ontology/validate", json={"plane": "a"})
        response = client.get("/api/ontology/conflicts", params={"status": "open"})
        assert response.status_code == 200
        assert response.json()["unreviewed"] >= 1

    def test_resolving_survives_a_revalidation(self, client, paths):
        """Idempotence, end to end: adjudication is not undone by a re-run."""
        client.post("/api/ontology/validate", json={"plane": "a"})
        conflict = client.get("/api/ontology/conflicts", params={"status": "open"}).json()["conflicts"][0]

        resolved = client.post(
            f"/api/ontology/conflicts/{conflict['conflict_id']}/resolve",
            json={"status": "metamodel_gap", "note": "blueprint too narrow", "resolved_by": "tester"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "metamodel_gap"

        client.post("/api/ontology/validate", json={"plane": "a"})
        again = client.get("/api/ontology/conflicts").json()
        row = next(c for c in again["conflicts"] if c["conflict_id"] == conflict["conflict_id"])
        assert row["status"] == "metamodel_gap"
        assert row["occurrences"] == 2

    def test_unknown_conflict_is_404(self, client, paths):
        response = client.post(
            "/api/ontology/conflicts/deadbeef/resolve", json={"status": "metamodel_gap"}
        )
        assert response.status_code == 404
        assert response.json()["error"]["error"] == "conflict_not_found"

    def test_invalid_status_is_rejected(self, client, paths):
        client.post("/api/ontology/validate", json={"plane": "a"})
        assert client.get("/api/ontology/conflicts", params={"status": "nonsense"}).status_code == 400
        assert client.post(
            "/api/ontology/conflicts/x/resolve", json={"status": "nonsense"}
        ).status_code == 422


class TestAmendments:
    def test_amendments_appear_only_after_a_metamodel_gap_ruling(self, client, paths):
        client.post("/api/ontology/validate", json={"plane": "a"})
        assert client.get("/api/ontology/amendments").json()["amendments"] == []

        conflict = client.get("/api/ontology/conflicts", params={"status": "open"}).json()["conflicts"][0]
        client.post(
            f"/api/ontology/conflicts/{conflict['conflict_id']}/resolve",
            json={"status": "metamodel_gap"},
        )
        amendments = client.get("/api/ontology/amendments").json()["amendments"]
        assert len(amendments) == 1
        assert amendments[0]["conflict_id"] == conflict["conflict_id"]

    def test_amendments_never_touch_the_metamodel_file(self, client, paths):
        """Proposals only. Editing the blueprint stays a human act."""
        before = open(paths["metamodel"], "rb").read()
        client.post("/api/ontology/validate", json={"plane": "a"})
        conflict = client.get("/api/ontology/conflicts", params={"status": "open"}).json()["conflicts"][0]
        client.post(
            f"/api/ontology/conflicts/{conflict['conflict_id']}/resolve",
            json={"status": "metamodel_gap"},
        )
        client.get("/api/ontology/amendments")
        assert open(paths["metamodel"], "rb").read() == before
