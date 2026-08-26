import type { EvidenceOut } from "../../api/types";
import { detailAtLeast, useDetailLevel } from "../../context/DetailLevelContext";
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
      title={`keywords: ${(neg.negation_keywords ?? []).join(", ") || "—"} · scope: ${(neg.negation_scope ?? []).join(", ") || "—"}`}
    >
      negation detected
    </span>
  );
}

function ComponentMatches({ evidence }: { evidence: EvidenceOut }) {
  const { level } = useDetailLevel();
  const m = evidence.component_matches;
  if (!m || !detailAtLeast(level, "detailed")) return null;
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
  const { level } = useDetailLevel();
  const showAnnotatedHtml = detailAtLeast(level, "trace") && evidence.annotated_html;
  const showPathway = detailAtLeast(level, "detailed");
  const showRawFooter = detailAtLeast(level, "trace");

  return (
    <div className="evidence-item">
      {showAnnotatedHtml ? (
        <div dangerouslySetInnerHTML={{ __html: evidence.annotated_html as string }} />
      ) : (
        <div>{evidence.text}</div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", margin: "0.4rem 0" }}>
        <NegationBadge evidence={evidence} />
        <ComponentMatches evidence={evidence} />
        <TemporalBadge evidence={evidence} />
      </div>
      {showPathway ? <RetrievalPathwayView pathway={evidence.retrieval_pathway} /> : null}
      {showRawFooter ? (
        <div style={{ fontSize: "0.74rem", color: "var(--gray)", marginTop: "0.3rem" }}>
          chunk {evidence.chunk_id} · source: {evidence.source} · confidence{" "}
          {evidence.confidence} · match: {evidence.match_type}
        </div>
      ) : null}
    </div>
  );
}
