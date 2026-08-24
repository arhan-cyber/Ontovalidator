import type { EvidenceOut } from "../../api/types";
import { RetrievalPathwayView } from "./RetrievalPathway";

interface EvidenceItemProps {
  evidence: EvidenceOut;
}

function TemporalBadge({ evidence }: { evidence: EvidenceOut }) {
  const status = evidence.temporal_status;
  if (!status || status === "unscoped" || status === "undated") return null;

  if (status === "current") {
    return <span className="badge badge-current">current</span>;
  }
  return (
    <span className="badge badge-outdated">
      {status}
      {evidence.chunk_timestamp ? ` · ${evidence.chunk_timestamp}` : ""}
    </span>
  );
}

function NegationBadge({ evidence }: { evidence: EvidenceOut }) {
  const neg = evidence.negation_analysis;
  if (!neg?.negation_detected) return null;
  return (
    <span
      className="badge badge-negation"
      title={`keywords: ${(neg.keywords ?? []).join(", ") || "—"} · scope: ${neg.scope ?? "—"}`}
    >
      negation detected
    </span>
  );
}

function ComponentMatches({ evidence }: { evidence: EvidenceOut }) {
  const m = evidence.component_matches;
  if (!m) return null;
  return (
    <span className="component-match" title="component matches">
      {(["subject", "relation", "object"] as const).map((part) => (
        <span key={part} className={m[part] ? "match-ok" : "match-fail"}>
          {part === "subject" ? "S" : part === "relation" ? "V" : "O"}
          {m[part] ? "✓" : "✕"}
        </span>
      ))}
    </span>
  );
}

export function EvidenceItem({ evidence }: EvidenceItemProps) {
  return (
    <div className="evidence-item">
      {evidence.annotated_html ? (
        <div dangerouslySetInnerHTML={{ __html: evidence.annotated_html }} />
      ) : (
        <div>{evidence.text}</div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", margin: "0.4rem 0" }}>
        <NegationBadge evidence={evidence} />
        <ComponentMatches evidence={evidence} />
        <TemporalBadge evidence={evidence} />
      </div>
      <RetrievalPathwayView pathway={evidence.retrieval_pathway} />
      <div style={{ fontSize: "0.74rem", color: "var(--gray)", marginTop: "0.3rem" }}>
        chunk {evidence.chunk_id} · source: {evidence.source} · confidence{" "}
        {evidence.confidence} · match: {evidence.match_type}
      </div>
    </div>
  );
}
