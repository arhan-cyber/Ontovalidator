import type { ReactNode } from "react";

interface StatChipProps {
  label: string;
  value: ReactNode;
}

export function StatChip({ label, value }: StatChipProps) {
  return (
    <span className="stat-chip">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </span>
  );
}
