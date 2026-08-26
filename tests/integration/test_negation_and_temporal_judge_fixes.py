"""Regression tests for the four stress-test bugs in the heuristic evidence
span classifier and the heuristic evidence judge:

1. NEGATION_TOKENS missing "unable to" / "incapable of" / "won't" / "failed to" forms.
2. Negation embedded in the object's own text misread as refuting the claim.
3. Double negation / hedging never resolved to correct polarity.
4. HeuristicEvidenceJudge ignoring temporal discounting and escalating
   stale-but-matching evidence back to "supported".
"""

import sqlite3
from datetime import datetime
import json

from src.classification.evidence_span_classifier import HeuristicEvidenceSpanClassifier
from src.classification.evidence_judge import HeuristicEvidenceJudge
from src.classification.temporal_evidence_classifier import TemporalEvidenceClassifier
from src.engine import SVOVerificationEngine
from src.fusion import WeightedFusionEngine
from src.models import (
    Chunk,
    EvidencePack,
    EvidencePackEntry,
    OntologyAssertion,
    RetrievalResult,
    TemporalScope,
)
from src.routing import MoERouter
from src.storage import SQLiteChunkStore
from src.validation import MinimalValidator


def _chunk(text: str, timestamp=None) -> Chunk:
    return Chunk(
        chunk_id="c1",
        document_id="doc",
        text=text,
        embedding=None,
        metadata={},
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Bug 1: negation cue list missing "unable to" / "incapable of" / etc.
# ---------------------------------------------------------------------------


def test_bug1_unable_to_is_recognized_as_negation():
    clf = HeuristicEvidenceSpanClassifier()
    assertion = OntologyAssertion(assertion_id="a1", subject="the drug", relation="cause", object="drowsiness")
    chunk = _chunk("The drug is unable to cause drowsiness.")

    span = clf.classify(assertion, chunk, source="lexical", retrieval_score=0.5)

    assert span.support_type == "refutes"


def test_bug1_failed_to_and_wont_are_recognized_as_negation():
    clf = HeuristicEvidenceSpanClassifier()

    a1 = OntologyAssertion(assertion_id="a1", subject="aspirin", relation="treat", object="malaria")
    span1 = clf.classify(a1, _chunk("Aspirin failed to treat malaria in the trial."), source="lexical", retrieval_score=0.5)
    assert span1.support_type == "refutes"

    a2 = OntologyAssertion(assertion_id="a2", subject="aspirin", relation="treat", object="malaria")
    span2 = clf.classify(a2, _chunk("Aspirin won't treat malaria."), source="lexical", retrieval_score=0.5)
    assert span2.support_type == "refutes"


def test_bug1_downstream_judge_no_longer_confidently_wrong():
    """Feeding the corrected 'refutes' span into the judge should not yield
    a confident 'supported' verdict for evidence that states the opposite."""
    clf = HeuristicEvidenceSpanClassifier()
    assertion = OntologyAssertion(assertion_id="a1", subject="the drug", relation="cause", object="drowsiness")
    chunk = _chunk("The drug is unable to cause drowsiness.")
    span = clf.classify(assertion, chunk, source="lexical", retrieval_score=0.5)

    pack = EvidencePack(
        assertion_id="a1",
        subject="the drug",
        relation="cause",
        object="drowsiness",
        polarity="must_hold",
        rule_type="constraint",
        evidence=[
            EvidencePackEntry(
                chunk_id="c1",
                text=span.text,
                source="lexical",
                retrieval_score=0.5,
                support_type=span.support_type,
                matched_subject=span.matched_subject,
                matched_relation=span.matched_relation,
                matched_object=span.matched_object,
                confidence=span.confidence,
                temporal_status=span.temporal_status,
            )
        ],
        graph_summary=[],
    )
    verdict = HeuristicEvidenceJudge().judge(pack)
    assert verdict.label != "supported"


# ---------------------------------------------------------------------------
# Bug 2: negation embedded in the object's own text shouldn't flip polarity.
# ---------------------------------------------------------------------------


def test_bug2_negation_inside_object_phrase_does_not_refute():
    clf = HeuristicEvidenceSpanClassifier()
    assertion = OntologyAssertion(
        assertion_id="a1",
        subject="security audits",
        relation="confirm",
        object="no major vulnerabilities",
    )
    chunk = _chunk("Security audits confirm no major vulnerabilities in the system.")

    span = clf.classify(assertion, chunk, source="lexical", retrieval_score=0.5)

    assert span.support_type == "supports"


def test_bug2_negation_outside_object_phrase_still_refutes():
    """Sanity check: the object-span carve-out shouldn't blanket-suppress
    negation that genuinely negates the relation elsewhere in the sentence."""
    clf = HeuristicEvidenceSpanClassifier()
    assertion = OntologyAssertion(
        assertion_id="a1",
        subject="security audits",
        relation="confirm",
        object="major vulnerabilities",
    )
    chunk = _chunk("Security audits do not confirm major vulnerabilities in the system.")

    span = clf.classify(assertion, chunk, source="lexical", retrieval_score=0.5)

    assert span.support_type == "refutes"


# ---------------------------------------------------------------------------
# Bug 3: double negation / hedging resolved via cue-parity.
# ---------------------------------------------------------------------------


def test_bug3_double_negative_idiom_resolves_to_affirmative():
    clf = HeuristicEvidenceSpanClassifier()
    assertion = OntologyAssertion(
        assertion_id="a1", subject="ibuprofen", relation="cause", object="stomach irritation"
    )
    chunk = _chunk("It is not uncommon for ibuprofen to cause stomach irritation.")

    span = clf.classify(assertion, chunk, source="lexical", retrieval_score=0.5)

    assert span.support_type == "supports"


def test_bug3_double_negation_via_cue_parity_resolves_to_affirmative():
    clf = HeuristicEvidenceSpanClassifier()
    assertion = OntologyAssertion(
        assertion_id="a1", subject="ibuprofen", relation="reduce", object="inflammation"
    )
    chunk = _chunk("There is no evidence that ibuprofen does not reduce inflammation.")

    span = clf.classify(assertion, chunk, source="lexical", retrieval_score=0.5)

    assert span.support_type != "refutes"


def test_bug3_single_negation_still_refutes():
    """Sanity check: parity counting shouldn't wash out a plain single negation."""
    clf = HeuristicEvidenceSpanClassifier()
    assertion = OntologyAssertion(assertion_id="a1", subject="aspirin", relation="treat", object="malaria")
    chunk = _chunk("Aspirin does not treat malaria.")

    span = clf.classify(assertion, chunk, source="lexical", retrieval_score=0.5)

    assert span.support_type == "refutes"


# ---------------------------------------------------------------------------
# Bug 4: heuristic judge must respect temporal discounting, not just match
# booleans.
# ---------------------------------------------------------------------------


def test_bug4_judge_does_not_escalate_low_confidence_evidence_to_supported():
    """Unit-level: an entry with full component matches but confidence
    knocked below the support bar (e.g. by temporal discounting) must not
    trigger the 'supported' branch on its own."""
    pack = EvidencePack(
        assertion_id="a1",
        subject="aspirin",
        relation="treats",
        object="headache",
        polarity="must_hold",
        rule_type="constraint",
        evidence=[
            EvidencePackEntry(
                chunk_id="c1",
                text="Aspirin treats headache.",
                source="lexical",
                retrieval_score=0.5,
                support_type="supports",
                matched_subject=True,
                matched_relation=True,
                matched_object=True,
                confidence=0.57,  # e.g. 0.95 discounted by outdated_evidence_confidence_penalty=0.6
                temporal_status="outdated",
            )
        ],
        graph_summary=[],
    )

    verdict = HeuristicEvidenceJudge().judge(pack)

    assert verdict.label != "supported"
    assert verdict.label == "partial"


def test_bug4_judge_still_supports_fresh_high_confidence_evidence():
    """Sanity check: the confidence/temporal gate shouldn't break the
    ordinary supported case."""
    pack = EvidencePack(
        assertion_id="a1",
        subject="aspirin",
        relation="treats",
        object="headache",
        polarity="must_hold",
        rule_type="constraint",
        evidence=[
            EvidencePackEntry(
                chunk_id="c1",
                text="Aspirin treats headache.",
                source="lexical",
                retrieval_score=0.5,
                support_type="supports",
                matched_subject=True,
                matched_relation=True,
                matched_object=True,
                confidence=0.95,
                temporal_status="current",
            )
        ],
        graph_summary=[],
    )

    verdict = HeuristicEvidenceJudge().judge(pack)

    assert verdict.label == "supported"


def _seed_chunk(db_path, chunk_id, text, metadata=None, timestamp=None):
    """Seed a chunk row via the real SQLiteChunkStore schema (including the
    timestamp column) so materialized chunks retain temporal info."""
    from src.storage.chunk_store import ensure_chunks_schema

    metadata = metadata or {}
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            ensure_chunks_schema(conn)
            conn.execute(
                "INSERT OR REPLACE INTO chunks "
                "(chunk_id, document_id, text, metadata, chunk_type, type_metadata, timestamp, temporal_metadata) "
                "VALUES (?, ?, ?, ?, 'text', NULL, ?, NULL)",
                (chunk_id, "doc", text, json.dumps(metadata), timestamp.isoformat() if timestamp else None),
            )
    finally:
        conn.close()


class _DummyRetriever:
    def __init__(self, results):
        self.results = results

    def retrieve(self, query: str, top_k: int, **kwargs):
        return list(self.results)


def test_bug4_full_engine_stale_evidence_lands_on_partial_not_supported(tmp_workspace):
    """End-to-end repro of Bug 4: a triple whose only evidence is stale
    (outside temporal_scope) should land on 'partial', not get escalated
    back to 'supported' by the heuristic judge that fires on the resulting
    'partial' label."""
    db_path = f"{tmp_workspace}/test.sqlite"
    text = "Aspirin treats headache."
    stale_timestamp = datetime(2000, 1, 1)
    _seed_chunk(db_path, "c1", text, timestamp=stale_timestamp)

    chunk = Chunk(chunk_id="c1", document_id="doc", text=text, embedding=None, metadata={}, timestamp=stale_timestamp)
    retrieval = [RetrievalResult(chunk_id="c1", score=0.9, source="lexical")]
    ranked = [RetrievalResult(chunk_id="c1", score=0.9, source="lexical", chunk=chunk)]

    engine = SVOVerificationEngine(
        router=MoERouter(),
        lexical_store=_DummyRetriever(retrieval),
        semantic_store=_DummyRetriever([]),
        graph_store=_DummyRetriever([]),
        fusion_engine=WeightedFusionEngine(),
        chunk_store=SQLiteChunkStore(db_path),
        validator=MinimalValidator(),
        evidence_span_classifier=TemporalEvidenceClassifier(
            base_classifier=HeuristicEvidenceSpanClassifier(),
            outdated_penalty=0.6,
        ),
        evidence_judge=HeuristicEvidenceJudge(),
    )

    class _StaticFusion:
        def fuse_and_rank(self, results, top_k):
            return ranked[:top_k]

    engine.fusion_engine = _StaticFusion()

    assertion = OntologyAssertion(
        assertion_id="a1",
        subject="Aspirin",
        relation="treats",
        object="headache",
        temporal_scope=TemporalScope(start_date=datetime(2020, 1, 1)),
    )

    verdict = engine.adjudicate_triple(document_text=None, assertion=assertion, top_k=1)

    assert verdict.label != "supported"
