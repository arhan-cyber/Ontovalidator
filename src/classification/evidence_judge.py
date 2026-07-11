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


class FewShotPromptEvidenceJudge(BaseEvidenceJudge):
    """Generative few-shot LM judge (Flan-T5-style) with heuristic fallback.

    Unlike PromptEvidenceJudge (an NLI zero-shot-classification pipeline, which
    doesn't support exemplar-based in-context learning), this judge prompts a
    generative instruction-tuned model with worked Evidence -> Label examples
    and parses the label out of the generated text, mirroring the few-shot
    pattern already used by TransformerConceptExtractor in this codebase.
    """

    LABELS = ("supported", "contradicted", "partial", "unknown")

    # Despite the few-shot examples showing the exact label words, generative models
    # sometimes paraphrase (e.g. "insufficient" instead of "unknown"). Map common
    # paraphrases to the canonical label rather than falling back to the heuristic.
    LABEL_ALIASES = {
        "support": "supported",
        "entail": "supported",
        "true": "supported",
        "contradict": "contradicted",
        "refute": "contradicted",
        "false": "contradicted",
        "partially": "partial",
        "mixed": "partial",
        "insufficient": "unknown",
        "not enough": "unknown",
        "no evidence": "unknown",
        "cannot determine": "unknown",
        "unclear": "unknown",
        "neutral": "unknown",
    }

    FEW_SHOT_EXAMPLES = [
        {
            "claim": "Aspirin treats headache",
            "evidence": "- [c1] lexical score=0.90 support=supports: Aspirin is commonly used to treat headache and relieve pain.",
            "graph_summary": "none",
            "label": "supported",
        },
        {
            "claim": "Aspirin treats malaria",
            "evidence": "- [c2] lexical score=0.85 support=refutes: Aspirin does not treat malaria; specific anti-malarial drugs are required instead.",
            "graph_summary": "none",
            "label": "contradicted",
        },
        {
            "claim": "Ibuprofen reduces inflammation",
            "evidence": "- [c3] semantic score=0.40 support=partial: Ibuprofen is an NSAID commonly used for pain relief.",
            "graph_summary": "none",
            "label": "partial",
        },
        {
            "claim": "Aspirin cures diabetes",
            "evidence": "- [c4] lexical score=0.10 support=unknown: This document discusses Aspirin's use for pain relief and fever, with no mention of diabetes.",
            "graph_summary": "none",
            "label": "unknown",
        },
    ]

    def __init__(self, model_name: str = "google/flan-t5-large"):
        self.model_name = model_name
        self._fallback = HeuristicEvidenceJudge()
        self.model = None
        self.tokenizer = None
        try:
            from transformers import T5Tokenizer, AutoModelForSeq2SeqLM
            self.tokenizer = T5Tokenizer.from_pretrained(model_name)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        except Exception:
            self.model = None
            self.tokenizer = None

    @staticmethod
    def _format_case(claim: str, evidence: str, graph_summary: str, label: str = None) -> str:
        block = f"Claim: {claim}\nEvidence:\n{evidence}\nGraph summary: {graph_summary}\nLabel:"
        if label is not None:
            block += f" {label}"
        return block

    def _build_few_shot_prompt(self, evidence_pack: EvidencePack) -> str:
        instructions = (
            "Classify whether the retrieved evidence supports, contradicts, partially "
            "supports, or is insufficient (unknown) to judge the claim. Respond with "
            "exactly one word: supported, contradicted, partial, or unknown."
        )
        examples = [
            f"Example {i}:\n" + self._format_case(ex["claim"], ex["evidence"], ex["graph_summary"], ex["label"])
            for i, ex in enumerate(self.FEW_SHOT_EXAMPLES, 1)
        ]

        claim = f"{evidence_pack.subject} {evidence_pack.relation} {evidence_pack.object}"
        evidence_lines = "\n".join(
            f"- [{e.chunk_id}] {e.source} score={e.retrieval_score:.3f} support={e.support_type}: {e.text}"
            for e in evidence_pack.evidence
        ) or "- none"
        graph_lines = "; ".join(evidence_pack.graph_summary) if evidence_pack.graph_summary else "none"
        case = "Now classify the following:\n" + self._format_case(claim, evidence_lines, graph_lines)

        return instructions + "\n\n" + "\n\n".join(examples) + "\n\n" + case

    @staticmethod
    def _sequence_confidence(scores, generated_ids) -> float:
        import torch

        if not scores:
            return 0.6
        probs = []
        for step_logits, token_id in zip(scores, generated_ids[1:]):
            step_probs = torch.softmax(step_logits[0], dim=-1)
            probs.append(max(step_probs[token_id].item(), 1e-9))
        if not probs:
            return 0.6
        geo_mean = 1.0
        for p in probs:
            geo_mean *= p
        geo_mean = geo_mean ** (1.0 / len(probs))
        return round(min(1.0, max(0.3, geo_mean)), 4)

    def judge(self, evidence_pack: EvidencePack) -> JudgeVerdict:
        if self.model is None or self.tokenizer is None:
            return self._fallback.judge(evidence_pack)

        prompt = self._build_few_shot_prompt(evidence_pack)
        try:
            import torch

            inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=768)
            with torch.no_grad():
                output = self.model.generate(
                    **inputs,
                    max_new_tokens=5,
                    num_beams=1,
                    return_dict_in_generate=True,
                    output_scores=True,
                )
            generated_ids = output.sequences[0]
            text = self.tokenizer.decode(generated_ids, skip_special_tokens=True).strip().lower()

            label = next((candidate for candidate in self.LABELS if candidate in text), None)
            if label is None:
                label = next((canonical for alias, canonical in self.LABEL_ALIASES.items() if alias in text), None)
            if label is None:
                verdict = self._fallback.judge(evidence_pack)
                verdict.rationale = f"{verdict.rationale} Few-shot LM judge produced unparsable output: {text!r}".strip()
                return verdict

            confidence = self._sequence_confidence(output.scores, generated_ids)
            support_ids = [e.chunk_id for e in evidence_pack.evidence if e.support_type == "supports"]
            counter_ids = [e.chunk_id for e in evidence_pack.evidence if e.support_type == "refutes"]
            graph_reasoning = "; ".join(evidence_pack.graph_summary) if evidence_pack.graph_summary else None
            return JudgeVerdict(
                label=label,
                confidence=confidence,
                rationale=f"Few-shot LM judge selected {label!r} from the evidence pack.",
                evidence_chunk_ids=support_ids,
                counterevidence_chunk_ids=counter_ids,
                graph_reasoning=graph_reasoning,
            )
        except Exception as exc:
            verdict = self._fallback.judge(evidence_pack)
            verdict.rationale = f"{verdict.rationale} Few-shot LM judge failed: {exc}".strip()
            return verdict


__all__ = [
    "BaseEvidenceJudge",
    "HeuristicEvidenceJudge",
    "PromptEvidenceJudge",
    "FewShotPromptEvidenceJudge",
]
