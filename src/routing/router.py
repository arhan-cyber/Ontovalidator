"""Query routing and classification."""

from abc import ABC, abstractmethod
from typing import List, Set
import re

from ..models import QueryType

# Which retrievers a given route actually queries. EXACT_MATCH favors the
# lexical retriever (literal term overlap); COMPLEX favors semantic
# similarity; MULTI_HOP needs the concept graph; ONTOLOGY (constraint/rule
# language) benefits from both exact terms and graph traversal.
ALL_RETRIEVERS: Set[str] = {"lexical", "semantic", "graph"}

ROUTE_RETRIEVERS = {
    QueryType.EXACT_MATCH: {"lexical"},
    QueryType.COMPLEX: {"semantic"},
    QueryType.MULTI_HOP: {"graph"},
    QueryType.ONTOLOGY: {"lexical", "graph"},
}


def retrievers_for(routes: List[QueryType]) -> Set[str]:
    """Union of retrievers to query for a set of matched route types.

    Falls back to querying all three if no route contributed any retriever
    (defensive; `MoERouter.route()` itself never returns an empty list since
    it has its own fallback, but this keeps the mapping safe if a QueryType is
    ever added without a corresponding entry above).
    """
    active: Set[str] = set()
    for route in routes:
        active |= ROUTE_RETRIEVERS.get(route, set())
    return active or set(ALL_RETRIEVERS)


class QueryRouter(ABC):
    @abstractmethod
    def route(self, query: str) -> List[QueryType]:
        pass


class MoERouter(QueryRouter):
    """Mixture-of-Experts router that decides which retrieval modalities to use."""

    def route(self, query: str) -> List[QueryType]:
        if not query or not isinstance(query, str):
            routes = {QueryType.COMPLEX, QueryType.EXACT_MATCH}
            return list(routes)

        query_lower = query.lower()
        routes = set()
        ontology_keywords = [
            "violat", "contradict", "inconsistent", "must",
            "require", "required", "requires", "forbid", "forbids", "forbidden",
            "constraint", "constraints", "rule", "rules",
        ]

        # 1. Multi-hop / Structural Priority
        multi_hop_keywords = ["indirect", "indirectly", "through", "via", "intermediate", "path", "connect", "connects"]
        if any(kw in query_lower for kw in multi_hop_keywords):
            routes.add(QueryType.MULTI_HOP)

        # 2. Complex Relations / Semantic Priority
        complex_keywords = [
            "improve", "improves", "relate", "relates", "affect", "affects",
            "cause", "causes", "impact", "impacts", "influence", "influences",
            "correlate", "correlates", "associated", "similar",
        ]
        if any(kw in query_lower for kw in complex_keywords):
            routes.add(QueryType.COMPLEX)

        # 3. Exact Match / Lexical Priority
        if re.search(r'".+"', query) or re.search(r'\b[A-Z0-9_-]{5,}\b', query):
            routes.add(QueryType.EXACT_MATCH)

        # 4. Ontology / Violation Priority
        if any(kw in query_lower for kw in ontology_keywords):
            routes.add(QueryType.ONTOLOGY)

        # 5. Fallback Strategy
        if not routes:
            routes.add(QueryType.COMPLEX)
            routes.add(QueryType.EXACT_MATCH)

        return list(routes)
