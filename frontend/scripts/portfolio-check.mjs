import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { mkdir, readFile } from "node:fs/promises";

const base = process.env.FRONTEND_URL || "http://127.0.0.1:3100";
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", headless: true });
await mkdir("artifacts", { recursive: true });
try {
  const context = await browser.newContext();
  const response = await context.request.get(`${base}/api/command-center?mode=portfolio`);
  const data = await response.json();
  assert.equal(data.requestMode, "portfolio");
  assert.equal(data.properties.length, 4, "Capture the real presentation portfolio first");
  const snapshot = JSON.parse(await readFile(process.env.PRESENTATION_PORTFOLIO_PATH || "../data/presentation_portfolio.json", "utf8"));
  for (const question of ["Qual cliente precisa mais de atenção agora?", "Vai chover nessa fazenda?", "Por que o Cliente A está em risco alto?", "Existe algum foco de calor relevante?", "Qual cliente está em situação normal?", "Quais dados são reais e quais são demonstrativos?", "Quando esses dados foram atualizados?"]) {
    const reply = await context.request.post(`${base}/api/agent`, { data: { question, mode: "portfolio", snapshotGeneratedAt: data.generatedAt } });
    assert.equal(reply.status(), 200);
    const answer = await reply.json();
    assert.equal(answer.readOnly, true);
    assert.equal(answer.snapshotGeneratedAt, data.generatedAt);
    assert.match(answer.answer, /demonstrativa/);
    assert.doesNotMatch(answer.answer, /ao vivo|incêndio confirmado/);
  }
  for (const property of data.properties) {
    assert.equal(property.propertyDemo, true);
    assert.equal(property.provenance.identity, "demo");
    assert.notEqual(property.environmentalDataOrigin, "demo");
    assert.notEqual(property.provenance.environmental.state, "real_live", "A snapshot read is not a live query");
    assert.ok(property.clientName);
    assert.equal(property.environmentalContext.schema, "environmental_context_v1");
    assert.ok(property.environmentalContext.sections.some((s) => s.title.startsWith("Previsão de 24h")));
    const original = snapshot.cases.find((c) => c.id === property.id);
    for (const factor of original?.risk?.fatores ?? []) {
      if (factor.contribuicao === 0) assert.equal(property.factors.some((f) => f.key === factor.fator), false, "Zero-contribution factors must not be presented as elevated evidence");
    }
  }
  for (const width of [390, 1440, 1920]) {
    const page = await context.newPage();
    await page.setViewportSize({ width, height: 900 });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`${base}/?mode=portfolio`, { waitUntil: "networkidle" });
    assert.equal(await page.evaluate(() => innerWidth), width);
    assert.equal(await page.getByLabel("Exposição da carteira", { exact: true }).getByText(/cliente demonstrativo/).count(), 4);
    await page.getByRole("button", { name: "Cliente", exact: true }).click();
    const selected = data.properties[2];
    await page.getByLabel("Propriedade do cliente").selectOption(selected.id);
    const scope = page.getByLabel("Situação da propriedade", { exact: true });
    await scope.getByRole("heading", { name: "Condições ambientais", exact: true }).waitFor();
    await page.getByRole("button", { name: "Abrir Assistente de Risco", exact: true }).click();
    const requestPromise = page.waitForRequest((r) => r.url().endsWith("/api/agent") && r.method() === "POST");
    await page.getByRole("button", { name: "Quando esses dados foram atualizados?", exact: true }).click();
    const agentRequest = (await requestPromise).postDataJSON();
    assert.equal(agentRequest.contextPropertyId, selected.id);
    assert.equal(agentRequest.mode, "portfolio");
    assert.equal(agentRequest.snapshotGeneratedAt, data.generatedAt);
    await page.getByLabel("Assistente de Risco", { exact: true }).getByText(/não representam segurados SOMPO/).waitFor();
    assert.equal(await page.getByLabel("Assistente de Risco", { exact: true }).getByText(new RegExp(data.properties[0].name)).count(), 0);
    await page.getByRole("button", { name: "Fechar assistente", exact: true }).click();
    await scope.getByText("O que fazer agora?", { exact: true }).waitFor();
    assert.equal(await scope.getByText(data.properties[0].name, { exact: true }).count(), 0);
    await scope.getByText("Dados usados nesta análise", { exact: true }).click();
    await scope.getByText(/Identidade fictícia de apresentação/).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: `artifacts/portfolio-client-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "SOMPO", exact: true }).click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: `artifacts/portfolio-sompo-${width}.png`, fullPage: true });
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log("PASS: captured real portfolio, seven Copilot questions through BFF, snapshot pin, read-only client scope and 390/1440/1920px layouts.");
} finally { await browser.close(); }
