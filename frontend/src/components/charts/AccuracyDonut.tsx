import { PolarAngleAxis, RadialBar, RadialBarChart, ResponsiveContainer } from "recharts";

import { CHART_COLORS } from "./chartTheme";

interface AccuracyDonutProps {
  accuracy: number;
}

function bandColor(accuracy: number): string {
  if (accuracy >= 0.8) return CHART_COLORS.green;
  if (accuracy >= 0.5) return CHART_COLORS.amber;
  return CHART_COLORS.red;
}

export function AccuracyDonut({ accuracy }: AccuracyDonutProps) {
  const pct = Math.round(accuracy * 100);
  const fill = bandColor(accuracy);

  return (
    <div style={{ position: "relative", width: "100%", maxWidth: 180 }}>
      <ResponsiveContainer width="100%" height={160}>
        <RadialBarChart
          data={[{ name: "accuracy", value: pct, fill }]}
          innerRadius="72%"
          outerRadius="100%"
          startAngle={90}
          endAngle={-270}
        >
          <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
          <RadialBar background dataKey="value" cornerRadius={8} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          pointerEvents: "none",
        }}
      >
        <strong style={{ fontSize: "1.4rem" }}>{pct}%</strong>
        <span style={{ color: CHART_COLORS.muted, fontSize: "0.75rem" }}>accuracy</span>
      </div>
    </div>
  );
}
