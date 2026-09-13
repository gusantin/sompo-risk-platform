import { Card } from "@/components/ui/card";
import { RiskBadge } from "@/components/risk-badge";
import { exposureHeading, provenanceLabel } from "@/lib/provenance";
import type { PropertyView } from "@/lib/types";
import { deliveryLabels } from "@/lib/operations";
import { EnvironmentalConditions } from "@/components/environmental-conditions";

export function ExposureSummary({ properties, client, onSelect }: { properties: PropertyView[]; client: boolean; onSelect: (property: PropertyView) => void }) {
  return <section aria-label={client ? "Situação da propriedade" : "Exposição da carteira"} className="grid gap-3 lg:grid-cols-3">
    {properties.map((p) => <Card key={p.id} className={`min-w-0 p-5 ${client ? "lg:col-span-3" : ""}`}>
      {!client && p.clientName && <p className="text-xs font-semibold text-slate-500">{p.clientName}{p.propertyDemo ? " · cliente demonstrativo" : ""}</p>}
      <button className="mt-1 text-left text-lg font-bold text-slate-900 hover:underline" onClick={() => onSelect(p)}>{p.name}</button>
      <p className="text-sm text-slate-500">{p.city} / {p.uf}</p>
      <div className="my-3 flex flex-wrap items-center gap-2"><span className="text-xs font-semibold">{exposureHeading(p)}</span><RiskBadge level={p.level} /><span className="text-sm">{p.riskType}</span></div>
      <div className={client ? "grid gap-4 md:grid-cols-3" : "space-y-3"}>
        <div><h3 className="text-xs font-bold text-slate-700">O que está acontecendo?</h3><p className="mt-1 text-sm text-slate-600">{p.factors[0]?.description ?? p.factors[0]?.label ?? (p.level === "unknown" ? "A avaliação não está disponível." : "Consulte os fatores da avaliação registrada.")}</p></div>
        <div><h3 className="text-xs font-bold text-slate-700">Por que isso importa?</h3>{p.factors.length ? <ul className="mt-1 space-y-1 text-sm text-slate-600">{p.factors.slice(0, 3).map((f) => <li key={f.key}>{f.description ?? f.label}</li>)}</ul> : <p className="mt-1 text-sm text-slate-600">Evidências detalhadas indisponíveis.</p>}</div>
        <div><h3 className="text-xs font-bold text-slate-700">O que fazer agora?</h3><p className="mt-1 text-sm text-slate-600">{p.recommendations?.map((r) => r.text).join(" ") || "Nenhuma ação preventiva específica foi informada nesta avaliação."}</p></div>
      </div>
      <EnvironmentalConditions context={p.environmentalContext} compact={!client} />
      <details className="mt-4 text-xs text-slate-600"><summary className="cursor-pointer font-semibold">Dados usados nesta análise</summary>
        {p.propertyDemo && <p className="mt-2">Identidade fictícia de apresentação; não representa cliente SOMPO.</p>}
        <p className="mt-2">{p.coordinateDisclosure}</p>
        <ul className="mt-2 space-y-1">{p.environmentalValues.map((v, i) => <li key={`${v.label}-${i}`}>{v.label}: {v.value}{v.source ? ` · ${v.source}` : ""}{v.updatedLabel ? ` · ${v.updatedLabel}` : ""}</li>)}</ul>
      </details>
      <p className="mt-3 text-xs font-semibold text-slate-700">{provenanceLabel(p)}</p>
      <p className="mt-1 text-xs text-slate-500">Última atualização: {p.analysisTimestamp ?? "não disponível"}</p>
      <p className="mt-1 text-xs text-slate-500">Fontes consultadas: {p.sources.filter((s) => s.updatedLabel).map((s) => s.name).join(" · ") || "não disponíveis"}</p>
      <p className="mt-2 text-xs text-slate-500">Alertas abertos: {p.alertCount ?? "não consultados"} · Telegram: {p.operationalState ? p.operationalState.alerts.flatMap((a) => a.notifications).map((n) => deliveryLabels[n.status] ?? "Estado indisponível").join(" · ") || "sem entrega registrada no recorte" : "consulta indisponível"}</p>
      {p.operationalState && <p className="mt-1 text-xs text-slate-500">Acompanhamento: {p.operationalState.alerts.map((a) => ({ open: "Aberto", acknowledged: "Reconhecido", resolved: "Resolvido" }[a.status] ?? "Estado indisponível")).join(" · ") || "sem alertas no recorte"}</p>}
    </Card>)}
  </section>;
}
