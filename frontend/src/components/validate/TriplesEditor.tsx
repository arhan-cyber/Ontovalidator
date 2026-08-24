import type { TripleIn } from "../../api/types";
interface TriplesEditorProps {
  triples: TripleIn[];
  onChange: (triples: TripleIn[]) => void;
}

function emptyTriple(): TripleIn {
  return { subject: "", relation: "", object: "" };
}

function isFilled(t: TripleIn): boolean {
  return t.subject.trim() !== "" || t.relation.trim() !== "" || t.object.trim() !== "";
}

export function TriplesEditor({ triples, onChange }: TriplesEditorProps) {
  const update = (index: number, field: keyof TripleIn, value: string) => {
    const next = triples.map((t, i) => (i === index ? { ...t, [field]: value } : t));
    onChange(next);
  };

  const remove = (index: number) => {
    if (triples.length === 1) {
      onChange([emptyTriple()]);
      return;
    }
    onChange(triples.filter((_, i) => i !== index));
  };

  return (
    <div>
      <div className="triple-header">
        <span>Subject</span>
        <span>Relation</span>
        <span>Object</span>
        <span />
      </div>
      {triples.map((triple, i) => (
        <div className="triple-row" key={i}>
          <input
            value={triple.subject}
            onChange={(e) => update(i, "subject", e.target.value)}
            placeholder="Subject"
          />
          <input
            value={triple.relation}
            onChange={(e) => update(i, "relation", e.target.value)}
            placeholder="Relation"
          />
          <input
            value={triple.object}
            onChange={(e) => update(i, "object", e.target.value)}
            placeholder="Object"
          />
          <button type="button" className="icon-btn" onClick={() => remove(i)} aria-label="Remove row">
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        className="btn btn-secondary"
        onClick={() => onChange([...triples, emptyTriple()])}
      >
        + Add Row
      </button>
      {triples.some(
        (t) =>
          isFilled(t) &&
          (t.subject.trim() === "" || t.relation.trim() === "" || t.object.trim() === ""),
      ) && (
        <p className="card-error" role="alert">
          Every triple needs a subject, relation, and object.
        </p>
      )}
    </div>
  );
}

export function initTriples(): TripleIn[] {
  return [emptyTriple()];
}
