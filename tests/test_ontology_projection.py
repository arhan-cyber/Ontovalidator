"""Projection turns ontology elements into claims the engine can retrieve on.

The tests that matter most here are about *query text*. The engine builds its
retrieval query as f"{subject} {relation} {object}", so a projection that
emits raw edge types and raw node ids produces queries no human-written
process manual will ever match - and the whole grounding plane silently
returns "unknown" for everything.
"""

import json

import pytest

from src.ontology.loader import load_ontology
from src.ontology.projection import (
    ALL_CLAIM_KINDS,
    ClaimKind,
    claims_to_assertions,
    clean_node_label,
    project_ontology,
    provenance_index,
    verbalize_edge,
)


# ---------------------------------------------------------------------------
# Verbalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("edge_type,expected", [
    ("includes_process", "includes the process"),
    ("executes_via", "is executed via"),
    ("measured_by", "is measured by"),
    ("on_success", "on success proceeds to"),
])
def test_known_edge_types_read_as_prose(edge_type, expected):
    assert verbalize_edge(edge_type) == expected


def test_unmapped_edge_type_degrades_to_spaced_words():
    """Never silently empty - a new grammar edge still yields a usable query."""
    assert verbalize_edge("some_new_edge") == "some new edge"


@pytest.mark.parametrize("raw,expected", [
    ("filter out event ?", "filter out event"),
    ("reason ?", "reason"),
    ("is major incident ?", "is major incident"),
    ("Event Management", "Event Management"),
])
def test_decision_question_marks_are_stripped(raw, expected):
    """The trailing '?' is punctuation in a query and hurts lexical overlap."""
    assert clean_node_label(raw) == expected


def test_clean_label_never_returns_empty():
    assert clean_node_label("?") == "?"


# ---------------------------------------------------------------------------
# Claim kinds
# ---------------------------------------------------------------------------


def test_edge_claim_query_is_readable(tmp_path):
    graph = _graph(tmp_path,
        classes=[_activity("Event Management"), _activity("Detect & Log Event")],
        relationships=[{"source": "Event Management", "target": "Detect & Log Event",
                        "type": "includes_process", "original_label": "IncludesProcess"}])
    claim = _only(project_ontology(graph, ["edge"]))
    assert claim.query == "Event Management includes the process Detect & Log Event"
    assert claim.assertion_id == "edge:Event Management|includes_process|Detect & Log Event"
    assert claim.provenance.edge_type == "includes_process"
    assert claim.provenance.original_label == "IncludesProcess"


def test_sipoc_skips_the_null_sentinel(tmp_path):
    """An unpopulated SIPOC field must yield no claim, not a claim about "null"."""
    graph = _graph(tmp_path, classes=[{
        "id": "Assure", "meta_class": "Activity_Class",
        "attributes": {"type": ["Domain Activity"], "supplier": ["Detect to Correct"],
                       "input": ["null"], "output": ["null"], "customer": ["Event Management"]},
    }])
    claims = project_ontology(graph, ["sipoc"])
    assert {c.query for c in claims} == {
        "Assure is supplied by Detect to Correct",
        "Assure delivers to Event Management",
    }


def test_sipoc_excludes_the_process_attribute(tmp_path):
    """`process` restates the node's own name, so it yields a tautology."""
    graph = _graph(tmp_path, classes=[{
        "id": "Assure", "meta_class": "Activity_Class",
        "attributes": {"type": ["Domain Activity"], "process": ["Assure"]},
    }])
    assert project_ontology(graph, ["sipoc"]) == []


def test_sipoc_only_applies_to_activities(tmp_path):
    graph = _graph(tmp_path, classes=[{
        "id": "Config", "meta_class": "Information_Class",
        "attributes": {"type": ["Dimension"], "supplier": ["X"]},
    }])
    assert project_ontology(graph, ["sipoc"]) == []


def test_decision_condition_stays_out_of_the_query(tmp_path):
    """Conditions are agent plumbing; folding them in adds unmatchable noise."""
    graph = _graph(tmp_path, classes=[
        _activity("Handle Duplicate Event"),
        {"id": "filter out event ?", "meta_class": "Decision_Class",
         "attributes": {"type": ["Decision Node"]},
         "agent_rules": {"execution": [{"action": "evaluate_decision", "branches": [
             {"condition": {"AND": [
                 {"property": "payload.arrival_delta_mins", "operator": "<", "value": 30},
                 {"property": "payload.is_identical", "operator": "==", "value": True}]},
              "target": "Handle Duplicate Event"}]}]}},
    ])
    claim = _only(project_ontology(graph, ["decision"]))
    assert claim.query == "filter out event routes to Handle Duplicate Event"
    assert claim.provenance.condition == (
        "arrival delta mins is less than 30 and is identical equals True"
    )


def test_default_branch_condition_is_verbalized(tmp_path):
    graph = _graph(tmp_path, classes=[
        _activity("Create Event"),
        {"id": "d ?", "meta_class": "Decision_Class",
         "agent_rules": {"execution": [{"action": "evaluate_decision", "branches": [
             {"condition": "default", "target": "Create Event"}]}]}},
    ])
    assert _only(project_ontology(graph, ["decision"])).provenance.condition == "by default"


def test_branch_target_that_is_not_a_node_is_skipped(tmp_path):
    """V4 has one: `is major incident ?` targets the action name `trace_back`.

    There is no ontology element for a document to agree with, so grounding
    skips it. The conformance engine reports it instead.
    """
    graph = _graph(tmp_path, classes=[
        _activity("Major Incident Management"),
        {"id": "is major incident ?", "meta_class": "Decision_Class",
         "agent_rules": {"execution": [{"action": "evaluate_decision", "branches": [
             {"condition": "x", "target": "Major Incident Management"},
             {"condition": "default", "target": "trace_back"}]}]}},
    ])
    claims = project_ontology(graph, ["decision"])
    assert [c.assertion.object for c in claims] == ["Major Incident Management"]


def test_description_claim_strips_authoring_prefix(tmp_path):
    graph = _graph(tmp_path, classes=[{
        "id": "filter out event ?", "meta_class": "Decision_Class",
        "description": "Decision node: Should this event be filtered out as noise?",
    }])
    claim = _only(project_ontology(graph, ["description"]))
    assert claim.query == (
        "filter out event is described as Should this event be filtered out as noise?"
    )


def test_empty_description_yields_no_claim(tmp_path):
    graph = _graph(tmp_path, classes=[{"id": "A", "meta_class": "Activity_Class", "description": "  "}])
    assert project_ontology(graph, ["description"]) == []


# ---------------------------------------------------------------------------
# Selection and invariants
# ---------------------------------------------------------------------------


def test_claim_kind_selection_is_respected(tmp_path):
    graph = _graph(tmp_path,
        classes=[_activity("A", supplier=["S"]), _activity("B")],
        relationships=[{"source": "A", "target": "B", "type": "triggers"}])
    assert {c.provenance.kind for c in project_ontology(graph, ["edge"])} == {ClaimKind.EDGE}
    assert len(project_ontology(graph)) == len(project_ontology(graph, ALL_CLAIM_KINDS))


def test_unknown_claim_kind_raises_rather_than_silently_dropping(tmp_path):
    """A config typo that quietly halves the validated surface is a bad failure."""
    graph = _graph(tmp_path, classes=[_activity("A")])
    with pytest.raises(ValueError) as exc:
        project_ontology(graph, ["edge", "typo"])
    assert "typo" in str(exc.value)


def test_rule_type_carries_the_claim_kind(tmp_path):
    graph = _graph(tmp_path,
        classes=[_activity("A", supplier=["S"])],
        relationships=[])
    claim = _only(project_ontology(graph, ["sipoc"]))
    assert claim.assertion.rule_type == "sipoc"
    assert claim.assertion.polarity == "must_hold"


def test_assertion_ids_are_unique_across_all_kinds(tmp_path):
    """Verdicts are cached by assertion_id; a collision shares one verdict."""
    graph = _graph(tmp_path,
        classes=[_activity("A", supplier=["S", "S"]), _activity("B")],
        relationships=[{"source": "A", "target": "B", "type": "triggers"}])
    claims = project_ontology(graph)
    ids = [c.assertion_id for c in claims]
    assert len(ids) == len(set(ids))
    assert set(provenance_index(claims)) == set(ids)


def test_helpers_round_trip(tmp_path):
    graph = _graph(tmp_path, classes=[_activity("A", supplier=["S"])])
    claims = project_ontology(graph, ["sipoc"])
    assert [a.assertion_id for a in claims_to_assertions(claims)] == [c.assertion_id for c in claims]


# ---------------------------------------------------------------------------
# Against the shipped ontology, when it is present
# ---------------------------------------------------------------------------


def test_shipped_ontology_projects_cleanly(shipped_ontology):
    """Inputs are gitignored; skip rather than fail on a clean checkout."""
    claims = project_ontology(shipped_ontology)
    assert len(claims) > 200
    by_kind = {}
    for claim in claims:
        by_kind[claim.provenance.kind] = by_kind.get(claim.provenance.kind, 0) + 1
    assert by_kind[ClaimKind.EDGE] == len(shipped_ontology.edges)
    # No query may leak a sentinel, a raw edge type, or a question mark.
    for claim in claims:
        assert "null" not in claim.query.split(), claim.query
        assert "_" not in claim.assertion.relation, claim.query
        assert "?" not in claim.assertion.subject, claim.query


@pytest.fixture
def shipped_ontology():
    import os
    from src.ontology.loader import DEFAULT_ONTOLOGY_PATH
    if not os.path.exists(DEFAULT_ONTOLOGY_PATH):
        pytest.skip(f"ontology input not present at {DEFAULT_ONTOLOGY_PATH} (gitignored)")
    return load_ontology()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _activity(node_id, **attrs):
    attributes = {"type": ["Process Activity"]}
    attributes.update(attrs)
    return {"id": node_id, "meta_class": "Activity_Class", "attributes": attributes}


def _graph(tmp_path, classes, relationships=None):
    path = tmp_path / f"ont_{len(list(tmp_path.iterdir()))}.json"
    path.write_text(json.dumps({"Ontology": {
        "classes": classes, "relationships": relationships or [], "systemic_rules": [],
    }}), encoding="utf-8")
    return load_ontology(str(path))


def _only(claims):
    assert len(claims) == 1, f"expected exactly one claim, got {[c.query for c in claims]}"
    return claims[0]
