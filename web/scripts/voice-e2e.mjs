// End-to-end check of the optional Gemini Live voice engine (/screen talk view and the /call page) against a running
// API started with the OFFLINE FAKE Gemini session (CHAOBA_GEMINI_FAKE=1) and the web app:
//
//   CHAOBA_GEMINI_FAKE=1 CHAOBA_DB=/tmp/x.db .venv/bin/uvicorn chaoba.server.app:app --port 8150
//   cd web && NEXT_PUBLIC_API_BASE=http://localhost:8150 npx next dev -p 3150
//   WEB=http://localhost:3150 API=http://localhost:8150 node web/scripts/voice-e2e.mjs
//
// NEVER makes a sound: Chromium runs with --mute-audio; every page uses ?mute=1 (no TTS, no audio output: Gemini audio
// is only timed) and ?tts=0; speechSynthesis.speak is a no-op and AudioContext / webkitAudioContext are replaced by a
// constructor that throws (any attempt is counted and fails the run). Elder turns are simulated (?sim=1) or typed
// (?typed=1), so no microphone is used. The fake streams digital silence frames + transcripts.
// Checks: badge "Giọng: Gemini Live", a full call reaches the end and today's day is updated; emergency path (typed);
// /call page full call; WebSocket failure -> seamless fallback to the browser voice with a status note.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { join } from "node:path";

const WEB = (process.env.WEB ?? "http://localhost:3150").replace(/\/$/, "");
const API = (process.env.API ?? "http://localhost:8150").replace(/\/$/, "");
const require = createRequire(import.meta.url);

function loadPlaywright() {
  const tries = [process.env.PLAYWRIGHT_MODULE, "playwright"].filter(Boolean);
  const npx = join(homedir(), ".npm", "_npx");
  if (existsSync(npx)) {
    tries.push(
      ...readdirSync(npx)
        .map((d) => join(npx, d, "node_modules", "playwright"))
        .filter((p) => existsSync(join(p, "package.json")))
        .map((p) => ({ p, v: JSON.parse(readFileSync(join(p, "package.json"), "utf8")).version }))
        .sort((a, b) => b.v.localeCompare(a.v, undefined, { numeric: true }))
        .map((x) => x.p),
    );
  }
  for (const t of tries) {
    try {
      return require(t);
    } catch {
      /* next */
    }
  }
  throw new Error("Playwright not found: set PLAYWRIGHT_MODULE=/path/to/node_modules/playwright");
}
const { chromium } = loadPlaywright();

const failures = [];
const pageErrors = [];
function check(cond, msg) {
  console.log(`${cond ? "ok  " : "FAIL"} ${msg}`);
  if (!cond) failures.push(msg);
}
const H = { "Content-Type": "application/json", "X-Actor": "e2e", "X-Role": "primary" };
const api = async (path, init) => (await fetch(API + path, { headers: H, ...init })).json();

const SILENCE = () => {
  // This page can never make a sound: no speech synthesis, no Web Audio output at all.
  window.__audioCtxAttempts = 0;
  try {
    if (window.speechSynthesis) window.speechSynthesis.speak = () => {};
  } catch {
    /* ignore */
  }
  const Blocked = function () {
    window.__audioCtxAttempts += 1;
    throw new Error("AudioContext blocked in tests");
  };
  window.AudioContext = Blocked;
  window.webkitAudioContext = Blocked;
};

const cfg = await api("/api/voice/config");
if (!cfg.gemini?.available || cfg.gemini.mode !== "fake") {
  console.error(`voice-e2e: the API must run with CHAOBA_GEMINI_FAKE=1 (got ${JSON.stringify(cfg.gemini)})`);
  process.exit(2);
}

const browser = await chromium.launch({ args: ["--mute-audio", "--autoplay-policy=user-gesture-required"] });
process.on("exit", () => {
  browser.close().catch(() => {});
});

async function open(path, { blockWs = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 540, height: 960 }, permissions: [] });
  await ctx.addInitScript(SILENCE);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => pageErrors.push(`${path}: ${e.message}`));
  if (blockWs) await page.routeWebSocket(/\/ws\/voice\//, (ws) => ws.close({ code: 1011, reason: "e2e: blocked" }));
  await page.goto(path.startsWith("http") ? path : WEB + path, { waitUntil: "domcontentloaded" });
  if (!path.startsWith("http")) await page.waitForSelector('[data-testid="elder-screen"]');
  await page.waitForTimeout(800); // let React hydrate before clicking
  return { ctx, page };
}
const audioAttempts = (page) => page.evaluate(() => window.__audioCtxAttempts);
const d0 = new Date();
const today = `${d0.getFullYear()}-${String(d0.getMonth() + 1).padStart(2, "0")}-${String(d0.getDate()).padStart(2, "0")}`;

// ---------------------------------------------------------------- 1. /screen: full call on Gemini Live (fake)
{
  await fetch(`${API}/api/demo/reset?elder=hanh`, { method: "POST" });
  const before = await api("/api/elders/hanh/today");
  const { ctx, page } = await open("/screen?elder=hanh&kiosk=1&sim=1&fast=1&tts=0&mute=1&engine=gemini");
  await page.waitForSelector('[data-testid="btn-talk"]');
  await page.click('[data-testid="btn-talk"]');
  await page.waitForSelector('[data-testid="engine-badge"][data-engine="gemini"][data-state="live"]', { timeout: 15000 });
  check((await page.textContent('[data-testid="engine-badge"]')).includes("Gemini Live"), "screen: badge 'Giọng: Gemini Live'");
  await page.waitForSelector('[data-testid="engine-hint"]', { timeout: 5000 });
  check((await page.textContent('[data-testid="engine-hint"]')).includes("nói chen vào"), "screen: barge-in hint shown");
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="captions"] > div').length >= 3, null, { timeout: 60000 });
  await page.waitForSelector('[data-testid="notice"]', { timeout: 240000 });
  const after = await api("/api/elders/hanh/today");
  check(after.date === today && after.day >= before.day && (after.calls ?? 0) >= 1, `screen: call ended and today's day updated (day ${after.day}, calls ${after.calls})`);
  check(after.rehearsal === true, "screen: simulated call saved as rehearsal");
  check((await audioAttempts(page)) === 0, "screen: no AudioContext was ever created (muted)");
  await ctx.close();
}

// ---------------------------------------------------------------- 2. /screen: emergency (typed) on Gemini Live
{
  await fetch(`${API}/api/demo/reset?elder=hanh`, { method: "POST" });
  const { ctx, page } = await open("/screen?elder=hanh&kiosk=1&typed=1&fast=1&tts=0&mute=1&engine=gemini");
  await page.waitForSelector('[data-testid="btn-talk"]');
  await page.click('[data-testid="btn-talk"]');
  await page.waitForSelector('[data-testid="engine-badge"][data-state="live"]', { timeout: 15000 });
  await page.waitForSelector('[data-testid="typed-input"]:not([disabled])', { timeout: 30000 });
  await page.fill('[data-testid="typed-input"]', "Sáng nay tôi bị tức ngực quá");
  await page.keyboard.press("Enter");
  await page.waitForSelector('[data-testid="emergency"]', { timeout: 20000 });
  check((await page.textContent('[data-testid="emergency"]')).includes("Đã báo cho chị Lan"), "emergency: red screen 'Đã báo cho chị Lan'");
  const alerts = await api("/api/elders/hanh/alerts");
  check(alerts.some((a) => a.type === "emergency" && a.severity === "red"), "emergency: red alert for the family");
  check((await audioAttempts(page)) === 0, "emergency: no AudioContext created");
  await ctx.close();
}

// ---------------------------------------------------------------- 3. /call page: full call on Gemini Live (fake)
{
  await fetch(`${API}/api/demo/reset?elder=tu`, { method: "POST" });
  // /call is served by the API itself (chaoba/server/static/call.html)
  const { ctx, page } = await open(`${API}/call?elder=tu&engine=gemini&sim=1&mute=1&tts=0`);
  await page.click("#big");
  await page.waitForSelector('#engineBadge[data-engine="gemini"][data-state="live"]', { timeout: 15000 });
  check((await page.textContent("#engineBadge")).includes("Gemini Live"), "/call: badge 'Giọng: Gemini Live'");
  check(await page.isVisible("#geminiPrivacy"), "/call: Gemini privacy note shown");
  await page.waitForSelector("#result", { state: "visible", timeout: 240000 });
  const t = await api("/api/elders/tu/today");
  check(t.date === today && (t.calls ?? 0) >= 1, `/call: call saved for today (day ${t.day})`);
  check((await audioAttempts(page)) === 0, "/call: no AudioContext created");
  await ctx.close();
}

// ---------------------------------------------------------------- 4. /call page: WebSocket fails -> browser voice
{
  await fetch(`${API}/api/demo/reset?elder=control`, { method: "POST" });
  const { ctx, page } = await open(`${API}/call?elder=control&engine=gemini&sim=1&mute=1&tts=0`, { blockWs: true });
  await page.click("#big");
  await page.waitForSelector('#engineBadge[data-state="fallback"]', { timeout: 15000 });
  check((await page.textContent("#engineBadge")).includes("trình duyệt"), "fallback: badge switched to 'Giọng: trình duyệt · dự phòng'");
  check(((await page.textContent("#engineNote")) || "").length > 0, "fallback: status note shown");
  await page.waitForSelector("#result", { state: "visible", timeout: 240000 });
  const t = await api("/api/elders/control/today");
  check((t.calls ?? 0) >= 1, "fallback: the same call finished on the browser pipeline");
  await ctx.close();
}

// ---------------------------------------------------------------- 5. /screen: WebSocket fails -> browser voice
{
  await fetch(`${API}/api/demo/reset?elder=tu`, { method: "POST" });
  const { ctx, page } = await open("/screen?elder=tu&kiosk=1&sim=1&fast=1&tts=0&mute=1&engine=gemini", { blockWs: true });
  await page.waitForSelector('[data-testid="btn-talk"]');
  await page.click('[data-testid="btn-talk"]');
  await page.waitForSelector('[data-testid="engine-badge"][data-state="fallback"]', { timeout: 15000 });
  check(await page.isVisible('[data-testid="engine-note"]'), "screen fallback: status note shown");
  await page.waitForSelector('[data-testid="notice"]', { timeout: 240000 });
  check(((await api("/api/elders/tu/today")).calls ?? 0) >= 1, "screen fallback: call finished on the browser voice");
  await ctx.close();
}

check(pageErrors.length === 0, `no page errors ${pageErrors.length ? JSON.stringify(pageErrors.slice(0, 5)) : ""}`);
await browser.close();
console.log(failures.length ? `\n${failures.length} check(s) failed` : "\nall voice e2e checks passed");
process.exit(failures.length ? 1 : 0);
