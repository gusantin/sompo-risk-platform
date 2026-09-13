import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import ts from "typescript";

const fixture = JSON.parse(await readFile("src/data/presentation-portfolio.json", "utf8"));
const source = await readFile("src/lib/backend.ts", "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
function loader(snapshot, response, configured = true) {
  let calls = 0;
  const loadedModule = { exports: {} };
  const require = (id) => {
    if (id === "server-only") return {};
    if (id === "@/data/presentation-portfolio.json") return snapshot;
    if (id === "@/lib/demo-data") return {};
    if (id === "@/lib/backend-config") return { backendUrl: () => configured ? "https://backend.example.test" : null, isPresentationDeployment: () => true };
    if (id === "node:fs/promises") return { readFile: () => { throw new Error("Production must not read local files"); } };
    throw new Error(`Unexpected import ${id}`);
  };
  vm.runInNewContext(compiled, { module: loadedModule, exports: loadedModule.exports, require, process: { env: {} }, structuredClone, Date, Intl, AbortSignal,
    fetch: async () => { calls++; return response; } });
  return { load: loadedModule.exports.loadPortfolioData, calls: () => calls };
}
const remote = structuredClone(fixture); remote.generatedAt = "2026-09-13T01:00:00Z";
const healthy = loader(fixture, Response.json(remote));
const result = await healthy.load(false, "seguradora");
assert.equal(result.backendAvailable, true); assert.equal(result.generatedAt, remote.generatedAt); assert.equal(healthy.calls(), 1);
for (const response of [Response.json({}), new Response("broken JSON"), new Response("unavailable", { status: 503 })]) {
  const failed = loader(fixture, response);
  const data = await failed.load(true, "segurado");
  assert.equal(data.backendAvailable, false); assert.equal(data.presentationMode, "snapshot"); assert.equal(data.properties.length, 2);
}
const unavailable = loader({}, null, false);
const empty = await unavailable.load(false, "seguradora");
assert.equal(empty.source, "unavailable"); assert.equal(empty.properties.length, 0); assert(empty.notices.length); assert.equal(unavailable.calls(), 0);
const offline = loader(fixture, null, false);
const portfolio = await offline.load(false, "seguradora");
for (const p of portfolio.properties) {
  const canonical = fixture.cases.find((c) => c.id === p.id);
  assert.equal(p.score, canonical.risk.score);
  assert.equal(p.provenance.environmental.acquiredAt, canonical.provenance.environmental.acquiredAt);
}
assert.equal(offline.calls(), 0);
console.log("Loader: healthy remote precedence, malformed/error fallback, failed snapshot unavailable, original scores/timestamps and zero local filesystem access passed");
