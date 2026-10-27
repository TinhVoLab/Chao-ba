// Snapshot the memory book + activities of the demo elders as offline fixtures (family view: shared stories only).
// Usage: node web/scripts/snapshot-memory-fixtures.mjs [http://localhost:8000]   (run against a freshly seeded API)
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const base = (process.argv[2] ?? "http://localhost:8000").replace(/\/$/, "");
const out = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "memories");
const viewers = { hanh: "Lan", tu: "B%C3%A0%20T%C6%B0", control: "Th%E1%BA%A3o" };
for (const [id, actor] of Object.entries(viewers)) {
  const headers = { "X-Actor": actor, "X-Role": "primary" };
  const memories = await (await fetch(`${base}/api/elders/${id}/memories`, { headers })).json();
  const activities = await (await fetch(`${base}/api/elders/${id}/activities`, { headers })).json();
  writeFileSync(join(out, `${id}.json`), JSON.stringify({ memories, activities }, null, 1) + "\n");
  console.log(id, memories.stories.length, "shared stories");
}
