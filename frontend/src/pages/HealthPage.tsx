import { useCallback, useEffect, useState } from "react";

import { ApiError, getConfig, getHealth } from "../api/client";
import type { ConfigResponse, HealthResponse } from "../api/types";
import { LatencyBars } from "../components/charts/LatencyBars";
import { Button } from "../components/shared/Button";
import { Card } from "../components/shared/Card";
import { ErrorBanner } from "../components/shared/ErrorBanner";
import { LoadingSpinner } from "../components/shared/LoadingSpinner";

function StatusBanner({ health }: { health: HealthResponse }) {
  const cls =
    health.overall_status === "healthy"
      ? "status-healthy"
      : health.overall_status === "degraded"
        ? "status-degraded"
        : "status-unhealthy";
  return (
    <div className={`status-banner ${cls}`}>
      <span>
        Backend Health: <strong>{health.overall_status}</strong>
      </span>
      <span style={{ fontSize: "0.78rem", fontWeight: "normal" }}>
        checked {health.timestamp}
      </span>
    </div>
  );
}

function ConfigCard({ config }: { config: ConfigResponse }) {
  const [showModels, setShowModels] = useState(false);

  return (
    <Card title="System Configuration">
      <ul className="config-list">
        <li>
          <span className="config-key">backend mode</span>
          <span className="config-val">{config.backend_mode}</span>
        </li>
        <li>
          <span className="config-key">embedding model</span>
          <span className="config-val">{config.embedding_model_name}</span>
        </li>
        <li>
          <span className="config-key">SVO extractor</span>
          <span className="config-val">{config.svo_extractor_name}</span>
        </li>
        <li>
          <span className="config-key">validator</span>
          <span className="config-val">{config.validator_name}</span>
        </li>
        <li>
          <span className="config-key">LM judge</span>
          <span className={`config-val ${config.enable_lm_judge ? "flag-on" : "flag-off"}`}>
            {config.enable_lm_judge ? "enabled" : "disabled"}
          </span>
        </li>
        <li>
          <span className="config-key">LM classifier</span>
          <span className={`config-val ${config.enable_lm_classifier ? "flag-on" : "flag-off"}`}>
            {config.enable_lm_classifier ? "enabled" : "disabled"}
          </span>
        </li>
        <li>
          <span className="config-key">backends</span>
          <span className="config-val">
            lexical {config.backend_status.lexical} · semantic{" "}
            {config.backend_status.semantic} · graph {config.backend_status.graph}
          </span>
        </li>
        <li>
          <span className="config-key">sqlite path</span>
          <span className="config-val muted">{config.sqlite_path}</span>
        </li>
      </ul>
      <button
        type="button"
        className="btn btn-secondary"
        style={{ marginTop: "0.6rem", fontSize: "0.8rem" }}
        onClick={() => setShowModels((v) => !v)}
      >
        {showModels ? "Hide" : "Show"} available models (
        {config.available_embedding_models.length} embeddings,{" "}
        {config.available_svo_extractors.length} extractors)
      </button>
      {showModels ? (
        <div style={{ fontSize: "0.78rem", color: "var(--muted)", marginTop: "0.4rem" }}>
          <div>embeddings: {config.available_embedding_models.join(", ")}</div>
          <div>extractors: {config.available_svo_extractors.join(", ")}</div>
        </div>
      ) : null}
    </Card>
  );
}

export default function HealthPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [refreshing, setRefreshing] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);

  const load = useCallback(async (force: boolean) => {
    if (force) setRefreshing(true);
    setError(null);
    try {
      setHealth(await getHealth(force));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load backend health.");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
    getConfig()
      .then(setConfig)
      .catch(() => null);
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = window.setInterval(() => void load(true), 30000);
    return () => window.clearInterval(id);
  }, [autoRefresh, load]);

  return (
    <>
      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      <div className="row-between">
        <h2 style={{ margin: 0 }}>Backend Health</h2>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.4rem",
            fontSize: "0.85rem",
            marginLeft: "auto",
            marginRight: "0.75rem",
          }}
        >
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
          />
          auto-refresh (30s)
        </label>
        <Button variant="secondary" loading={refreshing} onClick={() => void load(true)}>
          Refresh
        </Button>
      </div>

      {!health && refreshing ? <LoadingSpinner message="Checking backends…" /> : null}

      {health ? (
        <>
          <StatusBanner health={health} />

          <Card title="Latency by backend">
            <LatencyBars
              entries={Object.entries(health.backends ?? {}).map(([name, b]) => ({
                name,
                latency_ms: b.latency_ms ?? null,
              }))}
            />
          </Card>

          {Object.entries(health.backends ?? {}).map(([name, backend]) => (
            <Card key={name}>
              <div className="verdict-title">
                <span
                  className={`label-dot ${backend.is_healthy ? "label-supported" : "label-contradicted"}`}
                />
                <span>{backend.backend_name || name}</span>
                <span className="score">{backend.is_healthy ? "healthy" : "unhealthy"}</span>
              </div>
              <div style={{ fontSize: "0.8rem", color: "var(--muted)", marginTop: "0.3rem" }}>
                latency:{" "}
                {typeof backend.latency_ms === "number"
                  ? `${Math.round(backend.latency_ms)} ms`
                  : "—"}
                {" · "}
                checked {backend.timestamp ?? "—"}
              </div>
              {backend.error_message ? (
                <p className="card-error" role="alert">
                  {backend.error_message}
                </p>
              ) : null}
            </Card>
          ))}

          <Card title="Operational recommendations">
            {health.recommendations?.length ? (
              <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
                {health.recommendations.map((rec, i) => (
                  <li key={i}>{rec}</li>
                ))}
              </ul>
            ) : (
              <p className="hm-empty">No recommendations.</p>
            )}
          </Card>
        </>
      ) : null}

      {config ? <ConfigCard config={config} /> : null}
    </>
  );
}
