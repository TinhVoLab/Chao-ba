// Server-side data access. Every read tries the live API first and falls back to the
// bundled fixtures (offline demo data) when the API is unreachable or errors.
import { serverApiBase } from "./config";
import { fixtureElders, fixtureFor } from "./fixtures";
import { normAlerts } from "./normalize";
import { actorHeaders } from "./viewer";
import type { Alert, Dmaic, ElderProfile, ElderSummary, Loaded, Note, Privacy, Timeline, Today } from "./types";

async function get<T>(path: string, fallback: () => T, elderId?: string): Promise<Loaded<T>> {
  try {
    const res = await fetch(`${serverApiBase()}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
      headers: actorHeaders(elderId),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    return { data: (await res.json()) as T, live: true };
  } catch {
    return { data: fallback(), live: false };
  }
}

export const getElders = () => get<ElderSummary[]>("/api/elders", () => fixtureElders);

/** Resolve the requested elder id against the elder list (default: first elder). */
export function resolveElder(list: ElderSummary[], requested?: string | string[]): ElderSummary {
  const id = Array.isArray(requested) ? requested[0] : requested;
  return list.find((e) => e.id === id) ?? list[0] ?? fixtureElders[0];
}

const e = encodeURIComponent;
export const getProfile = (id: string) => get<ElderProfile>(`/api/elders/${e(id)}`, () => fixtureFor(id).profile, id);
export const getToday = (id: string) => get<Today>(`/api/elders/${e(id)}/today`, () => fixtureFor(id).today, id);
export const getTimeline = (id: string, days = 90) =>
  get<Timeline>(`/api/elders/${e(id)}/timeline?days=${days}`, () => fixtureFor(id).timeline, id);
export const getAlerts = async (id: string): Promise<Loaded<Alert[]>> => {
  const r = await get<Alert[]>(`/api/elders/${e(id)}/alerts`, () => fixtureFor(id).alerts, id);
  return { ...r, data: normAlerts(r.data) };
};
export const getDmaic = (id: string) => get<Dmaic>(`/api/elders/${e(id)}/dmaic`, () => fixtureFor(id).dmaic, id);
export const getNotes = (id: string) => get<Note[]>(`/api/elders/${e(id)}/notes`, () => fixtureFor(id).notes, id);
export const getPrivacy = (id: string) => get<Privacy>(`/api/elders/${e(id)}/privacy`, () => fixtureFor(id).privacy, id);

/** Loads the elder list + resolves the selected elder in one go. */
export async function loadElderContext(requested?: string | string[]) {
  const elders = await getElders();
  const raw = Array.isArray(elders.data) && elders.data.length ? elders.data : fixtureElders;
  // Story order for the demo: Bà Hạnh first, then Ông Tư, Ông Bảy, then anyone else.
  const rank = (id: string) => {
    const i = ["hanh", "tu", "control"].indexOf(id);
    return i < 0 ? 99 : i;
  };
  const list = [...raw].sort((a, b) => rank(a.id) - rank(b.id));
  const elder = resolveElder(list, requested);
  return { elders: list, elder, live: elders.live };
}
