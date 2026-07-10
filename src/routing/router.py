"""Query routing and classification."""

from abc import ABC, abstractmethod
from typing import List
import re

from ..models import QueryType


class QueryRouter(ABC):
    @abstractmethod
    def route(self, query: str) -> List[QueryType]:
        pass


class MoERouter(QueryRouter):
    """Mixture-of-Experts router that decides which retrieval modalities to use."""

    def route(self, query: str) -> List[QueryType]:
        query_lower = query.lower()
        routes = set()
        ontology_keywords = ["violat", "contradict", "inconsistent", "must", "required", "forbidden", "constraint", "rule"]

        # 1. Multi-hop / Structural Priority
        multi_hop_keywords = ["indirectly", "through", "via", "intermediate", "path", "connects"]
        if any(kw in query_lower for kw in multi_hop_keywords):
            routes.add(QueryType.MULTI_HOP)

        # 2. Complex Relations / Semantic Priority
        complex_keywords = ["improves", "relates", "affects", "causes", "impacts", "influences", "correlates", "associated", "similar"]
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
