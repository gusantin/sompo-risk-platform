import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright-core";
const phase = process.argv[2] || "after";
const base = process.env.FRONTEND_URL || "http://127.0.0.1:3201";
const dir = `artifacts/ux-polish/${phase}`;
await mkdir(dir, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", headless: true });
const results = [];
try {
  for (const width of [390, 1366, 1440, 1920]) {
    for (const [name, route] of [
      ["seguradora", "/seguradora"], ["segurado", "/segurado"],
      ["high", "/segurado?fazenda=demo_portfolio_confresa"],
      ["moderate", "/segurado?fazenda=demo_portfolio_horizonte"],
      ["low", "/seguradora?cliente=Cliente+C&fazenda=demo_portfolio_dourados"],
    ]) {
      const page = await browser.newPage({ viewport: { width, height: width === 1366 ? 768 : 900 } });
      const errors = []; page.on("pageerror", (e) => errors.push(e.message));
      assert.equal((await page.goto(base + route, { waitUntil: "networkidle" })).status(), 200);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name}/${width}: overflow`);
      if (route.split("?")[0] === "/segurado") assert.doesNotMatch(await page.locator("main").innerText(), /Cliente B|Cliente C|Pantanal Norte|Campo Sul/);
      await page.screenshot({ path: `${dir}/${name}-${width}.png`, fullPage: true });
      if (phase === "after" && name === "seguradora") {
        await page.getByRole("button", { name: "Ver situação", exact: true }).first().click();
        await page.getByLabel("Detalhe da fazenda", { exact: true }).waitFor();
        assert(new URL(page.url()).searchParams.get("fazenda"));
        assert.equal(await page.getByLabel("Mapa do escopo").getByRole("button", { pressed: true }).count(), 1);
        await page.getByRole("button", { name: "Voltar à carteira", exact: true }).click();
        await page.getByRole("navigation", { name: "Clientes da carteira" }).getByRole("button", { name: "Cliente A", exact: true }).click();
        assert.equal(await page.getByTestId("farm-card").count(), 2);
      }
      if (phase === "after" && name === "segurado") {
        let navigations = 0; page.on("request", (r) => { if (r.isNavigationRequest() && r.resourceType() === "document") navigations++; });
        for (const farm of ["Fazenda Horizonte", "Fazenda Araguaia"]) {
          const button = page.getByRole("navigation", { name: "Minhas propriedades" }).getByRole("button", { name: farm, exact: true });
          await button.click(); assert.equal(await button.getAttribute("aria-pressed"), "true");
          await page.getByLabel("Detalhe da fazenda", { exact: true }).getByRole("heading", { name: farm, exact: true }).waitFor();
          assert.equal(await page.getByLabel("Mapa do escopo").getByRole("button", { name: /^Abrir Fazenda/ }).count(), 1);
        }
        assert.equal(navigations, 0);
        await page.goBack(); await page.getByRole("heading", { name: "Fazenda Horizonte", exact: true }).waitFor();
        await page.getByRole("button", { name: "Abrir Assistente de Risco", exact: true }).click();
        const outgoing = page.waitForRequest((r) => r.url().endsWith("/api/perspectives/segurado/agent") && r.method() === "POST");
        await page.getByRole("button", { name: "Quando esses dados foram atualizados?", exact: true }).click();
        assert.equal((await outgoing).postDataJSON().contextPropertyId, "demo_portfolio_horizonte");
        await page.getByText(/Consulta determinística da captura/).waitFor();
        await page.getByRole("button", { name: "Fechar assistente" }).click();
        await page.getByRole("button", { name: "Adicionar fazenda", exact: true }).click();
        await page.getByRole("status").filter({ hasText: "cadastro e persistência desabilitados" }).waitFor();
      }
      assert.deepEqual(errors, []); results.push({ name, width, errors }); await page.close();
    }
  }
  await writeFile(`${dir}/results.json`, JSON.stringify(results, null, 2));
  console.log(`${phase}: ${results.length} screenshots; no overflow or runtime errors; insured scope preserved`);
} finally { await browser.close(); }
