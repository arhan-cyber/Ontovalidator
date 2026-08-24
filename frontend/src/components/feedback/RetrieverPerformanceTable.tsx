import type { RetrieverPerformance } from "../../api/types";
import { RetrieverAccuracyChart } from "../charts";

interface RetrieverPerformanceTableProps {
  performance?: RetrieverPerformance | null;
}

function sourceLabel(sources: string[] | null | undefined): string {
  return sources && sources.length > 0 ? sources.join("+") : "(none)";
}

export function RetrieverPerformanceTable({ performance }: RetrieverPerformanceTableProps) {
  const rows = performance?.all_combinations ?? [];
  if (rows.length === 0) {
    return <p className="hm-empty">No retriever data.</p>;
  }

  const bestKey = JSON.stringify(performance?.best_combination?.retrieval_sources ?? []);
  const worstKey = JSON.stringify(performance?.worst_combination?.retrieval_sources ?? []);

  return (
    <div>
      <table style={{ width: "100%", fontSize: "0.82rem", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ color: "var(--muted)", textAlign: "left" }}>
            <th style={{ padding: "0.3rem" }}>Combination</th>
            <th style={{ padding: "0.3rem" }}>Cases</th>
            <th style={{ padding: "0.3rem" }}>Accuracy</th>
            <th style={{ padding: "0.3rem" }}>Error rate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const key = JSON.stringify(r.retrieval_sources);
            const badge =
              key === bestKey ? (
                <span className="badge badge-current">best</span>
              ) : key === worstKey ? (
                <span className="badge badge-outdated">worst</span>
              ) : null;
            return (
              <tr key={key}>
                <td style={{ padding: "0.3rem" }}>
                  {sourceLabel(r.retrieval_sources)} {badge}
                </td>
                <td style={{ padding: "0.3rem" }}>{r.total_cases}</td>
                <td style={{ padding: "0.3rem", color: "var(--green)" }}>
                  {(r.accuracy * 100).toFixed(1)}%
                </td>
                <td style={{ padding: "0.3rem", color: r.error_rate > 0.5 ? "var(--red)" : "inherit" }}>
                  {(r.error_rate * 100).toFixed(1)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="chart-box" style={{ marginTop: "0.75rem" }}>
        <h4>Accuracy vs error rate by retriever combination</h4>
        <RetrieverAccuracyChart rows={rows} />
      </div>
    </div>
  );
}
