import { mkdir } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";

const executablePath = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const baseURL = process.env.FRONTEND_URL || "http://127.0.0.1:3000";
const outputDir = path.resolve("artifacts");
const sizes = [
  { width: 1366, height: 768, name: "1366x768" },
  { width: 1920, height: 1080, name: "1920x1080" },
];

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const results = [];

try {
  for (const size of sizes) {
    const page = await browser.newPage({ viewport: size, deviceScaleFactor: 1 });
    const errors = [];
    page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(baseURL, { waitUntil: "networkidle", timeout: 30_000 });
    await page.getByRole("heading", { name: "Visão operacional do piloto" }).waitFor();
    const metrics = await page.evaluate(() => ({
      bodyWidth: document.body.scrollWidth,
      viewportWidth: window.innerWidth,
      bodyHeight: document.body.scrollHeight,
      hasHydrationMarker: document.body.innerText.toLowerCase().includes("hydration"),
    }));
    await page.screenshot({ path: path.join(outputDir, `command-center-${size.name}.png`), fullPage: true });
    await page.getByRole("button", { name: /Abrir detalhes de/i }).first().click();
    await page.getByText("Por que esta propriedade exige atenção?").waitFor();
    await page.waitForTimeout(750);
    await page.screenshot({ path: path.join(outputDir, `drawer-${size.name}.png`) });
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: /Ver carteira em/i }).first().click();
    await page.getByText(/não é risco territorial/).waitFor();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: /Abrir (evento|alerta):/i }).first().click();
    await page.getByText(/Evento · algo aconteceu|Alerta · precisa de atenção/).waitFor();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: /Abrir foco/i }).first().click();
    await page.getByRole("heading", { name: "Focos recentes" }).waitFor();
    await page.keyboard.press("Escape");
    results.push({ viewport: size.name, errors, ...metrics });
    await page.close();
  }
} finally {
  await browser.close();
}

for (const result of results) console.log(JSON.stringify(result));
if (results.some((result) => result.errors.length || result.bodyWidth > result.viewportWidth || result.hasHydrationMarker)) process.exitCode = 1;
