// Explicit maintenance command, never a build step. Only public demo identities
// and the environmental presentation projection are exported.
import { readFile, writeFile, mkdir } from "node:fs/promises";
const input = process.argv[2] || "../data/presentation_portfolio.json";
const source = JSON.parse(await readFile(input, "utf8"));
if (source.schema !== "presentation_real_portfolio_v1") throw new Error("Invalid portfolio schema");
const identities = {
  demo_portfolio_confresa: ["Cliente A", "Fazenda Araguaia"],
  demo_portfolio_horizonte: ["Cliente A", "Fazenda Horizonte"],
  demo_portfolio_pocone: ["Cliente B", "Fazenda Pantanal Norte"],
  demo_portfolio_dourados: ["Cliente C", "Fazenda Campo Sul"],
};
const pick = (obj, keys) => Object.fromEntries(keys.filter((key) => key in obj).map((key) => [key, obj[key]]));
const cases = Object.entries(identities).map(([id, [clientName, nome]]) => {
  const item = source.cases.find((c) => c.id === id);
  if (!item || item.property.demoData !== true || item.property.clientName !== clientName || item.property.nome !== nome) throw new Error(`Non-demo or missing identity: ${id}`);
  return { ...pick(item, ["id", "riskType", "risk", "analysisAt", "environmentalDataReal", "weatherWarnings", "environmentalEvidence", "sourceHealth", "dataCoverage", "riskExplanation", "recommendations", "hotspots", "provenance", "alertState", "notificationState", "environmentalContext", "presentationFactors", "processingState"]),
    property: pick(item.property, ["fazendaId", "clientName", "nome", "municipio", "estado", "ibgeCode", "demoData", "identityOrigin", "latitude", "longitude", "coordinateSource", "representativeness", "preparedAt"]),
    ...(item.operationalState ? { operationalState: {
      openAlerts: item.operationalState.openAlerts,
      alerts: (item.operationalState.alerts || []).map((a, i) => ({ alertId: `snapshot_alert_${i}`, status: a.status, severity: a.severity,
        notifications: (a.notifications || []).map((n, j) => ({ notificationId: `snapshot_notification_${j}`, ...pick(n, ["channel", "status", "deliveredAt"]) })) })),
    } } : {}),
  };
});
const output = JSON.stringify({ schema: source.schema, mode: "snapshot", generatedAt: source.generatedAt, cases,
  limitations: ["Captura de apresentação: identidades fictícias e evidências ambientais reais armazenadas; não é uma consulta ao vivo."] }, (key, value) => {
  if (/^(private_key|private_key_id|client_email|client_id|token|api_?key|password|authorization|chat_?id|email|phone|cpf|cnpj)$/i.test(key)) throw new Error(`Private field rejected: ${key}`);
  return value === "real_live" ? "real_cached" : value;
}, 2) + "\n";
if (/-----BEGIN .*PRIVATE KEY-----|\b\d{6,12}:[A-Za-z0-9_-]{30,}\b|"type"\s*:\s*"service_account"/i.test(output)) throw new Error("Secret material rejected");
await mkdir("src/data", { recursive: true });
await writeFile("src/data/presentation-portfolio.json", output);
console.log(`Exported ${cases.length} demo properties; original acquisition timestamps preserved.`);
