"""Human-readable explanations for how each retriever scored a chunk."""

import re
from typing import Any, Dict, List, Optional

from ..models import RetrievalResult


def _tokens(text: str) -> List[str]:
    return re.findall(r"\w+", text.lower())


class RetrieverExplainer:
    """Turns per-retriever scores and ranks into sentences a reviewer can read.

    Explanations are derived from the numbers the retrievers actually produced,
    so they stay truthful even when a retriever is swapped for a different
    implementation; the wording describes the score, never a guessed mechanism.
    """

    MAX_LISTED_TERMS = 4

    def _overlap_terms(self, query: str, chunk_text: Optional[str]) -> List[str]:
        if not chunk_text:
            return []
        query_tokens = _tokens(query)
        chunk_tokens = set(_tokens(chunk_text))
        seen = []
        for token in query_tokens:
            if token in chunk_tokens and token not in seen:
                seen.append(token)
        return seen

    def _term_phrase(self, query: str, chunk_text: Optional[str]) -> str:
        terms = self._overlap_terms(query, chunk_text)
        if not terms:
            return ""
        shown = terms[: self.MAX_LISTED_TERMS]
        listed = " + ".join(f"'{t}'" for t in shown)
        if len(terms) > len(shown):
            listed += f" (+{len(terms) - len(shown)} more)"
        total = len(set(_tokens(query)))
        return f" on {listed} ({len(terms)}/{total} query terms)"

    def explain_lexical(
        self,
        query: str,
        score: Optional[float],
        rank: Optional[int],
        chunk_text: Optional[str] = None,
    ) -> str:
        if score is None:
            return "Not retrieved by the lexical retriever."
        return (
            f"Lexical match{self._term_phrase(query, chunk_text)}; "
            f"score {round(float(score), 4)}, rank {rank if rank is not None else 'n/a'}."
        )

    def explain_semantic(
        self,
        query: str,
        score: Optional[float],
        rank: Optional[int],
        chunk_text: Optional[str] = None,
    ) -> str:
        if score is None:
            return "Not retrieved by the semantic retriever."
        return (
            f"Vector similarity {round(float(score), 4)} between the query embedding "
            f"and this chunk; rank {rank if rank is not None else 'n/a'}."
        )

    def explain_graph(
        self,
        query: str,
        score: Optional[float],
        rank: Optional[int],
        chunk_text: Optional[str] = None,
    ) -> str:
        if score is None:
            return "Not retrieved by the graph retriever."
        return (
            f"Reached by concept-graph traversal with path score {round(float(score), 4)} "
            f"(score decays 0.8x per hop); rank {rank if rank is not None else 'n/a'}."
        )

    def explain_fusion(
        self,
        lexical: Optional[float],
        semantic: Optional[float],
        graph: Optional[float],
        final_score: float,
        breakdown: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not breakdown:
            return f"Fused score {round(float(final_score), 4)}."

        weights = breakdown.get("weights", {})
        normalized = breakdown.get("normalized", {})
        parts = " + ".join(
            f"{weights.get(name, 0)}x{normalized.get(name, 0)}"
            for name in ("lexical", "semantic", "graph")
        )
        boost = breakdown.get("cross_source_boost", 0.0)
        text = f"Weighted: {parts} = {breakdown.get('base_score')}"
        if boost:
            text += f", + {boost} cross-source boost"
        return f"{text} => {round(float(final_score), 4)}."

    def build_pathway(
        self,
        query: str,
        result: RetrievalResult,
        chunk_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Assemble the full retrieval_pathway payload for one fused result."""
        return {
            "lexical": {
                "rank": result.lexical_rank,
                "score": result.lexical_score,
                "reason": self.explain_lexical(query, result.lexical_score, result.lexical_rank, chunk_text),
            },
            "semantic": {
                "rank": result.semantic_rank,
                "score": result.semantic_score,
                "reason": self.explain_semantic(query, result.semantic_score, result.semantic_rank, chunk_text),
            },
            "graph": {
                "rank": result.graph_rank,
                "score": result.graph_score,
                "reason": self.explain_graph(query, result.graph_score, result.graph_rank, chunk_text),
            },
            "retriever_sources": list(result.retriever_sources or result.contributing_sources),
            "fusion_score": round(float(result.score), 4),
            "fusion_explanation": self.explain_fusion(
                result.lexical_score,
                result.semantic_score,
                result.graph_score,
                result.score,
                result.fusion_breakdown,
            ),
        }


__all__ = ["RetrieverExplainer"]
