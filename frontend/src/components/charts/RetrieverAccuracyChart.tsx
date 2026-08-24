import { Bar, BarChart, Legend, ResponsiveContainer, XAxis, YAxis } from "recharts";

import { AXIS_TICK, CHART_COLORS } from "./chartTheme";
import { DarkTooltip } from "./DarkTooltip";
import type { RetrieverCombinationStats } from "../../api/types";

interface RetrieverAccuracyChartProps {
  rows: RetrieverCombinationStats[];
}

export function RetrieverAccuracyChart({ rows }: RetrieverAccuracyChartProps) {
  if (!rows || rows.length === 0) {
    return <p className="hm-empty">No retriever data.</p>;
  }

  const data = rows.map((r) => ({
    combination: r.retrieval_sources.join("+") || "(none)",
    Accuracy: Math.round(r.accuracy * 100),
    "Error rate": Math.round(r.error_rate * 100),
  }));

  return (
    <ResponsiveContainer width="100%" height={Math.max(140, data.length * 44 + 40)}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 8 }}>
        <XAxis type="number" domain={[0, 100]} tick={AXIS_TICK} axisLine={{ stroke: CHART_COLORS.border }} tickLine={false} />
        <YAxis type="category" dataKey="combination" width={120} tick={AXIS_TICK} axisLine={false} tickLine={false} />
        <DarkTooltip />
        <Legend wrapperStyle={{ fontSize: 11, color: CHART_COLORS.muted }} />
        <Bar dataKey="Accuracy" fill={CHART_COLORS.green} radius={[0, 4, 4, 0]} barSize={12} />
        <Bar dataKey="Error rate" fill={CHART_COLORS.red} radius={[0, 4, 4, 0]} barSize={12} />
      </BarChart>
    </ResponsiveContainer>
  );
}
