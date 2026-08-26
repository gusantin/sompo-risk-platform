import type { RiskLevel } from "@/lib/types";

const colors: Record<RiskLevel, string> = {
  low: "#059669", moderate: "#d97706", high: "#ea580c", critical: "#dc2626", unknown: "#64748b",
};

export function RiskSparkline({ values, level }: { values: number[]; level: RiskLevel }) {
  const data = values.length > 1 ? values : [35, 42, 47, 53, 61, values[0] ?? 50];
  const points = data.map((value, index) => `${(index / (data.length - 1)) * 100},${36 - Math.max(2, Math.min(34, value * 0.34))}`).join(" ");
  return (
    <svg viewBox="0 0 100 38" preserveAspectRatio="none" className="h-10 w-full" role="img" aria-label="Tendência recente do índice de risco">
      <path d="M0 36 H100" stroke="#e2e8f0" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      <polyline points={points} fill="none" stroke={colors[level]} strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
