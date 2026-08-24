export const CHART_COLORS = {
  accent: "#4f8cff",
  green: "#38c172",
  red: "#e3342f",
  amber: "#f2a900",
  gray: "#6b7280",
  muted: "#9aa4b2",
  border: "#2a2f37",
  panel: "#171b21",
} as const;

export const LABEL_COLORS: Record<string, string> = {
  supported: CHART_COLORS.green,
  contradicted: CHART_COLORS.red,
  partial: CHART_COLORS.amber,
  unknown: CHART_COLORS.gray,
};

export const AXIS_TICK = { fill: CHART_COLORS.muted, fontSize: 11 } as const;
