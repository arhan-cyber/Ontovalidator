interface PathwayMiniBarsProps {
  score: number | null | undefined;
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

export function PathwayMiniBars({ score }: PathwayMiniBarsProps) {
  if (typeof score !== "number" || !Number.isFinite(score)) {
    return <span className="not-retrieved">not retrieved</span>;
  }
  return (
    <div className="bar-track" title={`score ${score}`}>
      <span
        className="bar-fill"
        style={{ width: `${clamp01(score) * 100}%` }}
      />
    </div>
  );
}

interface FusionGaugeProps {
  score: number;
  explanation?: string | null;
}

export function FusionGauge({ score, explanation }: FusionGaugeProps) {
  return (
    <div className="fusion-gauge">
      <div className="score-bar-row">
        <span className="score-bar-key">fusion_score</span>
        <span className="bar-track">
          <span className="bar-fill" style={{ width: `${clamp01(score) * 100}%` }} />
        </span>
        <span className="score-bar-value">{score}</span>
      </div>
      {explanation ? (
        <p style={{ color: "var(--muted)", fontSize: "0.78rem", margin: "0.25rem 0 0" }}>
          {explanation}
        </p>
      ) : null}
    </div>
  );
}
