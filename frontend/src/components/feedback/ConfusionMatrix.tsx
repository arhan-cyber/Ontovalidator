import type { MostCommonError, ConfusionMatrix } from "../../api/types";
import { ConfusionHeatmap } from "../charts";

interface ConfusionMatrixProps {
  matrix: ConfusionMatrix;
  mostCommonError: MostCommonError | null;
}

export function ConfusionMatrix({ matrix, mostCommonError }: ConfusionMatrixProps) {
  const total = Object.values(matrix ?? {}).reduce(
    (sum, row) => sum + Object.values(row ?? {}).reduce((s, c) => s + c, 0),
    0,
  );

  return (
    <div>
      <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginBottom: "0.5rem" }}>
        rows = predicted · columns = actual
      </div>
      <ConfusionHeatmap matrix={matrix} mostCommonError={mostCommonError} />
      {total > 0 && (
        <div style={{ fontSize: "0.78rem", color: "var(--muted)", marginTop: "0.5rem" }}>
          {mostCommonError ? (
            <>
              Most common error:{" "}
              <strong style={{ color: "var(--amber)" }}>
                {mostCommonError.predicted} → {mostCommonError.actual}
              </strong>{" "}
              ({mostCommonError.count} case{mostCommonError.count === 1 ? "" : "s"})
            </>
          ) : (
            <>All corrections agreed with the predicted labels.</>
          )}
        </div>
      )}
    </div>
  );
}
