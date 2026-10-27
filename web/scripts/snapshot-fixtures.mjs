// Snapshots the live Chào Bà API into web/fixtures/ so the offline demo data is
// byte-for-byte what the real pipeline produces.
// Usage: node scripts/snapshot-fixtures.mjs [apiBase]   (default $NEXT_PUBLIC_API_BASE or http://localhost:8000)
// Run it against a freshly seeded API (90 simulated days, before any real web call).
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = (process.argv[2] ?? process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures");
mkdirSync(OUT, { recursive: true });

async function get(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

const elders = await get("/api/elders");
const keep = ["hanh", "tu", "control"];
for (const id of keep) if (!elders.some((e) => e.id === id)) throw new Error(`elder ${id} missing from ${BASE}`);
writeFileSync(join(OUT, "elders.json"), JSON.stringify(elders, null, 1) + "\n");

for (const id of keep) {
  const e = encodeURIComponent(id);
  const [profile, today, timeline, alerts, dmaic, notes, privacy] = await Promise.all([
    get(`/api/elders/${e}`),
    get(`/api/elders/${e}/today`),
    get(`/api/elders/${e}/timeline?days=90`),
    get(`/api/elders/${e}/alerts`),
    get(`/api/elders/${e}/dmaic`),
    get(`/api/elders/${e}/notes`),
    get(`/api/elders/${e}/privacy`),
  ]);
  const bundle = { profile, today, timeline, alerts, dmaic, notes, privacy, _snapshot: { from: BASE, at: new Date().toISOString() } };
  writeFileSync(join(OUT, `${id}.json`), JSON.stringify(bundle, null, 1) + "\n");
  console.log(`${id}: day ${today.day} ${today.light}, ${timeline.records.length} records, ${alerts.length} alerts`);
}
console.log(`fixtures written from ${BASE}`);
