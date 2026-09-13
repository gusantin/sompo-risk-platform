import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright-core";
import AxeBuilder from "@axe-core/playwright";

const base = process.env.FRONTEND_URL || "http://127.0.0.1:3202";
const dir = "artifacts/quality-final";
await mkdir(dir, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", headless: true });
const results = [];
async function audit(page, name) {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]).analyze();
  const violations = result.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })) }));
  await writeFile(`${dir}/${name}-axe.json`, JSON.stringify({ violations, incomplete: result.incomplete }, null, 2));
  results.push({ name, violations });
}
try {
  for (const width of [320, 390, 700, 768, 1024, 1366, 1440, 1920]) {
    for (const [name, route] of [["insurer", "/seguradora"], ["insured", "/segurado"], ["high", "/segurado?fazenda=demo_portfolio_confresa"], ["moderate", "/segurado?fazenda=demo_portfolio_horizonte"], ["low", "/seguradora?cliente=Cliente+C&fazenda=demo_portfolio_dourados"]]) {
      const context = await browser.newContext({ viewport: { width, height: width === 1366 ? 768 : 900 }, reducedMotion: "reduce" });
      const page = await context.newPage();
      const errors = [];
      let expectedUnavailable = false;
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("console", (message) => { if (message.type() === "error" && !(expectedUnavailable && message.text().includes("503"))) errors.push(message.text()); });
      assert.equal((await page.goto(base + route, { waitUntil: "networkidle" })).status(), 200);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name}/${width}: horizontal overflow`);
      assert.equal(await page.locator("h1").count(), 1, `${name}: one page heading`);
      await page.screenshot({ path: `${dir}/${name}-${width}.png`, fullPage: true });
      await page.screenshot({ path: `${dir}/${name}-${width}-viewport.png` });
      if ([320, 768, 1440].includes(width)) await audit(page, `${name}-${width}`);
      if (name === "insured") {
        await page.keyboard.press("Tab");
        assert.equal(await page.locator(":focus").innerText(), "Pular para o conteúdo");
        await page.keyboard.press("Enter");
        assert.equal(await page.locator(":focus").getAttribute("id"), "conteudo");
        const trigger = page.getByRole("button", { name: "Abrir Assistente de Risco" });
        await trigger.click();
        const dialog = page.getByRole("dialog", { name: "Assistente de Risco" });
        await dialog.waitFor();
        for (let i = 0; i < 12; i++) {
          await page.keyboard.press("Tab");
          assert(await page.locator(":focus").evaluate((el) => !!el.closest('[role="dialog"]')), "Assistant must contain keyboard focus");
        }
        await audit(page, `assistant-${width}`);
        await page.screenshot({ path: `${dir}/assistant-${width}.png` });
        await page.keyboard.press("Escape");
        assert.equal(await trigger.evaluate((el) => el === document.activeElement), true, "Return focus on close");
        await trigger.click();
        expectedUnavailable = true;
        await page.route("**/api/perspectives/segurado/agent", (route) => route.fulfill({ status: 503, json: { mensagem: "Consulta indisponível. Tente novamente." } }));
        await page.getByLabel("Sua pergunta ao assistente").fill("Qual o risco?");
        await page.getByRole("button", { name: "Enviar pergunta" }).click();
        await page.getByRole("log").getByText("Consulta indisponível. Tente novamente.").waitFor();
        await page.unroute("**/api/perspectives/segurado/agent");
        expectedUnavailable = false;
        await page.getByLabel("Sua pergunta ao assistente").fill("Quando esses dados foram atualizados?");
        await page.getByRole("button", { name: "Enviar pergunta" }).click();
        await page.getByRole("log").getByText(/Consulta determinística da captura/).waitFor();
        await page.screenshot({ path: `${dir}/assistant-answer-${width}.png` });
        await page.keyboard.press("Escape");
        await page.getByRole("navigation", { name: "Minhas propriedades" }).getByRole("button", { name: "Fazenda Horizonte", exact: true }).click();
        await page.getByRole("region", { name: "Detalhe da fazenda", exact: true }).waitFor();
        await page.goBack();
        await page.getByRole("region", { name: "Propriedade em destaque" }).waitFor();
        await page.goForward();
        await page.getByRole("region", { name: "Detalhe da fazenda", exact: true }).waitFor();
      }
      assert.deepEqual(errors, [], `${name}/${width}: browser errors`);
      await context.close();
    }
    console.log(`Responsive and keyboard checks: ${width}px passed`);
  }
  const page = await browser.newPage();
  await page.setViewportSize({ width: 844, height: 390 });
  await page.goto(`${base}/segurado`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Abrir Assistente de Risco" }).click();
  const landscape = await page.getByRole("dialog").boundingBox();
  assert(landscape.y >= 0 && landscape.y + landscape.height <= 390, "Landscape dialog must fit the viewport");
  await page.screenshot({ path: `${dir}/assistant-landscape.png` });
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 640, height: 450 });
  await page.goto(`${base}/seguradora`, { waitUntil: "networkidle" });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "200% equivalent reflow");
  await page.screenshot({ path: `${dir}/insurer-reflow-640.png`, fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${base}/seguradora`, { waitUntil: "networkidle" });
  await page.getByLabel("Ordenar").selectOption("name");
  const names = await page.getByTestId("farm-card").locator("strong").allTextContents();
  assert.deepEqual(names, [...names].sort((a, b) => a.localeCompare(b)));
  await page.getByRole("navigation", { name: "Clientes da carteira" }).getByRole("button", { name: "Cliente C", exact: true }).click();
  assert.equal(await page.getByTestId("farm-card").count(), 1);
  await page.getByText("Nenhuma exposição moderada, alta ou crítica registrada neste recorte.").waitFor();
  await page.goto(`${base}/segurado?fazenda=demo_portfolio_dourados`, { waitUntil: "networkidle" });
  await page.getByRole("status").filter({ hasText: "Fazenda indisponível neste escopo" }).waitFor();
  assert.doesNotMatch(await page.locator("main").innerText(), /Cliente C|Campo Sul/);
  const own = await (await page.request.get(`${base}/api/perspectives/segurado`)).json();
  for (const [body, status] of [[{ question: "test", snapshotGeneratedAt: "old" }, 409], [{ question: "test", contextPropertyId: "demo_portfolio_dourados" }, 404], [{ question: " " }, 400]]) {
    assert.equal((await page.request.post(`${base}/api/perspectives/segurado/agent`, { data: body })).status(), status);
  }
  const reply = await (await page.request.post(`${base}/api/perspectives/segurado/agent`, { data: { question: "Fontes?", snapshotGeneratedAt: own.generatedAt, clientScope: "Cliente C", perspective: "seguradora" } })).json();
  assert.doesNotMatch(reply.answer, /Cliente B|Cliente C|Pantanal Norte|Campo Sul/);
  await page.close();
  await writeFile(`${dir}/results.json`, JSON.stringify(results, null, 2));
  assert.deepEqual(results.filter((r) => r.violations.length), [], "Accessibility violations; see artifacts/quality-final/*-axe.json");
  console.log("PASS: 40 responsive screens, keyboard dialog, failure recovery, history, sorting, scope and accessibility audits.");
} finally { await browser.close(); }
