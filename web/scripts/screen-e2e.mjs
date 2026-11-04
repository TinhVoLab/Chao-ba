// End-to-end check of the elder standing screen (/screen) against a running API + web app, with screenshots.
//
//   WEB=http://localhost:3000 API=http://localhost:8000 node web/scripts/screen-e2e.mjs
//
// Never makes a sound: Chromium runs with --mute-audio, every page uses ?tts=0 (captions only) and
// speechSynthesis.speak is replaced by a no-op before any page script runs. Conversations use ?sim=1 (scripted
// elder) or ?typed=1 (typed answers), so no microphone is needed. Calls POST /api/demo/reset?elder=… first.
// Writes docs/screenshots/screen-*.png (1080×1920 = 540×960 @2x, and 390×844 @2x). Exits 1 on any failed check.
// Playwright is not a dependency: PLAYWRIGHT_MODULE, else `playwright`, else the newest copy in ~/.npm/_npx.
import { existsSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const OUT = join(ROOT, "docs", "screenshots");
const WEB = (process.env.WEB ?? "http://localhost:3000").replace(/\/$/, "");
const API = (process.env.API ?? "http://localhost:8000").replace(/\/$/, "");
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
const consoleErrors = [];
function check(cond, msg) {
  console.log(`${cond ? "ok  " : "FAIL"} ${msg}`);
  if (!cond) failures.push(msg);
}
const ELDER_H = { "Content-Type": "application/json", "X-Actor": "e2e", "X-Role": "primary" };
const api = async (path, init) => (await fetch(API + path, { headers: ELDER_H, ...init })).json();

const SILENCE = () => {
  // Belt and braces on top of ?tts=0 and --mute-audio: this page can never speak.
  try {
    if (window.speechSynthesis) {
      window.speechSynthesis.speak = () => {};
    }
  } catch {
    /* ignore */
  }
};

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ args: ["--mute-audio", "--autoplay-policy=user-gesture-required"] });
process.on("exit", () => {
  browser.close().catch(() => {});
});

async function open(path, viewport = { width: 540, height: 960 }, { allowNetErrors = false } = {}) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2, permissions: [] });
  await ctx.addInitScript(SILENCE);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => consoleErrors.push(`${path}: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (allowNetErrors && /Failed to load resource|ERR_CONNECTION_REFUSED|Failed to fetch/i.test(m.text())) return;
    consoleErrors.push(`${path}: ${m.text()}`);
  });
  const sep = path.includes("?") ? "&" : "?";
  await page.goto(`${WEB}${path}${sep}tts=0&api=${encodeURIComponent(API)}`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForSelector('[data-testid="elder-screen"]');
  await page.waitForTimeout(500);
  return { ctx, page };
}
const shot = (page, name) => page.screenshot({ path: join(OUT, `screen-${name}.png`) });
async function noScroll(page, label) {
  const o = await page.evaluate(() => ({
    v: document.scrollingElement.scrollHeight > window.innerHeight + 1,
    h: document.scrollingElement.scrollWidth > window.innerWidth + 1,
  }));
  check(!o.v && !o.h, `${label}: no page scrolling`);
}
async function noClipping(page, label) {
  // Every visible text block inside the screen must fit (nothing pushed below the screen's bottom edge).
  const bad = await page.evaluate(() => {
    const root = document.querySelector('[data-testid="elder-screen"]').getBoundingClientRect();
    return [...document.querySelectorAll('[data-testid="elder-screen"] button, [data-testid="elder-screen"] p')]
      .filter((el) => el.offsetParent && el.getBoundingClientRect().bottom > root.bottom + 1)
      .map((el) => el.textContent.slice(0, 40));
  });
  check(bad.length === 0, `${label}: nothing below the screen edge ${bad.length ? JSON.stringify(bad) : ""}`);
}

const d0 = new Date();
const today = `${d0.getFullYear()}-${String(d0.getMonth() + 1).padStart(2, "0")}-${String(d0.getDate()).padStart(2, "0")}`;
await fetch(`${API}/api/demo/reset?elder=hanh`, { method: "POST" });

// ---------------------------------------------------------------- 1. idle (1080×1920)
{
  const { ctx, page } = await open("/screen?elder=hanh&kiosk=1&fast=1");
  check(/\d\d:\d\d/.test(await page.textContent('[data-testid="clock"]')), "idle: clock shows the time");
  check((await page.textContent('[data-testid="family-message"]')).includes("Lan"), "idle: family message from Lan");
  check(await page.isVisible('[data-testid="btn-talk"]'), "idle: talk button");
  check((await page.textContent('[data-testid="btn-video"]')).includes("Gọi con Lan"), "idle: 'Gọi con Lan' button");
  const small = await page.evaluate(() =>
    [...document.querySelectorAll('[data-testid="elder-screen"] *')]
      .filter((el) => el.childNodes.length && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))
      .filter((el) => el.offsetParent)
      .map((el) => parseFloat(getComputedStyle(el).fontSize) * (1080 / document.querySelector('[data-testid="elder-screen"]').clientWidth))
      .filter((px) => px < 31.5).length,
  );
  check(small === 0, `idle: all text >= 32px at 1080 wide (${small} smaller)`);
  const targets = await page.evaluate(() => {
    const k = 1080 / document.querySelector('[data-testid="elder-screen"]').clientWidth;
    return [...document.querySelectorAll('[data-testid="elder-screen"] button')]
      .filter((b) => b.offsetParent)
      .map((b) => Math.min(b.offsetWidth, b.offsetHeight) * k)
      .filter((px) => px < 96).length;
  });
  check(targets === 0, `idle: all buttons >= 96px at 1080 wide (${targets} smaller)`);
  await noScroll(page, "idle");
  await noClipping(page, "idle");
  await shot(page, "idle");
  await ctx.close();
}

// ---------------------------------------------------------------- 2. conversation (sim) -> end -> day updated
{
  const before = await api("/api/elders/hanh/today");
  const { ctx, page } = await open("/screen?elder=hanh&kiosk=1&sim=1&fast=1");
  await page.click('[data-testid="btn-talk"]');
  await page.waitForSelector('[data-testid="captions"] >> text=Út Thương', { timeout: 15000 });
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="captions"] > div').length >= 3, null, { timeout: 30000 });
  await noClipping(page, "talk");
  await shot(page, "talk");
  await page.waitForSelector('[data-testid="notice"]', { timeout: 180000 });
  await shot(page, "talk-ended");
  const after = await api("/api/elders/hanh/today");
  check(after.date === today, `conversation: today's record is dated today (${after.date})`);
  check(after.day >= before.day && (after.calls ?? 1) >= 1 && after.rehearsal === true, `conversation: day ${after.day} saved as rehearsal (calls ${after.calls})`);
  await ctx.close();
}

// ---------------------------------------------------------------- 3. emergency via typed text
{
  const { ctx, page } = await open("/screen?elder=hanh&kiosk=1&typed=1&fast=1");
  await page.click('[data-testid="btn-talk"]');
  await page.waitForSelector('[data-testid="typed-input"]:not([disabled])', { timeout: 15000 });
  await shot(page, "talk-typed");
  await page.fill('[data-testid="typed-input"]', "tôi bị tức ngực");
  await page.keyboard.press("Enter");
  await page.waitForSelector('[data-testid="emergency"]', { timeout: 15000 });
  const txt = await page.textContent('[data-testid="emergency"]');
  check(txt.includes("Đã báo cho chị Lan"), "emergency: 'Đã báo cho chị Lan'");
  check((await page.getAttribute('[data-testid="call-115"]', "href")) === "tel:115", "emergency: Gọi 115 tel link");
  await page.waitForTimeout(800);
  await noClipping(page, "emergency");
  await shot(page, "emergency");
  const alerts = await api("/api/elders/hanh/alerts");
  check(alerts.some((a) => a.type === "emergency"), "emergency: alert raised for the family");
  await ctx.close();
}

// ---------------------------------------------------------------- 4. video call -> contact logged
{
  const { ctx, page } = await open("/screen?elder=hanh&kiosk=1&fast=1");
  await page.click('[data-testid="btn-video"]');
  await page.waitForSelector('[data-testid="video-state"] >> text=Đã kết nối', { timeout: 10000 });
  check((await page.textContent('[data-testid="video-call"]')).includes("Mô phỏng cuộc gọi video"), "video: labelled as simulated");
  await page.waitForTimeout(1200);
  await shot(page, "video");
  await page.click('[data-testid="btn-video-end"]');
  await page.waitForSelector('[data-testid="btn-talk"]');
  const c = await api("/api/elders/hanh/contacts");
  check(c.last && c.last.member_id === "lan" && c.last.date === today, "video: family contact logged (Lan, today)");

  // ---------------------------------------------------------------- 5. medication
  // The Yes / Not yet buttons appear only from 30 minutes before the dose; earlier the row just says "Chưa tới giờ".
  if (await page.isVisible("text=Đã uống thuốc")) {
    await page.click("text=Đã uống thuốc");
    await page.waitForSelector('[data-testid="med-done"]', { timeout: 5000 });
    const med = await api("/api/elders/hanh/medication_log");
    check(med.today[0].status === "taken" && med.entries.at(-1).source === "elder_screen", "medication: stored as taken by the elder screen");
    await page.waitForTimeout(400);
    await shot(page, "idle-med-taken");
  } else {
    check(await page.isVisible("text=Chưa tới giờ"), "medication: no answer buttons before the dose window");
  }

  // ---------------------------------------------------------------- 6. mood
  await page.click('[data-testid="tile-mood"]');
  await page.waitForSelector('[data-testid="mood-happy"]');
  await noClipping(page, "mood");
  await shot(page, "mood");
  await page.click('[data-testid="mood-happy"]');
  await page.waitForTimeout(600);
  const mood = await api("/api/elders/hanh/mood_checkin");
  check(mood.today && mood.today.mood === "happy", "mood: self-report stored");

  // ---------------------------------------------------------------- 7. game
  await page.click('[data-testid="btn-home"]');
  await page.click('[data-testid="tile-game"]');
  await page.waitForSelector('[data-testid="game-choice"]');
  await noClipping(page, "game");
  await shot(page, "game");
  for (let i = 0; i < 3; i++) {
    const choices = page.locator('[data-testid="game-choice"]');
    await choices.nth(i % 3).click();
    await page.waitForSelector('[data-testid="game-feedback"] >> text=/./');
    if (i === 0) await shot(page, "game-feedback");
    await page.click('[data-testid="game-next"]');
  }
  await page.waitForSelector('[data-testid="game-done"]');
  await page.waitForTimeout(500);
  const plays = await api("/api/elders/hanh/game_plays");
  check(plays.today >= 3, `game: ${plays.today} plays stored`);
  await ctx.close();
}

// ---------------------------------------------------------------- 8. phone size, English, desktop frame, offline
{
  const { ctx, page } = await open("/screen?elder=hanh&fast=1", { width: 390, height: 844 });
  await noScroll(page, "390x844 idle");
  await noClipping(page, "390x844 idle");
  await shot(page, "phone-idle");
  await page.click('[data-testid="btn-video"]');
  await page.waitForSelector('[data-testid="video-state"] >> text=Đã kết nối');
  await shot(page, "phone-video");
  await page.click('[data-testid="btn-video-end"]');
  await ctx.close();
}
{
  const { ctx, page } = await open("/screen?elder=tu&kiosk=1&lang=en&fast=1");
  check((await page.textContent('[data-testid="btn-talk"]')).includes("Talk to Út Thương"), "English: ?lang=en");
  await noClipping(page, "tu en");
  await shot(page, "idle-en-tu");
  await ctx.close();
}
{
  const { ctx, page } = await open("/screen?elder=control&kiosk=1&fast=1");
  await noClipping(page, "control");
  await shot(page, "idle-control");
  await ctx.close();
}
{
  const { ctx, page } = await open("/screen?elder=hanh", { width: 1440, height: 900 });
  check(await page.isVisible("text=Hướng dẫn demo"), "desktop: demo guide beside the framed screen");
  await noScroll(page, "desktop");
  await shot(page, "desktop-frame");
  await ctx.close();
}
{
  // API unreachable from the browser: the screen still works from the server-rendered profile + local storage.
  const ctx = await browser.newContext({ viewport: { width: 540, height: 960 }, deviceScaleFactor: 2 });
  await ctx.addInitScript(SILENCE);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => consoleErrors.push(`offline: ${e.message}`));
  await page.goto(`${WEB}/screen?elder=hanh&kiosk=1&tts=0&api=${encodeURIComponent("http://127.0.0.1:9")}`, { waitUntil: "networkidle" });
  await page.waitForSelector("text=Đang ngoại tuyến", { timeout: 10000 });
  await page.click("text=Đã uống thuốc");
  await page.waitForSelector("text=sẽ gửi khi có mạng");
  check(true, "offline: medication tap kept on the device");
  await ctx.close();
}

check(consoleErrors.length === 0, `no console errors ${consoleErrors.length ? JSON.stringify(consoleErrors.slice(0, 5)) : ""}`);
await browser.close();
console.log(failures.length ? `\n${failures.length} check(s) failed` : "\nall screen checks passed");
process.exit(failures.length ? 1 : 0);
