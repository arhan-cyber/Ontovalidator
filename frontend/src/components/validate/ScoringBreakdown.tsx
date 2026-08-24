import { ScoreContributionBars } from "../charts";
import type { VerdictOut } from "../../api/types";

export function ScoringBreakdown({ verdict }: { verdict: VerdictOut }) {
  return (
    <details open={Boolean(verdict.scoring_breakdown)}>
      <summary>Scoring breakdown</summary>
      <div style={{ paddingTop: "0.5rem" }}>
        <ScoreContributionBars breakdown={verdict.scoring_breakdown} />
        {verdict.decision_thresholds ? (
          <div style={{ marginTop: "0.5rem", fontSize: "0.78rem", color: "var(--muted)" }}>
            <strong style={{ color: "var(--text)" }}>Decision rules</strong>
            <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1.1rem" }}>
              {Object.entries(verdict.decision_thresholds).map(([key, value]) => (
                <li key={key}>
                  <em>{key}</em>: {value}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </details>
  );
}
