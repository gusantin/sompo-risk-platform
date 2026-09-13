import "server-only";
import { readFile } from "node:fs/promises";
import { backendUrl, isPresentationDeployment } from "@/lib/backend-config";
import bundledPortfolio from "@/data/presentation-portfolio.json";

import { getDemoData } from "@/lib/demo-data";
import type { CommandCenterData, EnvironmentalContext, ExplainableFactor, HotspotView, LiveEvent, MachineView, PropertyView, RiskLevel, StateSummary } from "@/lib/types";

type JsonRecord = Record<string, unknown>;
const PILOT_STATES = ["MT", "MS", "GO", "MG", "PR"] as const;

function record(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {};
}

function array(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function values(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizeLevel(value: unknown): RiskLevel {
  const normalized = text(value).toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  if (["critico", "critical"].includes(normalized)) return "critical";
  if (["alto", "high"].includes(normalized)) return "high";
  if (["moderado", "moderate", "medium"].includes(normalized)) return "moderate";
  if (["baixo", "low"].includes(normalized)) return "low";
  return "unknown";
}

function relativeLabel(value: unknown): string {
  const timestamp = Date.parse(text(value));
  if (!Number.isFinite(timestamp)) return "sem comunicação registrada";
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 15) return "há poucos segundos";
  if (seconds < 60) return `há ${seconds} segundos`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  return `há ${Math.floor(hours / 24)} d`;
}

function timestampLabel(value: unknown): string | null {
  const timestamp = Date.parse(text(value));
  if (!Number.isFinite(timestamp)) return null;
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short", timeStyle: "medium", timeZone: "America/Sao_Paulo",
  }).format(timestamp);
}

function trendDirection(value: unknown): PropertyView["trend"] {
  const normalized = text(value).toLowerCase();
  if (["up", "rising", "increasing", "aumentando", "alta"].includes(normalized)) return "up";
  if (["down", "falling", "decreasing", "diminuindo", "queda"].includes(normalized)) return "down";
  if (["stable", "estavel", "estável"].includes(normalized)) return "stable";
  return "unknown";
}

async function backendFetch(path: string, timeoutMs = 3500): Promise<JsonRecord> {
  const base = backendUrl();
  if (!base) throw new Error("Backend not configured");
  const apiKey = process.env.SOMPO_BACKEND_API_KEY;
  const headers: HeadersInit = { Accept: "application/json" };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const response = await fetch(`${base.replace(/\/$/, "")}${path}`, {
    headers,
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) throw new Error(`Backend ${path}: HTTP ${response.status}`);
  return record(await response.json());
}

const FACTOR_LABELS: Record<string, string> = {
  temperatura_alta: "Temperatura ambiente elevada",
  umidade_relativa_baixa: "Umidade relativa baixa",
  rajadas: "Rajadas elevadas",
  ausencia_chuva: "Pouca precipitação",
  umidade_solo_baixa: "Umidade superficial do solo baixa",
  foco_calor_proximo: "Foco de calor próximo",
  temperatura_minima: "Temperatura mínima prevista",
  temperatura_atual: "Temperatura atual",
};

function readableFactor(raw: unknown): ExplainableFactor | null {
  const factor = record(raw);
  const rawKey = typeof raw === "string" ? raw : text(factor.fator ?? factor.key ?? factor.label);
  if (!rawKey) return null;
  const key = rawKey.toLowerCase();
  const label = FACTOR_LABELS[key] ?? rawKey.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
  const description = typeof raw === "string" ? null : text(factor.descricao ?? factor.description) || null;
  return { key, label, description, group: "now" };
}

function factorList(raw: unknown): ExplainableFactor[] {
  const unique = new Map<string, ExplainableFactor>();
  for (const item of values(raw).filter((item) => number(record(item).contribuicao) !== 0).sort((a, b) => (number(record(b).contribuicao) ?? 0) - (number(record(a).contribuicao) ?? 0))) {
    const factor = readableFactor(item);
    if (factor && !unique.has(factor.key)) unique.set(factor.key, factor);
  }
  return [...unique.values()];
}

function extractFactors(status: JsonRecord): ExplainableFactor[] {
  const explanations = record(status.riskExplanations);
  const explanation = record(explanations.incendio ?? explanations.geral);
  const explanationFactors = factorList(explanation.mainFactors ?? explanation.factors ?? explanation.fatores);
  if (explanationFactors.length) return explanationFactors.slice(0, 4);
  const risk = record(record(status.currentRisk).incendio);
  return factorList(risk.fatores).slice(0, 4);
}

function extractPropertyHistory(property: JsonRecord) {
  const items = [];
  if (typeof property.historicoIncendio === "boolean") {
    items.push({ label: "Histórico de incêndio informado", value: property.historicoIncendio ? "Sim" : "Não" });
  }
  if (typeof property.historicoPrincipioIncendioMaquinas === "boolean") {
    items.push({ label: "Princípio de incêndio em máquinas informado", value: property.historicoPrincipioIncendioMaquinas ? "Sim" : "Não" });
  }
  return items;
}

function extractPropertyContext(property: JsonRecord) {
  const items = [];
  if (typeof property.presencaPalhadaVegetacaoSeca === "boolean") {
    items.push({ label: "Palhada ou vegetação seca", value: property.presencaPalhadaVegetacaoSeca ? "Sim" : "Não" });
  }
  const criticalPoints = values(property.pontosAreasCriticas).filter((item): item is string => typeof item === "string" && Boolean(item.trim()));
  if (criticalPoints.length) items.push({ label: "Áreas críticas", value: criticalPoints.join(", ") });
  const criticalDescription = text(property.descricaoPontosCriticos);
  if (criticalDescription) items.push({ label: "Descrição das áreas críticas", value: criticalDescription });
  const crops = array(property.culturas).map((crop) => text(crop.nome)).filter(Boolean);
  if (crops.length) items.push({ label: "Culturas cadastradas", value: crops.join(", ") });
  const activity = text(property.atividadePrincipal);
  if (activity) items.push({ label: "Atividade principal", value: activity });
  const soil = [text(property.tipoSolo), text(property.texturaSolo)].filter(Boolean).join(" · ");
  if (soil) items.push({ label: "Solo", value: soil });
  return items;
}

function extractEnvironmentalValues(status: JsonRecord) {
  const explanation = record(record(status.riskExplanations).incendio);
  return values(explanation.evidence).flatMap((raw) => {
    const evidence = record(raw);
    const rawValue = evidence.value ?? evidence.valor ?? evidence.observedValue ?? evidence.measurement;
    if ((typeof rawValue !== "number" || !Number.isFinite(rawValue)) && typeof rawValue !== "string") return [];
    const label = text(evidence.label ?? evidence.fator ?? evidence.sensorId ?? evidence.type);
    if (!label) return [];
    const unit = text(evidence.unit ?? evidence.unidade);
    return [{ label, value: `${rawValue}${unit ? ` ${unit}` : ""}` }];
  }).slice(0, 8);
}

function extractCoverage(status: JsonRecord) {
  const labels: Record<string, string> = {
    weatherAvailable: "Clima", satelliteAvailable: "Hotspots / satélite", geospatialAvailable: "Geoespacial",
    historyAvailable: "Histórico", iotAvailable: "IoT", syntheticDemoData: "Cenário sintético",
  };
  return Object.entries(record(status.coverage)).map(([key, value]) => ({
    label: labels[key] ?? key,
    available: typeof value === "boolean" ? value : null,
  }));
}

function extractSources(status: JsonRecord) {
  const sourceLabels: Record<string, string> = {
    clima: "Open-Meteo", queimadas: "INPE Programa Queimadas", sgb: "SGB",
    inmet: "INMET", terreno: "Open-Meteo Elevation", hidrologia: "Hidrologia",
  };
  return Object.entries(record(status.sourceHealth)).map(([name, raw]) => {
    const source = record(raw);
    const updatedAt = source.updatedAt ?? source.consultadoEm ?? source.observedAt;
    return {
      name: sourceLabels[name] ?? name, status: text(source.status, "indisponível"),
      cacheHit: typeof source.cacheHit === "boolean" ? source.cacheHit : null,
      updatedLabel: timestampLabel(updatedAt) ? relativeLabel(updatedAt) : null,
    };
  });
}

function confidenceLabel(status: JsonRecord, risk: JsonRecord): string | null {
  const explanation = record(record(status.riskExplanations).incendio);
  const value = text(explanation.confidence ?? risk.confianca ?? risk.confidence);
  const labels: Record<string, string> = {
    high: "Alta", alta: "Alta", medium: "Média", media: "Média",
    low: "Baixa", baixa: "Baixa", insufficient: "Insuficiente", insuficiente: "Insuficiente",
  };
  return value ? labels[value.toLowerCase()] ?? value : null;
}

function hotspotFromAlerts(alertItems: JsonRecord[]) {
  const evidence = alertItems.flatMap((alert) => array(alert.evidence))
    .find((item) => number(item.distanceKm) !== null);
  if (!evidence) return { distance: null, details: [] };
  const details = [];
  const age = number(evidence.ageHours ?? evidence.idadeHoras);
  const detectedAt = timestampLabel(evidence.detectedAt ?? evidence.dataHoraUtc);
  const source = text(evidence.source);
  if (age !== null) details.push({ label: "Idade do foco", value: `${age.toLocaleString("pt-BR")} h` });
  if (detectedAt) details.push({ label: "Detectado em", value: detectedAt });
  if (source) details.push({ label: "Fonte", value: source });
  return { distance: number(evidence.distanceKm), details };
}

function latestMeasurement(
  machineStatus: JsonRecord,
  expectedTypes: string[],
  fallbackKey: string,
): MachineView["temperature"] {
  const measurements = record(machineStatus.latestMeasurements);
  const descriptors = record(machineStatus.latestMeasurementDescriptors);
  const identity = record(machineStatus.identity);
  const sensors = array(identity.sensoresConfigurados);
  const configured = sensors.map((sensor) => ({ sensorId: text(sensor.sensorId), descriptor: sensor }));
  const persisted = Object.entries(descriptors).map(([sensorId, value]) => ({ sensorId, descriptor: record(value) }));
  const candidates = [...configured, ...persisted].filter(({ descriptor }) =>
    expectedTypes.includes(text(descriptor.type).toLowerCase()));
  if (!candidates.some(({ sensorId }) => sensorId === fallbackKey)) {
    candidates.push({ sensorId: fallbackKey, descriptor: record(descriptors[fallbackKey]) });
  }
  for (const { sensorId, descriptor } of candidates) {
    const value = number(measurements[sensorId]);
    if (value !== null) {
      const type = text(descriptor.type).toLowerCase();
      const unit = text(descriptor.unit);
      const scope = text(descriptor.scope).toLowerCase();
      const target = text(descriptor.target);
      const isTemperature = expectedTypes.includes("temperature");
      const engineTarget = isTemperature && /motor|engine/i.test(target);
      const semanticScope = ["machine_component", "machine_internal"].includes(scope);
      const label = !isTemperature ? "Umidade" : engineTarget && semanticScope
        ? "Temperatura do motor"
        : target && semanticScope ? `Temperatura · ${target}` : "Temperatura";
      const scopeLabel = semanticScope
        ? `Escopo: ${scope}${target ? ` · alvo: ${target}` : ""}`
        : "Escopo do sensor não configurado";
      const displayUnit = unit === "celsius" ? "°C" : unit === "percent" ? "%" : unit || (type === "relative_humidity" ? "%" : "unidade não informada");
      return { value, unit: displayUnit, label, scopeLabel };
    }
  }
  return null;
}

function machineFromStatus(propertyId: string, propertyName: string, source: JsonRecord): MachineView {
  const identity = record(source.identity);
  const health = record(source.deviceHealth);
  const environmental = record(record(source.environmentalContext).geral);
  const physicalDeviceLinked = Boolean(text(source.deviceId)) && source.demoData !== true && identity.demoData !== true;
  const demo = !physicalDeviceLinked && (source.demoData === true || identity.demoData === true || propertyId.startsWith("demo_"));
  const deviceLinked = physicalDeviceLinked;
  const machineRisk = record(source.machineRisk);
  const metadata = record(identity.metadata);
  const connection = ((deviceLinked || demo) && ["online", "stale", "offline"].includes(text(health.status)) ? text(health.status) : "unknown") as MachineView["connection"];
  const currentReadings = connection === "online" && record(source.telemetryFreshness).fresh === true;
  return {
    id: text(identity.maquinaId, text(source.maquinaId, "maquina_sem_id")),
    propertyId,
    propertyName,
    name: text(identity.nome, text(source.nome, "Máquina monitorada")),
    telemetryFreshness: text(record(source.telemetryFreshness).status, "unavailable"),
    configuredSensors: array(identity.sensoresConfigurados).map((sensor) => ({ id: text(sensor.sensorId), type: text(sensor.type, "Não informado"), scope: text(sensor.scope, "Não informado") })),
    recommendations: array(source.recommendations).map((r) => ({ ruleId: text(r.ruleId), text: text(r.text) })),
    location: { latitude: number(record(source.mapLocation).latitude) ?? Number.NaN, longitude: number(record(source.mapLocation).longitude) ?? Number.NaN, current: record(source.mapLocation).current === true },
    deviceModel: text(metadata.deviceModel ?? metadata.hardwareModel, demo ? "ESP32" : "Dispositivo embarcado"),
    connection,
    deviceLinked,
    lastCommunication: (deviceLinked || demo) ? relativeLabel(source.lastSeenAt) : "Aguardando dispositivo embarcado",
    temperature: currentReadings ? latestMeasurement(source, ["temperature"], "temperature") : null,
    humidity: currentReadings ? latestMeasurement(source, ["humidity", "relative_humidity"], "humidity") : null,
    telemetryOrigin: demo ? "demo" : currentReadings ? "physical" : "unavailable",
    machineRisk: machineRisk.status === "insufficient_data" ? "unknown" : normalizeLevel(machineRisk.level),
    machineRiskStatus: text(machineRisk.status) === "ok"
      ? "ok" : text(machineRisk.status) === "insufficient_data" ? "insufficient_data" : "unknown",
    environmentalRisk: normalizeLevel(environmental.nivel ?? environmental.level),
    operationalRisk: record(source.operationalRisk).status === "insufficient_data" ? "unknown" : normalizeLevel(record(source.operationalRisk).level),
    demo,
  };
}

function eventFromBackend(
  item: JsonRecord,
  propertyById: Map<string, PropertyView>,
  machineNames: Map<string, string>,
  category: LiveEvent["category"],
): LiveEvent {
  const eventType = text(item.eventType ?? item.type);
  const kindMap: Record<string, LiveEvent["kind"]> = {
    hotspot_detected: "hotspot", environmental_risk_changed: "risk", machine_risk_changed: "machine",
    operational_risk_changed: "risk", telemetry_stale: "device", device_offline: "device",
    hotspot_near_property: "hotspot", machine_near_hotspot: "hotspot", environmental_fire_risk: "property",
    machine_risk: "machine", operational_combined_risk: "risk",
  };
  const titleMap: Record<string, string> = {
    hotspot_detected: "Foco de calor recente detectado", environmental_risk_changed: "Risco ambiental alterado",
    machine_risk_changed: "Risco da máquina alterado", operational_risk_changed: "Risco operacional alterado",
    telemetry_stale: "Telemetria sem atualização", device_offline: "Dispositivo offline",
    source_unavailable: "Fonte temporariamente indisponível",
    hotspot_near_property: "Hotspot próximo requer atenção", machine_near_hotspot: "Máquina próxima de hotspot",
    environmental_fire_risk: "Risco de incêndio requer atenção", machine_risk: "Máquina precisa de atenção",
    operational_combined_risk: "Risco operacional requer atenção",
  };
  const propertyId = text(item.fazendaId);
  const property = propertyById.get(propertyId);
  const machineId = text(item.maquinaId);
  const evidenceItems = array(item.evidence);
  const locationEvidence = evidenceItems.find((evidence) =>
    number(evidence.distanceKm) !== null || number(evidence.latitude ?? evidence.lat) !== null);
  const distanceKm = number((locationEvidence ?? {}).distanceKm);
  const detectedRaw = (locationEvidence ?? {}).detectedAt ?? (locationEvidence ?? {}).dataHoraUtc;
  const current = normalizeLevel(item.currentLevel ?? item.severity);
  const previous = normalizeLevel(item.previousLevel);
  const descriptionParts = [property?.name, property ? `${property.city} · ${property.uf}` : ""];
  if (distanceKm !== null) descriptionParts.push(`${distanceKm.toLocaleString("pt-BR")} km da propriedade`);
  else if (machineId) descriptionParts.push(machineNames.get(`${propertyId}:${machineId}`) ?? machineId);
  return {
    id: text(item.eventId ?? item.alertId ?? item.id, `event_${propertyId}_${eventType}`),
    category, eventType,
    alertStatus: category === "alert" && ["open", "acknowledged", "resolved"].includes(text(item.status)) ? item.status as LiveEvent["alertStatus"] : undefined,
    kind: kindMap[eventType] ?? "property",
    title: titleMap[eventType] ?? "Atualização de monitoramento",
    description: descriptionParts.filter(Boolean).join(" · ") || "Evento registrado pelo core",
    severity: current === "unknown" ? normalizeLevel(item.severity) : current,
    timeLabel: relativeLabel(item.occurredAt ?? item.updatedAt ?? item.createdAt),
    propertyId: propertyId || undefined,
    propertyName: property?.name, city: property?.city, uf: property?.uf,
    machineName: machineId ? machineNames.get(`${propertyId}:${machineId}`) ?? machineId : undefined,
    previousLevel: previous === "unknown" ? undefined : previous,
    currentLevel: current === "unknown" ? undefined : current,
    distanceKm: distanceKm ?? undefined,
    detectedAt: timestampLabel(detectedRaw) ?? undefined,
    source: text((locationEvidence ?? {}).source) || undefined,
    satellite: text((locationEvidence ?? {}).satelite ?? (locationEvidence ?? {}).satellite) || undefined,
    latitude: number((locationEvidence ?? {}).latitude ?? (locationEvidence ?? {}).lat) ?? undefined,
    longitude: number((locationEvidence ?? {}).longitude ?? (locationEvidence ?? {}).lon) ?? undefined,
    factors: factorList(item.factors),
    demo: item.demoData === true || propertyId.startsWith("demo_"),
  };
}

function buildStates(properties: PropertyView[]): StateSummary[] {
  return PILOT_STATES.map((uf) => {
    const matching = properties.filter((property) => property.uf === uf);
    const rank = { critical: 4, high: 3, moderate: 2, low: 1, unknown: 0 };
    const highest = matching.reduce<PropertyView | null>((current, property) =>
      current === null || rank[property.level] > rank[current.level] || (rank[property.level] === rank[current.level] && (property.score ?? -1) > (current.score ?? -1)) ? property : current, null);
    const withHotspotEvidence = matching.filter((property) => property.hotspotDistanceKm !== null);
    return {
      uf, propertiesMonitored: matching.length,
      highCriticalCount: matching.filter((property) => ["high", "critical"].includes(property.level)).length,
      highestLevel: highest?.level ?? "unknown", highestScore: highest?.score ?? null,
      alertCount: matching.some((p) => p.alertCount === null) ? null : matching.reduce((sum, property) => sum + (property.alertCount ?? 0), 0),
      nearbyHotspotCount: withHotspotEvidence.length ? withHotspotEvidence.length : null,
      demo: matching.length > 0 && matching.every((property) => property.propertyDemo),
    };
  });
}

function liveSources(caseItem: JsonRecord) {
  return Object.entries(record(caseItem.sourceHealth)).map(([name, raw]) => {
    const source = record(raw);
    return {
      name: text(source.attribution, name), status: text(source.status, "indisponível"),
      cacheHit: typeof source.cacheHit === "boolean" ? source.cacheHit : null,
      updatedLabel: source.consultedAt ? relativeLabel(source.consultedAt) : null,
    };
  });
}

function liveEnvironmentalValues(caseItem: JsonRecord) {
  return array(caseItem.environmentalEvidence).flatMap((raw) => {
    const value = raw.value;
    if ((typeof value !== "number" || !Number.isFinite(value)) && typeof value !== "string") return [];
    const label = text(raw.label);
    if (!label) return [];
    const formatted = typeof value === "number" ? value.toLocaleString("pt-BR") : value;
    const unit = text(raw.unit);
    return [{
      label, value: `${formatted}${unit ? ` ${unit}` : ""}`,
      source: text(raw.source) || undefined,
      updatedLabel: raw.observedAt ? relativeLabel(raw.observedAt) : null,
    }];
  });
}

function inmetAlertSeverity(value: unknown): RiskLevel {
  const normalized = text(value).toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  if (normalized === "grande perigo") return "critical";
  if (normalized === "perigo") return "high";
  if (normalized === "perigo potencial") return "moderate";
  return "unknown";
}

function liveProperty(caseItem: JsonRecord): PropertyView | null {
  const property = record(caseItem.property);
  const risk = record(caseItem.risk);
  const riskType = text(caseItem.riskType);
  const id = text(property.fazendaId ?? caseItem.id);
  const latitude = number(property.latitude);
  const longitude = number(property.longitude);
  if (!id) return null;
  const hotspotData = record(caseItem.hotspots);
  const nearest = record(hotspotData.nearest);
  const nearestDistance = number(nearest.distanciaKm ?? nearest.distanceKm);
  const recentItems = array(hotspotData.items);
  const hotspotDetails = [];
  const lookback = number(hotspotData.lookbackHours);
  if (lookback !== null) hotspotDetails.push({ label: "Período consultado", value: `Últimas ${lookback} horas` });
  const reportedCount = number(hotspotData.count48hWithin50Km);
  if (reportedCount !== null) hotspotDetails.push({ label: "Focos em até 50 km nas últimas 48 h · total informado pela fonte", value: `${reportedCount}` });
  else if (recentItems.length) hotspotDetails.push({ label: "Detecções exibidas neste recorte", value: `${recentItems.length}` });
  const detectedAt = nearest.detectedAt ?? nearest.dataHoraUtc;
  if (timestampLabel(detectedAt)) hotspotDetails.push({ label: "Detectado em", value: timestampLabel(detectedAt) as string });
  if (text(nearest.source)) hotspotDetails.push({ label: "Fonte", value: text(nearest.source) });
  if (text(nearest.satelite ?? nearest.satellite)) hotspotDetails.push({ label: "Satélite", value: text(nearest.satelite ?? nearest.satellite) });
  const explanation = record(caseItem.riskExplanation);
  const confidence = text(explanation.confidence);
  const confidenceNames: Record<string, string> = { high: "Alta", medium: "Média", low: "Baixa", insufficient: "Insuficiente" };
  const coverage = record(caseItem.dataCoverage);
  const analysisAt = caseItem.analysisAt;
  return {
    id, name: text(property.nome, id), city: text(property.municipio, "Local não informado"), uf: text(property.estado, "--"),
    latitude: latitude ?? Number.NaN, longitude: longitude ?? Number.NaN, score: number(risk.score), level: normalizeLevel(risk.nivel),
    riskType: ({ incendio: "Incêndio", geada: "Geada", inundacao: "Inundação", enxurrada: "Enxurrada", movimentoMassa: "Movimento de massa", weather: "Aviso meteorológico" } as Record<string, string>)[riskType] ?? "Ambiental", trend: "unknown",
    clientName: text(property.clientName) || undefined,
    coordinateDisclosure: text(property.representativeness) === "municipality_representative_point_only" ? "Ponto municipal do IBGE usado como localização demonstrativa; não representa limites de uma fazenda real." : undefined,
    recommendations: array(caseItem.recommendations).map((r) => ({ ruleId: text(r.ruleId), text: text(r.text) })),
    hotspotDistanceKm: riskType === "incendio" ? nearestDistance : null,
    hotspotDetails, factors: factorList(caseItem.presentationFactors ?? (id.startsWith("demo_portfolio_") ? [] : risk.fatores)),
    historyDetails: recentItems.length && lookback !== null
      ? [{ label: `Focos detectados nas últimas ${lookback} horas`, value: `${recentItems.length}` }] : [],
    contextDetails: [], environmentalValues: liveEnvironmentalValues(caseItem),
    environmentalContext: caseItem.environmentalContext as EnvironmentalContext | undefined,
    confidence: confidenceNames[confidence] ?? (confidence || null), coveragePercent: number(risk.coberturaDadosPct),
    coverage: Object.entries(coverage).map(([key, value]) => ({
      label: ({ weatherAvailable: "Clima", satelliteAvailable: "Hotspots / satélite", geospatialAvailable: "Geoespacial", historyAvailable: "Histórico", propertyContextAvailable: "Contexto da propriedade", iotAvailable: "IoT" } as Record<string, string>)[key] ?? key,
      available: typeof value === "boolean" ? value : null,
    })),
    sources: liveSources(caseItem), analysisTimestamp: timestampLabel(analysisAt),
    analysisFreshness: analysisAt ? relativeLabel(analysisAt) : "Timestamp não disponível",
    history: [], alertCount: null, machines: [], demo: false, propertyDemo: property.demoData === true,
    environmentalDataOrigin: caseItem.environmentalDataReal === true ? "real" : "unavailable",
  };
}

function validPortfolio(value: unknown): value is JsonRecord {
  const payload = record(value);
  return payload.schema === "presentation_real_portfolio_v1" && Boolean(text(payload.generatedAt)) &&
    Array.isArray(payload.cases) && payload.cases.length > 0 && payload.cases.every((item) => {
      const c = record(item), p = record(c.property), context = record(c.environmentalContext);
      return Boolean(text(c.id) && text(p.fazendaId) && text(p.nome) && text(p.clientName)) &&
        (!c.environmentalContext || Array.isArray(context.sections));
    });
}

export async function loadPortfolioData(refresh = false, perspective?: "seguradora" | "segurado"): Promise<CommandCenterData> {
  let payload: JsonRecord | null = null;
  let backendAvailable = false;
  let liveRefresh = false;
  if (backendUrl()) {
    try {
      const candidate = await backendFetch(refresh ? "/showcase/portfolio?refresh=true" : perspective ? `/showcase/perspectives/${perspective}` : "/showcase/portfolio", 3500);
      if (validPortfolio(candidate)) {
        payload = candidate;
        backendAvailable = true;
        liveRefresh = refresh;
      }
    } catch { /* Expected network/provider failure: read the presentation snapshot. */ }
  }
  if (!payload && !isPresentationDeployment() && process.env.PRESENTATION_PORTFOLIO_PATH) {
    try {
      const candidate = JSON.parse(await readFile(/* turbopackIgnore: true */ process.env.PRESENTATION_PORTFOLIO_PATH, "utf8"));
      if (validPortfolio(candidate)) payload = candidate;
    } catch { /* Optional local development override. */ }
  }
  if (!payload && validPortfolio(bundledPortfolio)) payload = bundledPortfolio;
  if (!payload) return { ...unavailableData(), requestMode: "portfolio", presentationMode: "snapshot",
    notices: ["Captura de apresentação indisponível. Tente novamente mais tarde."] };
  // Never mutate a module singleton: concurrent insured requests must not shrink the insurer portfolio.
  payload = structuredClone(payload);
  refresh = liveRefresh;
  if (perspective === "segurado") payload.cases = array(payload.cases).filter((c) => record(c.property).clientName === "Cliente A");
  // The file fallback contains the same canonical context, possibly captured live.
  // Reading that file is always cached; only freshness metadata changes here.
  if (!refresh) for (const c of array(payload.cases)) {
    c.environmentalContext = JSON.parse(JSON.stringify(c.environmentalContext ?? {}, (_key, value) => {
      if (value && typeof value === "object" && ["real_live", "real_cached"].includes(value.freshness)) {
        const at = Date.parse(value.observedAt || value.fetchedAt || "");
        return { ...value, freshness: Number.isFinite(at) && Date.now() - at > 21600000 ? "stale" : "real_cached" };
      }
      return value;
    }));
  }
  const properties = array(payload.cases).map((item) => {
    const property = liveProperty(item);
    if (!property) return null;
    const raw = record(record(item.provenance).environmental);
    const acquiredAt = text(raw.acquiredAt) || null;
    const age = acquiredAt ? Date.now() - Date.parse(acquiredAt) : Number.NaN;
    const validReal = raw.origin === "real" && Number.isFinite(age) && age >= 0 && array(Object.values(record(item.sourceHealth))).some((s) => text(s.attribution) && text(s.consultedAt));
    const state: NonNullable<PropertyView["provenance"]>["environmental"]["state"] = !validReal ? "unavailable" : age > 21600000 ? "stale" : raw.state === "insufficient_data" ? "insufficient_data" : refresh && raw.state === "real_live" ? "real_live" : "real_cached";
    const operational = record(item.operationalState);
    return { ...property, processingState: text(item.processingState), environmentalDataOrigin: validReal ? "real" as const : "unavailable" as const,
      alertCount: number(operational.openAlerts),
      operationalState: typeof operational.openAlerts === "number" ? { openAlerts: operational.openAlerts,
        alerts: array(operational.alerts).map((a) => ({ alertId: text(a.alertId), status: text(a.status), severity: text(a.severity),
          notifications: array(a.notifications).map((n) => ({ notificationId: text(n.notificationId), channel: text(n.channel), status: text(n.status), deliveredAt: text(n.deliveredAt) || undefined })) })) } : null,
      level: validReal ? property.level : "unknown" as const, score: validReal ? property.score : null,
      factors: validReal ? property.factors : [], environmentalValues: validReal ? property.environmentalValues : [],
      provenance: { identity: "demo" as const, environmental: { origin: validReal ? "real" as const : "unavailable" as const, state, acquiredAt } },
      analysisTimestamp: acquiredAt ? timestampLabel(acquiredAt) : null, analysisFreshness: acquiredAt ? relativeLabel(acquiredAt) : "Sem leitura real" };
  }).filter((p): p is NonNullable<typeof p> => p !== null);
  const hotspots: HotspotView[] = array(payload.cases).flatMap((item) => array(record(item.hotspots).items).flatMap((h, index) => {
    const latitude = number(h.latitude), longitude = number(h.longitude);
    if (latitude === null || longitude === null) return [];
    return [{ id: `${text(item.id)}_${text(h.id, String(index))}`, latitude, longitude, propertyId: text(item.id),
      detectedAt: text(h.detectedAt ?? h.dataHoraUtc) || null, detectedLabel: relativeLabel(h.detectedAt ?? h.dataHoraUtc),
      source: text(h.source, "INPE Programa Queimadas"), distanceKm: number(h.distanciaKm) ?? undefined, demo: false }];
  }));
  const events: LiveEvent[] = array(payload.cases).flatMap((c) => array(c.weatherWarnings).flatMap((w) => {
    const evidence = array(w.evidence).find((e) => text(e.weatherSeverity));
    if (!evidence) return [];
    const property = record(c.property);
    return [{ id: `${text(c.id)}_${text(w.sourceEventId)}`, category: "event" as const, eventType: "official_weather_warning", kind: "risk" as const,
      title: text(evidence.eventType), description: text(evidence.description, "Consulte o aviso oficial."), severity: normalizeLevel(w.severity),
      timeLabel: text(evidence.publishedAt) || "Horário indisponível", propertyId: text(c.id), propertyName: text(property.nome), city: text(property.municipio), uf: text(property.estado),
      source: text(evidence.source), sourceSeverity: text(evidence.weatherSeverity), endsAt: text(evidence.endsAt), factors: [], demo: false }];
  }));
  for (const c of array(payload.cases)) {
    const cap = array(record(record(c.environmentalContext).warnings).value);
    for (const w of cap) {
      const property = record(c.property);
      events.push({ id: `${text(c.id)}_cap_${text(w.id)}`, category: "event", eventType: "official_weather_context", kind: "risk",
        title: `${text(w.eventType)} · aviso na captura`, description: text(w.description),
        severity: normalizeLevel(({ Moderate: "moderate", Severe: "high", Extreme: "critical" } as Record<string, string>)[text(w.severity)]),
        timeLabel: timestampLabel(w.publishedAt) || "Horário indisponível", propertyId: text(c.id), propertyName: text(property.nome), city: text(property.municipio), uf: text(property.estado),
        source: text(w.source), sourceSeverity: text(w.severity), endsAt: text(w.endsAt), factors: [], demo: false });
    }
  }
  return { source: "live", requestMode: "portfolio", presentationMode: refresh ? "live" : "snapshot", generatedAt: text(payload.generatedAt),
    properties, states: buildStates(properties), machines: [], machineInventoryAvailable: false, events, hotspots,
    stale: properties.some((p) => p.provenance?.environmental.state === "stale"), backendAvailable,
    notices: [...(!backendAvailable ? ["Exibindo captura de apresentação armazenada, com horários originais; sem consulta ao vivo."] : []), ...values(payload.limitations).map((v) => text(v)).filter(Boolean)] };
}

function weatherEvents(payload: JsonRecord): LiveEvent[] {
  const events: LiveEvent[] = [];
  for (const item of array(payload.items).slice(0, 10)) {
    const eventType = text(item.eventType);
    const startsAt = text(item.startsAt);
    events.push({
      id: `inmet_alert_${text(item.id, startsAt)}`, category: "alert", eventType, kind: "risk",
      title: eventType, description: text(item.description, "Descrição não disponibilizada pela fonte."),
      severity: inmetAlertSeverity(item.severity), timeLabel: startsAt ? `Início ${startsAt}` : "Horário não disponibilizado",
      startsAt: startsAt || undefined, endsAt: text(item.endsAt) || undefined,
      location: text(item.location) || undefined, sourceSeverity: text(item.severity) || undefined,
      hailExplicit: item.hailExplicit === true, source: text(item.source, text(payload.source, "INMET")),
      recommendations: array(item.recommendations).map((r) => ({ ruleId: text(r.ruleId), text: text(r.text) })),
      factors: [], demo: false,
    });
  }
  return events;
}

async function loadLiveData(): Promise<CommandCenterData> {
  const payload = await backendFetch("/showcase/live-cases");
  const cases = array(payload.cases);
  const properties = cases.map(liveProperty).filter((property): property is PropertyView => property !== null);
  if (!properties.length || payload.environmentalDataReal !== true) throw new Error("Casos ambientais reais indisponíveis");
  const hotspots: HotspotView[] = cases.flatMap((caseItem) => {
    const property = liveProperty(caseItem);
    if (!property || text(caseItem.riskType) !== "incendio") return [];
    return array(record(caseItem.hotspots).items).map((item, index) => ({
      id: text(item.id, `live_hotspot_${index}_${text(item.detectedAt)}`),
      latitude: number(item.latitude) ?? 0, longitude: number(item.longitude) ?? 0,
      detectedAt: timestampLabel(item.detectedAt ?? item.dataHoraUtc),
      detectedLabel: relativeLabel(item.detectedAt ?? item.dataHoraUtc),
      source: text(item.source, "INPE Programa Queimadas"),
      satellite: text(item.satelite ?? item.satellite) || undefined,
      distanceKm: number(item.distanciaKm ?? item.distanceKm) ?? undefined,
      propertyId: property.id, city: text(item.municipio) || property.city,
      uf: text(item.uf) || property.uf, demo: false,
    })).filter((item) => Number.isFinite(item.latitude) && Number.isFinite(item.longitude) && Math.abs(item.latitude) <= 90 && Math.abs(item.longitude) <= 180);
  }).slice(0, 12);
  const events = weatherEvents(record(payload.weatherAlerts));
  const fireProperty = properties.find((property) => property.riskType === "Incêndio");
  const nearestFire = hotspots[0];
  if (fireProperty && nearestFire) events.push({
    id: `live_event_${nearestFire.id}`, category: "event", eventType: "hotspot_detected", kind: "hotspot",
    title: "Foco de calor recente detectado", description: `${fireProperty.name} · ${nearestFire.distanceKm?.toLocaleString("pt-BR") ?? "—"} km`,
    severity: fireProperty.level, timeLabel: nearestFire.detectedLabel, propertyId: fireProperty.id,
    propertyName: fireProperty.name, city: fireProperty.city, uf: fireProperty.uf,
    distanceKm: nearestFire.distanceKm, detectedAt: nearestFire.detectedAt ?? undefined,
    source: nearestFire.source, satellite: nearestFire.satellite,
    latitude: nearestFire.latitude, longitude: nearestFire.longitude,
    factors: fireProperty.factors, demo: false,
  });
  const frostProperty = properties.find((property) => property.riskType === "Geada");
  if (frostProperty && ["moderate", "high", "critical"].includes(frostProperty.level)) events.push({
    id: `live_event_${frostProperty.id}`, category: "event", eventType: "frost_condition", kind: "risk",
    title: "Condição de geada identificada", description: `${frostProperty.city} · ${frostProperty.uf}`,
    severity: frostProperty.level, timeLabel: frostProperty.analysisFreshness,
    propertyId: frostProperty.id, propertyName: frostProperty.name, city: frostProperty.city, uf: frostProperty.uf,
    currentLevel: frostProperty.level, factors: frostProperty.factors, demo: false,
  });
  const notices = values(payload.limitations).map((item) => text(item)).filter(Boolean);
  if (frostProperty && !["moderate", "high", "critical"].includes(frostProperty.level)) {
    notices.unshift("Nenhuma condição relevante de geada foi encontrada nesta execução; o melhor caso real permaneceu baixo.");
  }
  if (payload.stale === true) notices.unshift(`Dados reais desatualizados (${relativeLabel(payload.generatedAt)}).`);
  const machines = await loadPhysicalMachines();
  return {
    source: "live", generatedAt: text(payload.generatedAt, new Date().toISOString()),
    states: buildStates(properties), properties, machines, events, hotspots,
    backendAvailable: true, stale: payload.stale === true, notices,
  };
}

async function loadPhysicalMachines(): Promise<MachineView[]> {
  const configuredFarmId = process.env.SOMPO_PHYSICAL_FARM_ID || "demo_fazenda_01";
  const configuredMachineId = process.env.SOMPO_PHYSICAL_MACHINE_ID || "trator_fisico_01";
  try {
    const status = await backendFetch(`/fazendas/${encodeURIComponent(configuredFarmId)}/maquinas/${encodeURIComponent(configuredMachineId)}/status`, 7_000);
    const property = record(status.property);
    const configured = machineFromStatus(configuredFarmId, text(property.nome, configuredFarmId), status);
    if (configured.deviceLinked) return [configured];
  } catch {
    // A descoberta genérica abaixo mantém compatibilidade com outros ambientes.
  }
  try {
    const dashboard = await backendFetch("/dashboard?limit=20");
    const farms = array(dashboard.properties).slice(0, 20).map((card) => record(card.property));
    const farmStatuses = await Promise.all(farms.map(async (property) => {
      const propertyId = text(property.fazendaId ?? property.id);
      try {
        return { propertyId, propertyName: text(property.nome, propertyId), status: await backendFetch(`/fazendas/${encodeURIComponent(propertyId)}/status`) };
      } catch {
        return { propertyId, propertyName: text(property.nome, propertyId), status: {} };
      }
    }));
    const requests: Array<Promise<MachineView | null>> = [];
    for (const farm of farmStatuses) {
      for (const summary of array(farm.status.machines).slice(0, 8)) {
        const machineId = text(summary.maquinaId);
        requests.push((async () => {
          try {
            const status = await backendFetch(`/fazendas/${encodeURIComponent(farm.propertyId)}/maquinas/${encodeURIComponent(machineId)}/status`);
            const machine = machineFromStatus(farm.propertyId, farm.propertyName, status);
            return machine.deviceLinked ? machine : null;
          } catch {
            return null;
          }
        })());
      }
    }
    return (await Promise.all(requests)).filter((machine): machine is MachineView => machine !== null).slice(0, 12);
  } catch {
    return [];
  }
}

export async function getPhysicalMachines(): Promise<MachineView[]> {
  return loadPhysicalMachines();
}

async function loadBackendData(fetchData = backendFetch, demoPreview = false): Promise<CommandCenterData> {
  const dashboard = await fetchData("/dashboard?limit=20");
  const cards = array(dashboard.properties).filter((card) => { const p = record(card.property); return demoPreview ? p.demoData === true && text(p.fazendaId ?? p.id).startsWith("demo_") : p.demoData !== true && !text(p.fazendaId ?? p.id).startsWith("demo_"); });
  const statuses = await Promise.all(cards.map(async (card) => {
    const property = record(card.property);
    const id = text(property.fazendaId ?? property.id);
    try { return [id, await fetchData(`/fazendas/${encodeURIComponent(id)}/status`)] as const; }
    catch { return [id, { unavailable: true }] as const; }
  }));
  const statusByProperty = new Map(statuses);

  const machineRequests: Array<Promise<[string, JsonRecord]>> = [];
  for (const [propertyId, status] of statuses) {
    for (const machine of array(status.machines).slice(0, 4)) {
      const machineId = text(machine.maquinaId);
      machineRequests.push((async () => {
        try { return [propertyId, await fetchData(`/fazendas/${encodeURIComponent(propertyId)}/maquinas/${encodeURIComponent(machineId)}/status`)] as [string, JsonRecord]; }
        catch { return [propertyId, { ...machine, identity: machine, unavailable: true }] as [string, JsonRecord]; }
      })());
    }
  }
  const machineStatuses = await Promise.all(machineRequests);
  const propertyNames = new Map(cards.map((card) => {
    const property = record(card.property);
    const id = text(property.fazendaId ?? property.id);
    return [id, text(property.nome, id)] as const;
  }));
  const machines = machineStatuses.map(([propertyId, status]) => machineFromStatus(propertyId, propertyNames.get(propertyId) ?? propertyId, status));

  const properties: PropertyView[] = cards.map((card) => {
    const property = record(card.property);
    const id = text(property.fazendaId ?? property.id);
    const status = statusByProperty.get(id) ?? {};
    const fireRisk = record(record(status.currentRisk).incendio);
    const currentRisk = fireRisk; // Overall environmental risk must not be relabeled as fire risk.
    const riskScore = number(currentRisk.score ?? currentRisk.riskScore);
    const riskLevel = normalizeLevel(currentRisk.nivel ?? currentRisk.level ?? currentRisk.riskLevel);
    const trend = record(status.trend);
    const alertItems = array(status.alerts);
    const hotspot = hotspotFromAlerts(alertItems);
    const analysisTimestamp = timestampLabel(status.lastAnalysisAt);
    return {
      id,
      name: text(property.nome, id), city: text(property.municipio, "Local não informado"), uf: text(property.estado, "--"),
      latitude: number(property.latitude ?? record(property.pontoCentral).latitude) ?? Number.NaN,
      longitude: number(property.longitude ?? record(property.pontoCentral).longitude) ?? Number.NaN,
      score: riskScore, level: riskLevel, riskType: "Incêndio",
      environmentalLevel: normalizeLevel(record(record(status.currentRisk).geral).nivel ?? record(card.currentRisk).nivel),
      trend: trendDirection(trend.direction ?? trend.tendencia),
      hotspotDistanceKm: hotspot.distance, hotspotDetails: hotspot.details,
      factors: extractFactors(status), historyDetails: extractPropertyHistory(property),
      contextDetails: extractPropertyContext(property), environmentalValues: extractEnvironmentalValues(status),
      environmentalContext: status.environmentalContext as EnvironmentalContext | undefined,
      confidence: confidenceLabel(status, currentRisk), coveragePercent: number(currentRisk.coberturaDadosPct),
      coverage: extractCoverage(status), sources: extractSources(status),
      analysisTimestamp, analysisFreshness: analysisTimestamp ? relativeLabel(status.lastAnalysisAt) : "Timestamp não disponível",
      history: array(trend.points ?? trend.series).map((point) => number(point.score ?? point.riskScore)).filter((value): value is number => value !== null).slice(-8),
      alertCount: number(card.activeAlertCount ?? status.alertCount),
      machines: machines.filter((machine) => machine.propertyId === id),
      demo: property.demoData === true || id.startsWith("demo_"),
      propertyDemo: property.demoData === true || id.startsWith("demo_"),
      environmentalDataOrigin: property.demoData === true || id.startsWith("demo_") ? "demo" as const : "real" as const,
    };
  }).filter((property) => property.id && (demoPreview || !property.demo));

  const propertyById = new Map(properties.map((property) => [property.id, property]));
  const machineNames = new Map(machines.map((machine) => [`${machine.propertyId}:${machine.id}`, machine.name]));
  const eventResponses = await Promise.all(properties.slice(0, 5).map(async (property) => {
    try { return array((await fetchData(`/eventos?fazendaId=${encodeURIComponent(property.id)}&limit=8`)).items); }
    catch { return []; }
  }));
  const backendEvents = eventResponses.flat().map((item) => eventFromBackend(item, propertyById, machineNames, "event"));
  const alertEvents = array(dashboard.alerts).map((item) =>
    eventFromBackend({ ...item, eventType: item.type }, propertyById, machineNames, "alert"));

  const hotspotResponses = await Promise.all(PILOT_STATES.filter((uf) => properties.some((p) => p.uf === uf)).map(async (uf) => {
    try { return [uf, array((await fetchData(`/regional/hotspots?uf=${uf}`)).items)] as const; }
    catch { return [uf, []] as const; }
  }));
  const hotspots: HotspotView[] = hotspotResponses.flatMap(([uf, items]) => items.map((item, index) => ({
    id: `hotspot_${uf}_${index}_${text(item.detectedAt)}`,
    latitude: number(item.lat) ?? Number.NaN, longitude: number(item.lon) ?? Number.NaN,
    detectedAt: timestampLabel(item.detectedAt), detectedLabel: relativeLabel(item.detectedAt),
    source: text(item.source, "INPE Programa Queimadas"),
    satellite: text(item.satelite ?? item.satellite) || undefined, uf,
    demo: false,
  }))).filter((item) => Number.isFinite(item.latitude) && Number.isFinite(item.longitude) && Math.abs(item.latitude) <= 90 && Math.abs(item.longitude) <= 180);

  const states = buildStates(properties);
  let weather: LiveEvent[] = [];
  try { weather = weatherEvents(await fetchData("/weather/alerts")); } catch { /* Explicit notice below. */ }
  const events = [...weather, ...backendEvents, ...alertEvents.filter((e) => (demoPreview || !e.demo))].slice(0, 20);
  return {
    source: demoPreview ? "demo" : "backend", generatedAt: new Date().toISOString(), states,
    machineInventoryAvailable: statuses.every(([, status]) => Array.isArray(status.machines)) && machineStatuses.every(([, status]) => status.unavailable !== true),
    properties, machines: machines.filter((machine) => (demoPreview || !machine.demo)),
    events, hotspots, backendAvailable: true, stale: false, notices: ["Recorte consultado: até 20 propriedades e 4 máquinas por propriedade. Contagens não são totais da carteira. Snapshots podem estar desatualizados; consulte os horários de análise. Avisos meteorológicos são regionais; a incidência sobre a propriedade não foi confirmada."],
  };
}

function unavailableData(): CommandCenterData {
  return {
    source: "unavailable", generatedAt: new Date().toISOString(), states: buildStates([]),
    properties: [], machines: [], events: [], hotspots: [], backendAvailable: false, stale: false,
    notices: ["Dados reais indisponíveis. Use o cenário demonstrativo somente se desejar um fallback explícito."],
  };
}

export async function getCommandCenterData(mode?: string): Promise<CommandCenterData> {
  if (mode === "portfolio" || mode === "portfolio-live") {
    try { return await loadPortfolioData(mode === "portfolio-live"); }
    catch {
      if (mode === "portfolio-live") {
        try { const saved = await loadPortfolioData(); return { ...saved, notices: ["Consulta atual indisponível; exibindo última captura real com horário original.", ...saved.notices] }; } catch { /* No real snapshot. */ }
      }
      return { ...unavailableData(), requestMode: "portfolio", notices: ["Carteira real indisponível. Execute capture_presentation_portfolio --write; nenhum cenário sintético foi substituído."] };
    }
  }
  if (mode === "demo") {
    const path = isPresentationDeployment() ? undefined : process.env.SOMPO_DEMO_SCENARIO_PATH;
    if (!path) return getDemoData();
    try {
      const fixture = JSON.parse(await readFile(path, "utf8"));
      if (fixture.demoData !== true || !fixture.responses) throw new Error("Invalid DEMO export");
      const data = await loadBackendData(async (route) => record(fixture.responses[route] ?? { items: [] }), true);
      return { ...data, demoAlerts: fixture.alerts ?? [], generatedAt: fixture.generatedAt,
        notices: [`DEMO offline · ${fixture.scenario} · capturado em ${fixture.generatedAt}. Sem Firebase ou Telegram.`, "Cenário sintético fixo; não representa condições atuais."], backendAvailable: false };
    } catch { return { ...unavailableData(), notices: ["Exportação DEMO indisponível ou inválida. Execute seed_demo --export novamente."] }; }
  }
  if (mode === "live") {
    try { return await loadLiveData(); } catch { return unavailableData(); }
  }
  try { return await loadBackendData(); } catch { return unavailableData(); }
}
