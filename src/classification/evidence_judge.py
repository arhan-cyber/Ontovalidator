"""Evidence-level judge abstractions for last-mile triple adjudication."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import EvidencePack, JudgeVerdict


class BaseEvidenceJudge(ABC):
    @abstractmethod
    def judge(self, evidence_pack: EvidencePack) -> JudgeVerdict:
        raise NotImplementedError


class HeuristicEvidenceJudge(BaseEvidenceJudge):
    """Deterministic evidence judge used as the baseline and fallback."""

    def judge(self, evidence_pack: EvidencePack) -> JudgeVerdict:
        supports = [e for e in evidence_pack.evidence if e.support_type == "supports"]
        refutes = [e for e in evidence_pack.evidence if e.support_type == "refutes"]
        partials = [e for e in evidence_pack.evidence if e.support_type == "partial"]

        if refutes and len(refutes) >= len(supports) and sum(e.retrieval_score for e in refutes) >= 0.6:
            return JudgeVerdict(
                label="contradicted",
                confidence=0.8,
                rationale="Evidence contains explicit refutation of the assertion.",
                evidence_chunk_ids=[e.chunk_id for e in supports],
                counterevidence_chunk_ids=[e.chunk_id for e in refutes],
                graph_reasoning=None,
            )
        if supports and not refutes and any(e.matched_subject and e.matched_relation and e.matched_object for e in supports):
            return JudgeVerdict(
                label="supported",
                confidence=0.88,
                rationale="Evidence contains a direct support match for the assertion.",
                evidence_chunk_ids=[e.chunk_id for e in supports],
                counterevidence_chunk_ids=[],
                graph_reasoning=None,
            )
        if supports or partials:
            return JudgeVerdict(
                label="partial",
                confidence=0.55,
                rationale="Evidence partially matches the assertion but is not conclusive.",
                evidence_chunk_ids=[e.chunk_id for e in supports or partials],
                counterevidence_chunk_ids=[e.chunk_id for e in refutes],
                graph_reasoning=None,
            )
        return JudgeVerdict(
            label="unknown",
            confidence=0.2,
            rationale="The evidence is insufficient to determine the assertion.",
            evidence_chunk_ids=[],
            counterevidence_chunk_ids=[e.chunk_id for e in refutes],
            graph_reasoning=None,
        )


class PromptEvidenceJudge(BaseEvidenceJudge):
    """LM-backed evidence judge with heuristic fallback."""

    def __init__(self, model_name: str = "typeform/distilbert-base-uncased-mnli"):
        self.model_name = model_name
        self._fallback = HeuristicEvidenceJudge()
        self.classifier = None
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self.classifier = pipeline("zero-shot-classification", model=model, tokenizer=tokenizer)
        except Exception:
            self.classifier = None

    def _build_prompt(self, evidence_pack: EvidencePack) -> str:
        evidence_lines = []
        for entry in evidence_pack.evidence:
            evidence_lines.append(
                f"- [{entry.chunk_id}] {entry.source} score={entry.retrieval_score:.3f} support={entry.support_type}: {entry.text}"
            )
        graph_lines = "\n".join(f"- {line}" for line in evidence_pack.graph_summary) or "- none"
        return (
            f"Assertion: {evidence_pack.subject} {evidence_pack.relation} {evidence_pack.object}\n"
            f"Polarity: {evidence_pack.polarity}\n"
            f"Rule type: {evidence_pack.rule_type}\n"
            f"Evidence:\n{chr(10).join(evidence_lines)}\n"
            f"Graph summary:\n{graph_lines}"
        )

    def judge(self, evidence_pack: EvidencePack) -> JudgeVerdict:
        if self.classifier is None:
            return self._fallback.judge(evidence_pack)

        prompt = self._build_prompt(evidence_pack)
        candidate_labels = ["supported", "contradicted", "partial", "unknown"]
        try:
            result = self.classifier(prompt, candidate_labels=candidate_labels)
            label = result["labels"][0]
            confidence = float(result["scores"][0])
            rationale = f"LM judge selected {label!r} from the evidence pack."
            support_ids = [e.chunk_id for e in evidence_pack.evidence if e.support_type == "supports"]
            counter_ids = [e.chunk_id for e in evidence_pack.evidence if e.support_type == "refutes"]
            graph_reasoning = "; ".join(evidence_pack.graph_summary) if evidence_pack.graph_summary else None
            return JudgeVerdict(
                label=label,
                confidence=confidence,
                rationale=rationale,
                evidence_chunk_ids=support_ids,
                counterevidence_chunk_ids=counter_ids,
                graph_reasoning=graph_reasoning,
            )
        except Exception as exc:
            verdict = self._fallback.judge(evidence_pack)
            verdict.rationale = f"{verdict.rationale} LM judge failed: {exc}".strip()
            return verdict


__all__ = [
    "BaseEvidenceJudge",
    "HeuristicEvidenceJudge",
    "PromptEvidenceJudge",
]
