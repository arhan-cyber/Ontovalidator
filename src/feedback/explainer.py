"""Explains why a retrieved chunk did not make it into a verdict."""

from typing import List

from ..models import EvidenceSpan


class RejectionExplainer:
    """Produces a one-line reason for each chunk that was retrieved but unused."""

    def explain(self, rejected_span: EvidenceSpan, used_evidence: List[EvidenceSpan]) -> str:
        if rejected_span.support_type == "unknown":
            matched_count = sum(
                (
                    rejected_span.matched_subject,
                    rejected_span.matched_relation,
                    rejected_span.matched_object,
                )
            )
            return f"Too weak to be used (only {matched_count}/3 components matched)"

        if rejected_span.support_type == "partial":
            if not rejected_span.matched_relation:
                return "Relation component missing"
            if not rejected_span.matched_subject:
                return "Subject component missing"
            if not rejected_span.matched_object:
                return "Object component missing"
            return "Partial match, superseded by stronger evidence"

        same_type = [e for e in used_evidence if e.support_type == rejected_span.support_type]
        if same_type:
            best = max(e.confidence for e in same_type)
            if rejected_span.confidence < best:
                return (
                    f"Lower confidence ({round(rejected_span.confidence, 4)}) "
                    f"than used evidence ({round(best, 4)})"
                )
        return "Superseded by stronger evidence"


__all__ = ["RejectionExplainer"]
