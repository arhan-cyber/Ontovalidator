"""Retrieval pathway: per-retriever score/rank capture and their explanations."""

from src.fusion import WeightedFusionEngine
from src.models import RetrievalResult
from src.retrieval.explainer import RetrieverExplainer


def _results():
    return [
        RetrievalResult(chunk_id="a", score=3.0, source="lexical"),
        RetrievalResult(chunk_id="b", score=1.0, source="lexical"),
        RetrievalResult(chunk_id="a", score=0.4, source="semantic"),
        RetrievalResult(chunk_id="c", score=0.9, source="semantic"),
        RetrievalResult(chunk_id="a", score=0.8, source="graph"),
    ]


class TestFusionScoreCapture:
    def test_fusion_records_per_retriever_scores_and_ranks(self):
        ranked = WeightedFusionEngine().fuse_and_rank(_results(), top_k=10)
        by_id = {r.chunk_id: r for r in ranked}

        assert by_id["a"].lexical_score == 3.0
        assert by_id["a"].lexical_rank == 1
        assert by_id["a"].semantic_score == 0.4
        assert by_id["a"].semantic_rank == 2
        assert by_id["a"].graph_score == 0.8
        assert by_id["a"].graph_rank == 1
        assert by_id["a"].retriever_sources == ["graph", "lexical", "semantic"]

    def test_scores_are_none_for_retrievers_that_missed_the_chunk(self):
        ranked = WeightedFusionEngine().fuse_and_rank(_results(), top_k=10)
        by_id = {r.chunk_id: r for r in ranked}

        assert by_id["c"].lexical_score is None
        assert by_id["c"].graph_score is None
        assert by_id["c"].semantic_score == 0.9

    def test_fusion_breakdown_reproduces_the_final_score(self):
        ranked = WeightedFusionEngine().fuse_and_rank(_results(), top_k=10)
        result = next(r for r in ranked if r.chunk_id == "a")
        breakdown = result.fusion_breakdown

        recomputed = sum(
            breakdown["weights"][name] * breakdown["normalized"][name]
            for name in ("lexical", "semantic", "graph")
        )
        assert round(recomputed, 4) == breakdown["base_score"]
        assert round(breakdown["base_score"] + breakdown["cross_source_boost"], 4) == round(result.score, 4)

    def test_ranks_reflect_score_order_not_input_order(self):
        unsorted = [
            RetrievalResult(chunk_id="low", score=0.1, source="lexical"),
            RetrievalResult(chunk_id="high", score=9.0, source="lexical"),
        ]
        ranked = WeightedFusionEngine().fuse_and_rank(unsorted, top_k=10)
        by_id = {r.chunk_id: r for r in ranked}

        assert by_id["high"].lexical_rank == 1
        assert by_id["low"].lexical_rank == 2


class TestRetrieverExplainer:
    def test_lexical_explanation_names_the_matching_terms(self):
        explainer = RetrieverExplainer()
        text = explainer.explain_lexical(
            "Aspirin treats headache", 3.0, 1, "Aspirin treats headache and fever."
        )
        assert "'aspirin'" in text
        assert "3/3 query terms" in text
        assert "rank 1" in text

    def test_semantic_explanation_reports_similarity(self):
        text = RetrieverExplainer().explain_semantic("q", 0.9231, 2)
        assert "0.9231" in text
        assert "rank 2" in text

    def test_explanations_say_so_when_a_retriever_missed_the_chunk(self):
        explainer = RetrieverExplainer()
        assert "Not retrieved" in explainer.explain_lexical("q", None, None)
        assert "Not retrieved" in explainer.explain_semantic("q", None, None)
        assert "Not retrieved" in explainer.explain_graph("q", None, None)

    def test_fusion_explanation_shows_the_weighted_formula(self):
        ranked = WeightedFusionEngine().fuse_and_rank(_results(), top_k=10)
        result = next(r for r in ranked if r.chunk_id == "a")

        text = RetrieverExplainer().explain_fusion(
            result.lexical_score,
            result.semantic_score,
            result.graph_score,
            result.score,
            result.fusion_breakdown,
        )
        assert "0.3x" in text and "0.5x" in text and "0.2x" in text
        assert "cross-source boost" in text

    def test_build_pathway_contains_every_retriever_and_the_fusion_score(self):
        ranked = WeightedFusionEngine().fuse_and_rank(_results(), top_k=10)
        result = next(r for r in ranked if r.chunk_id == "a")

        pathway = RetrieverExplainer().build_pathway("Aspirin treats headache", result, "Aspirin treats headache.")

        assert set(pathway) == {
            "lexical", "semantic", "graph", "retriever_sources", "fusion_score", "fusion_explanation",
        }
        for source in ("lexical", "semantic", "graph"):
            assert set(pathway[source]) == {"rank", "score", "reason"}
        assert pathway["fusion_score"] == round(result.score, 4)
