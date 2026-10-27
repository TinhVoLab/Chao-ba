// End-to-end check of "Gửi yêu thương" (family micro-interactions) against a running API + web app, with screenshots.
//
//   WEB=http://localhost:3000 API=http://localhost:8000 node web/scripts/kudos-e2e.mjs
//
// Never makes a sound: Chromium runs with --mute-audio, /screen uses ?tts=0, and speechSynthesis.speak is replaced by
// a no-op before any page script runs. The elder's advice answer is typed (?typed=1), so no microphone is needed.
// Flow: family sends "Má ăn cơm chưa?" → /screen shows the card → tap "Ăn rồi" → family Today shows the reply;
// advice question → typed answer → saved as "Lời má dạy" after consent; free text with a dose is refused; a simulated
// phone call relays a pending card and records the reply. 390 px and 1280 px, Vietnamese and English, no console
// errors, no horizontal overflow. Writes docs/screenshots/kudos-*.png. Calls POST /api/demo/reset?elder=hanh first.
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
const hdr = (actor, role = "primary") => ({ "Content-Type": "application/json", "X-Actor": encodeURIComponent(actor), "X-Role": role });
const api = async (path, init = {}) => (await fetch(API + path, { headers: hdr("e2e"), ...init })).json();

const SILENCE = () => {
  // Belt and braces on top of ?tts=0 and --mute-audio: no page here can ever speak.
  try {
    if (window.speechSynthesis) window.speechSynthesis.speak = () => {};
  } catch {
    /* ignore */
  }
};

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ args: ["--mute-audio", "--autoplay-policy=user-gesture-required"] });
process.on("exit", () => {
  browser.close().catch(() => {});
});

async function context(viewport, lang = "vi") {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2, permissions: [] });
  await ctx.addInitScript(SILENCE);
  await ctx.addInitScript((l) => {
    try {
      localStorage.setItem("cb-lang", l);
      localStorage.setItem("cb-theme", "light");
    } catch {
      /* ignore */
    }
  }, lang);
  return ctx;
}
let expect422 = false; // the refused free-text message (step 4) is a 422 the browser logs as a failed resource
function watch(page, label) {
  page.on("pageerror", (e) => consoleErrors.push(`${label}: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (expect422 && /status of 422/.test(m.text())) return;
    consoleErrors.push(`${label}: ${m.text()}`);
  });
}
async function noOverflow(page, label) {
  const o = await page.evaluate(() => document.scrollingElement.scrollWidth > window.innerWidth + 1);
  check(!o, `${label}: no horizontal overflow`);
}
async function family(ctx, path, label) {
  const page = await ctx.newPage();
  watch(page, label);
  await page.goto(`${WEB}${path}`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForSelector('[data-testid="kudos-tray"]');
  return page;
}
async function screen(ctx, label, extra = "") {
  const page = await ctx.newPage();
  watch(page, label);
  await page.goto(`${WEB}/screen?elder=hanh&kiosk=1&fast=1&typed=1&tts=0${extra}&api=${encodeURIComponent(API)}`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForSelector('[data-testid="elder-screen"]');
  return page;
}
async function trayShot(page, name) {
  // element screenshots of tall regions would include the sticky header / fixed bottom nav: hide them for the shot
  const tag = await page.addStyleTag({ content: ".sticky, nav, .fixed { visibility: hidden !important; }" });
  const tray = page.locator('[data-testid="kudos-tray"]');
  await tray.scrollIntoViewIfNeeded();
  await tray.screenshot({ path: join(OUT, `kudos-${name}.png`) });
  await tag.evaluate((el) => el.remove());
}
async function elderSizes(page, label) {
  const r = await page.evaluate(() => {
    const root = document.querySelector('[data-testid="kudos-card"]');
    const k = 1080 / document.querySelector('[data-testid="elder-screen"]').clientWidth;
    const small = [...root.querySelectorAll("*")]
      .filter((el) => el.offsetParent && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))
      .map((el) => parseFloat(getComputedStyle(el).fontSize) * k)
      .filter((px) => px < 31.5).length;
    const btns = [...root.querySelectorAll("button")].filter((b) => b.offsetParent).map((b) => Math.min(b.offsetWidth, b.offsetHeight) * k);
    const sr = document.querySelector('[data-testid="elder-screen"]').getBoundingClientRect();
    const clipped = [...root.querySelectorAll("button, p")].filter((el) => el.offsetParent && el.getBoundingClientRect().bottom > sr.bottom + 1).length;
    return { small, minBtn: Math.min(...btns), clipped };
  });
  check(r.small === 0, `${label}: all card text >= 32px at 1080 wide (${r.small} smaller)`);
  check(r.minBtn >= 96, `${label}: answer buttons >= 96px (smallest ${Math.round(r.minBtn)}px)`);
  check(r.clipped === 0, `${label}: nothing below the screen edge`);
}

await fetch(`${API}/api/demo/reset?elder=hanh`, { method: "POST" });

// ---------------------------------------------------------------- 1. family sends "Má ăn cơm chưa?" (390 px, VI)
const phone = await context({ width: 390, height: 844 });
let today = await family(phone, "/?elder=hanh", "today-390");
check((await today.locator('[data-testid="kudos-tray"] button').count()) >= 11, "today: tray with quick cards");
check(await today.isVisible("text=Đã 5 ngày chưa ai gọi má."), "today: the 'nobody called' nudge still counts only calls");
check(await today.isVisible("text=lời thương tuần này, gọi má một cuộc nữa nha"), "today: nudge mentions this week's love notes");
await noOverflow(today, "today 390");
await trayShot(today, "family-tray");
await today.click('[data-testid="kudos-ate"]');
await today.waitForSelector('[data-testid="kudos-flash"]');
const firstRow = today.locator('[data-testid="kudos-row"]').first();
check((await firstRow.textContent()).includes("Má ăn cơm chưa?") && (await firstRow.getAttribute("data-status")) === "sent", "today: sent card listed as 'Đã gửi'");

// ---------------------------------------------------------------- 2. the standing screen shows it; tap "Ăn rồi"
const tablet = await context({ width: 540, height: 960 });
let scr = await screen(tablet, "screen-checkin");
await scr.waitForSelector('[data-testid="kudos-card"][data-kind="checkin"]', { timeout: 15000 });
check((await scr.textContent('[data-testid="kudos-text"]')).includes("Má ăn cơm chưa?"), "screen: card shows 'Má ăn cơm chưa?'");
check(await scr.isVisible("text=Con Lan gửi"), "screen: 'Con Lan gửi' with Lan's photo");
await scr.waitForTimeout(700);
await elderSizes(scr, "screen checkin");
await scr.screenshot({ path: join(OUT, "kudos-screen-checkin.png") });
await scr.click('[data-testid="kudos-choice-ate"]');
await scr.waitForSelector('[data-testid="kudos-done"]');
await scr.screenshot({ path: join(OUT, "kudos-screen-done.png") });
await scr.waitForSelector('[data-testid="kudos-card"]', { state: "detached", timeout: 8000 });
check(await scr.isVisible('[data-testid="btn-talk"]'), "screen: back to the idle screen after answering");
await scr.close();

today = await family(phone, "/?elder=hanh", "today-reply");
const reply = await today.locator('[data-testid="kudos-reply"]').first().textContent();
check(/Má trả lời: Ăn rồi con · \d\d:\d\d/.test(reply), `today: reply inline (“${reply}”)`);
await trayShot(today, "family-reply");

// ---------------------------------------------------------------- 3. advice: "Hỏi ý má" → typed answer → Sổ ký ức
await today.click('[data-testid="kudos-panel-advice"]');
await today.click('[data-testid="kudos-mai"]');
await today.waitForSelector('[data-testid="kudos-flash"]');
await trayShot(today, "family-advice-sent");
scr = await screen(tablet, "screen-advice");
await scr.waitForSelector('[data-testid="kudos-card"][data-kind="advice"]', { timeout: 15000 });
await scr.waitForTimeout(700);
await elderSizes(scr, "screen advice");
await scr.screenshot({ path: join(OUT, "kudos-screen-advice.png") });
await scr.click('[data-testid="kudos-speak"]');
await scr.fill('[data-testid="kudos-typed"]', "Tới rằm tháng chạp thì lặt hết lá, tưới nước cho đều, trời lạnh thì tưới nước ấm cho kịp Tết.");
await scr.click('[data-testid="kudos-typed-done"]');
await scr.click('[data-testid="kudos-send-answer"]');
await scr.waitForSelector('[data-testid="kudos-save-ask"]');
await scr.screenshot({ path: join(OUT, "kudos-screen-save.png") });
await scr.click('[data-testid="kudos-save-yes"]');
await scr.waitForSelector('[data-testid="kudos-done"]');
await scr.close();
const mem = await (await fetch(`${API}/api/elders/hanh/memories`, { headers: hdr("Lan") })).json();
check(mem.stories.some((s) => s.title_vi === "Lời má dạy: chăm mai ra nụ đúng Tết" && s.shared), "memory book: 'Lời má dạy' saved after the elder agreed");
today = await family(phone, "/?elder=hanh", "today-advice");
check(await today.isVisible("text=Đã lưu vào Sổ ký ức: Lời má dạy"), "today: advice answer shown and marked saved");

// ---------------------------------------------------------------- 4. free text with a dose is refused kindly
await today.click('[data-testid="kudos-panel-message"]');
await today.fill('[data-testid="kudos-text"]', "Má uống thêm 1 viên thuốc huyết áp nha");
expect422 = true;
await today.click('[data-testid="kudos-send-text"]');
await today.waitForSelector('[data-testid="kudos-refused"]');
expect422 = false;
check((await today.textContent('[data-testid="kudos-refused"]')).includes("không chuyển lời khuyên về thuốc"), "today: medication-dose message refused with a friendly note");
await trayShot(today, "family-refused");
await today.close();

// ---------------------------------------------------------------- 5. phone-only: a simulated call relays a pending card
const sent = await (await fetch(`${API}/api/elders/hanh/kudos`, { method: "POST", headers: hdr("Vy", "viewer"), body: JSON.stringify({ kind: "checkin", template_id: "slept" }) })).json();
const call = await api("/api/calls", { method: "POST", body: JSON.stringify({ elder_id: "hanh", channel: "web" }) });
let t = 12;
const lines = [];
for (let i = 0; i < 25; i++) {
  const line = await api(`/api/calls/${call.call_id}/simulate`);
  const out = await api(`/api/calls/${call.call_id}/turns`, { method: "POST", body: JSON.stringify({ text: line.text, start: t, end: t + line.duration_sec, pauses: line.pauses }) });
  lines.push(out.reply_text);
  t += line.duration_sec + 6;
  if (out.end_call) break;
}
const end = await api(`/api/calls/${call.call_id}/end`, { method: "POST" });
check(lines[0].includes("Cháu Vy gửi thương bà nè. Cháu Vy hỏi tối qua bà ngủ ngon hông bà?"), `call: relays Vy's card (“${lines[0]}”)`);
check(lines[1].startsWith("Dạ, con nhắn lại cho cháu Vy liền nha."), "call: confirms it will pass the answer on");
check(end.metrics.elder_speech_sec >= 45 && end.metrics.valid, `call: still a valid call (${end.metrics.elder_speech_sec}s elder speech)`);
const vy = await (await fetch(`${API}/api/elders/hanh/kudos?box=sent`, { headers: hdr("Vy", "viewer") })).json();
const relayed = vy.items.find((k) => k.id === sent.kudos.id);
check(relayed && relayed.reply?.via === "call" && relayed.reply?.choice === "good", "call: reply recorded on the card (via call)");

// ---------------------------------------------------------------- 6. English, 1280 px, the family page, the timeline, DMAIC
const desk = await context({ width: 1280, height: 900 }, "en");
const fam = await family(desk, "/family?elder=hanh", "family-1280-en");
check(await fam.isVisible("text=Send some love"), "family (EN): tray title in English");
check(await fam.isVisible("text=Sent by the family"), "family (EN): family list");
await noOverflow(fam, "family 1280 EN");
await trayShot(fam, "family-page-en");
await fam.screenshot({ path: join(OUT, "kudos-family-1280-en.png"), fullPage: false });
const feed = fam.locator("text=Lan to Mom:").first();
check((await feed.count()) > 0, "family (EN): love notes in the shared timeline");
const dm = await desk.newPage();
watch(dm, "dmaic-en");
await dm.goto(`${WEB}/dmaic?elder=hanh`, { waitUntil: "networkidle" });
await dm.waitForSelector('[data-testid="weekly-contacts"]');
await dm.locator('[data-testid="weekly-contacts"]').scrollIntoViewIfNeeded();
await dm.locator('[data-testid="weekly-contacts"]').screenshot({ path: join(OUT, "kudos-dmaic-weekly.png") });
await noOverflow(dm, "dmaic 1280 EN");
const todayEn = await family(await context({ width: 390, height: 844 }, "en"), "/?elder=hanh", "today-390-en");
check(await todayEn.isVisible("text=Send some love"), "today (EN 390): tray in English");
await noOverflow(todayEn, "today 390 EN");
await trayShot(todayEn, "family-tray-en");
const scrEn = await screen(await context({ width: 540, height: 960 }, "en"), "screen-en", "&lang=en");
await fetch(`${API}/api/elders/hanh/kudos`, { method: "POST", headers: hdr("Minh"), body: JSON.stringify({ kind: "love", template_id: "miss" }) });
await scrEn.waitForSelector('[data-testid="kudos-card"][data-kind="love"]', { timeout: 15000 });
await scrEn.waitForTimeout(700);
await elderSizes(scrEn, "screen love (EN)");
await scrEn.screenshot({ path: join(OUT, "kudos-screen-love-en.png") });
await scrEn.click('[data-testid="kudos-heart"]');
await scrEn.waitForSelector('[data-testid="kudos-done"]');

// 390 phone view of the screen (the stage fills the viewport)
const small = await screen(await context({ width: 390, height: 844 }), "screen-390");
await fetch(`${API}/api/elders/hanh/kudos`, { method: "POST", headers: hdr("Lan"), body: JSON.stringify({ kind: "checkin", template_id: "feeling" }) });
await small.waitForSelector('[data-testid="kudos-card"][data-kind="checkin"]', { timeout: 15000 });
await small.waitForTimeout(700);
await elderSizes(small, "screen 390");
await noOverflow(small, "screen 390");
await small.screenshot({ path: join(OUT, "kudos-screen-390.png") });

check(consoleErrors.length === 0, `no console errors ${consoleErrors.length ? JSON.stringify(consoleErrors.slice(0, 5)) : ""}`);
await browser.close();
console.log(failures.length ? `\n${failures.length} FAILED` : "\nall checks passed");
process.exit(failures.length ? 1 : 0);
