interface LatencyEntry {
  name: string;
  latency_ms: number | null | undefined;
}

interface LatencyBarsProps {
  entries: LatencyEntry[];
}

export function LatencyBars({ entries }: LatencyBarsProps) {
  const withValues = entries.filter((e) => typeof e.latency_ms === "number");
  if (entries.length === 0) return null;

  const max = Math.max(...withValues.map((e) => e.latency_ms as number), 1e-9);

  return (
    <div>
      {entries.map((entry) => {
        const ms = entry.latency_ms;
        const pct = typeof ms === "number" ? (ms / max) * 100 : 0;
        return (
          <div key={entry.name} className="latency-row">
            <span className="latency-name">{entry.name}</span>
            <span className="bar-track">
              {typeof ms === "number" && (
                <span
                  className="bar-fill"
                  style={{ width: `${pct}%` }}
                  title={`${entry.name}: ${ms} ms`}
                />
              )}
            </span>
            <span className="latency-ms">
              {typeof ms === "number" ? `${Math.round(ms)} ms` : "—"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
