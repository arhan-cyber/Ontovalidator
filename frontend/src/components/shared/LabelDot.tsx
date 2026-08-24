export type VerdictLabel = "supported" | "contradicted" | "partial" | "unknown";

interface LabelDotProps {
  label: string;
}

export function LabelDot({ label }: LabelDotProps) {
  return <span className={`label-dot label-${label}`} title={label} aria-label={label} />;
}
