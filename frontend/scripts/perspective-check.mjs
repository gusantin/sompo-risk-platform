import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { mkdir } from "node:fs/promises";
const base = process.env.FRONTEND_URL || "http://127.0.0.1:3100";
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", headless: true });
await mkdir("artifacts", { recursive: true });
try {
  const context = await browser.newContext();
  const all = await (await context.request.get(`${base}/api/perspectives/seguradora`)).json();
  const own = await (await context.request.get(`${base}/api/perspectives/segurado?client=Cliente%20C`)).json();
  assert.equal(all.properties.length, 4);
  assert.equal(new Set(all.properties.map((p) => p.clientName)).size, 3);
  assert.deepEqual(own.properties.map((p) => p.name).sort(), ["Fazenda Araguaia", "Fazenda Horizonte"]);
  assert.doesNotMatch(JSON.stringify(own), /Cliente B|Cliente C|demo_portfolio_pocone|demo_portfolio_dourados/);
  for (const p of own.properties) assert.deepEqual(p.environmentalContext, all.properties.find((a) => a.id === p.id).environmentalContext);
  for (const perspective of ["seguradora", "segurado"]) {
    const response = await context.request.post(`${base}/api/perspectives/${perspective}/agent`, { data: { question: "Quem foi notificado?", snapshotGeneratedAt: all.generatedAt, perspective: "seguradora", clientScope: "Cliente C" } });
    assert.equal(response.status(), 200);
    const answer = await response.json(); assert.equal(answer.readOnly, true);
    if (perspective === "segurado") { assert.equal(answer.trace.consultedIds.length, 2); assert.doesNotMatch(JSON.stringify(answer), /Cliente B|Cliente C|pocone|dourados/); }
  }
  const denied = await context.request.post(`${base}/api/perspectives/segurado/agent`, { data: { question: "Qual risco?", snapshotGeneratedAt: own.generatedAt, contextPropertyId: "demo_portfolio_dourados" } });
  assert.equal(denied.status(), 400);
  for (const width of [390, 1366, 1440, 1920]) for (const perspective of ["seguradora", "segurado"]) {
    const page = await context.newPage();
    await page.setViewportSize({ width, height: 900 });
    const errors = []; page.on("pageerror", (e) => errors.push(e.message));
    let navigations = 0; page.on("request", (request) => { if (request.isNavigationRequest() && request.resourceType() === "document") navigations++; });
    await page.goto(`${base}/${perspective}`, { waitUntil: "networkidle" });
    assert.equal(await page.evaluate(() => innerWidth), width);
    assert.equal(await page.getByTestId("farm-card").count(), perspective === "segurado" ? 2 : 4);
    if (perspective === "segurado") {
      assert.doesNotMatch(await page.locator("body").innerText(), /Cliente B|Cliente C|Pantanal Norte|Campo Sul|Prioridades da carteira/);
      assert.equal(await page.getByLabel("Mapa do escopo").getByRole("button", { name: /^Abrir Fazenda/ }).count(), 2);
      for (const name of ["Fazenda Horizonte", "Fazenda Araguaia"]) {
        await page.getByRole("navigation", { name: "Minhas propriedades" }).getByRole("button", { name, exact: true }).click();
        await page.getByLabel("Detalhe da fazenda").getByRole("heading", { name, exact: true }).waitFor();
        assert.equal(await page.getByLabel("Mapa do escopo").getByRole("button", { name: /^Abrir Fazenda/ }).count(), 1);
        assert.ok(new URL(page.url()).searchParams.get("fazenda"));
      }
      assert.equal(navigations, 1, "Property switching must not reload the document");
      await page.reload({ waitUntil: "networkidle" });
      await page.getByLabel("Detalhe da fazenda").getByRole("heading", { name: "Fazenda Araguaia", exact: true }).waitFor();
    } else {
      await page.getByLabel("Prioridades dos clientes").getByText("Cliente A", { exact: true }).locator("..").locator("..").getByRole("button", { name: "Abrir cliente" }).click();
      assert.equal(await page.getByTestId("farm-card").count(), 2);
      assert.match(page.url(), /\/seguradora\?/);
      await page.getByRole("button", { name: /Fazenda Araguaia Confresa/ }).click();
      await page.getByLabel("Detalhe da fazenda").waitFor();
      assert.match(page.url(), /\/seguradora\?/);
    }
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    await page.screenshot({ path: `artifacts/${perspective}-${width}.png`, fullPage: true });
    await page.close();
  }
  // Isolated browser fixture: exercise creation/loading without changing the real snapshot.
  const page = await context.newPage();
  await page.goto(`${base}/segurado`, { waitUntil: "networkidle" });
  const fixture = structuredClone(own);
  const pending = { ...fixture.properties[0], id: "demo_portfolio_test_new", name: "Fazenda Teste", level: "unknown", score: null, factors: [], environmentalContext: undefined, processingState: "waiting", environmentalValues: [], provenance: { identity: "demo", environmental: { origin: "unavailable", state: "unavailable" } } };
  fixture.properties.push(pending);
  await page.route("**/api/perspectives/segurado", (route) => route.fulfill({ json: fixture }));
  let release; const gate = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/insured/properties", async (route) => {
    const body = route.request().postDataJSON();
    if (body.analyzeId) { await gate; await route.fulfill({ status: 503, json: { mensagem: "Dados ambientais indisponíveis" } }); }
    else { assert.deepEqual(body, { nome: "Fazenda Teste", municipio: "Sorriso", estado: "MT" }); await route.fulfill({ status: 201, json: { property: { fazendaId: pending.id } } }); }
  });
  await page.getByRole("button", { name: "Adicionar fazenda", exact: true }).click();
  await page.getByLabel("Nome da fazenda", { exact: true }).fill("Fazenda Teste");
  await page.getByLabel("Município", { exact: true }).fill("Sorriso");
  await page.getByLabel("UF", { exact: true }).fill("MT");
  await page.getByRole("button", { name: "Salvar e analisar", exact: true }).click();
  await page.getByText("Aguardando dados", { exact: true }).waitFor();
  await page.getByRole("status").getByText(/Analisando condições/).waitFor();
  assert.equal(await page.getByLabel("Detalhe da fazenda").getByText(/61.*100/).count(), 0);
  release(); await page.getByRole("status").getByText("Dados ambientais indisponíveis", { exact: true }).waitFor();
  await page.close();
  console.log("PASS perspectives: backend/BFF scope, Copilot isolation, maps, two farms, URL switching without reload, safe creation; both routes at 390/1366/1440/1920px.");
} finally { await browser.close(); }
