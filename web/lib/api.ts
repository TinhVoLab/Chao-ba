// Server-side data access. Every read tries the live API first and falls back to the
// bundled fixtures (offline demo data) when the API is unreachable or errors.
import { serverApiBase } from "./config";
import { familyFixture, fixtureCommunity, fixtureElders, fixtureFor } from "./fixtures";
import { normAlerts } from "./normalize";
import type { KudosCatalog, KudosList } from "./kudos";
import { actorHeaders, stationHeaders } from "./viewer";
import { serverViewerId } from "./viewer-server";
import type {
  Alert,
  Community,
  Dmaic,
  ElderProfile,
  ElderSummary,
  FamilyOverview,
  FamilyTimeline,
  Loaded,
  Note,
  Privacy,
  Timeline,
  Today,
} from "./types";

async function get<T>(
  path: string,
  fallback: () => T,
  elderId?: string,
  headers?: Record<string, string>,
  timeoutMs = 3000,
): Promise<Loaded<T>> {
  try {
    const res = await fetch(`${serverApiBase()}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
      // The "Viewing as" member (cookie) for elder-scoped reads; the access log records who looked.
      headers: headers ?? (elderId ? actorHeaders(elderId, await serverViewerId(elderId)) : {}),
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

// Family coordination: what the API returns depends on who is viewing (primary carer vs viewer).
export const getFamily = async (id: string) => {
  const member = await serverViewerId(id);
  return get<FamilyOverview>(`/api/elders/${e(id)}/family`, () => familyFixture(id, member).overview, id);
};
export const getFamilyTimeline = async (id: string, days = 14) => {
  const member = await serverViewerId(id);
  return get<FamilyTimeline>(`/api/elders/${e(id)}/family/timeline?days=${days}`, () => familyFixture(id, member).timeline, id);
};
/** Community dashboard, read as the ward health station (first call builds the simulated ward: allow a bit longer). */
export const getCommunity = () => get<Community>("/api/community/overview", () => fixtureCommunity, undefined, stationHeaders(), 8000);

// The elder's own taps on the home screen (standing-screen endpoints). Read-only here, never scored; null offline.
export interface MedicationLog {
  today: { name: string; time: string; status: "taken" | "not_yet" | null; answered_at: string | null }[];
}
export interface MoodCheckin {
  today: { mood: "happy" | "neutral" | "sad"; label_vi: string; label_en: string; created_at: string } | null;
}
export const getMedicationLog = (id: string) => get<MedicationLog | null>(`/api/elders/${e(id)}/medication_log?days=1`, () => null, id);
export const getMoodCheckin = (id: string) => get<MoodCheckin | null>(`/api/elders/${e(id)}/mood_checkin?days=1`, () => null, id);

// "Gửi yêu thương" (kudos.py): the tray's catalog and the viewer's sent cards; null offline (the tray says so).
export const getKudosCatalog = (id: string) => get<KudosCatalog | null>(`/api/elders/${e(id)}/kudos/catalog`, () => null, id);
export const getKudosList = (id: string, box: "sent" | "family" = "sent") =>
  get<KudosList | null>(`/api/elders/${e(id)}/kudos?box=${box}&days=28`, () => null, id);

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
