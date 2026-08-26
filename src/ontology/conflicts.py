"""Persistence and adjudication of meta-model-vs-ontology conflicts.

Mirrors `src/feedback/recorder.py` deliberately: same SQLite-with-
`CREATE TABLE IF NOT EXISTS` shape, same `_connect` helper, same
record/query method split. See docs/ONTOLOGY_COMPLIANCE_PLAN.md §6
(Phase 1b) for the full spec this implements.

Every grammar/systemic-rule violation found by the (forthcoming) Plane A
checkers is not necessarily an ontology defect — some are plausibly
meta-model gaps (the blueprint is too narrow) or deliberate, documented
exceptions. Rather than flatten all three into "error", each disagreement
is persisted here and escalated to a human for adjudication. Only `open`
conflicts prompt on subsequent runs; already-adjudicated ones silently
reuse their stored decision.
"""

import json
import hashlib
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Dict, List, Optional

from ..storage.sqlite_conn import connect as _sqlite_connect
from .models import ConformanceFinding, Severity

SCHEMA = """
CREATE TABLE IF NOT EXISTS ontology_conflicts (
    conflict_id     TEXT PRIMARY KEY,   -- stable hash: rule_id + subject_id
    first_seen      DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen       DATETIME,
    rule_id         TEXT NOT NULL,      -- e.g. 'GRAMMAR' or 'ONT-005'
    subject_kind    TEXT NOT NULL,      -- 'node' | 'edge' | 'graph'
    subject_id      TEXT NOT NULL,      -- e.g. 'Log Monitor|executes_via|Cloud Watch'
    ontology_says   TEXT NOT NULL,      -- observed shape
    metamodel_says  TEXT NOT NULL,      -- required shape
    status          TEXT NOT NULL,      -- see lifecycle table in the plan
    resolution_note TEXT,
    resolved_by     TEXT,
    resolved_at     DATETIME,
    occurrences     INTEGER DEFAULT 1,
    metadata_json   TEXT
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_conflicts_status ON ontology_conflicts(status)",
    "CREATE INDEX IF NOT EXISTS idx_conflicts_rule ON ontology_conflicts(rule_id)",
)

# Status lifecycle (docs/ONTOLOGY_COMPLIANCE_PLAN.md §6):
#   open               - newly detected, not yet reviewed; surfaced in the queue
#   ontology_defect     - confirmed, V4 is wrong; reported as an error
#   metamodel_gap        - blueprint is too narrow; downgraded to info
#   accepted_exception  - deliberate, documented deviation; suppressed from the report
VALID_STATUSES = ("open", "ontology_defect", "metamodel_gap", "accepted_exception")

# Pattern used by `proposed_amendments` to pull a `<edge_type>.valid_from` /
# `<edge_type>.valid_to` field reference out of a free-text `metamodel_says`
# value. This is a best-effort convention, not a contract enforced on
# callers: the Plane A checkers that populate `metamodel_says` are not part
# of this phase, so there is no structured field to rely on instead. See the
# docstring on `proposed_amendments` for the derivation this drives.
_FIELD_PATTERN = re.compile(r"\b([A-Za-z_][\w]*\.(?:valid_from|valid_to))\b")


@contextmanager
def _connect(db_path: str):
    """Commit-on-success connection that is always closed.

    `with sqlite3.connect(...)` commits but leaves the handle open, so a
    long-running API process would accumulate one descriptor per conflict.
    """
    conn = _sqlite_connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _dump_metadata(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
    """Serialize a finding's structured detail, tolerating anything unusual."""
    if not metadata:
        return None
    try:
        return json.dumps(metadata, sort_keys=True)
    except (TypeError, ValueError):
        return None


def _load_metadata(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _compute_conflict_id(rule_id: str, subject_id: str) -> str:
    """Deterministic id for one (rule, subject) disagreement.

    Hashed from `rule_id` + `subject_id` ONLY. Deliberately excludes the
    message, severity, evidence, remediation, timestamp, and occurrence
    count — every one of those is free to change between runs (wording
    tweaks, a checker becoming more precise, a re-run a second later) while
    the underlying disagreement is the same one a human already looked at.
    If any mutable field leaked into this hash, every already-adjudicated
    conflict would get a new id on the next run, silently re-opening the
    whole review queue and burying the one or two genuinely new conflicts
    in noise the reviewer has already answered and will learn to ignore.
    `conflict_id` stability is the entire point of this module — see
    "Idempotence is the whole point" in the Phase 1b spec.

    A NUL separator is used (rather than e.g. "|") because subject_id
    values already contain "|" (edge keys are "source|type|target"); NUL
    cannot appear in either input, so no two distinct (rule_id, subject_id)
    pairs can collide by the separator shifting between them.
    """
    digest = hashlib.sha256(f"{rule_id}\x00{subject_id}".encode("utf-8")).hexdigest()
    return digest[:16]


class ConflictRegistry:
    """SQLite-backed store of meta-model-vs-ontology disagreements."""

    def __init__(self, conflict_db_path: str = "conflicts.db"):
        self.db_path = conflict_db_path
        self._init_db()

    def _init_db(self) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(SCHEMA)
            for statement in INDEXES:
                conn.execute(statement)
            conn.commit()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    @staticmethod
    def _observed_and_required(finding: ConformanceFinding) -> tuple[str, str]:
        """Map a `ConformanceFinding` onto (ontology_says, metamodel_says).

        `ConformanceFinding` has no dedicated "observed shape" / "required
        shape" fields (it predates this module and is shared with the
        report layer), so the mapping used is: `evidence` is what the
        checker actually observed in the ontology (-> ontology_says), and
        `remediation` is what the meta-model requires instead
        (-> metamodel_says). Either can be absent from a finding that
        hasn't been fleshed out yet; `message` is the fallback for both so
        the NOT NULL columns are always satisfiable.
        """
        ontology_says = finding.evidence if finding.evidence else finding.message
        metamodel_says = finding.remediation if finding.remediation else finding.message
        return ontology_says, metamodel_says

    def record(self, finding: ConformanceFinding) -> str:
        """Upsert one finding into the registry; returns its `conflict_id`.

        A brand-new (rule_id, subject_id) pair is inserted as `open` with
        `occurrences=1`. An existing one has its `last_seen`/`occurrences`
        bumped and its observed/required text refreshed, but its `status`
        and resolution fields are left untouched — a human's prior
        adjudication is never silently reset by a later run.
        """
        conflict_id, _ = self._record_one(finding)
        return conflict_id

    def _record_one(self, finding: ConformanceFinding) -> tuple[str, bool]:
        """Returns (conflict_id, is_new)."""
        conflict_id = _compute_conflict_id(finding.rule_id, finding.subject_id)
        ontology_says, metamodel_says = self._observed_and_required(finding)

        with _connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT conflict_id FROM ontology_conflicts WHERE conflict_id = ?",
                (conflict_id,),
            )
            existing = cur.fetchone()

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO ontology_conflicts
                    (conflict_id, first_seen, last_seen, rule_id, subject_kind,
                     subject_id, ontology_says, metamodel_says, status, occurrences,
                     metadata_json)
                    VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, 'open', 1, ?)
                    """,
                    (
                        conflict_id,
                        finding.rule_id,
                        finding.subject_kind.value,
                        finding.subject_id,
                        ontology_says,
                        metamodel_says,
                        _dump_metadata(finding.metadata),
                    ),
                )
                is_new = True
            else:
                conn.execute(
                    """
                    UPDATE ontology_conflicts
                    SET last_seen = CURRENT_TIMESTAMP,
                        occurrences = occurrences + 1,
                        ontology_says = ?,
                        metamodel_says = ?,
                        subject_kind = ?,
                        metadata_json = ?
                    WHERE conflict_id = ?
                    """,
                    (ontology_says, metamodel_says, finding.subject_kind.value,
                     _dump_metadata(finding.metadata), conflict_id),
                )
                is_new = False

            conn.commit()

        return conflict_id, is_new

    def record_many(self, findings) -> Dict[str, int]:
        """Batch `record`, returning counts of {new, seen_again}."""
        counts = {"new": 0, "seen_again": 0}
        for finding in findings:
            _, is_new = self._record_one(finding)
            counts["new" if is_new else "seen_again"] += 1
        return counts

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return dict(row)

    def get(self, conflict_id: str) -> Optional[Dict[str, Any]]:
        with _connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM ontology_conflicts WHERE conflict_id = ?", (conflict_id,)
            )
            row = cur.fetchone()
            return self._row_to_dict(row) if row else None

    def open_conflicts(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        return self.all_conflicts(status="open", limit=limit)

    def all_conflicts(
        self, status: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM ontology_conflicts"
        params: List[Any] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY first_seen ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with _connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(query, params)
            return [self._row_to_dict(row) for row in cur.fetchall()]

    def unreviewed_count(self) -> int:
        with _connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM ontology_conflicts WHERE status = 'open'"
            )
            return cur.fetchone()[0]

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(
        self,
        conflict_id: str,
        status: str,
        note: Optional[str] = None,
        resolved_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a human adjudication for one conflict.

        Raises `ValueError` for an unrecognized `status`, and `KeyError`
        when `conflict_id` isn't in the registry (e.g. `resolve()` called
        before the corresponding `record()`).
        """
        if status not in VALID_STATUSES:
            raise ValueError(
                f"status must be one of {VALID_STATUSES}, got {status!r}"
            )

        with _connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM ontology_conflicts WHERE conflict_id = ?", (conflict_id,)
            )
            if cur.fetchone() is None:
                raise KeyError(f"No conflict registered with conflict_id={conflict_id!r}")

            conn.execute(
                """
                UPDATE ontology_conflicts
                SET status = ?, resolution_note = ?, resolved_by = ?,
                    resolved_at = CURRENT_TIMESTAMP
                WHERE conflict_id = ?
                """,
                (status, note, resolved_by, conflict_id),
            )
            conn.commit()

        return self.get(conflict_id)

    # ------------------------------------------------------------------
    # Read path used by the report
    # ------------------------------------------------------------------

    def apply_resolutions(self, findings) -> List[ConformanceFinding]:
        """Re-label findings per their stored resolution.

        - `ontology_defect`    -> kept as an error (severity forced to ERROR)
        - `metamodel_gap`      -> downgraded to `Severity.INFO`
        - `accepted_exception` -> filtered out entirely
        - `open` / unrecorded  -> unchanged

        This is the only place a conflict's stored decision changes what
        the *report* shows; the registry itself never rewrites a finding.
        """
        out: List[ConformanceFinding] = []
        for finding in findings:
            conflict_id = _compute_conflict_id(finding.rule_id, finding.subject_id)
            row = self.get(conflict_id)
            status = row["status"] if row else "open"

            if status == "accepted_exception":
                continue
            if status == "metamodel_gap":
                out.append(replace(finding, severity=Severity.INFO))
            elif status == "ontology_defect":
                out.append(replace(finding, severity=Severity.ERROR))
            else:  # "open" or not (yet) recorded
                out.append(finding)

        return out

    # ------------------------------------------------------------------
    # Proposed amendments (metamodel_gap only, never written to disk)
    # ------------------------------------------------------------------

    def proposed_amendments(self) -> List[Dict[str, Any]]:
        """Proposed grammar amendments for conflicts resolved `metamodel_gap`.

        **Never writes to the meta-model JSON file.** It returns a structured
        proposed diff for a human to apply as a deliberate, separate edit to
        `Final_Ontology_meta_model.json`.

        Prefers the finding's structured `metadata` (which the grammar checker
        populates with `edge_type`, `valid_from`/`valid_to` and which end
        actually failed). Falls back to regexing `metamodel_says` for a
        `<name>.valid_from` token when metadata is absent - older rows, or
        checkers that don't populate it. Nothing is silently dropped: when
        neither yields a field, `field` is None and the raw texts are still
        returned.
        """
        amendments = []
        for row in self.all_conflicts(status="metamodel_gap"):
            metadata = _load_metadata(row.get("metadata_json"))
            edge_type = metadata.get("edge_type")
            violating_ends = metadata.get("violating_ends") or []

            changes = []
            for end in violating_ends:
                observed_key = "observed_from" if end == "valid_from" else "observed_to"
                observed = metadata.get(observed_key) or []
                declared = metadata.get(end) or []
                # Propose only the kinds not already permitted, so the diff is
                # minimal rather than restating the whole row.
                additions = [k for k in observed if k not in declared]
                if edge_type and additions:
                    changes.append({
                        "field": f"{edge_type}.{end}",
                        "add_values": additions,
                        "current_values": declared,
                    })

            if changes:
                field = changes[0]["field"]
                add_value = ", ".join(v for c in changes for v in c["add_values"])
            else:
                match = _FIELD_PATTERN.search(row["metamodel_says"] or "")
                field = match.group(1) if match else None
                add_value = row["ontology_says"]

            amendments.append({
                "conflict_id": row["conflict_id"],
                "rule_id": row["rule_id"],
                "subject_id": row["subject_id"],
                "field": field,
                "add_value": add_value,
                "changes": changes,
                "metamodel_says": row["metamodel_says"],
                "ontology_says": row["ontology_says"],
                "resolution_note": row["resolution_note"],
            })
        return amendments


__all__ = ["ConflictRegistry", "SCHEMA", "VALID_STATUSES"]
