import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";

// Isolated loopback fixtures: no Firebase, production credentials or notification delivery.
const origin = "http://127.0.0.1:3001";
let patches = 0;
const stub = createServer(async (req, res) => {
  assert.equal(req.headers.authorization, "Bearer fixture-only-key");
  let body = "";
  for await (const chunk of req) body += chunk;
  res.setHeader("Content-Type", "application/json");
  if (req.method === "PATCH") {
    patches++;
    assert.equal(req.url, "/alertas/a1");
    res.end(JSON.stringify({ alert: { alertId: "a1", ...JSON.parse(body) } }));
  } else res.end(JSON.stringify({ items: [] }));
});
await new Promise((resolve, reject) => { stub.once("error", reject); stub.listen(5001, "127.0.0.1", resolve); });
const child = spawn(process.execPath, ["node_modules/next/dist/bin/next", "dev", "--hostname", "127.0.0.1", "--port", "3001"], {
  windowsHide: true, stdio: "pipe",
  env: { ...process.env, NODE_ENV: "development", SOMPO_ENABLE_ALERT_ACTIONS: "true", SOMPO_BACKEND_URL: "http://127.0.0.1:5001", SOMPO_BACKEND_API_KEY: "fixture-only-key" },
});
let output = "";
child.stdout.on("data", (data) => { output += data; });
child.stderr.on("data", (data) => { output += data; });
try {
  let ready = false;
  for (let i = 0; i < 60; i++) {
    if (child.exitCode !== null) throw new Error(`Dev server exited: ${output}`);
    try { ready = (await fetch(`${origin}/api/alerts`)).ok; } catch { /* startup */ }
    if (ready) break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  assert.equal(ready, true, "Isolated dev server must start");
  assert.equal((await (await fetch(`${origin}/api/alerts`)).json()).actionsEnabled, true);
  const patch = (requestOrigin, status = "acknowledged") => fetch(`${origin}/api/alerts`, {
    method: "PATCH", headers: { "Content-Type": "application/json", ...(requestOrigin ? { Origin: requestOrigin } : {}) },
    body: JSON.stringify({ alertId: "a1", status }),
  });
  assert.equal((await patch()).status, 403);
  assert.equal((await patch("http://other.invalid")).status, 403);
  assert.equal((await patch(origin, "open")).status, 400);
  const acknowledged = await patch(origin);
  assert.equal(acknowledged.status, 200);
  assert.equal((await acknowledged.json()).alert.status, "acknowledged");
  assert.equal((await patch(origin, "resolved")).status, 200);
  assert.equal(patches, 2, "Only valid same-origin writes reach the backend");
  console.log("PASS: enabled development BFF, server-side key, same-origin enforcement and allowed transitions.");
} finally {
  if (process.platform === "win32") {
    const stop = spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], { windowsHide: true, stdio: "ignore" });
    await new Promise((resolve) => stop.on("exit", resolve));
  } else child.kill();
  await new Promise((resolve) => stub.close(resolve));
}
