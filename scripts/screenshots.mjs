// Regenerates every PNG in docs/screenshots/ (call-*.png, app-*.png, full/app-*.png) from the current build.
//
// Usage (from the repo root, after `cd web && npm run build`):
//   node scripts/screenshots.mjs
//
// What it does, in order:
//   1. starts the API (.venv/bin/uvicorn) on a fresh temporary SQLite DB on API_PORT (default 8000; the web build bakes
//      in http://localhost:8000 unless NEXT_PUBLIC_API_BASE was set at build time) and the built family app
//      (`next start`) on WEB_PORT (default 3456, so it does not clash with a dev server on 3000);
//   2. family-app screens on the freshly seeded data (390x844 @2x first screen + full page);
//   3. elder call page: idle, hands-free rehearsal in progress / ended, typed call, acute emergency, non-acute
//      confirm question, and the no-speech-API fallback (these write calls, so they run after step 2);
//   4. stops the API and shoots the offline fallback (bundled fixtures);
//   5. stops both servers and deletes the temporary DB.
//
// Playwright is not a project dependency. The script uses PLAYWRIGHT_MODULE if set, else `playwright` if resolvable,
// else the newest cached copy in ~/.npm/_npx (e.g. from an earlier `npx playwright`). Chromium comes from the normal
// Playwright browser cache (~/Library/Caches/ms-playwright); nothing is downloaded.
// Env: API_PORT, WEB_PORT, CHAOBA_END_DATE (pin the seeded calendar), PLAYWRIGHT_MODULE, ONLY=app|call|offline.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(ROOT, "docs", "screenshots");
const API_PORT = Number(process.env.API_PORT ?? 8000);
const WEB_PORT = Number(process.env.WEB_PORT ?? 3456);
const API = `http://localhost:${API_PORT}`;
const WEB = `http://localhost:${WEB_PORT}`;
const ONLY = process.env.ONLY;
const require = createRequire(import.meta.url);

function loadPlaywright() {
  const tries = [];
  if (process.env.PLAYWRIGHT_MODULE) tries.push(process.env.PLAYWRIGHT_MODULE);
  tries.push("playwright");
  const npx = join(homedir(), ".npm", "_npx");
  if (existsSync(npx)) {
    const found = readdirSync(npx)
      .map((d) => join(npx, d, "node_modules", "playwright"))
      .filter((p) => existsSync(join(p, "package.json")))
      .map((p) => ({ p, v: JSON.parse(readFileSync(join(p, "package.json"), "utf8")).version }))
      .sort((a, b) => b.v.localeCompare(a.v, undefined, { numeric: true }));
    tries.push(...found.map((f) => f.p));
  }
  for (const t of tries) {
    try { return require(t); } catch { /* next */ }
  }
  throw new Error("Playwright not found: set PLAYWRIGHT_MODULE=/path/to/node_modules/playwright");
}
const { chromium } = loadPlaywright();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(url, ms = 60000) {
  const t = Date.now();
  while (Date.now() - t < ms) {
    try { if ((await fetch(url)).ok) return; } catch { /* not up yet */ }
    await sleep(500);
  }
  throw new Error(`timeout waiting for ${url}`);
}
const procs = [];
function start(cmd, args, opts) {
  const p = spawn(cmd, args, { stdio: ["ignore", "ignore", "pipe"], ...opts });
  let err = "";
  p.stderr.on("data", (d) => { err = (err + d).slice(-4000); });
  p.on("exit", (code) => { if (code && !p.killedByUs) console.error(`${cmd} exited ${code}\n${err}`); });
  procs.push(p);
  return p;
}
function stop(p) { if (p && p.exitCode === null) { p.killedByUs = true; p.kill("SIGTERM"); } }
process.on("exit", () => procs.forEach(stop));

// ---------------------------------------------------------------- servers
const dbDir = mkdtempSync(join(tmpdir(), "chaoba-shots-"));
const api = start(join(ROOT, ".venv", "bin", "uvicorn"), ["chaoba.server.app:app", "--port", String(API_PORT)], {
  cwd: ROOT, env: { ...process.env, CHAOBA_DB: join(dbDir, "shots.db"), CHAOBA_DEMO: "1" },
});
const web = start(join(ROOT, "web", "node_modules", ".bin", "next"), ["start", "-p", String(WEB_PORT)], {
  cwd: join(ROOT, "web"), env: { ...process.env },
});
await waitFor(`${API}/api/health`);
await waitFor(`${WEB}/manifest.webmanifest`);
mkdirSync(join(OUT, "full"), { recursive: true });

const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
const problems = [];

async function appShot(name, path, lang, theme) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, colorScheme: theme });
  await ctx.addInitScript(([l, t]) => {
    try { localStorage.setItem("cb-lang", l); localStorage.setItem("cb-theme", t); } catch { /* ignore */ }
  }, [lang, theme]);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => problems.push(`${name}: ${e.message}`));
  await page.goto(WEB + path, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(800);
  await page.screenshot({ path: join(OUT, `${name}.png`) });
  let h = await page.evaluate(() => document.scrollingElement.scrollHeight);
  for (let i = 0; i < 4; i++) {
    await page.setViewportSize({ width: 390, height: h });
    await page.waitForTimeout(400);
    const h2 = await page.evaluate(() => document.scrollingElement.scrollHeight);
    if (h2 === h) break;
    h = h2;
  }
  await page.screenshot({ path: join(OUT, "full", `${name}.png`) });
  const overflow = await page.evaluate(() => document.scrollingElement.scrollWidth > window.innerWidth);
  if (overflow) problems.push(`${name}: horizontal overflow`);
  console.log(`app  ${name} (${h}px)`);
  await ctx.close();
}

const APP = [
  ["app-today-vi-light", "/?elder=hanh", "vi", "light"],
  ["app-today-vi-dark", "/?elder=hanh", "vi", "dark"],
  ["app-today-en-light", "/?elder=hanh", "en", "light"],
  ["app-today-tu-yellow-vi-light", "/?elder=tu", "vi", "light"],
  ["app-today-tu-yellow-en-dark", "/?elder=tu", "en", "dark"],
  ["app-trends-vi-light", "/trends?elder=hanh", "vi", "light"],
  ["app-trends-en-dark", "/trends?elder=hanh", "en", "dark"],
  ["app-trends-control-en-light", "/trends?elder=control", "en", "light"],
  ["app-alerts-vi-light", "/alerts?elder=hanh", "vi", "light"],
  ["app-alerts-en-dark", "/alerts?elder=hanh", "en", "dark"],
  ["app-dmaic-vi-light", "/dmaic?elder=hanh", "vi", "light"],
  ["app-dmaic-en-light", "/dmaic?elder=hanh", "en", "light"],
  ["app-dmaic-tu-en-dark", "/dmaic?elder=tu", "en", "dark"],
  ["app-privacy-vi-light", "/privacy?elder=hanh", "vi", "light"],
  ["app-privacy-en-dark", "/privacy?elder=hanh", "en", "dark"],
  ["app-call-vi-light", "/call?elder=hanh", "vi", "light"],
  ["app-screen-vi", "/screen?elder=hanh", "vi", "light"],
  ["app-screen-en", "/screen?elder=hanh", "en", "light"],
];
const OFFLINE = [
  ["app-offline-today-vi-light", "/?elder=hanh", "vi", "light"],
  ["app-offline-trends-en-light", "/trends?elder=hanh", "en", "light"],
];

// ---------------------------------------------------------------- elder call page
async function callPage({ noSpeech = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: "vi-VN" });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => problems.push(`call: ${e.message}`));
  page.on("crash", () => console.error("call page crashed"));
  page.on("close", () => console.error("call page closed"));
  if (noSpeech) await page.addInitScript(() => {
    delete window.SpeechRecognition; delete window.webkitSpeechRecognition;
    delete window.speechSynthesis; delete window.SpeechSynthesisUtterance;
  });
  return { ctx, page };
}
const ended = (page, ms) => page.waitForFunction(() => document.getElementById("result").style.display === "block", null, { timeout: ms });
const typedReady = (page) => page.waitForFunction(() => document.getElementById("status").textContent.includes("Gõ câu trả lời")
  || document.getElementById("result").style.display === "block", null, { timeout: 30000 });
async function say(page, text) {
  await typedReady(page);
  await page.fill("#typedInput", text);
  const resp = page.waitForResponse((r) => r.url().includes("/turns"));
  await page.click("#typedSend");
  return (await resp).json();
}
const shot = (page, name, fullPage = false) => page.screenshot({ path: join(OUT, `${name}.png`), fullPage }).then(() => console.log(`call ${name}`));

async function callShots() {
  // 1. idle + hands-free rehearsal (Bà Hạnh). A rehearsal is stored as simulated and never scored.
  {
    const { ctx, page } = await callPage();
    await page.goto(`${API}/call?elder=hanh&sim=1`);
    await page.waitForFunction(() => document.getElementById("who").textContent === "Bà Hạnh");
    await shot(page, "call-idle");
    await page.click("#big");
    await page.waitForFunction(() => document.querySelectorAll(".bubble").length >= 9, null, { timeout: 200000 });
    await shot(page, "call-sim-in-progress");
    await ended(page, 400000);
    await page.waitForTimeout(500);
    const result = await page.$eval("#result", (e) => e.innerText);
    if (!/Dữ liệu mô phỏng|Diễn tập/.test(result) || /Cuộc gọi thật/.test(result)) problems.push(`call-sim-ended: rehearsal label missing: ${result.slice(0, 200)}`);
    await shot(page, "call-sim-ended", true);
    await ctx.close();
  }
  // 2. typed call (Ông Tư), shown mid-call and at the end.
  {
    const { ctx, page } = await callPage();
    await page.goto(`${API}/call?elder=tu&tts=0`);
    await page.waitForFunction(() => document.getElementById("who").textContent === "Ông Tư");
    await page.click("#typeBtn");
    await page.click("#big");
    const lines = ["Dạ được con, tui đang rảnh.", "Đêm qua tui ngủ cũng ngon.", "Sáng nay tui ăn hủ tiếu.",
      "Trong người cũng khỏe.", "Ờ để coi, tui quên rồi.", "À cờ tướng, tui mê cờ tướng lắm.",
      "Hồi trẻ tui dạy Văn ở trường Lê Quý Đôn ba chục năm.", "Học trò cũ hay về thăm tui lắm.",
      "Tết rồi tụi nó về đông lắm.", "Vui lắm con.", "Ừ chào con."];
    for (const l of lines) {
      await typedReady(page);
      if (await page.$eval("#result", (e) => e.style.display === "block")) break;
      await say(page, l);
      if (l.startsWith("Sáng nay")) { await page.waitForTimeout(400); await shot(page, "call-typed"); }
    }
    await ended(page, 30000);
    await page.waitForTimeout(500);
    await shot(page, "call-typed-ended", true);
    await ctx.close();
  }
  // 3. no speech APIs (graceful fallback to typing) + acute emergency (Ông Bảy).
  {
    const { ctx, page } = await callPage({ noSpeech: true });
    await page.goto(`${API}/call?elder=control`);
    await page.waitForFunction(() => document.getElementById("who").textContent === "Ông Bảy");
    await shot(page, "call-no-speech-apis");
    await page.click("#big");
    await say(page, "Dạ được con");
    await say(page, "Tui té hổng dậy được");
    await page.waitForFunction(() => getComputedStyle(document.getElementById("banner")).display === "block", null, { timeout: 15000 });
    await ended(page, 30000);
    await page.waitForTimeout(500);
    await shot(page, "call-emergency");
    await ctx.close();
  }
  await fetch(`${API}/api/demo/reset?elder=control`, { method: "POST" });
  // 4. non-acute past event: one confirm question, no 115.
  {
    const { ctx, page } = await callPage();
    await page.goto(`${API}/call?elder=control&tts=0`);
    await page.waitForFunction(() => document.getElementById("who").textContent === "Ông Bảy");
    await page.click("#typeBtn");
    await page.click("#big");
    await say(page, "Dạ được con");
    await say(page, "Hôm qua tui hơi tức ngực");
    await typedReady(page);
    await page.waitForTimeout(400);
    const last = await page.$$eval(".bubble.agent", (b) => b.at(-1)?.innerText ?? "");
    if (!/đang đau|chảy máu/.test(last)) problems.push(`call-non-acute-confirm: unexpected question: ${last}`);
    await shot(page, "call-non-acute-confirm");
    await ctx.close();
  }
  await fetch(`${API}/api/demo/reset?elder=control`, { method: "POST" });
}

try {
  if (!ONLY || ONLY === "app") for (const s of APP) await appShot(...s);
  if (!ONLY || ONLY === "call") await callShots();
  if (!ONLY || ONLY === "offline") {
    stop(api);
    await sleep(1500);
    for (const s of OFFLINE) await appShot(...s);
  }
} finally {
  await browser.close();
  procs.forEach(stop);
  rmSync(dbDir, { recursive: true, force: true });
}
if (problems.length) { console.error("PROBLEMS:\n" + problems.join("\n")); process.exit(1); }
console.log(`screenshots written to ${OUT}`);
