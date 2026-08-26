import { DETAIL_LEVELS, useDetailLevel, type DetailLevel } from "../../context/DetailLevelContext";

const LABELS: Record<DetailLevel, string> = {
  verdict: "Verdict",
  summary: "Summary",
  detailed: "Detailed",
  trace: "Full trace",
};

const HINTS: Record<DetailLevel, string> = {
  verdict: "Label, score, and rationale only",
  summary: "+ evidence text and rule hits",
  detailed: "+ retrieval pathway and scoring breakdown",
  trace: "+ raw retrieval reasoning, chunk IDs, and verdict JSON",
};

export function DetailLevelToggle() {
  const { level, setLevel } = useDetailLevel();
  return (
    <div className="detail-level-toggle" role="radiogroup" aria-label="Trace detail level">
      {DETAIL_LEVELS.map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={level === option}
          className={`detail-level-option${level === option ? " active" : ""}`}
          title={HINTS[option]}
          onClick={() => setLevel(option)}
        >
          {LABELS[option]}
        </button>
      ))}
    </div>
  );
}
