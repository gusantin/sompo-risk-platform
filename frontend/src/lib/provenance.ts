import type { PropertyView } from "./types";

export function provenanceLabel(property: PropertyView) {
  const state = property.provenance?.environmental.state;
  if (state) return { real_live: "Consulta real recente", real_cached: "Última leitura real", stale: "Leitura real desatualizada", synthetic: "Dados sintéticos · DEMO", unavailable: "Dados indisponíveis", insufficient_data: "Dados insuficientes" }[state];
  return property.environmentalDataOrigin === "demo" ? "Dados sintéticos · DEMO" : property.environmentalDataOrigin === "real" ? "Dados ambientais reais · leitura registrada" : "Dados indisponíveis";
}

export function exposureHeading(property: PropertyView) {
  const state = property.provenance?.environmental.state;
  return state === "stale" || state === "real_cached" ? "Último risco conhecido" : "Risco atual";
}
