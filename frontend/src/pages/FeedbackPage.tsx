import { useCallback, useEffect, useState } from "react";

import { ApiError, getFeedbackAnalysis } from "../api/client";
import type { FeedbackAnalysisResponse } from "../api/types";
import { AccuracyDonut } from "../components/charts";
import { ConfusionMatrix } from "../components/feedback/ConfusionMatrix";
import { RecommendationsList } from "../components/feedback/RecommendationsList";
import { RetrieverPerformanceTable } from "../components/feedback/RetrieverPerformanceTable";
import { Card } from "../components/shared/Card";
import { ErrorBanner } from "../components/shared/ErrorBanner";
import { LoadingSpinner } from "../components/shared/LoadingSpinner";

const DAY_OPTIONS = [7, 14, 30, 90] as const;

export default function FeedbackPage() {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<FeedbackAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (windowDays: number) => {
    setLoading(true);
    setError(null);
    try {
      setData(await getFeedbackAnalysis(windowDays));
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not load feedback analysis.",
      );
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [days, load]);

  return (
    <>
      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      <div className="row-between">
        <h2 style={{ margin: 0 }}>Feedback Analysis</h2>
        <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          Window
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {DAY_OPTIONS.map((d) => (
              <option key={d} value={d}>
                last {d} days
              </option>
            ))}
          </select>
        </label>
      </div>

      {loading ? <LoadingSpinner message="Analyzing feedback…" /> : null}

      {data && !loading ? (
        <>
          <div className="summary" style={{ alignItems: "center" }}>
            <span className="stat-chip">
              <span className="stat-value">{data.summary.total_corrections}</span>
              <span className="stat-label">corrections</span>
            </span>
            <span className="stat-chip">
              <span className="stat-value">{data.summary.window_days}</span>
              <span className="stat-label">day window</span>
            </span>
          </div>

          <div className="card chart-box" style={{ maxWidth: 260 }}>
            <h4>System accuracy</h4>
            <AccuracyDonut accuracy={data.summary.system_accuracy} />
          </div>

          <Card title="Predicted vs actual (confusion matrix)">
            <ConfusionMatrix
              matrix={data.error_analysis.confusion_matrix}
              mostCommonError={data.error_analysis.most_common_error}
            />
          </Card>

          <Card title="Retriever performance">
            <RetrieverPerformanceTable performance={data.retriever_performance} />
          </Card>

          <Card title="Recommendations">
            <RecommendationsList recommendations={data.recommendations} />
          </Card>
        </>
      ) : null}
    </>
  );
}
