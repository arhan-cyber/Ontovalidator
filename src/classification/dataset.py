"""Dataset and training example utilities."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Iterable
import json
from pathlib import Path


@dataclass
class AssertionInput:
    assertion_id: str
    subject: str
    relation: str
    object: str
    polarity: str = "must_hold"
    rule_type: str = "constraint"


@dataclass
class TripleClassificationExample:
    example_id: str
    task: str
    document_id: str
    chunk_id: str
    input: Dict[str, Any]
    output: Dict[str, Any]

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=True)


@dataclass
class TripleClassificationResult:
    label: str
    confidence: float
    rationale: str
    raw_output: Optional[str] = None


class TripleDatasetWriter:
    """Append-only JSONL writer for QLoRA-style training data."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_example(self, example: TripleClassificationExample) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(example.to_jsonl() + "\n")

    def write_examples(self, examples: Iterable[TripleClassificationExample]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            for example in examples:
                handle.write(example.to_jsonl() + "\n")


def triple_training_example(
    example_id: str,
    document_id: str,
    chunk_id: str,
    chunk_text: str,
    assertion: Dict[str, Any],
    label: str,
    score_bucket: str,
    rationale: str,
) -> TripleClassificationExample:
    return TripleClassificationExample(
        example_id=example_id,
        task="triple_classification",
        document_id=document_id,
        chunk_id=chunk_id,
        input={
            "chunk_text": chunk_text,
            "assertion": assertion,
        },
        output={
            "label": label,
            "score_bucket": score_bucket,
            "rationale": rationale,
        },
    )


def score_bucket_from_confidence(confidence: float) -> str:
    if confidence >= 0.9:
        return "very_high"
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.5:
        return "medium"
    if confidence >= 0.25:
        return "low"
    return "very_low"


def triple_verdict_to_example(
    verdict: Any,
    document_id: str = "unknown_document",
    chunk_id: Optional[str] = None,
) -> TripleClassificationExample:
    """Convert a TripleVerdict into a training example."""
    top_evidence = verdict.evidence[0] if getattr(verdict, "evidence", None) else None
    chosen_chunk_id = chunk_id or getattr(top_evidence, "chunk_id", "unknown_chunk")
    chunk_text = getattr(top_evidence, "text", "")
    return TripleClassificationExample(
        example_id=f"ex_{getattr(verdict, 'assertion_id', 'unknown')}_{chosen_chunk_id}",
        task="triple_classification",
        document_id=document_id,
        chunk_id=chosen_chunk_id,
        input={
            "chunk_text": chunk_text,
            "assertion": {
                "assertion_id": getattr(verdict, "assertion_id", ""),
                "subject": getattr(verdict, "subject", ""),
                "relation": getattr(verdict, "relation", ""),
                "object": getattr(verdict, "object", ""),
                "polarity": "must_hold",
                "rule_type": "constraint",
            },
        },
        output={
            "label": getattr(verdict, "label", "unknown"),
            "score_bucket": score_bucket_from_confidence(float(getattr(verdict, "score", 0.0))),
            "rationale": getattr(verdict, "rationale", ""),
            "retrieval_sources": getattr(verdict, "retrieval_sources", []),
            "rule_hits": getattr(verdict, "rule_hits", []),
        },
    )
