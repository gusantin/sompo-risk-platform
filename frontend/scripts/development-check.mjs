import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import path from "node:path";

// This server has no real backend or credentials. Creation is intercepted in the browser.
const env = { ...process.env, NODE_ENV: "development", SOMPO_BACKEND_URL: "http://127.0.0.1:59999", SOMPO_BACKEND_API_KEY: "fixture-only-key", SOMPO_DEMO_SCENARIO_PATH: path.resolve("artifacts/demo-scenario.json"), FRONTEND_URL: "http://127.0.0.1:3214", TEST_CREATION_ENABLED: "1" };
delete env.VERCEL;
const server = spawn(process.execPath, ["node_modules/next/dist/bin/next", "dev", "--hostname", "127.0.0.1", "--port", "3214"], { env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
let logs = "";
server.stdout.on("data", (data) => { logs += data; });
server.stderr.on("data", (data) => { logs += data; });
try {
  for (let i = 0; i < 200 && !logs.includes("Ready"); i++) {
    assert.equal(server.exitCode, null, logs);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert(logs.includes("Ready"), logs);
  for (const script of ["perspective-check.mjs", "presentation-check.mjs"]) {
    const test = spawn(process.execPath, [`scripts/${script}`], { env, windowsHide: true, stdio: "inherit" });
    assert.equal(await new Promise((resolve) => test.once("exit", resolve)), 0, script);
  }
} finally {
  server.kill();
  await new Promise((resolve) => server.once("exit", resolve));
}
