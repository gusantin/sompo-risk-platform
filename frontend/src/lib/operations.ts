import type { CommandCenterData, RiskLevel } from "./types";

export type OperationalAlert = {
  alertId: string; fazendaId: string; maquinaId?: string; type: string; riskType: string;
  severity: RiskLevel; status: "open" | "acknowledged" | "resolved";
  createdAt?: string; lastTriggeredAt?: string; acknowledgedAt?: string; resolvedAt?: string;
  factors: unknown[]; evidence: unknown[]; recommendations?: { ruleId: string; text: string }[]; demoData?: boolean;
};
export type Delivery = { notificationId: string; status: string; channel: string; createdAt?: string; attemptedAt?: string; deliveredAt?: string; retryable?: boolean; kind?: string };
export const severityRank: Record<RiskLevel, number> = { critical: 4, high: 3, moderate: 2, low: 1, unknown: 0 };
export const statusLabels = { open: "Aberto", acknowledged: "Reconhecido", resolved: "Resolvido" };
export const deliveryLabels: Record<string, string> = { created: "Na fila", attempting: "Envio em processamento", delivered: "Entrega aceita pelo Telegram", failed: "Falha no envio", unknown: "Entrega incerta · verificar", permanently_failed: "Tentativas esgotadas", cancelled: "Envio cancelado" };
export const alertTypeLabels: Record<string, string> = { environmental_fire_risk: "Risco de incêndio", environmental_risk: "Risco ambiental", machine_risk: "Condição da máquina", operational_combined_risk: "Exposição operacional", hotspot_near_property: "Foco de calor no entorno", machine_near_hotspot: "Máquina exposta a foco de calor", severe_weather_warning: "Aviso meteorológico" };
export function evidenceText(value: unknown): string | null {
  if (!value || typeof value !== "object") return typeof value === "string" ? value : null;
  const e = value as Record<string, unknown>;
  if (typeof e.description === "string") return e.description;
  if (e.weatherSeverity) return `${e.eventType ?? "Aviso meteorológico"} · ${e.weatherSeverity}${e.source ? ` · ${e.source}` : ""}`;
  if (typeof e.distanceKm === "number" && Number.isFinite(e.distanceKm)) return `Distância registrada do foco de calor: ${e.distanceKm.toLocaleString("pt-BR")} km. Não confirma incêndio.`;
  if (typeof e.value === "number" && Number.isFinite(e.value)) {
    const internal = ["machine_internal", "machine_component"].includes(String(e.scope));
    const label = typeof e.label === "string" ? e.label : e.type === "temperature" ? internal ? "Temperatura do componente" : e.scope === "ambient_local" ? "Temperatura ambiente/local" : "Temperatura medida · contexto não informado" : e.type === "vibration" && internal ? "Vibração do componente" : "Medição informada";
    const unit = e.unit === "celsius" ? "°C" : e.unit === "percent" ? "%" : e.unit ?? "";
    return `${label}: ${e.value.toLocaleString("pt-BR")} ${unit}`;
  }
  if (typeof e.score === "number") return `Índice oficial registrado: ${e.score}/100`;
  return null;
}
const time = (value?: string | null) => value && Number.isFinite(Date.parse(value)) ? Date.parse(value) : 0;
export const stamp = (value?: string) => time(value) ? new Date(value!).toLocaleString("pt-BR") : "Não informado";
export function factorText(value: unknown): string {
  if (typeof value === "string") {
    const labels: Record<string, string> = {
      environmental_fire_elevated: "Risco ambiental de incêndio elevado",
      machine_risk_elevated: "Risco interno da máquina elevado",
      recent_machine_location: "Localização recente da máquina",
      nearby_hotspot: "Foco de calor próximo",
      recent_hotspot_near_property: "Foco de calor recente próximo da propriedade",
    };
    return labels[value] ?? value.replaceAll("_", " ");
  }
  if (value && typeof value === "object") {
    const factor = value as Record<string, unknown>;
    return factorText(factor.description ?? factor.descricao ?? factor.label ?? factor.fator ?? factor.key);
  }
  return "Fator não informado";
}
export function compareAlerts(a: OperationalAlert, b: OperationalAlert) {
  return severityRank[b.severity] - severityRank[a.severity]
    || ({ open: 0, acknowledged: 1, resolved: 2 }[a.status] - { open: 0, acknowledged: 1, resolved: 2 }[b.status])
    || time(b.lastTriggeredAt ?? b.createdAt) - time(a.lastTriggeredAt ?? a.createdAt)
    || a.alertId.localeCompare(b.alertId);
}
export function alertTimeline(alert: OperationalAlert, deliveries: Delivery[] = []) {
  const entries = [
    { at: alert.createdAt, label: "Alerta criado" },
    { at: alert.acknowledgedAt, label: "Alerta reconhecido" },
    { at: alert.resolvedAt, label: "Alerta resolvido" },
    // An alert ID can be reused after reopening; older deliveries belong to a prior occurrence.
    ...deliveries.filter((d) => time(alert.createdAt) && time(d.createdAt) && time(d.createdAt) >= time(alert.createdAt)).flatMap((d) => [
      { at: d.createdAt, label: `Notificação preparada · ${d.channel}` },
      { at: d.attemptedAt, label: `Tentativa de envio · ${d.channel}` },
      { at: d.deliveredAt, label: `Entrega aceita pelo canal · ${d.channel}` },
    ]),
  ];
  return entries.filter((e) => time(e.at)).sort((a, b) => time(a.at) - time(b.at));
}
export function priorityItems(data: CommandCenterData, alerts: OperationalAlert[] | null, propertyId?: string) {
  const unique = new Map<string, OperationalAlert>();
  for (const alert of alerts ?? []) unique.set(alert.alertId, alert);
  const active = [...unique.values()].filter((a) => a.status !== "resolved");
  const items = active.map((a) => {
    const p = data.properties.find((p) => p.id === a.fazendaId);
    const m = data.machines.find((m) => m.propertyId === a.fazendaId && m.id === a.maquinaId);
    return { id: a.alertId, propertyId: a.fazendaId, name: m?.name ?? p?.name ?? a.maquinaId ?? a.fazendaId,
      level: a.severity, risk: a.riskType, factor: factorText(a.factors?.[0]),
      recommendation: a.recommendations?.[0]?.text, status: statusLabels[a.status], state: a.status as string,
      at: a.lastTriggeredAt ?? a.createdAt, freshness: m?.lastCommunication ?? p?.analysisFreshness ?? "Atualização indisponível", alertId: a.alertId };
  });
  for (const p of data.properties) {
    const level = p.environmentalLevel ?? p.level;
    if (level === "low" || active.some((a) => a.fazendaId === p.id && !a.maquinaId)) continue;
    items.push({ id: `property:${p.id}`, propertyId: p.id, name: p.name, level, risk: "Ambiental",
      factor: level === "unknown" ? "Avaliação ambiental indisponível" : p.factors[0]?.description ?? p.factors[0]?.label ?? "Consulte os fatores por categoria na propriedade",
      recommendation: p.recommendations?.[0]?.text, status: alerts ? "Sem alerta ativo no recorte" : "Alertas indisponíveis", state: "none",
      at: p.analysisTimestamp ?? undefined, freshness: p.analysisFreshness, alertId: "" });
  }
  for (const m of data.machines) {
    const level = severityRank[m.machineRisk] > severityRank[m.operationalRisk] ? m.machineRisk : m.operationalRisk;
    if ((level === "low" && m.connection === "online") || active.some((a) => a.fazendaId === m.propertyId && a.maquinaId === m.id)) continue;
    items.push({ id: `machine:${m.propertyId}:${m.id}`, propertyId: m.propertyId, name: m.name, level,
      risk: "Máquina / operação", factor: m.connection !== "online" ? "Telemetria desatualizada ou indisponível" : "Consultar evidências da máquina",
      recommendation: m.recommendations?.[0]?.text, status: alerts ? "Sem alerta ativo no recorte" : "Alertas indisponíveis", state: "none",
      at: undefined, freshness: m.lastCommunication, alertId: "" });
  }
  const stateRank: Record<string, number> = { open: 0, acknowledged: 1, none: 2 };
  return items.filter((i) => !propertyId || i.propertyId === propertyId).sort((a, b) => severityRank[b.level] - severityRank[a.level]
    || stateRank[a.state] - stateRank[b.state] || time(b.at) - time(a.at) || a.id.localeCompare(b.id));
}
