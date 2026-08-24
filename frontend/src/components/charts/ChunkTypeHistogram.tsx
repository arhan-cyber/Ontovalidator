import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis } from "recharts";

import { AXIS_TICK, CHART_COLORS } from "./chartTheme";
import { DarkTooltip } from "./DarkTooltip";

interface ChunkTypeHistogramProps {
  data: Record<string, number>;
}

export function ChunkTypeHistogram({ data }: ChunkTypeHistogramProps) {
  const entries = Object.entries(data ?? {});
  if (entries.length === 0) {
    return <p className="hm-empty">No chunks ingested.</p>;
  }

  const rows = entries
    .sort((a, b) => b[1] - a[1])
    .map(([chunkType, count]) => ({ chunkType, count }));

  return (
    <ResponsiveContainer width="100%" height={Math.max(120, rows.length * 32 + 30)}>
      <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 24 }}>
        <XAxis type="number" allowDecimals={false} tick={AXIS_TICK} axisLine={{ stroke: "#2a2f37" }} tickLine={false} />
        <YAxis type="category" dataKey="chunkType" width={80} tick={AXIS_TICK} axisLine={false} tickLine={false} />
        <DarkTooltip />
        <Bar dataKey="count" fill={CHART_COLORS.accent} radius={[0, 4, 4, 0]} barSize={16} />
      </BarChart>
    </ResponsiveContainer>
  );
}
