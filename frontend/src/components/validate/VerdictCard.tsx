import type { VerdictOut } from "../../api/types";
import { LabelDot } from "../shared/LabelDot";
import { EvidenceItem } from "./EvidenceItem";
import { FeedbackCorrectionForm } from "./FeedbackCorrectionForm";
import { RejectedEvidenceList } from "./RejectedEvidenceList";
import { ScoringBreakdown } from "./ScoringBreakdown";

interface VerdictCardProps {
  verdict: VerdictOut;
  documentId?: string;
}

export function VerdictCard({ verdict, documentId }: VerdictCardProps) {
  return (
    <article className="verdict-card">
      <div className="verdict-title">
        <LabelDot label={verdict.label} />
        <span>
          {verdict.subject} — {verdict.relation} — {verdict.object}
        </span>
        <span className="score">{verdict.label} · score {verdict.score}</span>
      </div>

      <p className="rationale">{verdict.rationale}</p>

      {verdict.rule_hits.length > 0 ? (
        <div style={{ fontSize: "0.74rem", color: "var(--gray)", marginBottom: "0.4rem" }}>
          rules: {verdict.rule_hits.join(", ")} · sources:{" "}
          {verdict.retrieval_sources.join(", ") || "none"}
        </div>
      ) : null}

      <details open={verdict.evidence.length > 0}>
        <summary>Evidence ({verdict.evidence.length})</summary>
        <div style={{ paddingTop: "0.4rem" }}>
          {verdict.evidence.length === 0 ? (
            <p className="hm-empty">No supporting evidence retrieved.</p>
          ) : (
            verdict.evidence.map((ev) => <EvidenceItem key={ev.chunk_id} evidence={ev} />)
          )}
        </div>
      </details>

      <RejectedEvidenceList rejected={verdict.rejected_evidence} />
      <ScoringBreakdown verdict={verdict} />
      <FeedbackCorrectionForm verdict={verdict} documentId={documentId} />
    </article>
  );
}
