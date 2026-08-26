import { cn } from "@/lib/utils";
import type { RiskLevel } from "@/lib/types";

export const riskLabels: Record<RiskLevel, string> = {
  low: "Baixo", moderate: "Moderado", high: "Alto", critical: "Crítico", unknown: "Sem dados",
};

export const riskTone: Record<RiskLevel, string> = {
  low: "border-emerald-200 bg-emerald-50 text-emerald-700",
  moderate: "border-amber-200 bg-amber-50 text-amber-700",
  high: "border-orange-200 bg-orange-50 text-orange-700",
  critical: "border-red-200 bg-red-50 text-red-700",
  unknown: "border-slate-200 bg-slate-100 text-slate-500",
};

export function RiskBadge({ level, className }: { level: RiskLevel; className?: string }) {
  return <span className={cn("inline-flex rounded-full border px-2.5 py-1 text-[10px] font-extrabold uppercase tracking-[0.12em]", riskTone[level], className)}>{riskLabels[level]}</span>;
}
