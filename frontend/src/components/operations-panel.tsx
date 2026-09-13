"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { RiskBadge, riskLabels } from "@/components/risk-badge";
import type { CommandCenterData, RiskLevel } from "@/lib/types";

import { alertTimeline, alertTypeLabels, compareAlerts, deliveryLabels, evidenceText, factorText, priorityItems, stamp, statusLabels, type OperationalAlert as Alert, type Delivery } from "@/lib/operations";
const attention = (level: string) => ["high", "critical"].includes(level);

export function OperationsPanel({ data, perspective, propertyId, onAlertUpdated }: { onAlertUpdated?: (alert: Alert) => void; data: CommandCenterData; perspective: "sompo" | "client"; propertyId?: string }) {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [filter, setFilter] = useState("active");
  const [busy, setBusy] = useState<string | null>(null);
  const mutationLock = useRef(false);
  const [confirmation, setConfirmation] = useState<{ alert: Alert; status: "acknowledged" | "resolved" } | null>(null);
  const [success, setSuccess] = useState("");
  const [error, setError] = useState("");
  const [deliveries, setDeliveries] = useState<Record<string, Delivery[] | null>>({});
  useEffect(() => {
    let cancelled = false;
    if (data.source !== "backend") return;
    fetch("/api/alerts", { cache: "no-store" }).then(async (r) => {
      if (!r.ok) throw new Error();
      const result = await r.json();
      if (!cancelled) { setAlerts(result.items); setEnabled(result.actionsEnabled === true); }
    }).catch(() => { if (!cancelled) setAlerts(null); });
    return () => { cancelled = true; };
  }, [data.source, data.generatedAt]);
  const official = data.source === "backend";
  const preview = data.source === "demo" && data.demoAlerts !== undefined;
  const inventoryAvailable = (official || preview) && data.machineInventoryAvailable !== false;
  const scoped = data.source === "demo" && data.demoAlerts ? data.demoAlerts.filter((a) => perspective === "sompo" || a.fazendaId === propertyId) : official ? alerts?.filter((a) => !a.demoData && !a.fazendaId.startsWith("demo_") && data.properties.some((p) => p.id === a.fazendaId) && (perspective === "sompo" || a.fazendaId === propertyId)) ?? null : null;
  const properties = data.properties.filter((p) => perspective === "sompo" || p.id === propertyId);
  const machines = data.machines.filter((m) => perspective === "sompo" || m.propertyId === propertyId);
  const active = scoped?.filter((a) => a.status !== "resolved");
  const priorities = priorityItems({ ...data, properties, machines }, scoped, perspective === "client" ? propertyId : undefined);
  const ordered = scoped?.filter((a) => filter === "all" || (filter === "active" ? a.status !== "resolved" : a.status === filter)).sort(compareAlerts);
  async function update(alert: Alert, status: "acknowledged" | "resolved") {
    if (mutationLock.current || !enabled || !official) return;
    mutationLock.current = true;
    setBusy(alert.alertId); setError(""); setSuccess("");
    try {
      const r = await fetch("/api/alerts", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ alertId: alert.alertId, status }) });
      if (!r.ok) throw new Error();
      const result = await r.json();
      setSuccess(`Alerta ${statusLabels[result.alert.status as Alert["status"]].toLowerCase()} com confirmação do backend.`);
      setConfirmation(null);
      onAlertUpdated?.(result.alert);
      setAlerts((current) => current?.map((a) => a.alertId === alert.alertId ? { ...result.alert, recommendations: result.recommendations } : a) ?? null);
    } catch { setError("Alteração não confirmada. Atualize os dados antes de tentar novamente."); }
    finally { mutationLock.current = false; setBusy(null); }
  }
  return <section aria-label="Operações de risco" className="space-y-4">
    {data.source === "demo" && data.demoAlerts && <p className="rounded-lg bg-violet-100 p-3 text-sm font-semibold text-violet-900">DEMO offline · alertas sintéticos em consulta. Nenhuma escrita ou notificação real.</p>}
    <Card className="border-t-4 border-t-red-600 p-5">
      <h2 className="text-lg font-bold">{perspective === "sompo" ? "Prioridades agora" : "O que eu preciso fazer agora?"}</h2>
      <p className="mt-1 text-xs text-slate-500">{perspective === "client" ? "Condições e ações da sua propriedade" : `${properties.length} propriedades no recorte · ${machines.length} máquinas`}</p>
      <p className="mt-2 text-xs text-slate-500">Situações mais urgentes primeiro. Dados insuficientes permanecem identificados.</p>
      <ol aria-label="Fila de prioridades" className={`mt-4 grid gap-3 ${priorities.length <= 4 ? "lg:grid-cols-2 xl:grid-cols-4" : "lg:grid-cols-3"}`}>
        {priorities.slice(0, 6).map((item, index) => <li key={item.id} className="min-w-0 rounded-xl border border-slate-200 bg-slate-50/70 p-4">
          <div className="flex flex-wrap items-center gap-2"><span className="text-xs font-bold text-slate-500">{index + 1}</span><RiskBadge level={item.level} /><span className="text-xs text-slate-500">{item.status}</span></div>
          <h3 className="mt-2 break-words font-bold">{item.name}</h3><p className="text-xs text-slate-500">{item.risk}</p>
          <p className="mt-2 text-sm"><strong>Por quê:</strong> {item.factor}</p>
          <p className="mt-2 text-sm"><strong>Ação recomendada:</strong> {item.recommendation ?? "Recomendação determinística indisponível."}</p>
          <p className="mt-2 text-xs text-slate-500">{item.freshness}</p>
          {item.alertId && <a className="mt-3 inline-block text-sm font-semibold text-red-700 underline underline-offset-4" href={`#alert-${item.alertId}`} onClick={() => setFilter("active")}>Acompanhar alerta</a>}
        </li>)}
      </ol>
      {!priorities.length && <p className="mt-3 text-sm text-slate-500">{official && scoped ? "Nenhuma prioridade sinalizada no recorte disponível." : "Prioridades operacionais indisponíveis neste recorte."}</p>}
      {priorities.length > 6 && <p className="mt-3 text-xs text-slate-500">6 de {priorities.length} itens sinalizados. Consulte os alertas e ativos abaixo.</p>}
    </Card>
    <Card className="p-5">
      <h2 className="text-lg font-bold">{perspective === "sompo" ? "Exposição da carteira" : "O que precisa de atenção agora?"}</h2>
      <p className="mt-1 text-xs text-slate-500">{official ? "Leitura de snapshots oficiais · contagens do recorte consultado, não totais globais." : preview ? "DEMO offline: contagens e estados sintéticos do cenário exportado." : "DEMO / showcase: métricas operacionais e ciclo de alertas reais não disponíveis neste modo."}</p>
      {perspective === "sompo" && <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-5">{(["low", "moderate", "high", "critical", "unknown"] as RiskLevel[]).map((level) => <div key={level} className="rounded-lg bg-slate-50 p-3"><RiskBadge level={level} /><strong className="mt-2 block text-xl">{official || preview ? properties.filter((p) => (p.environmentalLevel ?? p.level) === level).length : "—"}</strong><p className="text-xs text-slate-500">Propriedades · risco ambiental</p></div>)}</div>}
      <div className="mt-4 grid gap-3 sm:grid-cols-3">{(["open", "acknowledged", "resolved"] as const).map((status) => <div key={status} className="rounded-lg border border-slate-200 p-3"><p className="text-xs text-slate-500">{statusLabels[status]}</p><strong className="text-2xl">{scoped ? scoped.filter((a) => a.status === status).length : "—"}</strong></div>)}</div>
      <p className="mt-2 text-xs text-slate-500">Até 100 alertas recentes. Ausência de registros de entrega não confirma notificação ao responsável.</p>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div><h3 className="text-sm font-bold">Ativos que exigem atenção</h3>{properties.filter((p) => attention(p.environmentalLevel ?? p.level) || active?.some((a) => a.fazendaId === p.id)).map((p) => <p key={p.id} className="mt-2 text-sm">{p.name} · {riskLabels[p.environmentalLevel ?? p.level]} <span className="text-xs text-slate-500">{p.analysisFreshness}</span></p>)}{machines.filter((m) => attention(m.machineRisk) || attention(m.operationalRisk) || ["stale", "offline"].includes(m.connection) || active?.some((a) => a.maquinaId === m.id && a.fazendaId === m.propertyId)).map((m) => <p key={`${m.propertyId}:${m.id}`} className="mt-2 text-sm">{m.name} · máquina {riskLabels[m.machineRisk]} · operacional {riskLabels[m.operationalRisk]}<span className="block text-xs text-slate-500">{m.lastCommunication}</span></p>)}<p className="mt-2 text-xs text-slate-500">{inventoryAvailable ? `${machines.length} máquinas no recorte · ${machines.filter((m) => m.machineRiskStatus !== "ok").length} sem avaliação interna suficiente.` : "Inventário de máquinas indisponível ou incompleto."}</p></div>
        <div><h3 className="text-sm font-bold">Categorias ativas / exposição operacional</h3><p className="mt-2 text-sm">{active ? [...new Set(active.map((a) => a.riskType))].join(" · ") || "Nenhuma categoria no recorte de alertas" : "Categorias indisponíveis"}</p><p className="mt-2 text-sm">Máquinas em risco alto/crítico: {inventoryAvailable ? machines.filter((m) => attention(m.machineRisk)).length : "—"}</p><p className="mt-2 text-sm">Operação em risco alto/crítico: {inventoryAvailable ? machines.filter((m) => attention(m.operationalRisk)).length : "—"}</p></div>
      </div>
    </Card>
    <Card className="p-5">
      <div className="flex flex-wrap justify-between gap-3"><h2 className="text-lg font-bold">Alertas preventivos · ações</h2><select aria-label="Filtrar status do alerta" className="rounded border p-2 text-sm" value={filter} onChange={(e) => setFilter(e.target.value)}><option value="active">Ativos</option><option value="open">Abertos</option><option value="acknowledged">Reconhecidos</option><option value="resolved">Resolvidos</option><option value="all">Histórico disponível</option></select></div>
      {!enabled && <p className="mt-2 text-xs text-slate-500">Acompanhamento em modo de consulta.</p>}
      {success && <p role="status" className="mt-2 text-sm text-emerald-700">{success}</p>}
      {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
      {!scoped ? <p className="mt-4 text-sm text-slate-500">Ciclo de alertas indisponível. Nenhum status foi inferido.</p> : !ordered?.length ? <p className="mt-4 text-sm text-slate-500">Nenhum alerta neste filtro e recorte.</p> : ordered.map((a) => <article id={`alert-${a.alertId}`} key={a.alertId} className="mt-4 rounded-xl border border-slate-200 p-4">
        <div className="flex flex-wrap items-center gap-2"><RiskBadge level={a.severity} /><strong>{alertTypeLabels[a.type] ?? "Alerta preventivo"}</strong><span className="ml-auto rounded bg-slate-100 px-2 py-1 text-xs">{statusLabels[a.status]}</span></div>
        <p className="mt-2 text-sm">{data.properties.find((p) => p.id === a.fazendaId)?.name ?? a.fazendaId}{a.maquinaId ? ` · ${a.maquinaId}` : ""}</p>
        <p className="mt-1 text-xs text-slate-500">Alerta criado: {stamp(a.createdAt)}</p>
        <p className="mt-3 text-sm"><strong>Por quê:</strong> {factorText(a.factors?.[0])}</p><details className="mt-3 text-xs"><summary className="cursor-pointer font-semibold">Fatores e evidências oficiais</summary><ul className="mt-2 space-y-2 rounded bg-slate-50 p-3">{[...a.factors.map(factorText), ...a.evidence.map(evidenceText)].filter(Boolean).map((text, i) => <li key={i}>{text}</li>)}</ul></details>
        {a.recommendations?.length ? a.recommendations.map((r) => <p key={r.ruleId} className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-950"><strong className="mb-1 block text-xs">Ação preventiva recomendada</strong>{r.text}<span className="mt-1 block text-xs text-amber-700">Orientação preventiva da avaliação registrada.</span></p>) : <p className="mt-3 text-xs text-slate-500">Recomendação determinística não disponível para esta condição.</p>}
        <ol aria-label="Linha do tempo do alerta" className="mt-4 space-y-2 border-l-2 border-slate-200 pl-4 text-xs text-slate-600">{alertTimeline(a, deliveries[a.alertId] ?? []).map((event, i) => <li key={i}><time>{stamp(event.at)}</time> — {event.label}</li>)}</ol>
        <p className="mt-2 text-xs text-slate-500">Reconhecido: {stamp(a.acknowledgedAt)} · Resolvido: {stamp(a.resolvedAt)}</p>
        <div className="mt-3 flex flex-wrap gap-2">{a.status === "open" && <Button size="sm" disabled={!enabled || busy !== null} onClick={() => setConfirmation({ alert: a, status: "acknowledged" })}>Reconhecer</Button>}{a.status !== "resolved" && <Button size="sm" variant="outline" disabled={!enabled || busy !== null} onClick={() => setConfirmation({ alert: a, status: "resolved" })}>Resolver</Button>}<Button size="sm" variant="outline" disabled={!official} onClick={async () => { try { const r = await fetch(`/api/alerts?alertId=${encodeURIComponent(a.alertId)}`); if (!r.ok) throw new Error(); const d = await r.json(); setDeliveries((v) => ({ ...v, [a.alertId]: d.items })); } catch { setDeliveries((v) => ({ ...v, [a.alertId]: null })); } }}>Consultar notificação</Button></div>
        {confirmation?.alert.alertId === a.alertId && <div role="group" aria-label="Confirmar ação do alerta" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-sm">{confirmation.status === "resolved" ? "Confirmar resolução? O alerta sairá da fila ativa." : "Confirmar que este alerta foi reconhecido?"}</p>
          <div className="mt-2 flex gap-2"><Button size="sm" disabled={busy !== null} onClick={() => update(a, confirmation.status)}>{busy === a.alertId ? "Confirmando…" : "Confirmar ação"}</Button><Button size="sm" variant="outline" disabled={busy !== null} onClick={() => setConfirmation(null)}>Cancelar</Button></div>
        </div>}
        {a.alertId in deliveries && <p className="mt-2 text-xs text-slate-500">{deliveries[a.alertId]?.length ? deliveries[a.alertId]!.map((d) => `${d.channel}${d.kind === "resolution" ? " · Encerramento" : d.kind === "escalation" ? " · Escalada" : ""}: ${d.retryable ? "Aguardando nova tentativa" : deliveryLabels[d.status] ?? "Estado indisponível"} · ${stamp(d.deliveredAt ?? d.attemptedAt)}`).join("; ") : "Entrega não confirmada / registro indisponível"}</p>}
      </article>)}
      {perspective === "client" && machines.flatMap((m) => (m.recommendations ?? []).map((r) => <p key={`${m.propertyId}:${m.id}:${r.ruleId}`} className="mt-3 rounded bg-amber-50 p-3 text-sm">{m.name}: {r.text} Regra: {r.ruleId} · {m.lastCommunication}</p>))}
    </Card>
  </section>;
}
