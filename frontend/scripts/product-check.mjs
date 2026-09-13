import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { mkdir } from "node:fs/promises";
import { createServer } from "node:http";
const base = process.env.FRONTEND_URL || "http://127.0.0.1:3000";
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", headless: true });
await mkdir("artifacts", { recursive: true });
try {
  const context = await browser.newContext();
  const response = await context.request.get(`${base}/api/command-center?mode=demo`);
  assert.equal(response.status(), 200);
  const fixture = await response.json();
  fixture.source = "backend";
  fixture.properties = fixture.properties.slice(0, 2).map((p, i) => ({ ...p, id: `f${i + 1}`, name: `Property ${i + 1}`, demo: false, propertyDemo: false, environmentalDataOrigin: "real", level: i ? "unknown" : "critical" }));
  fixture.machines = fixture.machines.slice(0, 2).map((m, i) => ({ ...m, id: "m1", propertyId: `f${i + 1}`, name: `Machine ${i + 1}`, demo: false }));
  fixture.hotspots = []; fixture.events = [{ id: "a1", category: "alert", eventType: "machine_risk", kind: "machine", title: "Machine alert", description: "Official fixture", severity: "critical", timeLabel: "agora", propertyId: "f1", factors: [], demo: false, alertStatus: "open" }]; fixture.states = [];
  fixture.notices = ["Fixture isolada de teste · dados sintéticos, sem acesso ao Firebase."];
  let alert = { alertId: "a1", fazendaId: "f1", maquinaId: "m1", type: "machine_risk", riskType: "machine", severity: "critical", status: "open", createdAt: "2026-09-12T10:00:00Z", factors: ["temp_motor:critical"], evidence: [], recommendations: [{ ruleId: "machine_overheat", text: "Inspecionar antes de continuar." }] };
  let patches = 0;
  let rejectPatch = false;
  let actionsEnabled = true;
  const errors = [];
  const page = await context.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("**/api/command-center", (route) => route.fulfill({ json: fixture }));
  await page.route("**/api/alerts*", async (route) => {
    if (route.request().method() === "GET" && new URL(route.request().url()).searchParams.has("alertId")) {
      return route.fulfill({ json: { items: [{ notificationId: "n1", channel: "telegram", status: "delivered", createdAt: "2026-09-12T10:01:00Z", attemptedAt: "2026-09-12T10:01:01Z", deliveredAt: "2026-09-12T10:01:02Z" }] } });
    }
    if (route.request().method() === "PATCH") {
      patches++;
      if (rejectPatch) return route.fulfill({ status: 503, json: { error: "fixture failure" } });
      const body = route.request().postDataJSON();
      assert.equal(body.alertId, "a1");
      alert = { ...alert, status: body.status, ...(body.status === "acknowledged" ? { acknowledgedAt: "2026-09-12T10:05:00Z" } : { resolvedAt: "2026-09-12T10:10:00Z" }) };
      return route.fulfill({ json: { alert, recommendations: alert.recommendations } });
    }
    return route.fulfill({ json: { items: [alert], actionsEnabled } });
  });
  await page.goto(base, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Atualizar dados" }).click();
  await page.getByRole("button", { name: "Reconhecer", exact: true }).waitFor();
  await page.getByRole("heading", { name: "SOMPO Control Center", exact: true }).waitFor();
  await page.getByRole("button", { name: "Consultar notificação", exact: true }).click();
  await page.getByText(/telegram: Entrega aceita pelo Telegram/).waitFor();
  await page.getByLabel("Selecionar máquina").selectOption("f2:m1");
  await page.getByRole("button", { name: "Atualizar dados" }).click();
  assert.equal(await page.getByLabel("Selecionar máquina").inputValue(), "f2:m1", "Refresh must preserve composite machine identity");
  await page.getByRole("button", { name: "Reconhecer", exact: true }).click();
  assert.equal(patches, 0, "Opening confirmation must not mutate");
  await page.getByRole("button", { name: "Cancelar", exact: true }).click();
  assert.equal(patches, 0);
  await page.getByRole("button", { name: "Reconhecer", exact: true }).click();
  rejectPatch = true;
  await page.getByRole("button", { name: "Confirmar ação", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "Alteração não confirmada" }).waitFor();
  assert.equal(alert.status, "open");
  rejectPatch = false;
  await page.getByRole("button", { name: "Confirmar ação", exact: true }).click();
  await page.getByRole("status").filter({ hasText: "confirmação do backend" }).waitFor();
  await page.waitForFunction(() => ![...document.querySelectorAll("button")].some((b) => b.textContent === "Reconhecer"));
  assert.equal(alert.status, "acknowledged");
  await page.getByRole("button", { name: "Abrir alerta: Machine alert" }).getByText("Reconhecido", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Resolver", exact: true }).click();
  await page.getByRole("button", { name: "Confirmar ação", exact: true }).click();
  await page.getByLabel("Filtrar status do alerta").selectOption("resolved");
  await page.locator("article").getByText("Resolvido", { exact: true }).waitFor();
  assert.equal(alert.status, "resolved");
  await page.getByRole("button", { name: "Abrir alerta: Machine alert" }).getByText("Resolvido", { exact: true }).waitFor();
  assert.equal(patches, 3);
  await page.getByLabel("Linha do tempo do alerta").getByText("Alerta reconhecido", { exact: false }).waitFor();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const view of ["SOMPO", "Cliente"]) {
      await page.getByRole("button", { name: view, exact: true }).click();
      await page.getByRole("heading", { name: view === "SOMPO" ? "SOMPO Control Center" : "Client Operations Center", exact: true }).waitFor();
      if (view === "Cliente") {
        await page.getByLabel("Propriedade do cliente").selectOption("f2");
        assert.equal(await page.locator("article").count(), 0, "Another property's alert leaked into client view");
        assert.equal(await page.getByLabel("Indicadores principais").count(), 0);
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false, `${view} overflow at ${width}`);
      await page.screenshot({ path: `artifacts/product-${view}-${width}.png`, fullPage: true });
    }
  }
  actionsEnabled = false;
  alert = { ...alert, status: "open" };
  await page.getByRole("button", { name: "SOMPO", exact: true }).click();
  await page.getByRole("button", { name: "Atualizar dados" }).click();
  await page.getByLabel("Filtrar status do alerta").selectOption("active");
  assert.equal(await page.getByRole("button", { name: "Reconhecer", exact: true }).isDisabled(), true);
  assert.deepEqual(errors, []);
  const blocked = await context.request.patch(`${base}/api/alerts`, { data: { alertId: "a1", status: "resolved" } });
  assert.equal(blocked.status(), 403);
  let inventoryUnavailable = false;
  const stub = createServer((req, res) => {
    const farm = { id: "f1", nome: "Contract property", estado: "MT" };
    const machine = { maquinaId: "m1", nome: "Contract machine" };
    let body = { items: [] };
    if (req.url.startsWith("/dashboard")) body = { properties: [{ property: farm, currentRisk: { nivel: "alto", score: 75 } }, { property: { id: "demo_hidden", demoData: true } }], alerts: [] };
    if (req.url === "/fazendas/f1/status") body = { machines: [machine], currentRisk: null };
    if (req.url === "/fazendas/f1/status" && inventoryUnavailable) { res.statusCode = 503; body = { error: "fixture unavailable" }; }
    if (req.url === "/fazendas/f1/maquinas/m1/status") body = { identity: machine, machineRisk: { status: "insufficient_data", level: "low" } };
    res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify(body));
  });
  // Local contract fixture only; refuses to replace an existing backend on this port.
  await new Promise((resolve, reject) => { stub.once("error", reject); stub.listen(5000, "127.0.0.1", resolve); });
  try {
    const adapted = await (await context.request.get(`${base}/api/command-center`)).json();
    assert.equal(adapted.source, "backend");
    assert.equal(adapted.properties.length, 1, "DEMO properties must be excluded");
    assert.equal(adapted.properties[0].score, null);
    assert.equal(adapted.properties[0].alertCount, null, "Unavailable alert counts cannot become zero");
    assert.equal(adapted.properties[0].level, "unknown");
    assert.equal(adapted.properties[0].environmentalLevel, "high", "Overall risk cannot be relabeled as fire risk");
    assert.equal(adapted.properties[0].latitude, null, "Missing coordinates must not become zero");
    assert.equal(adapted.machines[0].machineRisk, "unknown");
    assert.equal(adapted.machines[0].temperature, null);
    assert.equal(adapted.machineInventoryAvailable, true);
    inventoryUnavailable = true;
    const partial = await (await context.request.get(`${base}/api/command-center`)).json();
    assert.equal(partial.machineInventoryAvailable, false, "Failed inventory reads must remain unavailable");
  } finally { await new Promise((resolve) => stub.close(resolve)); }
  console.log("PASS: both views, desktop/mobile, client scope, acknowledge/resolve, write gate and no runtime errors.");
  console.log("PASS: real BFF adapters preserve missing risk/telemetry/coordinates and exclude DEMO properties.");
} finally { await browser.close(); }
