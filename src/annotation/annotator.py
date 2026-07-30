"""Marks up evidence chunks so a reviewer can see what matched and what negated it."""

import re
from html import escape
from typing import Any, Dict, List, Optional, Tuple

from ..models import EvidenceSpan, OntologyAssertion
from ..classification.evidence_span_classifier import HeuristicEvidenceSpanClassifier

# Ordered longest-first so "does not" wins over "not" when both start at the same offset.
NEGATION_KEYWORDS = [
    "does not",
    "do not",
    "did not",
    "cannot",
    "fails to",
    "failed to",
    "without",
    "never",
    "neither",
    "nor",
    "not",
    "no",
]

_SCOPE_TERMINATORS = ".;:!?"


class ChunkAnnotator:
    """Produces `annotated_html`, negation analysis, and component-match flags for a chunk.

    The classification itself is not repeated here — the engine has already run
    the (possibly model-backed) span classifier, so the resulting `EvidenceSpan`
    is passed in and its match flags are reported verbatim.
    """

    CSS_CLASSES = {"subject": "subject", "relation": "relation", "object": "object"}

    def annotate(
        self,
        chunk_text: str,
        assertion: OntologyAssertion,
        evidence_span: Optional[EvidenceSpan] = None,
    ) -> Dict[str, Any]:
        spans: List[Tuple[int, int, str]] = []
        for component in ("subject", "relation", "object"):
            value = getattr(assertion, component, "") or ""
            for start, end in self._find_spans(chunk_text, value):
                spans.append((start, end, component))

        if evidence_span is not None:
            component_matches = {
                "subject": evidence_span.matched_subject,
                "relation": evidence_span.matched_relation,
                "object": evidence_span.matched_object,
            }
            negation_detected = evidence_span.support_type == "refutes"
        else:
            matched = HeuristicEvidenceSpanClassifier._compute_match_flags(assertion, chunk_text)
            component_matches = {
                "subject": matched[0],
                "relation": matched[1],
                "object": matched[2],
            }
            negation_detected = bool(self._detect_negations(chunk_text))

        negations = self._detect_negations(chunk_text)
        return {
            "annotated_html": self._build_html_with_marks(chunk_text, spans),
            "negation_analysis": {
                "negation_detected": negation_detected,
                "negation_keywords": [n["keyword"] for n in negations],
                "negation_scope": [n["scope"] for n in negations],
            },
            "component_matches": component_matches,
        }

    def _find_spans(self, text: str, needle: str) -> List[Tuple[int, int]]:
        """Case-insensitive, whole-word occurrences of `needle` in `text`."""
        needle = (needle or "").strip()
        if not needle:
            return []
        pattern = r"\s+".join(re.escape(part) for part in needle.split())
        # \b is wrong when the term starts/ends with punctuation, so only guard
        # boundaries on word characters.
        prefix = r"\b" if needle[0].isalnum() else ""
        suffix = r"\b" if needle[-1].isalnum() else ""
        return [m.span() for m in re.finditer(f"{prefix}{pattern}{suffix}", text, re.IGNORECASE)]

    def _build_html_with_marks(self, text: str, spans: List[Tuple[int, int, str]]) -> str:
        """Wrap each matched span in <mark>, dropping spans that overlap an earlier one."""
        # Longest match first at a given offset, so nested terms don't split a longer one.
        ordered = sorted(spans, key=lambda s: (s[0], -(s[1] - s[0])))

        accepted: List[Tuple[int, int, str]] = []
        cursor = 0
        for start, end, component in ordered:
            if start < cursor:
                continue
            accepted.append((start, end, component))
            cursor = end

        parts: List[str] = []
        position = 0
        for start, end, component in accepted:
            parts.append(escape(text[position:start]))
            css_class = self.CSS_CLASSES.get(component, component)
            parts.append(f"<mark class='{css_class}'>{escape(text[start:end])}</mark>")
            position = end
        parts.append(escape(text[position:]))
        return f"<p>{''.join(parts)}</p>"

    def _detect_negations(self, text: str) -> List[Dict[str, Any]]:
        """Locate negation cues and the clause each one scopes over."""
        found: List[Dict[str, Any]] = []
        claimed: List[Tuple[int, int]] = []
        for keyword in NEGATION_KEYWORDS:
            for match in re.finditer(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE):
                start, end = match.span()
                if any(s <= start < e for s, e in claimed):
                    continue
                claimed.append((start, end))
                found.append({
                    "keyword": match.group(0).lower(),
                    "span": [start, end],
                    "scope": self._compute_scope(text, end),
                })
        found.sort(key=lambda n: n["span"][0])
        return found

    def _compute_scope(self, text: str, from_index: int) -> str:
        """Text a negation applies to: up to the next clause terminator."""
        end = len(text)
        for index in range(from_index, len(text)):
            if text[index] in _SCOPE_TERMINATORS:
                end = index
                break
        return text[from_index:end].strip()


__all__ = ["ChunkAnnotator", "NEGATION_KEYWORDS"]
