import { Tooltip, TooltipProps } from "recharts";

import { CHART_COLORS } from "./chartTheme";

export function DarkTooltip(props: TooltipProps<number, string>) {
  return (
    <Tooltip
      cursor={{ fill: "rgba(79, 140, 255, 0.08)" }}
      contentStyle={{
        backgroundColor: CHART_COLORS.panel,
        border: `1px solid ${CHART_COLORS.border}`,
        borderRadius: 6,
        color: "#e6e9ef",
        fontSize: 12,
      }}
      labelStyle={{ color: "#e6e9ef" }}
      itemStyle={{ color: "#e6e9ef" }}
      {...props}
    />
  );
}
