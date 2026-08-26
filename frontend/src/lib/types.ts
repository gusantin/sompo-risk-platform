export type RiskLevel = "low" | "moderate" | "high" | "critical" | "unknown";

export interface StateSummary {
  uf: "MT" | "MS" | "GO" | "MG" | "PR";
  propertiesMonitored: number;
  highCriticalCount: number;
  highestLevel: RiskLevel;
  highestScore: number | null;
  alertCount: number;
  nearbyHotspotCount: number | null;
  demo: boolean;
}

export interface DetailItem {
  label: string;
  value: string;
  source?: string;
  updatedLabel?: string | null;
}

export interface ExplainableFactor {
  key: string;
  label: string;
  description: string | null;
  group: "now" | "history" | "context";
}

export interface CoverageItem {
  label: string;
  available: boolean | null;
}

export interface SourceItem {
  name: string;
  status: string;
  cacheHit: boolean | null;
  updatedLabel: string | null;
}

export interface MachineView {
  id: string;
  propertyId: string;
  propertyName: string;
  name: string;
  deviceModel: string;
  connection: "online" | "stale" | "offline" | "unknown";
  deviceLinked: boolean;
  lastCommunication: string;
  temperature: { value: number; unit: string; label: string; scopeLabel: string } | null;
  humidity: { value: number; unit: string; label: string; scopeLabel: string } | null;
  telemetryOrigin: "physical" | "demo" | "unavailable";
  machineRisk: RiskLevel;
  machineRiskStatus: "ok" | "insufficient_data" | "unknown";
  environmentalRisk: RiskLevel;
  operationalRisk: RiskLevel;
  demo: boolean;
}

export interface PropertyView {
  id: string;
  name: string;
  city: string;
  uf: string;
  latitude: number;
  longitude: number;
  score: number | null;
  level: RiskLevel;
  riskType: string;
  trend: "up" | "down" | "stable" | "unknown";
  hotspotDistanceKm: number | null;
  hotspotDetails: DetailItem[];
  factors: ExplainableFactor[];
  historyDetails: DetailItem[];
  contextDetails: DetailItem[];
  environmentalValues: DetailItem[];
  confidence: string | null;
  coveragePercent: number | null;
  coverage: CoverageItem[];
  sources: SourceItem[];
  analysisTimestamp: string | null;
  analysisFreshness: string;
  history: number[];
  alertCount: number;
  machines: MachineView[];
  demo: boolean;
  propertyDemo: boolean;
  environmentalDataOrigin: "real" | "demo" | "unavailable";
}

export interface LiveEvent {
  id: string;
  category: "event" | "alert";
  eventType: string;
  kind: "hotspot" | "property" | "machine" | "device" | "risk";
  title: string;
  description: string;
  severity: RiskLevel;
  timeLabel: string;
  propertyId?: string;
  propertyName?: string;
  city?: string;
  uf?: string;
  machineName?: string;
  previousLevel?: RiskLevel;
  currentLevel?: RiskLevel;
  distanceKm?: number;
  detectedAt?: string;
  startsAt?: string;
  endsAt?: string;
  location?: string;
  sourceSeverity?: string;
  hailExplicit?: boolean;
  source?: string;
  satellite?: string;
  latitude?: number;
  longitude?: number;
  factors: ExplainableFactor[];
  demo: boolean;
}

export interface HotspotView {
  id: string;
  latitude: number;
  longitude: number;
  detectedAt: string | null;
  detectedLabel: string;
  source: string;
  satellite?: string;
  distanceKm?: number;
  propertyId?: string;
  city?: string;
  uf?: string;
  demo: boolean;
}

export interface CommandCenterData {
  source: "live" | "backend" | "demo" | "mixed" | "unavailable";
  generatedAt: string;
  states: StateSummary[];
  properties: PropertyView[];
  machines: MachineView[];
  events: LiveEvent[];
  hotspots: HotspotView[];
  backendAvailable: boolean;
  stale: boolean;
  notices: string[];
}
