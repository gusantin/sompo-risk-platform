import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { chromium } from "playwright-core";
import AxeBuilder from "@axe-core/playwright";

const base = process.env.FRONTEND_URL || "http://127.0.0.1:3216";
const dir = "artifacts/geographic";
await mkdir(dir, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", headless: true });
const results = [];
const zoomOnly = process.argv.includes("--zoom-only");
const sizes = zoomOnly ? [] : [[320, 800], [390, 844], [430, 932], [768, 1024], [1024, 768], [1366, 900], [1440, 900], [1920, 1080], [1366, 650], [844, 390]];

async function screenshot(page, name, suffix = "") {
  const path = `${dir}/${name}${suffix}.png`;
  if (name.includes("200-percent-zoom")) {
    // Native zoom uses physical viewport pixels. Avoid Playwright's CSS clip,
    // which can capture a blank region when the underlying page is scrolled.
    const session = await page.context().newCDPSession(page);
    const capture = await session.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(path, Buffer.from(capture.data, "base64"));
    await session.detach();
  } else await page.screenshot({ path });
}

async function inspect(page, name) {
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  const body = dialog.getByRole("region", { name: /^Conteúdo de/ });
  const close = dialog.getByRole("button", { name: "Fechar painel" });
  if (name.includes("long-")) await dialog.locator("details").evaluateAll((nodes) => nodes.forEach((el) => { el.open = true; }));
  const geometry = await dialog.evaluate((el) => {
    const rect = el.getBoundingClientRect();
    const scroller = el.querySelector('[role="region"]');
    return { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom,
      viewport: [innerWidth, innerHeight], scrollWidth: scroller.scrollWidth, clientWidth: scroller.clientWidth,
      scrollHeight: scroller.scrollHeight, clientHeight: scroller.clientHeight };
  });
  assert(geometry.x >= 7 && geometry.y >= 7 && geometry.right <= geometry.viewport[0] - 7 && geometry.bottom <= geometry.viewport[1] - 7, `${name}: frame ${JSON.stringify(geometry)}`);
  assert(geometry.scrollWidth <= geometry.clientWidth + 1, `${name}: horizontal content overflow ${JSON.stringify(geometry)}`);
  for (const score of await dialog.locator(".geographic-state-property > div:last-child > strong").all()) {
    assert(await score.evaluate((el) => el.getBoundingClientRect().height <= parseFloat(getComputedStyle(el).lineHeight) + 1), `${name}: risk score must remain on one line`);
  }
  assert.equal(await page.locator("body").evaluate((el) => getComputedStyle(el).overflow), "hidden", "Modal locks page scroll");
  await body.focus();
  await page.keyboard.press("End");
  await page.waitForTimeout(150);
  const scroll = await body.evaluate((el) => ({ top: el.scrollTop, height: el.clientHeight, total: el.scrollHeight }));
  assert(scroll.top + scroll.height >= scroll.total - 2, `${name}: end reachable by keyboard`);
  const closeBox = await close.boundingBox();
  assert(closeBox.y >= 0 && closeBox.y + closeBox.height <= geometry.viewport[1], `${name}: close reachable at bottom`);
  await screenshot(page, name, "-bottom");
  await body.evaluate((el) => { el.scrollTop = 0; });
  await screenshot(page, name);
  if (/^(state|municipality-reference)-(390x844|1440x900)$/.test(name)) {
    const audit = await new AxeBuilder({ page }).include(".geographic-detail").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    await writeFile(`${dir}/${name}-axe.json`, JSON.stringify(audit.violations, null, 2));
    assert.deepEqual(audit.violations, [], `${name}: accessibility`);
  }
  await close.focus();
  await page.keyboard.press("Tab");
  assert(await page.locator(":focus").evaluate((el) => !!el.closest('[role="dialog"]')), "Focus remains inside modal");
  results.push({ name, geometry });
}

try {
  for (const [width, height] of sizes) {
    for (const long of [false, true]) {
      const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(`${base}/?mode=portfolio`, { waitUntil: "networkidle" });
      if (long) {
        // Browser-only stress fixture: no portfolio file or backend data is changed.
        const fixture = await (await page.request.get(`${base}/api/command-center?mode=portfolio`)).json();
        const original = fixture.properties[0];
        fixture.properties = Array.from({ length: 40 }, (_, index) => ({ ...original,
          id: `layout_stress_${index}`, name: `${original.name} — teste de nome extenso ${index}`,
          city: "MunicípioComNomeExtensoSemEspaços".repeat(6),
          contextDetails: Array.from({ length: 30 }, (_, i) => ({ label: `Contexto de teste ${i}`, value: original.contextDetails[0]?.value || "Conteúdo extenso para validação de layout" })),
        }));
        fixture.states = [{ ...fixture.states.find((state) => state.uf === original.uf), propertiesMonitored: 40 }];
        await page.route("**/api/command-center**", (route) => route.fulfill({ json: fixture }));
        await page.getByRole("button", { name: "Atualizar dados" }).click();
        await page.getByRole("button", { name: /Ver carteira em/ }).first().waitFor();
      }
      const state = page.getByRole("button", { name: /Ver carteira em/ }).first();
      await state.click();
      const prefix = `${long ? "long-" : ""}${width}x${height}`;
      await inspect(page, `state-${prefix}`);
      // Selecting the municipal reference/property from the state replaces its detail.
      await page.getByRole("dialog").getByRole("button").filter({ hasText: /Fazenda/ }).first().click();
      assert.equal(await page.getByRole("dialog").count(), 1);
      await inspect(page, `municipality-reference-${prefix}`);
      await page.keyboard.press("Escape");
      await page.getByRole("dialog").waitFor({ state: "detached" });
      await page.waitForTimeout(100);
      assert(await state.evaluate((el) => el === document.activeElement), "State-to-property close returns to state trigger");
      assert.notEqual(await page.locator("body").evaluate((el) => getComputedStyle(el).overflow), "hidden");
      if (!long && await page.getByRole("button", { name: /Ver carteira em/ }).count() > 1) {
        const anotherState = page.getByRole("button", { name: /Ver carteira em/ }).last();
        const label = await anotherState.getAttribute("aria-label");
        await anotherState.click();
        await page.getByRole("dialog", { name: label.replace("Ver carteira em ", "") }).waitFor();
        assert.equal(await page.locator(".geographic-detail-scroll").evaluate((el) => el.scrollTop), 0);
        await page.keyboard.press("Escape");
      }
      const marker = page.getByRole("button", { name: /^Abrir Fazenda/ }).last();
      await marker.evaluate((el) => el.scrollIntoView({ block: "center" }));
      if (long) {
        // Stress fixture intentionally overlaps 40 markers at one coordinate.
        await marker.focus();
        await page.keyboard.press("Enter");
      } else await marker.click();
      await page.getByRole("dialog").getByRole("button", { name: "Fechar painel" }).click();
      await page.waitForTimeout(100);
      assert(await marker.evaluate((el) => el === document.activeElement), "Map interaction and focus restored");
      assert.deepEqual(errors, []);
      await context.close();
    }
  }
  // Real Chrome page zoom, configured only in a disposable test profile.
  const zoomContext = await chromium.launchPersistentContext(await mkdtemp(`${dir}/chrome-profile-`), {
    executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    headless: true, viewport: null, args: ["--window-size=1366,650"], reducedMotion: "reduce",
  });
  try {
    const zoom = await zoomContext.newPage();
    await zoom.goto("chrome://settings/appearance");
    await zoom.evaluate(() => new Promise((resolve) => chrome.settingsPrivate.setDefaultZoom(2, resolve)));
    await zoom.goto(`${base}/?mode=portfolio`, { waitUntil: "networkidle" });
    assert(await zoom.evaluate(() => devicePixelRatio === 2 && innerWidth < 700), "Native 200% page zoom applied");
    await zoom.getByRole("button", { name: /Ver carteira em/ }).first().click();
    await inspect(zoom, "state-200-percent-zoom");
    await zoom.getByRole("dialog").getByRole("button").filter({ hasText: /Fazenda/ }).first().click();
    await inspect(zoom, "municipality-reference-200-percent-zoom");
  } finally { await zoomContext.close(); }
  await writeFile(`${dir}/${zoomOnly ? "zoom-results" : "results"}.json`, JSON.stringify(results, null, 2));
  console.log(`PASS: ${results.length} geographic detail cases, keyboard scrolling, focus return, viewport containment; screenshots in ${dir}`);
} finally { await browser.close(); }
