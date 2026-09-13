import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
const source = await readFile("src/lib/operations.ts", "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { compareAlerts, alertTimeline, priorityItems, stamp } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const alert = { alertId: "a", fazendaId: "f", severity: "high", status: "open", createdAt: "2026-09-12T10:00:00Z", factors: [], evidence: [] };
const items = [
  { ...alert, alertId: "resolved", severity: "critical", status: "resolved" },
  { ...alert, alertId: "ack", status: "acknowledged", createdAt: "2026-09-12T12:00:00Z" },
  { ...alert, alertId: "old" },
  { ...alert, alertId: "new", createdAt: "2026-09-12T11:00:00Z" },
  { ...alert, alertId: "critical", severity: "critical" },
];
assert.deepEqual([...items].sort(compareAlerts).map((a) => a.alertId), ["critical", "resolved", "new", "old", "ack"]);
const data = { properties: [{ id: "f", name: "Farm", level: "unknown", score: null, analysisFreshness: "Indisponível" }], machines: [] };
const queue = priorityItems(data, items);
assert.deepEqual(queue.filter((a) => a.alertId).map((a) => a.alertId), ["critical", "new", "old", "ack"]);
assert.equal(priorityItems(data, [], "other").length, 0);
assert.equal(priorityItems(data, [alert, alert]).filter((i) => i.alertId).length, 1, "Repeated events cannot duplicate a priority");
assert.equal(priorityItems(data, [{ ...alert, status: "resolved" }]).some((i) => i.alertId), false);
assert.equal(priorityItems(data, [{ ...alert, severity: "critical", status: "acknowledged" }, { ...alert, alertId: "high-open" }])[0].level, "critical");
assert.equal(priorityItems(data, [])[0].level, "unknown");
assert.equal(priorityItems(data, null)[0].status, "Alertas indisponíveis");
assert.deepEqual(alertTimeline(alert).map((e) => e.label), ["Alerta criado"]);
assert.deepEqual(alertTimeline({ ...alert, acknowledgedAt: "2026-09-12T10:05:00Z", resolvedAt: "2026-09-12T10:10:00Z" }, [{ channel: "telegram", createdAt: "2026-09-12T10:01:00Z" }]).map((e) => e.label), ["Alerta criado", "Notificação preparada · telegram", "Alerta reconhecido", "Alerta resolvido"]);
assert.deepEqual(alertTimeline({ ...alert, createdAt: "invalid" }), []);
assert.equal(alertTimeline(alert, [{ channel: "telegram", createdAt: "2026-09-11T10:00:00Z", deliveredAt: "2026-09-11T10:01:00Z" }]).length, 1, "Do not attach deliveries from an earlier occurrence");
assert.equal(stamp("invalid"), "Não informado");
console.log("PASS: deterministic priority order, scope, unknown risk, unavailable alerts and factual timeline.");
