import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { mkdir } from "node:fs/promises";
const base = process.env.FRONTEND_URL || "http://127.0.0.1:3100";
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", headless: true });
await mkdir("artifacts", { recursive: true });
try {
  for (const width of [390, 1366, 1440, 1920]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const response = await page.request.get(`${base}/api/command-center?mode=demo`);
    assert.equal(response.status(), 200);
    const data = await response.json();
    assert.equal(data.source, "demo");
    assert.equal(data.properties.length, 1, "Use seed_demo --export, not the built-in showcase");
    assert.equal(data.machines.length, 1);
    assert.ok(data.demoAlerts.length > 0, "Use combined_critical for this presentation smoke");
    assert.ok(data.machines[0].recommendations.length > 0);
    await page.goto(`${base}/?mode=demo`, { waitUntil: "networkidle" });
    for (const perspective of ["SOMPO", "Cliente"]) {
      await page.getByRole("button", { name: perspective, exact: true }).click();
      await page.getByRole("heading", { name: perspective === "SOMPO" ? "SOMPO Control Center" : "Client Operations Center", exact: true }).waitFor();
      assert.ok(await page.getByLabel("Fila de prioridades").locator("li").count());
      assert.ok(await page.locator("article").count());
      assert.equal(await page.getByRole("button", { name: "Reconhecer", exact: true }).first().isDisabled(), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.screenshot({ path: `artifacts/presentation-${perspective}-${width}.png`, fullPage: true });
    }
    assert.deepEqual(errors, []);
    await page.close();
    console.log(`PASS ${width}px: exported DEMO, priorities, recommendations, alerts, read-only actions, SOMPO and client`);
  }
} finally { await browser.close(); }
