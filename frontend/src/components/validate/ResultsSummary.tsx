import type { ValidateResponse } from "../../api/types";
import {
  ChunkTypeHistogram,
  LabelDistributionChart,
} from "../charts";

interface ResultsSummaryProps {
  result: ValidateResponse;
}

export function ResultsSummary({ result }: ResultsSummaryProps) {
  const { summary, chunk_types } = result;

  return (
    <section>
      <div className="summary">
        <span>
          <strong>{summary.total_triples}</strong> total
        </span>
        <span>
          supported: <strong>{summary.supported}</strong>
        </span>
        <span>
          contradicted: <strong>{summary.contradicted}</strong>
        </span>
        <span>
          partial: <strong>{summary.partial}</strong>
        </span>
        <span>
          unknown: <strong>{summary.unknown}</strong>
        </span>
        <span>
          avg score: <strong>{summary.avg_score.toFixed(2)}</strong>
        </span>
        <span>
          cache hits: <strong>{summary.cache_hits}</strong>
        </span>
        {summary.errors > 0 && (
          <span className="badge badge-outdated" title="Triples whose adjudication failed server-side; see logs.">
            errors: <strong>{summary.errors}</strong>
          </span>
        )}
      </div>

      <div className="charts-row">
        <div className="card chart-box">
          <h4>Verdict distribution</h4>
          <LabelDistributionChart
            supported={summary.supported}
            contradicted={summary.contradicted}
            partial={summary.partial}
            unknown={summary.unknown}
          />
        </div>
        <div className="card chart-box">
          <h4>Chunk types ingested</h4>
          <ChunkTypeHistogram data={chunk_types} />
        </div>
      </div>

      <p style={{ color: "var(--gray)", fontSize: "0.78rem", margin: "0 0 1rem" }}>
        {result.ingestion_status} · {result.chunks_ingested} chunks ·{" "}
        {result.svos_extracted} SVOs extracted
      </p>
    </section>
  );
}
