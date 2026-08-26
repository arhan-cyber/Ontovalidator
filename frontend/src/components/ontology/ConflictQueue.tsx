import { useState } from "react";

import { resolveConflict } from "../../api/client";
import type { Conflict, ConflictStatus } from "../../api/types";
import { Button, Card, ErrorBanner } from "../shared";

/** The three rulings, in the order the CLI offers them. */
const RULINGS: Array<{ status: ConflictStatus; label: string; hint: string }> = [
  {
    status: "ontology_defect",
    label: "Ontology defect",
    hint: "The ontology is wrong — keep this as an error.",
  },
  {
    status: "metamodel_gap",
    label: "Meta-model gap",
    hint: "The blueprint is too narrow — downgrade to info and propose an amendment.",
  },
  {
    status: "accepted_exception",
    label: "Accepted exception",
    hint: "A deliberate deviation — suppress from the report, keep in the registry.",
  },
];

interface Props {
  conflicts: Conflict[];
  unreviewed: number;
  onResolved: () => void;
}

export function ConflictQueue({ conflicts, unreviewed, onResolved }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  const open = conflicts.filter((c) => c.status === "open");

  async function rule(conflict: Conflict, status: ConflictStatus) {
    setBusy(conflict.conflict_id);
    setError(null);
    try {
      await resolveConflict(conflict.conflict_id, status, notes[conflict.conflict_id]);
      onResolved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card title={`Conflict review queue (${unreviewed} unreviewed)`}>
      <p className="muted small">
        The meta-model is authoritative, but not every disagreement is an ontology defect —
        an external system genuinely is an external system. Rulings persist across runs, so
        re-validating never re-asks a question you have already answered.
      </p>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      {open.length === 0 ? (
        <p className="muted">Nothing awaiting review.</p>
      ) : (
        <ul className="conflict-list">
          {open.map((conflict) => (
            <li key={conflict.conflict_id} className="conflict">
              <div className="conflict-head">
                <span className="mono">{conflict.rule_id}</span>
                <span className="mono strong">{conflict.subject_id}</span>
                {conflict.occurrences > 1 && (
                  <span className="badge" title="times seen across runs">
                    seen {conflict.occurrences}×
                  </span>
                )}
              </div>
              <dl className="conflict-detail">
                <dt>ontology</dt>
                <dd>{conflict.ontology_says}</dd>
                <dt>meta-model</dt>
                <dd>{conflict.metamodel_says}</dd>
              </dl>
              <input
                type="text"
                placeholder="note (optional)"
                value={notes[conflict.conflict_id] ?? ""}
                onChange={(e) =>
                  setNotes((n) => ({ ...n, [conflict.conflict_id]: e.target.value }))
                }
              />
              <div className="conflict-actions">
                {RULINGS.map((r) => (
                  <Button
                    key={r.status}
                    title={r.hint}
                    disabled={busy === conflict.conflict_id}
                    onClick={() => rule(conflict, r.status)}
                  >
                    {r.label}
                  </Button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
