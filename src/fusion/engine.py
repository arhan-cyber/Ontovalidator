"""Fusion engine for combining multi-modal retrieval results."""

from abc import ABC, abstractmethod
from typing import Dict, List

from ..models import RetrievalResult


class FusionEngine(ABC):
    @abstractmethod
    def fuse_and_rank(self, results: List[RetrievalResult], top_k: int) -> List[RetrievalResult]:
        pass


class WeightedFusionEngine(FusionEngine):
    """Fuses results from multiple retrievers with weighted scoring and cross-source boost."""

    WEIGHTS = {"lexical": 0.3, "semantic": 0.5, "graph": 0.2}
    CROSS_SOURCE_BOOST = 0.1

    @staticmethod
    def _ranks_by_source(results: List[RetrievalResult]) -> Dict[str, Dict[str, int]]:
        """1-indexed rank of each chunk within each retriever's own result list.

        Ranks are recomputed here rather than taken from list order so that a
        retriever returning unsorted results still gets meaningful ranks.
        """
        by_source: Dict[str, List[RetrievalResult]] = {}
        for res in results:
            by_source.setdefault(res.source, []).append(res)

        ranks: Dict[str, Dict[str, int]] = {}
        for source, source_results in by_source.items():
            ordered = sorted(source_results, key=lambda r: r.score, reverse=True)
            source_ranks: Dict[str, int] = {}
            for index, res in enumerate(ordered, start=1):
                source_ranks.setdefault(res.chunk_id, index)
            ranks[source] = source_ranks
        return ranks

    def fuse_and_rank(self, results: List[RetrievalResult], top_k: int) -> List[RetrievalResult]:
        if not results:
            return []

        ranks = self._ranks_by_source(results)

        # 1. Group by chunk_id
        chunk_data = {}
        for res in results:
            if res.chunk_id not in chunk_data:
                chunk_data[res.chunk_id] = {"lexical": 0.0, "semantic": 0.0, "graph": 0.0, "sources": set()}

            source_key = res.source if res.source in {"lexical", "semantic", "graph"} else "lexical"
            chunk_data[res.chunk_id][source_key] = max(chunk_data[res.chunk_id][source_key], res.score)
            chunk_data[res.chunk_id]["sources"].add(res.source)

        # Extract lexical scores for normalization
        lex_scores = [data["lexical"] for data in chunk_data.values() if data["lexical"] > 0]
        min_lex = min(lex_scores) if lex_scores else 0.0
        max_lex = max(lex_scores) if lex_scores else 0.0

        fused_results = []
        for chunk_id, data in chunk_data.items():
            # 2. Normalize scores
            norm_lex = 0.0
            if data["lexical"] > 0:
                if max_lex > min_lex:
                    norm_lex = (data["lexical"] - min_lex) / (max_lex - min_lex)
                else:
                    norm_lex = 1.0

            norm_sem = max(0.0, min(1.0, data["semantic"]))
            norm_graph = max(0.0, min(1.0, data["graph"]))

            # 3. Calculate weighted score
            base_score = (
                self.WEIGHTS["lexical"] * norm_lex
                + self.WEIGHTS["semantic"] * norm_sem
                + self.WEIGHTS["graph"] * norm_graph
            )

            # Cross-source boost: +0.1 for every additional source beyond the first
            boost = self.CROSS_SOURCE_BOOST * (len(data["sources"]) - 1)
            final_score = base_score + boost

            sources = sorted(data["sources"])
            fused_results.append(RetrievalResult(
                chunk_id=chunk_id,
                score=final_score,
                source="fusion",
                contributing_sources=sources,
                retriever_sources=sources,
                lexical_score=data["lexical"] if "lexical" in data["sources"] else None,
                lexical_rank=ranks.get("lexical", {}).get(chunk_id),
                semantic_score=data["semantic"] if "semantic" in data["sources"] else None,
                semantic_rank=ranks.get("semantic", {}).get(chunk_id),
                graph_score=data["graph"] if "graph" in data["sources"] else None,
                graph_rank=ranks.get("graph", {}).get(chunk_id),
                fusion_breakdown={
                    "weights": dict(self.WEIGHTS),
                    "normalized": {
                        "lexical": round(norm_lex, 4),
                        "semantic": round(norm_sem, 4),
                        "graph": round(norm_graph, 4),
                    },
                    "base_score": round(base_score, 4),
                    "cross_source_boost": round(boost, 4),
                    "final_score": round(final_score, 4),
                },
            ))

        # 4. Return top-K ranked results
        fused_results.sort(key=lambda x: x.score, reverse=True)
        return fused_results[:top_k]
