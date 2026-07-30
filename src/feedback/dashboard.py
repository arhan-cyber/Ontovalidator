"""Turns recorded corrections into metrics and actionable recommendations."""

from typing import Any, Dict, List, Optional

from .recorder import FeedbackRecorder


class FeedbackDashboard:
    """Aggregates feedback into a summary an operator can act on."""

    # A confusion cell needs this many hits before it is worth recommending on.
    MIN_PATTERN_COUNT = 3
    HIGH_ERROR_RATE = 0.5

    def __init__(self, recorder: Optional[FeedbackRecorder] = None):
        self.recorder = recorder or FeedbackRecorder()

    def compute_metrics(self, days: int = 30) -> Dict[str, Any]:
        patterns = self.recorder.get_error_patterns(days)
        retriever_analysis = self.recorder.get_retriever_analysis(days)

        return {
            "summary": {
                "total_corrections": patterns["total_corrections"],
                "system_accuracy": patterns["accuracy"],
                "window_days": days,
            },
            "error_analysis": {
                "most_common_error": self._find_most_common_error(patterns),
                "confusion_matrix": patterns["confusion_matrix"],
            },
            "retriever_performance": {
                "best_combination": retriever_analysis[-1] if retriever_analysis else None,
                "worst_combination": retriever_analysis[0] if retriever_analysis else None,
                "all_combinations": retriever_analysis,
            },
            "recommendations": self._generate_recommendations(patterns, retriever_analysis),
        }

    @staticmethod
    def _find_most_common_error(patterns: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Largest off-diagonal cell of the confusion matrix."""
        worst = None
        for predicted, row in patterns["confusion_matrix"].items():
            for actual, count in row.items():
                if predicted == actual:
                    continue
                if worst is None or count > worst["count"]:
                    worst = {"predicted": predicted, "actual": actual, "count": count}
        return worst

    def _generate_recommendations(
        self,
        patterns: Dict[str, Any],
        retriever_analysis: List[Dict[str, Any]],
    ) -> List[str]:
        recommendations: List[str] = []
        matrix = patterns["confusion_matrix"]

        if matrix.get("supported", {}).get("partial", 0) >= self.MIN_PATTERN_COUNT:
            recommendations.append(
                "Verdicts labelled 'supported' are frequently corrected to 'partial' — "
                "consider raising the support_strength threshold above 0.7."
            )
        if matrix.get("partial", {}).get("supported", 0) >= self.MIN_PATTERN_COUNT:
            recommendations.append(
                "Verdicts labelled 'partial' are frequently corrected to 'supported' — "
                "consider lowering the 'partial' threshold or improving object matching."
            )
        if matrix.get("supported", {}).get("contradicted", 0) >= self.MIN_PATTERN_COUNT:
            recommendations.append(
                "Contradictions are being missed — review negation detection in the "
                "evidence-span classifier."
            )
        if matrix.get("unknown", {}).get("supported", 0) >= self.MIN_PATTERN_COUNT:
            recommendations.append(
                "Supporting evidence is being retrieved but not recognised — review "
                "retrieval recall and the unknown/partial boundary."
            )

        # Only flag a bad retriever combination once there is enough signal for the
        # error rate to mean anything.
        if retriever_analysis:
            worst = retriever_analysis[0]
            if worst["error_rate"] > self.HIGH_ERROR_RATE and worst["total_cases"] >= self.MIN_PATTERN_COUNT:
                recommendations.append(
                    f"Retriever combination {worst['retrieval_sources']} has an error rate of "
                    f"{worst['error_rate']} over {worst['total_cases']} cases — consider reweighting it."
                )

        return recommendations


__all__ = ["FeedbackDashboard"]
