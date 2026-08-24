import type { RejectedEvidenceOut } from "../../api/types";

interface RejectedEvidenceListProps {
  rejected: RejectedEvidenceOut[];
}

export function RejectedEvidenceList({ rejected }: RejectedEvidenceListProps) {
  if (!rejected || rejected.length === 0) return null;

  return (
    <details open>
      <summary>Rejected evidence ({rejected.length})</summary>
      <div style={{ paddingTop: "0.4rem" }}>
        {rejected.map((r) => (
          <div key={`${r.chunk_id}-${r.adjudication}`} className="rejected-item">
            <div className="rejected-text">{r.text}</div>
            <div style={{ fontSize: "0.74rem", color: "var(--gray)" }}>
              chunk {r.chunk_id} · retrieval score {r.retrieval_score} · adjudication:{" "}
              {r.adjudication} · reason: {r.reason_rejected}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}
