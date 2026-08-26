import type { CommandCenterData, HotspotView, LiveEvent, MachineView, PropertyView, StateSummary } from "@/lib/types";

const demoMachineBase = {
  deviceModel: "ESP32",
  connection: "unknown" as const,
  deviceLinked: false,
  lastCommunication: "Aguardando dispositivo embarcado",
  temperature: null,
  humidity: null,
  telemetryOrigin: "demo" as const,
  machineRiskStatus: "ok" as const,
  demo: true,
};

const trator: MachineView = {
  ...demoMachineBase, id: "demo_trator_01", propertyId: "demo_fazenda_01", propertyName: "Fazenda Horizonte", name: "Trator 01",
  machineRisk: "high", environmentalRisk: "critical", operationalRisk: "critical",
};

const pulverizador: MachineView = {
  ...demoMachineBase, id: "demo_pulverizador_01", propertyId: "demo_fazenda_02", propertyName: "Fazenda Boa Esperança", name: "Pulverizador 02",
  machineRisk: "moderate", environmentalRisk: "high", operationalRisk: "high",
};

const unavailableDetails = {
  factors: [], historyDetails: [], contextDetails: [], environmentalValues: [],
  confidence: null, coveragePercent: null, coverage: [], sources: [],
  analysisTimestamp: null, analysisFreshness: "Timestamp não disponível no cenário",
};

export const demoProperties: PropertyView[] = [
  {
    ...unavailableDetails,
    id: "demo_fazenda_01", name: "Fazenda Boa Vista", city: "Sorriso", uf: "MT",
    latitude: -12.5425, longitude: -55.7211, score: 84, level: "critical", riskType: "Incêndio",
    trend: "up", hotspotDistanceKm: 4.6, hotspotDetails: [],
    history: [42, 48, 51, 63, 72, 84], alertCount: 3, machines: [trator], demo: true,
    propertyDemo: true, environmentalDataOrigin: "demo",
  },
  {
    ...unavailableDetails,
    id: "demo_fazenda_02", name: "Fazenda Santa Clara", city: "Bonito", uf: "MS",
    latitude: -21.1261, longitude: -56.4836, score: 71, level: "high", riskType: "Incêndio",
    trend: "up", hotspotDistanceKm: 12.8, hotspotDetails: [],
    history: [39, 44, 48, 53, 65, 71], alertCount: 2, machines: [pulverizador], demo: true,
    propertyDemo: true, environmentalDataOrigin: "demo",
  },
  {
    ...unavailableDetails,
    id: "demo_fazenda_03", name: "Fazenda Horizonte", city: "Rio Verde", uf: "GO",
    latitude: -17.7923, longitude: -50.9192, score: 58, level: "moderate", riskType: "Incêndio",
    trend: "stable", hotspotDistanceKm: null, hotspotDetails: [],
    history: [54, 57, 55, 59, 57, 58], alertCount: 0, machines: [], demo: true,
    propertyDemo: true, environmentalDataOrigin: "demo",
  },
  {
    ...unavailableDetails,
    id: "demo_fazenda_04", name: "Fazenda Três Rios", city: "Uberaba", uf: "MG",
    latitude: -19.7472, longitude: -47.9381, score: 29, level: "low", riskType: "Incêndio",
    trend: "down", hotspotDistanceKm: null, hotspotDetails: [],
    history: [46, 42, 39, 34, 31, 29], alertCount: 0, machines: [], demo: true,
    propertyDemo: true, environmentalDataOrigin: "demo",
  },
];

export const demoStates: StateSummary[] = [
  { uf: "MT", propertiesMonitored: 1, highCriticalCount: 1, highestLevel: "critical", highestScore: 84, alertCount: 3, nearbyHotspotCount: 1, demo: true },
  { uf: "MS", propertiesMonitored: 1, highCriticalCount: 1, highestLevel: "high", highestScore: 71, alertCount: 2, nearbyHotspotCount: 1, demo: true },
  { uf: "GO", propertiesMonitored: 1, highCriticalCount: 0, highestLevel: "moderate", highestScore: 58, alertCount: 0, nearbyHotspotCount: null, demo: true },
  { uf: "MG", propertiesMonitored: 1, highCriticalCount: 0, highestLevel: "low", highestScore: 29, alertCount: 0, nearbyHotspotCount: null, demo: true },
  { uf: "PR", propertiesMonitored: 0, highCriticalCount: 0, highestLevel: "unknown", highestScore: null, alertCount: 0, nearbyHotspotCount: null, demo: false },
];

export const demoHotspots: HotspotView[] = [
  { id: "demo_hotspot_01", latitude: -12.50, longitude: -55.68, detectedAt: null, detectedLabel: "há 18 min", source: "DEMO — cenário sintético", city: "Sorriso", uf: "MT", distanceKm: 4.6, propertyId: "demo_fazenda_01", demo: true },
  { id: "demo_hotspot_02", latitude: -12.68, longitude: -55.80, detectedAt: null, detectedLabel: "há 46 min", source: "DEMO — cenário sintético", city: "Sorriso", uf: "MT", distanceKm: 11.2, propertyId: "demo_fazenda_01", demo: true },
  { id: "demo_hotspot_03", latitude: -21.08, longitude: -56.41, detectedAt: null, detectedLabel: "há 1 h", source: "DEMO — cenário sintético", city: "Bonito", uf: "MS", distanceKm: 12.8, propertyId: "demo_fazenda_02", demo: true },
];

export const demoEvents: LiveEvent[] = [
  { id: "demo_evt_01", category: "event", eventType: "hotspot_detected", kind: "hotspot", title: "Foco de calor recente detectado", description: "Fazenda Boa Vista · 4,6 km da propriedade", severity: "critical", timeLabel: "há 18 min", propertyId: "demo_fazenda_01", propertyName: "Fazenda Boa Vista", city: "Sorriso", uf: "MT", distanceKm: 4.6, source: "DEMO — cenário sintético", latitude: -12.50, longitude: -55.68, factors: [], demo: true },
  { id: "demo_evt_02", category: "event", eventType: "environmental_risk_changed", kind: "risk", title: "Nível de risco alterado", description: "Fazenda Boa Vista · passou para crítico", severity: "critical", timeLabel: "há 24 min", propertyId: "demo_fazenda_01", propertyName: "Fazenda Boa Vista", city: "Sorriso", uf: "MT", currentLevel: "critical", factors: [], demo: true },
  { id: "demo_evt_03", category: "alert", eventType: "machine_risk", kind: "machine", title: "Máquina precisa de atenção", description: "Trator 01 · risco alto no cenário", severity: "high", timeLabel: "há 31 min", propertyId: "demo_fazenda_01", propertyName: "Fazenda Boa Vista", city: "Sorriso", uf: "MT", machineName: "Trator 01", currentLevel: "high", factors: [], demo: true },
  { id: "demo_evt_04", category: "event", eventType: "device_offline", kind: "device", title: "Dispositivo aguardando conexão", description: "Pulverizador 02 · cenário demonstrativo", severity: "unknown", timeLabel: "sem timestamp real", propertyId: "demo_fazenda_02", propertyName: "Fazenda Santa Clara", city: "Bonito", uf: "MS", machineName: "Pulverizador 02", factors: [], demo: true },
];

export function getDemoData(): CommandCenterData {
  return {
    source: "demo", generatedAt: new Date().toISOString(), states: demoStates,
    properties: demoProperties, machines: [trator, pulverizador], events: demoEvents,
    hotspots: demoHotspots, backendAvailable: false, stale: false,
    notices: ["Cenário demonstrativo selecionado pelo usuário; valores ambientais são sintéticos."],
  };
}
