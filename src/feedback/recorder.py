"""Persistence and analysis of user corrections to pipeline verdicts."""

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from ..models import TripleVerdict
from ..storage.sqlite_conn import connect as _sqlite_connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    assertion_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    subject TEXT,
    relation TEXT,
    object TEXT,
    predicted_label TEXT,
    predicted_score REAL,
    actual_label TEXT,
    actual_reason TEXT,
    used_evidence_count INTEGER,
    retrieval_sources TEXT,
    evidence_json TEXT,
    UNIQUE(assertion_id, document_id)
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON feedback(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_labels ON feedback(predicted_label, actual_label)",
)

VALID_LABELS = ("supported", "contradicted", "partial", "unknown")


@contextmanager
def _connect(db_path: str):
    """Commit-on-success connection that is always closed.

    `with sqlite3.connect(...)` commits but leaves the handle open, so a
    long-running API process would accumulate one descriptor per correction.
    """
    conn = _sqlite_connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


class FeedbackRecorder:
    """SQLite-backed store of (predicted label, corrected label) pairs."""

    def __init__(self, feedback_db_path: str = "feedback.db"):
        self.db_path = feedback_db_path
        self._init_db()

    def _init_db(self) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(SCHEMA)
            for statement in INDEXES:
                conn.execute(statement)
            conn.commit()

    def record_correction(
        self,
        verdict: TripleVerdict,
        actual_label: str,
        document_id: str,
        actual_reason: Optional[str] = None,
    ) -> None:
        """Record that a user replaced `verdict.label` with `actual_label`."""
        if actual_label not in VALID_LABELS:
            raise ValueError(f"actual_label must be one of {VALID_LABELS}, got {actual_label!r}")

        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO feedback
                (assertion_id, document_id, subject, relation, object,
                 predicted_label, predicted_score, actual_label, actual_reason,
                 used_evidence_count, retrieval_sources, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verdict.assertion_id,
                    document_id,
                    verdict.subject,
                    verdict.relation,
                    verdict.object,
                    verdict.label,
                    float(verdict.score),
                    actual_label,
                    actual_reason,
                    len(verdict.evidence),
                    json.dumps(sorted(set(verdict.retrieval_sources))),
                    json.dumps([
                        {
                            "chunk_id": e.chunk_id,
                            "support_type": e.support_type,
                            "confidence": e.confidence,
                        }
                        for e in verdict.evidence
                    ]),
                ),
            )
            conn.commit()

    def get_error_patterns(self, limit_days: int = 30) -> Dict[str, Any]:
        """Confusion matrix of predicted vs. corrected labels over a recent window."""
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT predicted_label, actual_label, COUNT(*) as count
                FROM feedback
                WHERE datetime(timestamp) > datetime('now', '-' || ? || ' days')
                GROUP BY predicted_label, actual_label
                """,
                (limit_days,),
            )
            confusion_matrix: Dict[str, Dict[str, int]] = {}
            for predicted, actual, count in cursor.fetchall():
                confusion_matrix.setdefault(predicted, {})[actual] = count

        return {
            "confusion_matrix": confusion_matrix,
            "total_corrections": sum(sum(row.values()) for row in confusion_matrix.values()),
            "accuracy": self._compute_accuracy(confusion_matrix),
        }

    @staticmethod
    def _compute_accuracy(confusion_matrix: Dict[str, Dict[str, int]]) -> float:
        total = sum(sum(row.values()) for row in confusion_matrix.values())
        if not total:
            return 0.0
        correct = sum(row.get(predicted, 0) for predicted, row in confusion_matrix.items())
        return round(correct / total, 4)

    def get_retriever_analysis(self, limit_days: int = 30) -> List[Dict[str, Any]]:
        """Per retriever-combination accuracy, worst error rate first."""
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT
                    retrieval_sources,
                    COUNT(*) as total,
                    SUM(CASE WHEN predicted_label = actual_label THEN 1 ELSE 0 END) as correct
                FROM feedback
                WHERE datetime(timestamp) > datetime('now', '-' || ? || ' days')
                GROUP BY retrieval_sources
                """,
                (limit_days,),
            )
            rows = cursor.fetchall()

        results = []
        for sources_json, total, correct in rows:
            try:
                sources = json.loads(sources_json) if sources_json else []
            except json.JSONDecodeError:
                sources = []
            accuracy = (correct or 0) / total if total else 0.0
            results.append({
                "retrieval_sources": sources,
                "total_cases": total,
                "accuracy": round(accuracy, 4),
                "error_rate": round(1 - accuracy, 4),
            })

        return sorted(results, key=lambda x: x["error_rate"], reverse=True)

    def get_corrections(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Most recent corrections, newest first."""
        with _connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM feedback ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]


__all__ = ["FeedbackRecorder", "SCHEMA", "VALID_LABELS"]
