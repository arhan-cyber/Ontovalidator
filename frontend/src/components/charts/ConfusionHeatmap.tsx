import { Fragment } from "react";

import type { ConfusionMatrix, MostCommonError } from "../../api/types";

interface ConfusionHeatmapProps {
  matrix: ConfusionMatrix;
  mostCommonError?: MostCommonError | null;
}

const LABELS = ["supported", "contradicted", "partial", "unknown"] as const;

function cellColor(count: number, max: number, diagonal: boolean): string {
  if (count <= 0) return "transparent";
  const intensity = 0.12 + 0.68 * Math.sqrt(max > 0 ? count / max : 0);
  const base = diagonal ? "56, 193, 114" : "227, 52, 47";
  return `rgba(${base}, ${intensity.toFixed(3)})`;
}

export function ConfusionHeatmap({ matrix, mostCommonError }: ConfusionHeatmapProps) {
  const counts = LABELS.flatMap((p) => LABELS.map((a) => matrix?.[p]?.[a] ?? 0));
  const total = counts.reduce((sum, c) => sum + c, 0);
  if (total === 0) {
    return <p className="hm-empty">No corrections recorded yet.</p>;
  }

  const max = Math.max(...counts);

  return (
    <div
      className="heatmap-grid"
      style={{ gridTemplateColumns: `110px repeat(${LABELS.length}, minmax(64px, 1fr))` }}
    >
      <span className="hm-corner" aria-hidden="true" />
      {LABELS.map((actual) => (
        <span key={`head-${actual}`} className="hm-head">
          {actual}
        </span>
      ))}

      {LABELS.map((predicted) => (
        <Fragment key={predicted}>
          <span className="hm-row-head">{predicted}</span>
          {LABELS.map((actual) => {
            const count = matrix?.[predicted]?.[actual] ?? 0;
            const diagonal = predicted === actual;
            const isMax =
              mostCommonError != null &&
              !diagonal &&
              mostCommonError.predicted === predicted &&
              mostCommonError.actual === actual;
            return (
              <span
                key={`${predicted}-${actual}`}
                className={`hm-cell${isMax ? " hm-max" : ""}`}
                style={{ background: cellColor(count, max, diagonal) }}
                title={`predicted "${predicted}" → actual "${actual}": ${count}`}
              >
                {count}
              </span>
            );
          })}
        </Fragment>
      ))}
    </div>
  );
}
