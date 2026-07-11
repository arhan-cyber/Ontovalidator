import sqlite3

from src.engine import SVOVerificationEngine
from src.models import Chunk, EvidencePack, EvidencePackEntry, JudgeVerdict, OntologyAssertion, RetrievalResult
from src.classification.evidence_judge import HeuristicEvidenceJudge
from src.fusion import WeightedFusionEngine
from src.routing import MoERouter
from src.storage import SQLiteChunkStore
from src.validation import MinimalValidator


class DummyRetriever:
    def __init__(self, results):
        self.results = results

    def retrieve(self, query: str, top_k: int, **kwargs):
        return list(self.results)


class DummyJudge:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = []

    def judge(self, evidence_pack):
        self.calls.append(evidence_pack)
        return self.verdict


class DummyFusion:
    def __init__(self, results):
        self.results = results

    def fuse_and_rank(self, results, top_k):
        return list(self.results)[:top_k]


def make_engine(db_path, retrieval_results, ranked_results=None, judge=None):
    store = SQLiteChunkStore(db_path)
    ranked_results = ranked_results or retrieval_results
    return SVOVerificationEngine(
        router=MoERouter(),
        lexical_store=DummyRetriever(retrieval_results),
        semantic_store=DummyRetriever([]),
        graph_store=DummyRetriever([]),
        fusion_engine=DummyFusion(ranked_results),
        chunk_store=store,
        validator=MinimalValidator(),
        evidence_judge=judge or HeuristicEvidenceJudge(),
    )


def seed_chunk(db_path, chunk_id, text, metadata=None):
    metadata = metadata or {}
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT,
                    text TEXT,
                    metadata TEXT
                )
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO chunks (chunk_id, document_id, text, metadata) VALUES (?, ?, ?, ?)",
                (chunk_id, "doc", text, __import__("json").dumps(metadata)),
            )
    finally:
        conn.close()


def test_heuristic_evidence_judge_supports_direct_match():
    pack = EvidencePack(
        assertion_id="a1",
        subject="Aspirin",
        relation="treats",
        object="headache",
        polarity="must_hold",
        rule_type="constraint",
        evidence=[
            EvidencePackEntry(
                chunk_id="c1",
                text="Aspirin treats pain.",
                source="lexical",
                retrieval_score=0.42,
                support_type="partial",
                matched_subject=True,
                matched_relation=True,
                matched_object=False,
            )
        ],
        graph_summary=[],
    )

    verdict = HeuristicEvidenceJudge().judge(pack)

    assert verdict.label == "partial"
    assert verdict.evidence_chunk_ids == ["c1"]


def test_engine_uses_evidence_judge_when_gated(tmp_workspace):
    db_path = f"{tmp_workspace}/test.sqlite"
    seed_chunk(db_path, "c1", "Aspirin treats pain.", {"graph_summary": "Aspirin -> treats -> headache"})

    retrieval = [RetrievalResult(chunk_id="c1", score=0.42, source="lexical")]
    ranked = [RetrievalResult(chunk_id="c1", score=0.42, source="lexical", chunk=Chunk(chunk_id="c1", document_id="doc", text="Aspirin treats pain.", embedding=None, metadata={"graph_summary": "Aspirin -> treats -> headache"}))]
    judge = DummyJudge(JudgeVerdict(
        label="supported",
        confidence=0.99,
        rationale="LM override",
        evidence_chunk_ids=["c1"],
        counterevidence_chunk_ids=[],
        graph_reasoning="Aspirin -> treats -> headache",
    ))
    engine = make_engine(db_path, retrieval, ranked_results=ranked, judge=judge)

    verdict = engine.adjudicate_triple(
        document_text=None,
        assertion=OntologyAssertion(assertion_id="a1", subject="Aspirin", relation="treats", object="headache"),
        top_k=1,
    )

    assert verdict.label == "supported"
    assert judge.calls, "expected the evidence judge to be invoked"
    assert "evidence_judge" in verdict.rule_hits


def test_engine_falls_back_when_judge_not_invoked(tmp_workspace):
    db_path = f"{tmp_workspace}/test.sqlite"
    seed_chunk(db_path, "c1", "Aspirin treats headache.")

    retrieval = [RetrievalResult(chunk_id="c1", score=0.92, source="lexical")]
    ranked = [RetrievalResult(chunk_id="c1", score=0.92, source="lexical", chunk=Chunk(chunk_id="c1", document_id="doc", text="Aspirin treats headache.", embedding=None, metadata={}))]
    judge = DummyJudge(__import__("src.models", fromlist=["JudgeVerdict"]).JudgeVerdict(
        label="contradicted",
        confidence=0.99,
        rationale="LM override",
        evidence_chunk_ids=[],
        counterevidence_chunk_ids=["c1"],
    ))
    engine = make_engine(db_path, retrieval, ranked_results=ranked, judge=judge)

    verdict = engine.adjudicate_triple(
        document_text=None,
        assertion=OntologyAssertion(assertion_id="a1", subject="Aspirin", relation="treats", object="headache"),
        top_k=1,
    )

    assert verdict.label == "supported"
    assert not judge.calls
