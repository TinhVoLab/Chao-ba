// Client-safe helpers for the memory book (no server-only imports).
import { API_BASE } from "./config";

/** Browser URL of the printable memoir (shared stories only; opens in a new tab). */
export const exportUrl = (id: string, lang: "vi" | "en") =>
  `${API_BASE}/api/elders/${encodeURIComponent(id)}/memories/export?lang=${lang}`;

/** Percent string for a 0..1 rate. */
export const pct = (x: number | null | undefined) => (x == null ? "–" : `${Math.round(x * 100)}%`);
