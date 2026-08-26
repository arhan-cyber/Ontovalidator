import type { VerdictOut } from "../../api/types";
import { detailAtLeast, useDetailLevel } from "../../context/DetailLevelContext";
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
  const { level } = useDetailLevel();
  const showEvidence = detailAtLeast(level, "summary");
  const showRuleHits = detailAtLeast(level, "summary");
  const showRejected = detailAtLeast(level, "detailed");
  const showScoring = detailAtLeast(level, "detailed");
  const showRawTrace = detailAtLeast(level, "trace");

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

      {showRuleHits && verdict.rule_hits.length > 0 ? (
        <div style={{ fontSize: "0.74rem", color: "var(--gray)", marginBottom: "0.4rem" }}>
          rules: {verdict.rule_hits.join(", ")} · sources:{" "}
          {verdict.retrieval_sources.join(", ") || "none"}
        </div>
      ) : null}

      {showEvidence ? (
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
      ) : null}

      {showRejected ? <RejectedEvidenceList rejected={verdict.rejected_evidence} /> : null}
      {showScoring ? <ScoringBreakdown verdict={verdict} /> : null}
      {showRawTrace ? (
        <details>
          <summary>Raw verdict JSON</summary>
          <pre className="raw-trace">{JSON.stringify(verdict, null, 2)}</pre>
        </details>
      ) : null}
      <FeedbackCorrectionForm verdict={verdict} documentId={documentId} />
    </article>
  );
}
