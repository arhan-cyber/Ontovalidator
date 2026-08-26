"""MoERouter now actually gates which retrievers get queried.

Previously `route()`'s result was only logged ("unused for gating" - an
explicit comment in the old code); all three retrievers ran on every
request regardless of query type. `ONTO_ENABLE_QUERY_ROUTING=false` is the
rollback switch back to that old always-query-all-three behavior.
"""

from unittest import mock

from src.config import PipelineConfig, BackendMode
from src.engine import SVOVerificationEngine
from src.models import OntologyAssertion, QueryType
from src.routing.router import MoERouter, retrievers_for, ROUTE_RETRIEVERS, ALL_RETRIEVERS


def test_retrievers_for_maps_each_route_type():
    assert retrievers_for([QueryType.EXACT_MATCH]) == {"lexical"}
    assert retrievers_for([QueryType.COMPLEX]) == {"semantic"}
    assert retrievers_for([QueryType.MULTI_HOP]) == {"graph"}
    assert retrievers_for([QueryType.ONTOLOGY]) == {"lexical", "graph"}


def test_retrievers_for_unions_multiple_routes():
    active = retrievers_for([QueryType.EXACT_MATCH, QueryType.MULTI_HOP])
    assert active == {"lexical", "graph"}


def test_retrievers_for_empty_routes_falls_back_to_all():
    assert retrievers_for([]) == set(ALL_RETRIEVERS)


def test_exact_match_query_routes_to_lexical_only():
    router = MoERouter()
    routes = router.route('"EXACT_PHRASE_12345"')
    assert QueryType.EXACT_MATCH in routes
    assert retrievers_for(routes) == {"lexical"}


def _make_engine(temp_db_path, enable_routing=True):
    config = PipelineConfig(
        backend_mode=BackendMode.DEMO,
        sqlite_path=temp_db_path,
        enable_query_routing=enable_routing,
    )
    return SVOVerificationEngine.from_config(config)


def test_routing_disabled_queries_all_three_retrievers(temp_db_path, sample_document):
    engine = _make_engine(temp_db_path, enable_routing=False)
    triple = OntologyAssertion(
        assertion_id="t1", subject="Aspirin", relation="treats", object="headache",
        polarity="must_hold", rule_type="constraint",
    )
    engine.validate_triples_batch(document_id="doc1", raw_text=sample_document, triples=[], top_k=5)

    with mock.patch.object(engine.lexical_store, "retrieve", wraps=engine.lexical_store.retrieve) as lex, \
         mock.patch.object(engine.semantic_store, "retrieve", wraps=engine.semantic_store.retrieve) as sem, \
         mock.patch.object(engine.graph_store, "retrieve", wraps=engine.graph_store.retrieve) as graph:
        engine.adjudicate_triple(document_text=None, assertion=triple, document_id="doc1", top_k=5)

    lex.assert_called_once()
    sem.assert_called_once()
    graph.assert_called_once()


def test_routing_enabled_exact_match_only_hits_lexical(temp_db_path, sample_document):
    engine = _make_engine(temp_db_path, enable_routing=True)
    engine.validate_triples_batch(document_id="doc1", raw_text=sample_document, triples=[], top_k=5)

    triple = OntologyAssertion(
        assertion_id="t1",
        subject='"EXACT_PHRASE_12345"',
        relation="matches",
        object="term",
        polarity="must_hold",
        rule_type="constraint",
    )

    with mock.patch.object(engine.lexical_store, "retrieve", wraps=engine.lexical_store.retrieve) as lex, \
         mock.patch.object(engine.semantic_store, "retrieve", wraps=engine.semantic_store.retrieve) as sem, \
         mock.patch.object(engine.graph_store, "retrieve", wraps=engine.graph_store.retrieve) as graph:
        engine.adjudicate_triple(document_text=None, assertion=triple, document_id="doc1", top_k=5)

    lex.assert_called_once()
    sem.assert_not_called()
    graph.assert_not_called()
