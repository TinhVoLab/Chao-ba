// Snapshots the family-coordination and community endpoints into web/fixtures/{family,community}.json (offline demo
// data). One snapshot per care-circle member, so the offline app still shows the right view for "Viewing as".
// Usage: node scripts/snapshot-family-fixtures.mjs [apiBase]   (run against a freshly seeded API, like snapshot-fixtures.mjs)
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = (process.argv[2] ?? process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures");
mkdirSync(OUT, { recursive: true });

// Mirrors CIRCLES in web/lib/viewer.ts.
const CIRCLES = {
  hanh: [["lan", "Lan", "primary"], ["minh", "Minh", "viewer"], ["vy", "Vy", "viewer"]],
  tu: [["ba_tu", "Bà Tư", "primary"], ["khoa", "Khoa", "viewer"], ["ngan", "Ngân", "viewer"]],
  control: [["thao", "Thảo", "primary"], ["tam", "Tâm", "viewer"]],
};

async function get(path, actor, role) {
  const res = await fetch(BASE + path, { headers: { "X-Actor": encodeURIComponent(actor), "X-Role": role } });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

const family = {};
for (const [elder, members] of Object.entries(CIRCLES)) {
  family[elder] = {};
  for (const [id, name, role] of members) {
    const overview = await get(`/api/elders/${elder}/family`, name, role);
    const timeline = await get(`/api/elders/${elder}/family/timeline?days=14`, name, role);
    family[elder][id] = { overview, timeline };
  }
  console.log(`${elder}: ${members.length} viewers`);
}
writeFileSync(join(OUT, "family.json"), JSON.stringify({ ...family, _snapshot: { from: BASE, at: new Date().toISOString() } }) + "\n");
const community = await get("/api/community/overview", "Trạm Y tế Phường X", "health_station");
writeFileSync(join(OUT, "community.json"), JSON.stringify({ ...community, _snapshot: { from: BASE, at: new Date().toISOString() } }) + "\n");
console.log(`community: ${community.ward.elders} elders, ${community.visit_list.length} on the visit list`);
