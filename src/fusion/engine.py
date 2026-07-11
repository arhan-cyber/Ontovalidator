"""Fusion engine for combining multi-modal retrieval results."""

from abc import ABC, abstractmethod
from typing import List

from ..models import RetrievalResult


class FusionEngine(ABC):
    @abstractmethod
    def fuse_and_rank(self, results: List[RetrievalResult], top_k: int) -> List[RetrievalResult]:
        pass


class WeightedFusionEngine(FusionEngine):
    """Fuses results from multiple retrievers with weighted scoring and cross-source boost."""

    def fuse_and_rank(self, results: List[RetrievalResult], top_k: int) -> List[RetrievalResult]:
        if not results:
            return []

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
            base_score = (0.3 * norm_lex) + (0.5 * norm_sem) + (0.2 * norm_graph)

            # Cross-source boost: +0.1 for every additional source beyond the first
            boost = 0.1 * (len(data["sources"]) - 1)
            final_score = base_score + boost

            fused_results.append(RetrievalResult(
                chunk_id=chunk_id,
                score=final_score,
                source="fusion",
                contributing_sources=sorted(data["sources"]),
            ))

        # 4. Return top-K ranked results
        fused_results.sort(key=lambda x: x.score, reverse=True)
        return fused_results[:top_k]
