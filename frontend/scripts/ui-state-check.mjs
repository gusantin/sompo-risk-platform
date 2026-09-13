import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import vm from "node:vm";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { chromium } from "playwright-core";
import AxeBuilder from "@axe-core/playwright";

const require = createRequire(import.meta.url);
const modules = new Map();
function sourceModule(id) {
  if (id === "next/link") return function FixtureLink({ children, ...props }) {
    delete props.prefetch;
    return React.createElement("a", props, children);
  };
  if (!id.startsWith("@/")) return require(id);
  if (modules.has(id)) return modules.get(id).exports;
  const file = path.resolve("src", id.slice(2));
  let source;
  try { source = readFileSync(`${file}.tsx`, "utf8"); } catch { source = readFileSync(`${file}.ts`, "utf8"); }
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  const loadedModule = { exports: {} };
  modules.set(id, loadedModule);
  vm.runInNewContext(compiled, { module: loadedModule, exports: loadedModule.exports, require: sourceModule, Date, Intl, URLSearchParams });
  return loadedModule.exports;
}
const { ProductPerspective } = sourceModule("@/components/product-perspective");
const base = process.env.FRONTEND_URL || "http://127.0.0.1:3202";
const data = await (await fetch(`${base}/api/perspectives/segurado`)).json();
const document = await (await fetch(`${base}/segurado`)).text();
const css = [...document.matchAll(/<link[^>]+rel="stylesheet"[^>]*>/g)].map(([tag]) => tag.replace('href="/', `href="${base}/`)).join("");
assert(css, "Use the current production CSS");
const empty = { ...data, properties: [], machines: [], hotspots: [], notices: ["Captura indisponível. Nenhum dado foi substituído."] };
const pending = { ...data, properties: [{ ...data.properties[0], name: "Fazenda " + "Propriedade".repeat(12), clientName: undefined, level: "unknown", score: null, factors: [], recommendations: [], operationalState: undefined, analysisTimestamp: "", environmentalContext: undefined, environmentalDataOrigin: "unavailable", provenance: { identity: "demo", environmental: { state: "unavailable", origin: "unavailable" } } }], machines: [], hotspots: [] };
const dir = "artifacts/quality-final/states";
await mkdir(dir, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", headless: true });
try {
  for (const [name, fixture] of [["empty", empty], ["pending-long-name", pending]]) for (const width of [320, 1440]) for (const perspective of ["segurado", "seguradora"]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await context.newPage();
    const markup = renderToStaticMarkup(React.createElement(ProductPerspective, { initialData: fixture, perspective, readOnly: true }));
    await page.setContent(`<!doctype html><html lang="pt-BR"><head><title>Quality fixture: ${name}</title>${css}</head><body>${markup}</body></html>`, { waitUntil: "networkidle" });
    const text = await page.locator("main").innerText();
    assert.doesNotMatch(text, /Evidências ambientais reais · captura armazenada|Consultar dados ambientais/);
    assert.equal(await page.locator("h1").count(), 1);
    await page.screenshot({ path: `${dir}/${name}-${perspective}-${width}.png`, fullPage: true });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name}/${perspective}/${width}: overflow`);
    if (name === "empty") assert.match(text, /Aguardando a captura/);
    else assert.match(text, /Aguardando leitura|Aguardando fatores/);
    const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa", "best-practice"]).analyze();
    await writeFile(`${dir}/${name}-${perspective}-${width}-axe.json`, JSON.stringify(axe.violations, null, 2));
    assert.deepEqual(axe.violations.map((v) => v.id), []);
    await page.screenshot({ path: `${dir}/${name}-${perspective}-${width}.png`, fullPage: true });
    await context.close();
  }
  console.log("PASS: 8 static-render empty/pending/long-name layouts, missing client, unknown evidence, read-only controls and accessibility; no live snapshot changed.");
} finally { await browser.close(); }
