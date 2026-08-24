import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis } from "recharts";

import { AXIS_TICK, LABEL_COLORS } from "./chartTheme";
import { DarkTooltip } from "./DarkTooltip";

interface LabelDistributionChartProps {
  supported: number;
  contradicted: number;
  partial: number;
  unknown: number;
}

const LABELS = ["supported", "contradicted", "partial", "unknown"] as const;

export function LabelDistributionChart({
  supported,
  contradicted,
  partial,
  unknown,
}: LabelDistributionChartProps) {
  const data = LABELS.map((label) => ({
    label,
    count:
      label === "supported"
        ? supported
        : label === "contradicted"
          ? contradicted
          : label === "partial"
            ? partial
            : unknown,
    fill: LABEL_COLORS[label],
  }));

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -24 }}>
        <XAxis dataKey="label" tick={AXIS_TICK} axisLine={{ stroke: "#2a2f37" }} tickLine={false} />
        <YAxis allowDecimals={false} tick={AXIS_TICK} axisLine={false} tickLine={false} />
        <DarkTooltip />
        <Bar dataKey="count" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
