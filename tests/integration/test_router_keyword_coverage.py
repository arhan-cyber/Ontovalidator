"""Bug 4 repro tests: src/routing/router.py's keyword lists were unstemmed, missing
common inflected forms (e.g. "cause" without a following "-s" wasn't recognized even
though "causes" was), and route(None) crashed instead of degrading gracefully.
"""

import pytest

from src.models import QueryType
from src.routing.router import MoERouter


@pytest.fixture
def router():
    return MoERouter()


def test_cause_without_s_routes_complex_and_still_matches_others(router):
    # Confirmed repro from the bug report.
    routes = router.route(
        "Does X cause Y through an intermediate pathway that is required by policy?"
    )
    assert QueryType.COMPLEX in routes
    assert QueryType.MULTI_HOP in routes
    assert QueryType.ONTOLOGY in routes


def test_indirect_without_ly_routes_multi_hop(router):
    routes = router.route("Is there an indirect relationship between X and Y?")
    assert QueryType.MULTI_HOP in routes


def test_forbid_and_forbids_route_ontology(router):
    assert QueryType.ONTOLOGY in router.route("Policy X forbids state Y.")
    assert QueryType.ONTOLOGY in router.route("Does the rule forbid this action?")


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Does X relate to Y?", QueryType.COMPLEX),
        ("Does X affect Y?", QueryType.COMPLEX),
        ("Does X impact Y?", QueryType.COMPLEX),
        ("Does X influence Y?", QueryType.COMPLEX),
        ("Does X correlate with Y?", QueryType.COMPLEX),
        ("Does X improve Y?", QueryType.COMPLEX),
        ("Does X connect to Y?", QueryType.MULTI_HOP),
        ("Is Y required by the constraint?", QueryType.ONTOLOGY),
    ],
)
def test_base_form_keywords_route_correctly(router, query, expected):
    assert expected in router.route(query)


def test_none_query_does_not_crash_and_returns_fallback(router):
    routes = router.route(None)
    assert set(routes) == {QueryType.COMPLEX, QueryType.EXACT_MATCH}


def test_empty_string_query_returns_fallback(router):
    routes = router.route("")
    assert set(routes) == {QueryType.COMPLEX, QueryType.EXACT_MATCH}


def test_non_string_query_does_not_crash(router):
    routes = router.route(12345)
    assert set(routes) == {QueryType.COMPLEX, QueryType.EXACT_MATCH}


def test_existing_inflected_forms_still_match(router):
    """Regression guard: the original (already-present) inflected forms must keep
    matching after the keyword-list additions."""
    assert QueryType.COMPLEX in router.route("X improves Y.")
    assert QueryType.COMPLEX in router.route("X causes Y.")
    assert QueryType.MULTI_HOP in router.route("X connects indirectly to Y.")
    assert QueryType.ONTOLOGY in router.route("This is forbidden by the rule.")
