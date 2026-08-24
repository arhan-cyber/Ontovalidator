interface ScoreContributionBarsProps {
  breakdown?: Record<string, unknown> | null;
}

function isNumeric(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function ScoreContributionBars({ breakdown }: ScoreContributionBarsProps) {
  if (!breakdown || typeof breakdown !== "object") {
    return <p className="hm-empty">No scoring breakdown available.</p>;
  }

  const entries = Object.entries(breakdown);
  const numeric = entries.filter(([, v]) => isNumeric(v));
  const textual = entries.filter(([, v]) => !isNumeric(v));
  const maxAbs = Math.max(...numeric.map(([, v]) => Math.abs(v as number)), 1e-9);

  return (
    <div>
      {numeric.map(([key, value]) => {
        const v = value as number;
        const width = (Math.abs(v) / maxAbs) * 100;
        const positive = v >= 0;
        const isFinal = key === "final_score" || key === "clipped_score";
        return (
          <div key={key} className={`score-bar-row${isFinal ? " final" : ""}`}>
            <span className="score-bar-key">{key}</span>
            <span className="bar-track">
              <span
                className={`bar-fill ${positive ? "positive" : "negative"}`}
                style={{ width: `${width}%` }}
                title={`${key}: ${v}`}
              />
            </span>
            <span className="score-bar-value">{v}</span>
          </div>
        );
      })}
      {textual.map(([key, value]) => (
        <div key={key} className="score-bar-row">
          <span className="score-bar-key">{key}</span>
          <span style={{ color: "var(--muted)", fontSize: "0.78rem" }}>{String(value)}</span>
        </div>
      ))}
    </div>
  );
}
