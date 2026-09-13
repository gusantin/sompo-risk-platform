import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright-core";

await mkdir("artifacts/vercel", { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", headless: true });
const request = async (base, path, body) => fetch(base + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
let implicitRequests = 0;
const trap = createServer((_req, res) => { implicitRequests++; res.writeHead(503).end(); });
await new Promise((resolve, reject) => { trap.once("error", reject); trap.listen(5000, "127.0.0.1", resolve); });
try {
  for (const [scenario, backend] of [["unconfigured", ""], ["invalid", "http://127.0.0.1:59999"]]) {
    const env = { ...process.env, VERCEL: "1", NODE_ENV: "production" };
    for (const key of Object.keys(env)) if (/SOMPO_|FIREBASE|TELEGRAM|OLLAMA|PRESENTATION_PORTFOLIO|^PORT$/.test(key)) delete env[key];
    if (backend) env.SOMPO_BACKEND_URL = backend;
    const base = "http://127.0.0.1:3198";
    const server = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "--port", "3198"], { env, stdio: ["ignore", "pipe", "pipe"] });
    let logs = "";
    server.stdout.on("data", (b) => { logs += b; }); server.stderr.on("data", (b) => { logs += b; });
    try {
      for (let i = 0; i < 100; i++) {
        if (logs.includes("Ready")) break;
        if (server.exitCode !== null) throw new Error(logs);
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
      const root = await fetch(base, { redirect: "manual" });
      assert.equal(root.status, 307); assert.equal(root.headers.get("location"), "/seguradora");
      const insurer = await (await request(base, "/api/perspectives/seguradora")).json();
      const insured = await (await request(base, "/api/perspectives/segurado")).json();
      assert.equal(insurer.properties.length, 4); assert.equal(insured.properties.length, 2);
      assert(insured.properties.every((p) => p.clientName === "Cliente A"));
      assert.equal(insurer.backendAvailable, false); assert.equal(insurer.presentationMode, "snapshot");
      assert(insurer.properties.every((p) => p.environmentalContext && p.provenance.environmental.state !== "real_live"));
      assert(!JSON.stringify(insured).includes("Cliente B")); assert(!JSON.stringify(insured).includes("Pantanal Norte"));
      const concurrent = await Promise.all(Array.from({ length: 8 }, (_, i) => request(base, `/api/perspectives/${i % 2 ? "segurado" : "seguradora"}`).then((r) => r.json())));
      concurrent.forEach((data, i) => assert.equal(data.properties.length, i % 2 ? 2 : 4));
      for (const path of ["/api/command-center?mode=portfolio", "/api/command-center?mode=portfolio-live", "/api/machines"]) assert.equal((await request(base, path)).status, 200);
      assert.equal((await request(base, "/api/alerts")).status, 503);
      assert.equal((await request(base, "/api/insured/properties", { nome: "Test" })).status, 403);
      assert.equal((await request(base, "/api/agent", { question: "test" })).status, 503);
      const answer = await request(base, "/api/perspectives/segurado/agent", { question: "Qual risco?", snapshotGeneratedAt: insured.generatedAt });
      assert.equal(answer.status, 200); const summary = await answer.json();
      assert.match(summary.answer, /determinística/); assert(!summary.answer.includes("Cliente B"));
      assert.equal((await request(base, "/api/perspectives/segurado/agent", { question: "test", contextPropertyId: "demo_portfolio_pocone" })).status, 404);
      assert.equal((await request(base, "/api/perspectives/segurado/agent", { question: "test", snapshotGeneratedAt: "old" })).status, 409);
      for (const width of [390, 1366, 1440, 1920]) for (const perspective of ["seguradora", "segurado"]) {
        const page = await browser.newPage({ viewport: { width, height: 1000 } });
        const errors = []; page.on("pageerror", (error) => errors.push(error.message));
        const response = await page.goto(`${base}/${perspective}`, { waitUntil: "networkidle" });
        assert.equal(response.status(), 200);
        assert.equal(await page.getByTestId("farm-card").count(), perspective === "segurado" ? 2 : 4);
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `Overflow: ${width}/${perspective}`);
        await page.getByRole("region", { name: "Mapa do escopo" }).waitFor();
        if (perspective === "segurado") {
          await page.getByRole("button", { name: "Adicionar fazenda", exact: true }).click();
          await page.getByRole("status").filter({ hasText: "cadastro e persistência desabilitados" }).waitFor();
          assert.equal(await page.getByRole("form", { name: "Adicionar fazenda" }).count(), 0);
        }
        await page.screenshot({ path: `artifacts/vercel/${scenario}-${perspective}-${width}.png`, fullPage: true });
        await page.getByTestId("farm-card").first().getByRole("button").click();
        await page.getByRole("region", { name: "Detalhe da fazenda" }).waitFor();
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        await page.getByRole("button", { name: "Abrir Assistente de Risco" }).click();
        await page.getByRole("button", { name: "Quando esses dados foram atualizados?", exact: true }).click();
        await page.getByText(/Consulta determinística da captura/).waitFor();
        assert.deepEqual(errors, []);
        await page.close();
      }
      assert(!/ENOENT|uncaught|⨯/.test(logs), logs);
      console.log(`${scenario}: routes, scoped APIs, concurrent isolation, Copilot, read-only registration and 8 layouts passed`);
    } finally {
      server.kill(); await new Promise((resolve) => server.once("exit", resolve));
    }
  }
  assert.equal(implicitRequests, 0, "Production attempted implicit localhost Flask");
  console.log("No implicit localhost:5000 requests");
} finally { await browser.close(); trap.close(); }
